#include "Vmetadata_component.h"
#include "verilated.h"
#include <array>
#include <deque>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <stdexcept>
static uint32_t bits(float x){uint32_t u;std::memcpy(&u,&x,4);return u;}
struct Expected {uint32_t value;uint64_t tag;std::array<uint32_t,3> aux;};
int main(int argc,char**argv){try{
 Verilated::commandArgs(argc,argv);bool fixed_ready=argc>1&&!std::strcmp(argv[1],"--fixed-ready");
 Vmetadata_component d;std::deque<Expected> q;
 unsigned issued=0,retired=0,stalls=0,cycles=0;bool offered=false;d.reset_n=0;d.valid=d.ready=0;
 auto tick=[&](){d.clk=0;d.eval();d.clk=1;d.eval();cycles++;};
 for(unsigned i=0;i<4;i++)tick();d.reset_n=1;
 while(retired<1024&&cycles<20000){
  d.clk=0;if(!offered&&issued<1024&&cycles%11!=0)offered=true;
  d.valid=offered;d.ready=fixed_ready||((cycles%29>=9)&&(cycles%7!=0));
  float a=float(int(issued%127)-63)/17.0f,b=float((issued*23)%53+1)/19.0f;
  volatile float product=a*b;d.a=bits(a);d.b=bits(b);
  uint64_t tag=(uint64_t(0xa1b2c300+(issued%251))<<32)|(0x12340000+issued);
  d.tag=tag;std::array<uint32_t,3> aux{0xdead0000u+issued,0xabcd1000u+(issued*133),issued&8191u};
  for(unsigned i=0;i<3;i++)d.aux[i]=aux[i];d.eval();
  bool in=d.valid&&d.input_ready,out=d.output_valid&&d.ready;
  if(d.output_valid&&!d.ready)stalls++;
  if(out){
   if(q.empty())throw std::runtime_error("unexpected FP output");Expected x=q.front();q.pop_front();
   if(d.result!=x.value||d.output_tag!=x.tag||d.output_aux[0]!=x.aux[0]||d.output_aux[1]!=x.aux[1]||d.output_aux[2]!=x.aux[2]){
    std::fprintf(stderr,"FP metadata/value mismatch at %u tag=%016llx expected=%016llx result=%08x expected_result=%08x\n",retired,
      (unsigned long long)d.output_tag,(unsigned long long)x.tag,d.result,x.value);
    return 1;
   }retired++;
  }
  if(in){q.push_back({bits(product),tag,aux});issued++;offered=false;}
  d.clk=1;d.eval();cycles++;
 }
 if(retired!=1024||!q.empty()||(!fixed_ready&&stalls<100))throw std::runtime_error("metadata coverage/deadline");
 std::printf("{\"status\":\"PASS\",\"fp_requests\":%u,\"distinct_epochs\":251,\"distinct_sequences\":1024,\"output_backpressure\":%s,\"backpressure_cycles\":%u,\"aux_bits\":77,\"cycles\":%u}\n",retired,fixed_ready?"false":"true",stalls,cycles);
 std::puts("FP_METADATA_PASS");return 0;
 }catch(const std::exception&e){std::fprintf(stderr,"FP_METADATA_FAIL %s\n",e.what());return 1;}}
