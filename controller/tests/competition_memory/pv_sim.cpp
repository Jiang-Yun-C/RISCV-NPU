#include "Vpv_component.h"
#include "verilated.h"
#include <array>
#include <vector>
#include <cstdint>
#include <cstring>
#include <cstdio>
#include <cstdlib>
#include <cfenv>
#include <stdexcept>
#include <string>

static uint32_t bits(float x){uint32_t v;std::memcpy(&v,&x,4);return v;}
static float fp(uint32_t x){float v;std::memcpy(&v,&x,4);return v;}
static float mul(float a,float b){volatile float v=a*b;return v;}
static float add(float a,float b){volatile float v=a+b;return v;}
static void require(bool ok,const char *s){if(!ok)throw std::runtime_error(s);}
struct Sim {
 Vpv_component d;
 std::array<uint32_t,16384> scratch{};
 std::vector<uint32_t> p,v,y;
 uint64_t cycles=0,read_bytes=0,write_bytes=0;
 uint32_t commands=0,read_commands=0,write_commands=0;
 uint32_t y_base=0xac200000;
 int pending=0,error_at=0;
 unsigned seed=0x11223344;
 unsigned rng(){seed^=seed<<13;seed^=seed>>17;seed^=seed<<5;return seed;}
 void tick(){
  d.clk=0;d.dma_ready=pending==0&&(rng()%5!=0);
  d.dma_result_valid=pending==1;d.dma_idle=pending==0;
  d.dma_resp=(pending==1&&error_at&&commands==(unsigned)error_at)?2:0;
  d.eval();
  std::array<uint32_t,4> q{};bool re=d.ram_en;
  unsigned ri=d.ram_address*4;
  if(re){require(ri+4<=scratch.size(),"scratch read range");for(unsigned i=0;i<4;i++)q[i]=scratch[ri+i];}
  bool take=d.dma_valid&&d.dma_ready;unsigned size=1u<<d.dma_size;
  unsigned count=(d.dma_len+1)*size,off=d.dma_scratch,addr=d.dma_address;
  bool wr=d.dma_write;unsigned mask=d.ram_mask;
  std::array<uint32_t,4> data{};for(unsigned i=0;i<4;i++)data[i]=d.ram_data[i];
  d.clk=1;d.eval();cycles++;
  if(re){
   for(unsigned i=0;i<4;i++){
    uint32_t m=0;for(unsigned b=0;b<4;b++)if(mask&(1u<<(4*i+b)))m|=255u<<(8*b);
    scratch[ri+i]=(scratch[ri+i]&~m)|(data[i]&m);
    d.ram_q[i]=q[i];
   }
  }
  if(pending)pending--;
  if(take){
   commands++;require(count&&count<=512&&off+count<=65536,"DMA shape/scratch");
   require((addr&4095u)+count<=4096,"DMA crossed 4KiB");
   require(!(off&15)&&size==16,"DMA alignment/size");
   if(wr){
    require(addr>=y_base&&uint64_t(addr)+count<=y_base+y.size()*4,"write escaped output");
    for(unsigned i=0;i<count/4;i++)y[(addr-y_base)/4+i]=scratch[off/4+i];
    write_bytes+=count;write_commands++;
   }else{
    const std::vector<uint32_t> *a=nullptr;uint32_t base=0;
    if(addr>=0xac100000&&uint64_t(addr)+count<=0xac100000+p.size()*4){a=&p;base=0xac100000;}
    if(addr>=0xa8000000&&uint64_t(addr)+count<=0xa8000000+v.size()*4){a=&v;base=0xa8000000;}
    require(a,"read escaped operands");
    for(unsigned i=0;i<count/4;i++)scratch[off/4+i]=(*a)[(addr-base)/4+i];
    read_bytes+=count;read_commands++;
   }
   pending=2+(rng()%5);
  }
  d.eval();
 }
 void reset(){d.reset_n=0;d.submit=d.reset_grant=d.stop_new=d.abort_publish=0;d.run_limit=50000000;
  for(int i=0;i<4;i++)tick();d.reset_n=1;for(int i=0;i<3;i++)tick();cycles=0;}
 uint64_t run(unsigned len,unsigned heads,unsigned padded,int fault=0,unsigned page_offset=0){
  reset();error_at=fault>0?fault:0;y_base+=page_offset;unsigned pitch=len>64?padded:64;
  if(fault==-1)d.run_limit=100;
  p.assign(heads*pitch,0);v.assign(len*128,0x7fc12345);y.assign(heads*64,0xdeadbeef);
  for(unsigned h=0;h<heads;h++)for(unsigned t=0;t<len;t++)p[h*pitch+t]=bits(float((h*37+t*13)%121+1)/127.0f);
  for(unsigned t=0;t<len;t++)for(unsigned i=0;i<64;i++)v[t*128+i]=bits(float(int((t*103+i*17)%251)-125)/83.0f);
  std::array<uint32_t,32> desc{};
  desc[0]=0x34364543;desc[1]=1;desc[2]=128;desc[4]=1;desc[5]=1;
  desc[8]=0x4c4e3135;desc[9]=96;desc[10]=1;desc[12]=1;desc[14]=5;
  desc[15]=desc[16]=1;desc[17]=len;desc[18]=0xac100000;desc[19]=y_base;
  desc[20]=0xa8000000;desc[24]=heads;desc[25]=padded;desc[26]=512;
  for(int i=0;i<32;i++)d.descriptor[i]=desc[i];d.submit=1;tick();d.submit=0;
  while(!d.completion_valid){if(fault==-2&&cycles>100)d.stop_new=1;tick();require(cycles<50000000,"PV timeout");}
  int status=int32_t(d.completion[14]);
  if(fault){require(status!=0,"injected error accepted");require(write_commands==0,"published Y after failure");
   if(fault==-3)require(commands==0,"malformed shape issued DMA");
   std::printf("{\"fault\":%d,\"status\":%d,\"dma_commands\":%u,\"write_commands\":%u}\n",fault,status,commands,write_commands);return cycles;}
  require(status==0&&d.completion[15]==1,"PV failed");
  for(unsigned h=0;h<heads;h++)for(unsigned i=0;i<64;i++){
   std::vector<float> values(padded,0);
   for(unsigned t=0;t<len;t++)values[t]=mul(fp(p[h*pitch+t]),fp(v[t*128+i]));
   for(unsigned n=padded;n>1;n/=2)for(unsigned t=0;t<n/2;t++)values[t]=add(values[2*t],values[2*t+1]);
   if(y[h*64+i]!=bits(values[0])){
    std::fprintf(stderr,"PV mismatch len=%u heads=%u h=%u dim=%u got=%08x expected=%08x\n",len,heads,h,i,y[h*64+i],bits(values[0]));
    throw std::runtime_error("PV FP32 tree mismatch");
   }
  }
  require(read_bytes==uint64_t(heads)*pitch*4+uint64_t(len)*256,"V reread or missing P");
  require(write_bytes==uint64_t(heads)*256,"wrong output payload");
  uint64_t ct=uint64_t(d.completion[24])|(uint64_t(d.completion[25])<<32);
  require(ct>0&&ct<=cycles,"cycle report mismatch");
  std::printf("{\"len\":%u,\"heads\":%u,\"padded\":%u,\"cycles\":%llu,\"read_bytes\":%llu,\"write_bytes\":%llu,\"read_commands\":%u,\"words_checked\":%u}\n",
   len,heads,padded,(unsigned long long)ct,(unsigned long long)read_bytes,(unsigned long long)write_bytes,read_commands,heads*64);
  return ct;
 }
};
int main(int argc,char **argv){
 try{Verilated::commandArgs(argc,argv);std::fesetround(FE_TONEAREST);
  if(argc>1){unsigned len=std::stoul(argv[1]),heads=argc>2?std::stoul(argv[2]):2,pad=1;while(pad<len)pad*=2;Sim s;s.run(len,heads,pad);return 0;}
  for(unsigned len:{1,3,63,64,65,127,128,129,255,256,257,511,512}){
   unsigned pad=1;while(pad<len)pad*=2;unsigned heads=len<=128?7:len<=256?4:2;Sim s;s.run(len,heads,pad);
  }
  Sim full;full.run(512,7,512);
  Sim crossing;crossing.run(65,7,128,0,4080);
  for(int at:{1,2,5,-1,-2}){Sim fail;fail.run(65,2,128,at);}
  Sim malformed;malformed.run(513,7,1024,-3);
  std::puts("PV_RTL_PASS");return 0;
 }catch(const std::exception &e){std::fprintf(stderr,"PV_FAIL %s\n",e.what());return 1;}
}
