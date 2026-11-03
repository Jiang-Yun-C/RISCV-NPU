// Observe the real pre-rising-edge RTL. Never write a CPU/internal signal.
#pragma once
#include "VT09Cpu_T09Cpu.h"
#include <array>
#include <cstdint>
#include <deque>
#include <fstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace pipeline {
enum Field { CYCLE, FPC, DPC, EPC, MPC, WPC, INSN, VALID, STUCK, FIRE, REMOVE,
    FLUSH, RETIRE, ESTALL, BRANCH, BRANCHPC, MISPRED, PENDING, HAZARD, REFILL,
    LOAD, STORE, AXIFIRE, AXIBLOCK, IWAIT, DWAIT, BWAIT, FIELD_COUNT };
static constexpr const char *names[FIELD_COUNT] = {"cycle", "fetch_pc", "decode_pc",
    "execute_pc", "memory_pc", "writeback_pc", "retire_instruction", "valid_mask",
    "stuck_mask", "fire_mask", "remove_mask", "fetch_flush", "retire",
    "execute_stall", "conditional_branch", "branch_pc", "mispredict",
    "pending_writes", "data_bus_hazard", "data_refilling", "execute_load_valid",
    "execute_store_valid", "axi_fire_mask", "axi_backpressure_mask", "i_read_wait",
    "d_read_wait", "write_response_wait"};
static constexpr unsigned widths[FIELD_COUNT] = {64,32,32,32,32,32,32,5,5,5,4,
    1,1,1,1,32,1,3,1,1,1,1,7,7,1,1,1};
using Row = std::array<uint64_t, FIELD_COUNT>;

struct Counts {
    uint64_t cycles=0,retired=0,execute_stall=0,branches=0,mispredicts=0;
    uint64_t i_wait=0,d_wait=0,b_wait=0,hazard=0,refill=0,pending=0,max_pending=0;
    uint64_t loads=0,stores=0,flush=0;
    std::array<uint64_t,5> valid{},stuck{},fire{};
    std::array<uint64_t,7> axi_fire{},axi_block{};
    void add(const Row &r) {
        cycles++;retired+=r[RETIRE];execute_stall+=r[ESTALL];branches+=r[BRANCH];
        mispredicts+=r[MISPRED];i_wait+=r[IWAIT];d_wait+=r[DWAIT];b_wait+=r[BWAIT];
        hazard+=r[HAZARD];refill+=r[REFILL];pending+=r[PENDING]!=0;
        if(r[PENDING]>max_pending)max_pending=r[PENDING];
        loads+=r[LOAD]&&bool(r[FIRE]&4);stores+=r[STORE]&&bool(r[FIRE]&4);flush+=r[FLUSH];
        for(unsigned i=0;i<5;i++){valid[i]+=(r[VALID]>>i)&1;stuck[i]+=(r[STUCK]>>i)&1;fire[i]+=(r[FIRE]>>i)&1;}
        for(unsigned i=0;i<7;i++){axi_fire[i]+=(r[AXIFIRE]>>i)&1;axi_block[i]+=(r[AXIBLOCK]>>i)&1;}
    }
    template<size_t N> static void array_json(std::ostream &o,const std::array<uint64_t,N>& a){
        o<<'[';for(size_t i=0;i<N;i++){if(i)o<<',';o<<a[i];}o<<']';
    }
    void json(std::ostream &o) const {
        o<<"{\"active_cycles\":"<<cycles<<",\"retired\":"<<retired
         <<",\"no_retire_cycles\":"<<cycles-retired<<",\"execute_stall_cycles\":"<<execute_stall
         <<",\"conditional_branches\":"<<branches<<",\"conditional_mispredicts\":"<<mispredicts
         <<",\"i_read_wait_cycles\":"<<i_wait<<",\"d_read_wait_cycles\":"<<d_wait
         <<",\"write_response_wait_cycles\":"<<b_wait<<",\"data_bus_hazard_cycles\":"<<hazard
         <<",\"data_refilling_cycles\":"<<refill<<",\"pending_write_cycles\":"<<pending
         <<",\"max_pending_writes\":"<<max_pending<<",\"execute_load_fires\":"<<loads
         <<",\"execute_store_fires\":"<<stores<<",\"fetch_flush_cycles\":"<<flush
         <<",\"stage_valid_cycles\":";array_json(o,valid);
        o<<",\"stage_stuck_cycles\":";array_json(o,stuck);
        o<<",\"stage_fire_cycles\":";array_json(o,fire);
        o<<",\"axi_handshakes\":";array_json(o,axi_fire);
        o<<",\"axi_backpressure_cycles\":";array_json(o,axi_block);o<<'}';
    }
};
}

class PipelineProfiler {
    uint64_t low,high,trigger_cycle=0;
    std::string kind;
    size_t capacity,pretrigger;
    std::deque<pipeline::Row> history;
    std::vector<pipeline::Row> rows;
    pipeline::Counts all,window;
    bool triggered=false;
    size_t actual_pretrigger=0;
public:
    PipelineProfiler(uint64_t lo,uint64_t hi,const std::string &k,size_t cap,size_t pre):
        low(lo),high(hi),kind(k),capacity(cap),pretrigger(pre) {
        if(lo>=hi||hi>0x100000000ull||cap<1||cap>16384||pre>=cap||
           (k!="retire"&&k!="mispredict"&&k!="data-wait"))
            throw std::runtime_error("invalid bounded trace configuration");
        rows.reserve(capacity);
    }
    void sample(const VT09Cpu &c,uint64_t cycle,bool i_active,bool d_active,bool b_pending) {
        using namespace pipeline;
        const auto &s=*c.T09Cpu;
        Row r{};r[CYCLE]=cycle;
        r[FPC]=s.T09IBus_iBusRsp_stages_2_input_payload;r[DPC]=s.decode_PC;
        r[EPC]=s.execute_PC;r[MPC]=s.memory_PC;r[WPC]=s.writeBack_PC;
        r[INSN]=c.trace_instruction;
        r[VALID]=s.T09IBus_iBusRsp_stages_2_input_valid;
        r[STUCK]=s.T09IBus_iBusRsp_stages_2_input_valid&&!s.T09IBus_iBusRsp_stages_2_input_ready;
        r[FIRE]=s.T09IBus_iBusRsp_stages_2_output_valid&&s.T09IBus_iBusRsp_stages_2_output_ready;
#define STAGE(name,bit) \
        r[VALID]|=uint64_t(s.name##_arbitration_isValid)<<(bit); \
        r[STUCK]|=uint64_t(s.name##_arbitration_isValid&&s.name##_arbitration_isStuck)<<(bit); \
        r[FIRE]|=uint64_t(s.name##_arbitration_isFiring)<<(bit); \
        r[REMOVE]|=uint64_t(s.name##_arbitration_removeIt)<<((bit)-1)
        STAGE(decode,1);STAGE(execute,2);STAGE(memory,3);STAGE(writeBack,4);
#undef STAGE
        r[FLUSH]=s.T09IBus_iBusRsp_flush;r[RETIRE]=c.trace_retire;r[ESTALL]=c.trace_stall;
        r[BRANCH]=c.trace_branch;r[BRANCHPC]=c.trace_branch_pc;r[MISPRED]=c.trace_mispredict;
        r[PENDING]=s.dBusToAxi4Shared_pendingWrites_value;r[HAZARD]=s.dBusToAxi4Shared_hazard;
        r[REFILL]=s.dataCache_1_io_cpu_execute_refilling;
        r[LOAD]=s.execute_arbitration_isValid&&s.execute_MEMORY_ENABLE&&!s.execute_MEMORY_WR;
        r[STORE]=s.execute_arbitration_isValid&&s.execute_MEMORY_ENABLE&&s.execute_MEMORY_WR;
#define AXI(name,bit) \
        r[AXIFIRE]|=uint64_t(c.name##_valid&&c.name##_ready)<<(bit); \
        r[AXIBLOCK]|=uint64_t(c.name##_valid&&!c.name##_ready)<<(bit)
        AXI(iAxi_ar,0);AXI(iAxi_r,1);AXI(dAxi_ar,2);AXI(dAxi_r,3);
        AXI(dAxi_aw,4);AXI(dAxi_w,5);AXI(dAxi_b,6);
#undef AXI
        r[IWAIT]=i_active&&!c.iAxi_r_valid;r[DWAIT]=d_active&&!c.dAxi_r_valid;
        r[BWAIT]=b_pending&&!c.dAxi_b_valid;
        all.add(r);
        auto inside=[&](uint64_t pc){return pc>=low&&pc<high;};
        const bool hit=(kind=="retire"&&r[RETIRE]&&inside(r[WPC]))||
            (kind=="mispredict"&&r[MISPRED]&&inside(r[BRANCHPC]))||
            (kind=="data-wait"&&r[DWAIT]&&(r[VALID]&4)&&inside(r[EPC]));
        if(!triggered&&hit){
            triggered=true;trigger_cycle=cycle;actual_pretrigger=history.size();
            rows.assign(history.begin(),history.end());history.clear();
        }
        if(triggered){if(rows.size()<capacity)rows.push_back(r);}
        else {if(pretrigger){history.push_back(r);if(history.size()>pretrigger)history.pop_front();}}
    }
    void write_traces(const char *csv,const char *vcd) {
        using namespace pipeline;
        std::ofstream c(csv),v(vcd);
        if(!c||!v)throw std::runtime_error("cannot create trace output");
        for(unsigned i=0;i<FIELD_COUNT;i++){if(i)c<<',';c<<names[i];}c<<'\n';
        v<<"$comment Actual RTL sampled before each rising edge. Simulation only; logical time is not measured board frequency. $end\n"
         <<"$timescale 1ns $end\n$scope module t09_sampled_pipeline $end\n$var wire 1 clock sample_clock $end\n";
        for(unsigned i=0;i<FIELD_COUNT;i++)v<<"$var wire "<<widths[i]<<" s"<<i<<' '<<names[i]<<" $end\n";
        v<<"$upscope $end\n$enddefinitions $end\n";
        for(const auto &r:rows){
            window.add(r);
            for(unsigned i=0;i<FIELD_COUNT;i++){if(i)c<<',';c<<r[i];}c<<'\n';
            v<<'#'<<r[CYCLE]*10<<"\n0clock\n";
            for(unsigned i=0;i<FIELD_COUNT;i++){
                v<<'b';for(int b=int(widths[i])-1;b>=0;b--)v<<((r[i]>>b)&1);
                v<<" s"<<i<<'\n';
            }
            v<<'#'<<r[CYCLE]*10+5<<"\n1clock\n";
        }
        if(!c||!v)throw std::runtime_error("trace output write failed");
    }
    void json(std::ostream &o) const {
        o<<"{\"schema\":1,\"sampling\":\"pre_rising_edge_active_cycles_only\","
          "\"scope\":\"whole program plus one bounded window; not CoreMark timed-kernel attribution or physical ILA\","
          "\"counter_semantics\":\"overlapping event counts; never an additive stall decomposition\","
          "\"stage_order\":[\"fetch_response\",\"decode\",\"execute\",\"memory\",\"writeback\"],"
          "\"axi_order\":[\"i_ar\",\"i_r\",\"d_ar\",\"d_r\",\"d_aw\",\"d_w\",\"d_b\"],"
          "\"whole_program\":";all.json(o);
        o<<",\"trace\":{\"trigger_kind\":\""<<kind<<"\",\"symbol_start\":"<<low
         <<",\"symbol_end_exclusive\":"<<high<<",\"triggered\":"<<(triggered?"true":"false")
         <<",\"complete\":"<<(rows.size()==capacity?"true":"false")
         <<",\"trigger_cycle\":"<<trigger_cycle<<",\"requested_samples\":"<<capacity
         <<",\"samples\":"<<rows.size()<<",\"pretrigger_samples\":"<<actual_pretrigger
         <<",\"first_cycle\":"<<(rows.empty()?0:rows.front()[pipeline::CYCLE])
         <<",\"last_cycle\":"<<(rows.empty()?0:rows.back()[pipeline::CYCLE])
         <<",\"counters\":";window.json(o);o<<"}}";
    }
};
