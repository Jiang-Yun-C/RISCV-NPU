// Unchanged T09 plus the production SRAM peripheral and test-only routing.
// Program DDR/MMIO remain behavioral; this is not complete SoC/PHY or a board score.
#include "VT09CpuLocal.h"
#include "verilated.h"
#include <cstdint>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

struct Counts {
    uint64_t cycles=0, retired=0, stalls=0, branches=0, mispredicts=0;
    uint64_t i_reads=0, d_reads=0, d_writes=0, workspace_reads=0;
    void json(std::ostream &o) const {
        o << "{\"cycles\":" << cycles << ",\"retired\":" << retired
          << ",\"stalls\":" << stalls << ",\"branches\":" << branches
          << ",\"mispredicts\":" << mispredicts << ",\"i_read_beats\":" << i_reads
          << ",\"d_read_beats\":" << d_reads << ",\"d_write_beats\":" << d_writes
          << ",\"workspace_read_beats\":" << workspace_reads << "}";
    }
};

static std::string quoted(const std::string &s) {
    std::string r="\"";
    for (unsigned char c:s) {
        if (c=='"'||c=='\\') { r+='\\';r+=c; }
        else if(c=='\n') r+="\\n";
        else if(c=='\r') r+="\\r";
        else if(c=='\t') r+="\\t";
        else if(c>=32&&c<127) r+=c;
        else {const char *h="0123456789abcdef";r+="\\u00";r+=h[c>>4];r+=h[c&15];}
    }
    return r+'"';
}

struct Memory {
    std::vector<uint8_t> program=std::vector<uint8_t>(8u<<20,0xa5);
    std::vector<uint8_t> stack=std::vector<uint8_t>(64u<<10,0xa5);
    std::vector<uint8_t> workspace=std::vector<uint8_t>(2u<<20,0xa5);
    Counts total, window;
    bool measuring=false;
    uint64_t cycle=0, exit_cycle=0, start_mark=0, stop_mark=0;
    uint32_t exit_code=0;
    unsigned marker_starts=0, marker_stops=0;
    std::string uart;
    uint8_t &byte(uint32_t a) {
        if(a>=0xb4000000u&&a<0xb4800000u)return program[a-0xb4000000u];
        if(a>=0x20000u&&a<0x30000u)throw std::runtime_error("SRAM transaction escaped the actual RTL peripheral");
        if(a>=0xac000000u&&a<0xac200000u)return workspace[a-0xac000000u];
        throw std::runtime_error("access outside modeled memory at "+std::to_string(a));
    }
    uint32_t read(uint32_t a) {
        a &= ~3u;
        // ROM performs the platform handoff to the actual ELF entry. No
        // architectural registers or application results are backdoor-written.
        if(a==0x10000u)return 0xb40002b7u; // lui t0,0xb4000
        if(a==0x10004u)return 0x00028067u; // jalr zero,t0,0
        if(a>=0x10000u&&a<0x20000u)return 0x00000013u;
        if(a==0x10000004u)return 0; // immediate behavioral UART sink
        if(a==0x10000008u)return uint32_t(cycle);
        if(a==0x1000000cu)return uint32_t(cycle>>32);
        if(a>=0x10000000u&&a<0x10001000u)return 0;
        uint32_t v=0;
        for(unsigned i=0;i<4;i++)v|=uint32_t(byte(a+i))<<(8*i);
        return v;
    }
    void write(uint32_t a,uint32_t v,unsigned mask) {
        a &= ~3u;
        if(a==0x10000000u) {if(mask&1)uart+=char(v&255);return;}
        if(a==0x10000020u) {exit_code=v;exit_cycle=cycle;return;}
        if(a==0x100000f0u) {
            if(v==1) {if(measuring||marker_starts)throw std::runtime_error("duplicate start marker");
                measuring=true;window=Counts{};start_mark=cycle;marker_starts++;}
            else if(v==2) {if(!measuring)throw std::runtime_error("stop without start marker");
                measuring=false;stop_mark=cycle;marker_stops++;}
            else throw std::runtime_error("unexpected measurement marker");
            return;
        }
        if(a>=0x10000000u&&a<0x10001000u)return;
        for(unsigned i=0;i<4;i++)if(mask&(1u<<i))byte(a+i)=uint8_t(v>>(8*i));
    }
};

struct ReadPort {
    bool active=false,valid=false;
    uint32_t address=0,data=0;
    unsigned length=0,beat=0,size=2,delay=0;
    void prepare(Memory &m) {if(active&&!valid&&!delay){data=m.read(address+(beat<<size));valid=true;}}
    void advance(bool fire) {
        if(delay)delay--;
        if(fire){if(!valid)throw std::runtime_error("read without valid");valid=false;
            if(beat==length)active=false;else beat++;}
    }
    void accept(uint32_t a,unsigned l,unsigned s,unsigned latency) {
        if(active||s>2)throw std::runtime_error("invalid overlapping read");
        active=true;valid=false;address=a;length=l;size=s;beat=0;delay=latency;
    }
    uint32_t current_address() const{return address+(beat<<size);}
};

int main(int argc,char **argv) {
    if(argc<7){std::cerr<<"usage: cpu binary result.json max_cycles read_latency write_latency hold_reset\n";return 2;}
    const uint64_t limit=std::stoull(argv[3]);
    const unsigned rlat=std::stoul(argv[4]),wlat=std::stoul(argv[5]);
    const bool hold=std::stoul(argv[6])!=0;
    VerilatedContext context;
    context.commandArgs(argc,argv);
    VT09CpuLocal cpu(&context);
    Memory mem;
    ReadPort ip,dp;
    bool aw=false,bpending=false,bvalid=false;
    uint32_t wa=0,rom=0,last_pc=0;
    unsigned wl=0,wb=0,ws=0,bdelay=0;
    std::string error;
    bool success=false;
    try {
        std::ifstream f(argv[1],std::ios::binary);
        if(!f)throw std::runtime_error("cannot open binary");
        f.seekg(0,std::ios::end);auto bytes=f.tellg();f.seekg(0);
        if(bytes<=0||uint64_t(bytes)>mem.program.size())throw std::runtime_error("binary outside program window");
        f.read(reinterpret_cast<char *>(mem.program.data()),bytes);
        cpu.timerInterrupt=cpu.externalInterrupt=cpu.softwareInterrupt=0;
        for(uint64_t cycle=0;cycle<limit;cycle++) {
            mem.cycle=cycle;mem.total.cycles=cycle+1;
            cpu.clk=0;cpu.reset=hold||cycle<12;cpu.rom_data=rom;
            ip.prepare(mem);dp.prepare(mem);
            if(bpending&&!bdelay)bvalid=true;
            cpu.iAxi_ar_ready=!ip.active;
            cpu.iAxi_r_valid=ip.valid;cpu.iAxi_r_payload_data=ip.data;
            cpu.iAxi_r_payload_resp=0;cpu.iAxi_r_payload_last=ip.beat==ip.length;
            cpu.dAxi_ar_ready=!dp.active;
            cpu.dAxi_r_valid=dp.valid;cpu.dAxi_r_payload_data=dp.data;
            cpu.dAxi_r_payload_resp=0;cpu.dAxi_r_payload_last=dp.beat==dp.length;
            cpu.dAxi_aw_ready=!aw&&!bpending;
            cpu.dAxi_w_ready=aw&&!bpending;
            cpu.dAxi_b_valid=bvalid;cpu.dAxi_b_payload_resp=0;
            cpu.eval();
            const bool iar=cpu.iAxi_ar_valid&&cpu.iAxi_ar_ready;
            const bool ir=cpu.iAxi_r_valid&&cpu.iAxi_r_ready;
            const bool dar=cpu.dAxi_ar_valid&&cpu.dAxi_ar_ready;
            const bool dr=cpu.dAxi_r_valid&&cpu.dAxi_r_ready;
            const bool daw=cpu.dAxi_aw_valid&&cpu.dAxi_aw_ready;
            const bool dw=cpu.dAxi_w_valid&&cpu.dAxi_w_ready;
            const bool db=cpu.dAxi_b_valid&&cpu.dAxi_b_ready;
            const uint32_t ia=cpu.iAxi_ar_payload_addr,da=cpu.dAxi_ar_payload_addr;
            const unsigned il=cpu.iAxi_ar_payload_len,dl=cpu.dAxi_ar_payload_len,ds=cpu.dAxi_ar_payload_size;
            const uint32_t nwa=cpu.dAxi_aw_payload_addr,wdata=cpu.dAxi_w_payload_data;
            const unsigned nwl=cpu.dAxi_aw_payload_len,nws=cpu.dAxi_aw_payload_size,wstrb=cpu.dAxi_w_payload_strb;
            const bool wlast=cpu.dAxi_w_payload_last;
            const uint32_t next_rom=cpu.rom_enable?mem.read(cpu.rom_address):rom;
            if(!cpu.reset) {
                auto count=[&](Counts &s){
                    s.retired+=cpu.trace_retire;s.stalls+=cpu.trace_stall;
                    s.branches+=cpu.trace_branch;s.mispredicts+=cpu.trace_mispredict;
                    s.i_reads+=ir+cpu.local_i_r_fire;s.d_reads+=dr+cpu.local_d_r_fire;s.d_writes+=dw+cpu.local_d_w_fire;
                    s.workspace_reads+=dr&&dp.current_address()>=0xac000000u&&dp.current_address()<0xac200000u;
                };
                count(mem.total);if(mem.measuring){count(mem.window);mem.window.cycles++;}
                if(cpu.trace_retire)last_pc=cpu.trace_pc;
            }
            cpu.clk=1;cpu.eval();context.timeInc(10);
            if(!cpu.reset) {
                ip.advance(ir);dp.advance(dr);
                if(iar){if(cpu.iAxi_ar_payload_burst!=1)throw std::runtime_error("non-INCR I burst");ip.accept(ia,il,2,rlat);}
                if(dar)dp.accept(da,dl,ds,(da>=0x20000u&&da<0x30000u)?1:rlat);
                if(bdelay)bdelay--;
                if(db){bvalid=false;bpending=false;aw=false;}
                if(daw){if(aw||nws>2)throw std::runtime_error("bad AW");aw=true;wa=nwa;wl=nwl;ws=nws;wb=0;}
                if(dw){
                    if(!aw||wlast!=(wb==wl))throw std::runtime_error("W burst mismatch");
                    mem.write(wa+(wb<<ws),wdata,wstrb);
                    if(wb==wl){bpending=true;bvalid=false;
                        bdelay=(wa>=0x20000u&&wa<0x30000u)||(wa>=0x10000000u&&wa<0x10001000u)?1:wlat;}
                    else wb++;
                }
            }
            rom=next_rom;
            if(mem.exit_code&&cycle>=mem.exit_cycle+32){success=mem.exit_code==0xc021u;break;}
        }
        if(!success)error=mem.exit_code?"firmware failure":"cycle limit reached";
    } catch(const std::exception &e){error=e.what();}
    cpu.final();
    std::ofstream out(argv[2]);
    out<<"{\"status\":"<<quoted(success?"PASS_CPU_LOCAL_SRAM_RTL":"FAIL")
       <<",\"scope\":\"Unchanged T09 plus actual production SRAM RTL; behavioral program DDR/MMIO; not complete SoC DDR/PHY, formal CoreMark or board latency\""
       <<",\"read_latency\":"<<rlat<<",\"write_latency\":"<<wlat
       <<",\"hold_reset\":"<<(hold?"true":"false")<<",\"last_pc\":"<<last_pc
       <<",\"exit_code\":"<<mem.exit_code<<",\"marker_starts\":"<<mem.marker_starts
       <<",\"marker_stops\":"<<mem.marker_stops<<",\"marker_start_cycle\":"<<mem.start_mark
       <<",\"marker_stop_cycle\":"<<mem.stop_mark<<",\"total\":";mem.total.json(out);
    out<<",\"window\":";mem.window.json(out);
    out<<",\"error\":"<<quoted(error)<<",\"uart\":"<<quoted(mem.uart)<<"}\n";
    std::cout<<mem.uart;
    if(!success)std::cerr<<error<<" pc="<<std::hex<<last_pc<<" exit="<<mem.exit_code<<"\n";
    return success?0:1;
}
