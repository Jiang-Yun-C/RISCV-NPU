#include "Vnx_ce64_head_argmax.h"
#include "verilated.h"
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <vector>
#include <stdexcept>
#include <string>
#include <cmath>
static constexpr unsigned N=151936,BASE=0xac0cc000;
static uint32_t bits(float x){uint32_t v;std::memcpy(&v,&x,4);return v;}
static float fp(uint32_t x){float v;std::memcpy(&v,&x,4);return v;}
static void check(bool ok,const char *s){if(!ok)throw std::runtime_error(s);}
struct Sim {
 Vnx_ce64_head_argmax d;uint64_t cycles=0;
 void tick(){d.clk=0;d.eval();d.clk=1;d.eval();cycles++;}
 void begin(){
  d.reset_n=0;d.start=d.revoke=d.complete=d.aw_take=d.w_take=d.w_last=0;
  for(int i=0;i<4;i++)tick();d.reset_n=1;d.epoch=3;d.generation=17;
  for(int i=0;i<32;i++)d.descriptor[i]=0;
  d.descriptor[14]=2;d.descriptor[15]=1;d.descriptor[16]=N;
  d.descriptor[19]=BASE;d.descriptor[10]=0x1234;d.descriptor[11]=8;
  d.descriptor[12]=0x5678;d.descriptor[13]=9;d.start=1;tick();d.start=0;tick();
  check(d.result[0]==0,"stale valid after start");
 }
 void write(const std::vector<uint32_t>&v,int fault,bool narrow=false){
  if(narrow){
   for(unsigned i=0;i<N;i++){
    d.aw_address=BASE+i*4;d.aw_size=2;d.aw_length=0;d.aw_take=1;
    d.w_take=1;d.w_last=1;d.w_mask=0xf<<((i&3)*4);
    for(unsigned lane=0;lane<4;lane++)d.w_data[lane]=lane==(i&3)?v[i]:0x7fc12345;
    tick();d.aw_take=d.w_take=0;if(i%31==0)tick();
   }
   tick();return;
  }
  unsigned end=fault==3?N-4:N;
  for(unsigned off=0;off<end;){
   if(off%4096==0){d.aw_take=d.w_take=0;for(int t=0;t<3;t++)tick();}
   unsigned count=std::min(128u,end-off);
   d.aw_address=BASE+off*4;d.aw_size=4;d.aw_length=count/4-1;d.aw_take=1;d.w_take=0;tick();d.aw_take=0;
   for(unsigned j=0;j<count;j+=4){
    if((off+j)%100==0){d.w_take=0;tick();}
    d.w_take=1;d.w_last=j+4==count;d.w_mask=0xffff;
    if(fault==4&&off+j==128)d.w_mask=0x0fff;
    if(fault==5&&off+j==0)d.w_last=1;
    for(unsigned lane=0;lane<4;lane++)d.w_data[lane]=v[off+j+lane];
    tick();
   }
   d.w_take=0;off+=count;
  }
  d.aw_take=d.w_take=0;tick();
  if(fault==10){ // A duplicate output must fail coverage/ordering.
   d.aw_address=BASE;d.aw_size=4;d.aw_length=0;d.aw_take=1;tick();d.aw_take=0;
   d.w_take=d.w_last=1;d.w_mask=0xffff;for(unsigned i=0;i<4;i++)d.w_data[i]=v[i];tick();d.w_take=0;
  }
  if(fault==11){d.aw_address=BASE+N*4;d.aw_size=4;d.aw_length=0;d.aw_take=1;tick();d.aw_take=0;}
 }
 void finish(int fault){
  for(int i=0;i<40;i++)d.completion[i]=0;
  d.completion[3]=3;d.completion[10]=0x1234;d.completion[11]=8;
  d.completion[12]=0x5678;d.completion[13]=9;d.completion[15]=1;d.completion[38]=d.completion[39]=17;
  if(fault==6)d.completion[3]++;
  if(fault==7)d.completion[12]++;
  if(fault==8)d.completion[39]++;
  if(fault==9)d.completion[14]=uint32_t(-11);
  if(fault==12)d.completion[38]++;
  if(fault==13)d.completion[10]++;
  if(fault==14)d.completion[15]=0;
  d.complete=1;tick();d.complete=0;tick();
 }
};
static void run(unsigned kind){
 Sim s;s.begin();std::vector<uint32_t> data(N);
 for(unsigned i=0;i<N;i++)data[i]=bits(float(int((i*37)%1709)-855)/21.0f);
 int fault=0;
 if(kind==1)for(unsigned i=0;i<N;i++)data[i]=(i&1)?0:0x80000000;
 if(kind==2){data[123]=bits(1000.25f);data[456]=data[123];}
 if(kind==3)data[N-1]=0x7fc12345;
 if(kind==4)data[0]=0x7f800000;
 if(kind>=5&&kind<=11)fault=int(kind)-2;
 if(kind==13)data[N-1]=0xff800000;
 if(kind==14)data[N/2]=0x7f800001;
 if(kind==15)for(unsigned i=0;i<N;i++)data[i]=(i&1)?0x80000000:0;
 if(kind==16)for(unsigned i=0;i<N;i++)data[i]=(i%7==0)?0x007fffff:0x80000001;
 if(kind>=17)fault=int(kind)-7;
 s.write(data,fault,kind==12);s.finish(fault);
 bool finite=true;unsigned best=0;
 for(unsigned i=0;i<N;i++){finite&=std::isfinite(fp(data[i]));if(fp(data[i])>fp(data[best]))best=i;}
 bool want=finite&&fault==0;
 check(bool(s.d.result[0]&1)==want,"valid mismatch");
 if(want){
  check(s.d.result[1]==best,"argmax token mismatch");check(s.d.result[2]==data[best],"argmax value mismatch");
  check(s.d.result[3]==N&&s.d.result[4]==3&&s.d.result[5]==17,"counts/identity mismatch");
  check(s.d.result[6]==0x1234&&s.d.result[7]==8&&s.d.result[8]==0x5678&&s.d.result[9]==9,"session mismatch");
  check(s.d.result[10]==BASE&&s.d.result[11]==N,"shape mismatch");
  for(int i=0;i<16;i++)s.tick();check(s.d.result[0]==1,"successful result did not persist");
 }
 s.d.revoke=1;s.tick();check(!(s.d.result[0]&1),"revoke retained token");
 std::printf("{\"case\":%u,\"finite\":%s,\"injected_fault\":%d,\"valid\":%s,\"words\":%u,\"cycles\":%llu}\n",
 kind,finite?"true":"false",fault,want?"true":"false",N,(unsigned long long)s.cycles);
}
int main(int argc,char **argv){try{Verilated::commandArgs(argc,argv);for(unsigned k=0;k<22;k++)run(k);
 std::puts("ARGMAX_RTL_PASS");return 0;}catch(const std::exception&e){std::fprintf(stderr,"ARGMAX_FAIL %s\n",e.what());return 1;}}
