#include "Vce_component.h"
#include "verilated.h"
#include <array>
#include <vector>
#include <deque>
#include <cstdint>
#include <cstring>
#include <cstdio>
#include <stdexcept>
#include <algorithm>
#include <cfenv>
static uint32_t bits(float f){uint32_t u;std::memcpy(&u,&f,4);return u;}
static float fp(uint32_t u){float f;std::memcpy(&f,&u,4);return f;}
static float mul(float a,float b){volatile float f=a*b;return f;}
static float add(float a,float b){volatile float f=a+b;return f;}
static void check(bool v,const char*s){if(!v)throw std::runtime_error(s);}
struct Region {uint32_t base;std::vector<uint8_t> bytes;};
struct Burst {uint32_t address,id,size,left;unsigned wait;};
struct AcceptedTransfer {uint32_t address,bytes;};
struct Sim {
 Vce_component d;uint64_t cycles=0,read_bytes=0,write_bytes=0;unsigned seed=0x458123;
 std::vector<Region> memory;std::deque<Burst> reads;Burst write{};bool writing=false;
 unsigned b_wait=0;uint32_t b_id=0;unsigned aw_count=0,ar_count=0,b_count=0;
 std::vector<AcceptedTransfer> accepted_aw,accepted_ar;
 unsigned random(){seed^=seed<<13;seed^=seed>>17;seed^=seed<<5;return seed;}
 void region(uint32_t a,size_t n,uint8_t fill=0){memory.push_back({a,std::vector<uint8_t>(n,fill)});}
 uint8_t&byte(uint32_t a){for(auto&r:memory)if(a>=r.base&&uint64_t(a)<uint64_t(r.base)+r.bytes.size())return r.bytes[a-r.base];
  std::fprintf(stderr,"unmapped AXI address %08x\n",a);throw std::runtime_error("unmapped DDR access");}
 void word(uint32_t a,uint32_t u){for(unsigned i=0;i<4;i++)byte(a+i)=uint8_t(u>>(8*i));}
 uint32_t word(uint32_t a){uint32_t u=0;for(unsigned i=0;i<4;i++)u|=uint32_t(byte(a+i))<<(8*i);return u;}
 void tick(){
  d.clk=0;d.mem_awready=!writing&&!b_wait&&(random()%5!=0);d.mem_wready=writing&&(random()%5!=0);
  d.mem_arready=reads.size()<3&&(random()%5!=0);d.mem_bvalid=b_wait==1;d.mem_bid=b_id;d.mem_bresp=0;
  d.mem_rvalid=!reads.empty()&&reads.front().wait==0;d.mem_rresp=0;
  for(unsigned lane=0;lane<4;lane++)d.mem_rdata[lane]=0;
  if(d.mem_rvalid){auto&r=reads.front();d.mem_rid=r.id;d.mem_rlast=r.left==1;
   for(unsigned i=0;i<r.size;i++){unsigned lane=(r.address+i)&15;d.mem_rdata[lane/4]|=uint32_t(byte(r.address+i))<<(8*(lane%4));}}
  d.eval();
  bool ar=d.mem_arready&&d.mem_arvalid,aw=d.mem_awready&&d.mem_awvalid;
  bool r=d.mem_rvalid&&d.mem_rready,w=d.mem_wready&&d.mem_wvalid,b=d.mem_bvalid&&d.mem_bready;
  Burst incoming_r{d.mem_araddr,d.mem_arid,1u<<d.mem_arsize,unsigned(d.mem_arlen)+1,2+(random()%4)};
  Burst incoming_w{d.mem_awaddr,d.mem_awid,1u<<d.mem_awsize,unsigned(d.mem_awlen)+1,0};
  std::array<uint32_t,4> data{};for(unsigned i=0;i<4;i++)data[i]=d.mem_wdata[i];
  unsigned mask=d.mem_wstrb;bool last=d.mem_wlast;
  d.clk=1;d.eval();cycles++;check(cycles<80000000,"CE simulation deadline");
  if(b){b_wait=0;b_count++;}else if(b_wait>1)b_wait--;
  if(r){auto&x=reads.front();read_bytes+=x.size;x.address+=x.size;x.left--;x.wait=random()%3;if(!x.left)reads.pop_front();}
  else if(!reads.empty()&&reads.front().wait)reads.front().wait--;
  if(ar){check(d.mem_arburst==1,"nonincrementing AR");check(incoming_r.size<=16&&((incoming_r.address&4095)+incoming_r.size*incoming_r.left)<=4096,"AR 4KiB violation");accepted_ar.push_back({incoming_r.address,incoming_r.size*incoming_r.left});reads.push_back(incoming_r);ar_count++;}
  if(aw){check(d.mem_awburst==1,"nonincrementing AW");check(incoming_w.size<=16&&((incoming_w.address&4095)+incoming_w.size*incoming_w.left)<=4096,"AW 4KiB violation");accepted_aw.push_back({incoming_w.address,incoming_w.size*incoming_w.left});write=incoming_w;writing=true;aw_count++;}
  if(w){check(writing,"W without AW");check(last==(write.left==1),"WLAST mismatch");
   for(unsigned i=0;i<16;i++)if(mask&(1u<<i)){uint32_t a=(write.address&~15u)+i;check(a>=write.address&&a<write.address+write.size,"strobe outside transfer");byte(a)=uint8_t(data[i/4]>>(8*(i%4)));write_bytes++;}
   write.address+=write.size;write.left--;if(!write.left){writing=false;b_id=write.id;b_wait=4+(random()%8);}}
  d.eval();
 }
 void reset(){d.reset_n=0;d.mm_awvalid=d.mm_wvalid=d.mm_arvalid=0;d.external_isolate=d.window_isolate=0;
  for(int i=0;i<4;i++)tick();d.reset_n=1;for(int i=0;i<5;i++)tick();}
 void wr(uint32_t a,uint32_t v){d.mm_address=a;d.mm_write_data=v;d.mm_awvalid=d.mm_wvalid=1;
  bool aw=false,w=false;for(unsigned i=0;i<1000;i++){
   d.clk=0;d.eval();bool at=d.mm_awvalid&&d.mm_awready,wt=d.mm_wvalid&&d.mm_wready;tick();
   if(at){aw=true;d.mm_awvalid=0;}if(wt){w=true;d.mm_wvalid=0;}
   if(aw&&w&&d.mm_bvalid){check(d.mm_bresp==0,"MMIO write rejected");tick();return;}}
  throw std::runtime_error("MMIO write deadline");}
 uint32_t rd(uint32_t a){d.mm_address=a;d.mm_arvalid=1;
  for(unsigned i=0;i<1000;i++){d.clk=0;d.eval();bool at=d.mm_arready&&d.mm_arvalid;tick();if(at)d.mm_arvalid=0;
   if(d.mm_rvalid){check(d.mm_rresp==0,"MMIO read rejected");uint32_t v=d.mm_read_data;tick();return v;}}
  throw std::runtime_error("MMIO read deadline");}
 unsigned generation=0;
 std::array<uint32_t,40> execute(std::array<uint32_t,32> desc){
  desc[0]=0x34364543;desc[1]=1;desc[2]=128;desc[4]=rd(0x1c);desc[5]=1;
  desc[8]=0x4c4e3135;desc[9]=96;desc[10]=9;desc[12]=++generation;
  wr(0x10,1);wr(0x30,50000000);wr(0x34,0);
  for(unsigned i=0;i<32;i++)wr(0x200+4*i,desc[i]);wr(0x20,generation);
  uint32_t status=0;while(!((status=rd(0xc))&16)){for(unsigned i=0;i<47;i++)tick();}
  check(!writing&&!b_wait&&reads.empty()&&aw_count==b_count,"completion before DDR drain");
  uint32_t bank=status&128?0x500:0x400;std::array<uint32_t,40> c{};
  for(unsigned i=0;i<40;i++)c[i]=rd(bank+4*i);
  if(c[14]!=0)std::fprintf(stderr,"CE failed status=%d op=%u M=%u N=%u K=%u cycles=%llu\n",int32_t(c[14]),desc[14],desc[15],desc[16],desc[17],(unsigned long long)cycles);
  check(c[14]==0&&c[15]==1&&c[39]==generation,"CE completion failed");wr(0x28,generation);
  return c;
 }
 void init_linear(){
  region(0x88000000,128*896+64);region(0x98000000,128*14*4+64);
  region(0x9a000000,128*4+64);region(0xba000000,4*896+64);region(0xba010000,4*14*4+64);
  region(0xba100000,2048);region(0xa8000000,15728640,0xa5);
  for(unsigned n=0;n<128;n++){for(unsigned k=0;k<896;k++)byte(0x88000000+n*896+k)=uint8_t(int((n*11+k*7)%43)-21);
   for(unsigned g=0;g<14;g++)word(0x98000000+(n*14+g)*4,bits(float((n+g)%11+1)/713.0f));
   word(0x9a000000+n*4,bits(float(int(n%9)-4)/13.0f));}
  for(unsigned r=0;r<4;r++){for(unsigned k=0;k<896;k++)byte(0xba000000+r*896+k)=uint8_t(int((r*17+k*13)%31)-15);
   for(unsigned g=0;g<14;g++)word(0xba010000+(r*14+g)*4,bits(float((r+g)%7+1)/127.0f));}
 }
 void linear(unsigned rows,unsigned value){
  unsigned past=512-rows;uint32_t y=0xa8000000+((value*24*640+23*640+past)*128*4);
  std::array<uint32_t,32> desc{};desc[14]=2;desc[15]=rows;desc[16]=128;desc[17]=896;
  desc[18]=0x88000000;desc[19]=0xba100000;desc[20]=0x98000000;desc[21]=0x9a000000;
  desc[22]=0xba000000;desc[23]=0xba010000;desc[24]=512;
  uint64_t before=cycles;execute(desc);std::vector<uint32_t> baseline(rows*128);
  for(unsigned i=0;i<baseline.size();i++)baseline[i]=word(0xba100000+i*4);
  desc[19]=y;uint64_t out_before=write_bytes;execute(desc);check(write_bytes-out_before==rows*512,"direct KV output byte count");
  for(unsigned r=0;r<rows;r++)for(unsigned n=0;n<128;n++){
   float expected=0.0f;
   for(unsigned g=0;g<14;g++){int dot=0;for(unsigned k=0;k<64;k++)dot+=int(int8_t(byte(0xba000000+r*896+g*64+k)))*int(int8_t(byte(0x88000000+n*896+g*64+k)));
    expected=add(expected,mul(mul(float(dot),fp(word(0xba010000+(r*14+g)*4))),fp(word(0x98000000+(n*14+g)*4))));}
   expected=add(expected,fp(word(0x9a000000+n*4)));
   uint32_t got=word(y+(r*128+n)*4);if(got!=bits(expected))std::fprintf(stderr,"linear mismatch r=%u n=%u got=%08x want=%08x\n",r,n,got,bits(expected));
   check(got==bits(expected)&&got==baseline[r*128+n],"direct KV FP32 mismatch");}
  for(uint32_t a=y-512;a<y;a++)check(byte(a)==0xa5,"published prefix changed");
  for(uint32_t a=y+rows*512;a<y+rows*512+512;a++)check(byte(a)==0xa5,"KV after tail changed");
  std::printf("{\"kind\":\"real_ce_kv\",\"rows\":%u,\"value\":%u,\"past\":%u,\"words_compared\":%u,\"baseline_plus_direct_cycles\":%llu}\n",rows,value,past,rows*128,(unsigned long long)(cycles-before));
 }
 void pv(){
  constexpr unsigned len=65,heads=7,pad=128;region(0xba200000,heads*pad*4);region(0xac300ff0,heads*256);
  for(unsigned h=0;h<heads;h++)for(unsigned t=0;t<len;t++)word(0xba200000+(h*pad+t)*4,bits(float((h*13+t*3)%79+1)/97.0f));
  for(unsigned t=0;t<len;t++)for(unsigned i=0;i<64;i++)word(0xa8000000+(t*128+i)*4,bits(float(int((t*47+i*9)%137)-67)/89.0f));
  std::array<uint32_t,32> desc{};desc[14]=5;desc[15]=desc[16]=1;desc[17]=len;desc[18]=0xba200000;
  desc[19]=0xac300ff0;desc[20]=0xa8000000;desc[24]=heads;desc[25]=pad;desc[26]=512;
  uint64_t start=cycles,rb=read_bytes,wb=write_bytes;execute(desc);
  for(unsigned h=0;h<heads;h++)for(unsigned i=0;i<64;i++){
   std::array<float,pad> x{};for(unsigned t=0;t<len;t++)x[t]=mul(fp(word(0xba200000+(h*pad+t)*4)),fp(word(0xa8000000+(t*128+i)*4)));
   for(unsigned n=pad;n>1;n/=2)for(unsigned j=0;j<n/2;j++)x[j]=add(x[j*2],x[j*2+1]);
   check(word(0xac300ff0+(h*64+i)*4)==bits(x[0]),"integrated long PV tree mismatch");}
  check(read_bytes-rb==heads*pad*4+len*256&&write_bytes-wb==heads*256,"integrated PV payload mismatch");
  std::printf("{\"kind\":\"real_ce_long_pv\",\"len\":65,\"heads\":7,\"y_page_offset\":4080,\"words_compared\":448,\"cycles\":%llu,\"read_bytes\":%llu,\"write_bytes\":%llu}\n",(unsigned long long)(cycles-start),(unsigned long long)(read_bytes-rb),(unsigned long long)(write_bytes-wb));
 }
};
int main(int argc,char**argv){try{Verilated::commandArgs(argc,argv);std::fesetround(FE_TONEAREST);Sim s;s.reset();
 uint32_t pv=s.rd(0x130),head=s.rd(0x134);check((pv==0&&head==0)||(pv==0x50563531&&head==0x414d5831),"capability encoding");
 if(!pv){std::puts("CE_BASELINE_CAPS_PASS");return 0;}
 s.init_linear();for(unsigned rows:{1,4})for(unsigned value:{0,1})s.linear(rows,value);s.pv();
 check(!s.d.quarantined,"quarantined after successful runs");std::puts("CE_INTEGRATION_PASS");return 0;
 }catch(const std::exception&e){std::fprintf(stderr,"CE_FAIL %s\n",e.what());return 1;}}
