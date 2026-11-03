#include "Vpv_boundary_component.h"
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

#ifndef TEST_MAX_LENGTH
#error TEST_MAX_LENGTH must match the RTL parameter
#endif

static uint32_t bits(float x){uint32_t v;std::memcpy(&v,&x,4);return v;}
static float fp(uint32_t x){float v;std::memcpy(&v,&x,4);return v;}
static float mul(float a,float b){volatile float v=a*b;return v;}
static float add(float a,float b){volatile float v=a+b;return v;}
static void need(bool ok,const char *s){if(!ok)throw std::runtime_error(s);}
static uint64_t mix(uint64_t h,uint32_t v){for(unsigned n=0;n<4;n++){h^=(v>>(n*8))&255;h*=1099511628211ULL;}return h;}
static unsigned rounded(unsigned n){unsigned r=1;while(r<n)r*=2;return r;}

struct Case {
 std::string name;
 unsigned length=1,heads=7;
 uint32_t p=0xac100000,v=0xa8000000,y=0xac200000;
 bool local=false;
 char old_cross=0; // Exact defect expected in v3, never a wildcard failure.
 char error_path=0;
 unsigned error_number=0;
 int stop=0; // 1: cycle100, 2: while second V fragment response is pending.
 bool timeout=false;
 int shape_status=0;
};
struct Command {
 bool active=false,write=false;
 unsigned delay=0,bytes=0,scratch=0,response=0;
 uint32_t address=0;
 char path=0;
};
struct Sim {
 Vpv_boundary_component d;
 std::array<uint32_t,16384> scratch{};
 std::vector<uint32_t> p,v,y,pcov,vcov,ycov;
 const Case *c=nullptr;
 Command pending,held;
 bool have_held=false,old=false;
 FILE *trace=nullptr;
 uint64_t cycles=0,read_bytes=0,write_bytes=0,good_read=0,good_write=0;
 uint64_t command_hash=1469598103934665603ULL;
 unsigned commands=0,p_commands=0,v_commands=0,y_commands=0,rejected=0,injected=0;
 unsigned ready_stalls=0,drain_waits=0,cooldown=0,seed=0,sequence=1;
 uint32_t rejected_address=0,rejected_bytes=0;
 char rejected_path=0;
 bool stop_seen=false;
 explicit Sim(bool expect_old,FILE *t,unsigned s):old(expect_old),trace(t),seed(s){
  d.reset_n=0;d.submit=d.reset_grant=d.stop_new=d.abort_publish=0;
  d.run_limit=50000000;d.window_valid=0;
  for(int n=0;n<4;n++)tick();d.reset_n=1;for(int n=0;n<3;n++)tick();
 }
 unsigned rng(){seed^=seed<<13;seed^=seed>>17;seed^=seed<<5;return seed;}
 void tick(){
  d.clk=0;
  d.dma_ready=!pending.active&&!cooldown&&rng()%4!=0;
  d.dma_result_valid=pending.active&&pending.delay==0;
  d.dma_resp=pending.response;
  d.dma_idle=!pending.active;
  d.transport_drained=!pending.active&&!cooldown;
  d.eval();
  if(d.completion_valid)need(d.dma_idle&&d.transport_drained,"completion preceded DMA/drain");
  if(d.dma_idle&&!d.transport_drained)drain_waits++;
  Command offered;
  offered.address=d.dma_address;offered.bytes=(unsigned(d.dma_len)+1)*(1u<<d.dma_size);
  offered.scratch=d.dma_scratch;offered.write=d.dma_write;
  if(have_held&&d.dma_valid){
   need(held.address==offered.address&&held.bytes==offered.bytes&&
        held.scratch==offered.scratch&&held.write==offered.write,"DMA command changed while stalled");
  }
  have_held=d.dma_valid&&!d.dma_ready;
  if(have_held){held=offered;ready_stalls++;}
  bool take=d.dma_valid&&d.dma_ready;
  bool response=d.dma_result_valid&&d.dma_result_ready;
  unsigned ri=d.ram_address*4,mask=d.ram_mask;
  bool re=d.ram_en,we=d.window_en;
  std::array<uint32_t,4> q{},data{};
  uint32_t wq=0;
  if(re){need(ri+4<=scratch.size(),"scratch range");for(unsigned i=0;i<4;i++)q[i]=scratch[ri+i];}
  if(we){need(d.window_address<p.size(),"P window escaped sealed size");wq=p[d.window_address];}
  for(unsigned i=0;i<4;i++)data[i]=d.ram_data[i];
  d.clk=1;d.eval();cycles++;
  if(re)for(unsigned i=0;i<4;i++){
   uint32_t m=0;for(unsigned b=0;b<4;b++)if(mask&(1u<<(4*i+b)))m|=255u<<(8*b);
   scratch[ri+i]=(scratch[ri+i]&~m)|(data[i]&m);d.ram_q[i]=q[i];
  }
  if(we)d.window_q=wq;
  if(cooldown)cooldown--;
  if(response){
   if(!pending.response){if(pending.write)good_write+=pending.bytes;else good_read+=pending.bytes;}
   pending.active=false;cooldown=1+rng()%4;
  }else if(pending.active&&pending.delay)pending.delay--;
  if(take){
   need(c!=nullptr&&!pending.active,"DMA accepted with another command pending");
   Command x=offered;x.active=true;x.delay=2+rng()%12;
   need(d.dma_size==4&&x.bytes>0&&x.bytes<=512&&!(x.address&15)&&!(x.scratch&15)&&
        x.scratch+x.bytes<=65536,"invalid DMA shape or alignment");
   bool in_p=x.address>=c->p&&uint64_t(x.address)+x.bytes<=uint64_t(c->p)+p.size()*4;
   bool in_v=x.address>=c->v&&uint64_t(x.address)+x.bytes<=uint64_t(c->v)+v.size()*4;
   if(x.write)x.path='Y';else if(in_p&&!c->local)x.path='P';else if(in_v)x.path='V';
   need(x.path,"DMA escaped operand spans");
   unsigned count=x.path=='P'?++p_commands:x.path=='V'?++v_commands:++y_commands;
   commands++;
   bool page_ok=(x.address&4095u)+x.bytes<=4096;
   if(!page_ok){
    // Model nx_ce64_dma accepted_legal rejection: response DECERR, no DDR payload.
    x.response=3;rejected++;rejected_address=x.address;rejected_bytes=x.bytes;rejected_path=x.path;
   }else{
    if(c->error_path==x.path&&c->error_number==count){x.response=2;injected++;}
    if(x.path=='Y'){
     need(x.address>=c->y&&uint64_t(x.address)+x.bytes<=uint64_t(c->y)+c->heads*256,"Y escaped exact span");
     for(unsigned i=0;i<x.bytes/4;i++){unsigned index=(x.address-c->y)/4+i;y[16+index]=scratch[x.scratch/4+i];ycov[index]++;}
     write_bytes+=x.bytes;
    }else{
     const auto &src=x.path=='P'?p:v;auto &cov=x.path=='P'?pcov:vcov;
     uint32_t base=x.path=='P'?c->p:c->v;
     for(unsigned i=0;i<x.bytes/4;i++){unsigned index=(x.address-base)/4+i;scratch[x.scratch/4+i]=src[index];cov[index]++;}
     read_bytes+=x.bytes;
    }
   }
   for(uint32_t n:{uint32_t(x.path),x.address,x.bytes,x.scratch,x.response})command_hash=mix(command_hash,n);
   std::fprintf(trace,"{\"case\":\"%s\",\"max_length\":%u,\"command\":%u,\"cycle\":%llu,\"path\":\"%c\",\"address\":\"%08x\",\"bytes\":%u,\"scratch\":%u,\"page_ok\":%s,\"response\":%u}\n",
    c->name.c_str(),TEST_MAX_LENGTH,commands,(unsigned long long)cycles,x.path,x.address,x.bytes,x.scratch,page_ok?"true":"false",x.response);
   pending=x;
  }
  d.eval();
 }
 void run(const Case &spec){
  need(!pending.active&&!cooldown,"new request before drain");
  c=&spec;cycles=read_bytes=write_bytes=good_read=good_write=0;
  commands=p_commands=v_commands=y_commands=rejected=injected=ready_stalls=drain_waits=0;
  rejected_address=rejected_bytes=0;rejected_path=0;have_held=false;stop_seen=false;
  command_hash=1469598103934665603ULL;
  d.stop_new=d.abort_publish=d.reset_grant=0;d.run_limit=c->timeout?100:50000000;
  unsigned padded=rounded(c->length),pitch=c->length>64?padded:64;
  p.assign(c->heads*pitch,0);v.assign(c->length*128,0x7fc12345);
  y.assign(c->heads*64+32,0xdeadbeef);pcov.assign(p.size(),0);vcov.assign(v.size(),0);ycov.assign(c->heads*64,0);
  scratch.fill(0x7fc54321);
  for(unsigned h=0;h<c->heads;h++)for(unsigned t=0;t<c->length;t++)p[h*pitch+t]=bits(float((h*37+t*13)%121+1)/127.0f);
  for(unsigned t=0;t<c->length;t++)for(unsigned i=0;i<64;i++)v[t*128+i]=bits(float(int((t*103+i*17)%251)-125)/83.0f);
  std::array<uint32_t,32> desc{};
  desc[0]=0x34364543;desc[1]=1;desc[2]=128;desc[4]=1;desc[5]=1;
  desc[8]=0x4c4e3135;desc[9]=96;desc[10]=0x89abcdef;desc[11]=0x12345678;
  desc[12]=sequence++;desc[13]=0x76543210;desc[14]=5;desc[15]=desc[16]=1;
  desc[17]=c->length;desc[18]=c->local?0:c->p;desc[19]=c->y;desc[20]=c->v;
  desc[24]=c->heads;desc[25]=padded;desc[26]=512;desc[27]=c->local;
  for(unsigned i=0;i<32;i++)d.descriptor[i]=desc[i];
  d.window_valid=c->local;d.window_epoch=1;d.window_words=c->heads*64;
  d.window_length=c->length;d.window_padded=padded;
  d.window_session=(uint64_t(desc[11])<<32)|desc[10];d.window_sequence=(uint64_t(desc[13])<<32)|desc[12];
  d.submit=1;tick();d.submit=0;
  while(!d.completion_valid){
   if((c->stop==1&&cycles>=100)||(c->stop==2&&v_commands==2&&pending.active)){
    d.stop_new=1;stop_seen=true;
   }
   tick();need(cycles<50000000,"bounded PV test deadline");
  }
  need(!pending.active&&!cooldown,"PV completion not drained");
  int status=int32_t(d.completion[14]);
  need(d.completion[3]==1&&d.completion[38]==11&&d.completion[39]==11,"completion epoch/generation changed");
  for(unsigned i=10;i<14;i++)need(d.completion[i]==desc[i],"completion session/sequence changed");
  bool negative=old&&c->old_cross&&!c->shape_status;
  int expected=c->shape_status?c->shape_status:negative?-11:c->timeout?-7:(c->stop||c->error_path)?-11:0;
  if(status!=expected){std::fprintf(stderr,"case=%s status=%d expected=%d\n",c->name.c_str(),status,expected);throw std::runtime_error("completion status mismatch");}
  need(d.completion[15]==unsigned(status==0),"invalid completion success flag");
  if(negative){need(rejected==1&&rejected_path==c->old_cross,"expected specific v3 page rejection was not observed");}
  else need(rejected==0,"fixed or aligned request crossed a page");
  if(c->shape_status)need(commands==0,"invalid descriptor issued DMA");
  if(c->error_path&&!negative)need(injected==1,"targeted response error was not injected");
  if(c->stop&&!negative)need(stop_seen,"requested cancellation point not reached");
  if(status&&c->error_path!='Y')need(y_commands==0||(negative&&c->old_cross=='Y'),"Y issued after input failure/cancellation");
  unsigned words=0;uint64_t output_hash=1469598103934665603ULL;
  if(!status){
   for(unsigned h=0;h<c->heads;h++)for(unsigned dim=0;dim<64;dim++){
    std::vector<float> values(padded,0);
    for(unsigned t=0;t<c->length;t++)values[t]=mul(fp(p[h*pitch+t]),fp(v[t*128+dim]));
    for(unsigned n=padded;n>1;n/=2)for(unsigned t=0;t<n/2;t++)values[t]=add(values[2*t],values[2*t+1]);
    uint32_t want=bits(values[0]),got=y[16+h*64+dim];
    if(got!=want){std::fprintf(stderr,"case=%s h=%u dim=%u got=%08x expected=%08x\n",c->name.c_str(),h,dim,got,want);throw std::runtime_error("FP32 adjacent tree mismatch");}
    need(ycov[h*64+dim]==1,"missing/duplicate Y payload");words++;output_hash=mix(output_hash,got);
   }
   for(unsigned n:pcov)need(n==unsigned(!c->local),"missing/duplicate P payload");
   for(unsigned t=0;t<c->length;t++)for(unsigned dim=0;dim<128;dim++)need(vcov[t*128+dim]==unsigned(dim<64),"missing/duplicate/extra V payload");
   need(read_bytes==(c->local?0:uint64_t(c->heads)*pitch*4)+uint64_t(c->length)*256,"wrong P/V byte count");
   need(write_bytes==uint64_t(c->heads)*256,"wrong Y byte count");
   uint64_t reported_read=uint64_t(d.completion[20])|(uint64_t(d.completion[21])<<32);
   uint64_t reported_write=uint64_t(d.completion[22])|(uint64_t(d.completion[23])<<32);
   need(reported_read==good_read&&reported_write==good_write,"completion byte count changed");
  }
  for(unsigned i=0;i<16;i++)need(y[i]==0xdeadbeef&&y[y.size()-1-i]==0xdeadbeef,"Y surrounding sentinel changed");
  std::printf("{\"case\":\"%s\",\"max_length\":%u,\"length\":%u,\"local_p\":%s,\"p\":\"%08x\",\"v\":\"%08x\",\"y\":\"%08x\",\"status\":%d,\"success\":%s,\"result\":\"%s\",\"cycles\":%llu,\"words_checked\":%u,\"read_bytes\":%llu,\"write_bytes\":%llu,\"p_commands\":%u,\"v_commands\":%u,\"y_commands\":%u,\"ready_stalls\":%u,\"drain_waits\":%u,\"page_rejections\":%u,\"rejected_path\":\"%c\",\"rejected_address\":\"%08x\",\"rejected_bytes\":%u,\"injected_errors\":%u,\"command_hash\":\"%016llx\",\"output_hash\":\"%016llx\"}\n",
   c->name.c_str(),TEST_MAX_LENGTH,c->length,c->local?"true":"false",c->p,c->v,c->y,status,status==0?"true":"false",negative?"EXPECTED_NEGATIVE":status?"EXPECTED_FAILURE":"PASS",
   (unsigned long long)cycles,words,(unsigned long long)read_bytes,(unsigned long long)write_bytes,p_commands,v_commands,y_commands,ready_stalls,drain_waits,rejected,rejected_path?rejected_path:'-',rejected_address,rejected_bytes,injected,(unsigned long long)command_hash,(unsigned long long)output_hash);
  std::fflush(stdout);d.stop_new=0;tick(); // Accept completion, retain actual controller state for any next submit.
 }
};

int main(int argc,char **argv){
 try{
  Verilated::commandArgs(argc,argv);std::fesetround(FE_TONEAREST);
  bool old=false;unsigned seed=0x11223344;const char *trace_path=nullptr;
  for(int i=1;i<argc;i++){
   std::string a=argv[i];if(a=="--expect-v3-defect")old=true;
   else if(a=="--trace"&&i+1<argc)trace_path=argv[++i];
   else if(a=="--seed"&&i+1<argc)seed=std::stoul(argv[++i],nullptr,0);
   else throw std::runtime_error("unknown/missing argument");
  }
  need(trace_path,"--trace is required");FILE *trace=std::fopen(trace_path,"w");need(trace,"cannot open DMA trace");
  std::vector<Case> cases;
  for(unsigned len:{1,63,64}){
   Case base;base.length=len;base.name="aligned_ddr_len"+std::to_string(len);cases.push_back(base);
   for(uint32_t off:{0xf00u,0xff0u}){
    Case py=base;py.local=true;py.y=0xac00a000+off;py.old_cross='Y';py.name="local_y_"+std::to_string(off)+"_len"+std::to_string(len);cases.push_back(py);
    Case pr=base;pr.p+=off;pr.old_cross='P';pr.name="external_p_"+std::to_string(off)+"_len"+std::to_string(len);cases.push_back(pr);
   }
   Case vr=base;vr.local=true;vr.v+=0xff0;vr.old_cross='V';vr.name="short_v_ff0_len"+std::to_string(len);cases.push_back(vr);
  }
  Case production;production.name="production_first_group_len1";production.local=true;production.y=0xac00a800;cases.push_back(production);
  Case vfit;vfit.name="short_v_f00_exact_page_end";vfit.local=true;vfit.v+=0xf00;cases.push_back(vfit);
  Case vend;vend.name="short_v_f10_last16_fragment";vend.local=true;vend.v+=0xf10;vend.old_cross='V';cases.push_back(vend);
  Case vlater;vlater.name="short_v_cross_at_later_row";vlater.length=64;vlater.local=true;vlater.v+=0x1f0;vlater.old_cross='V';cases.push_back(vlater);
  for(unsigned len:{65,512}){
   if(TEST_MAX_LENGTH<512){Case x;x.length=len;x.name="unsupported_len"+std::to_string(len);x.shape_status=-4;cases.push_back(x);continue;}
   for(uint32_t off:{0u,0xf00u,0xff0u}){
    Case x;x.length=len;x.p+=0xe00;x.y+=off;x.name="long_y_"+std::to_string(off)+"_len"+std::to_string(len);cases.push_back(x);
   }
  }
  if(TEST_MAX_LENGTH==512){Case x;x.length=65;x.p+=0xf00;x.name="long_p_unaligned_still_rejected";x.shape_status=-4;cases.push_back(x);}
  for(char path:{'P','V','Y'}){Case x;x.name=std::string("response_error_")+path;x.error_path=path;x.error_number=1;cases.push_back(x);}
  Case timeout;timeout.name="timeout_during_short_pv";timeout.length=64;timeout.timeout=true;cases.push_back(timeout);
  Case stop;stop.name="stop_during_short_pv";stop.length=64;stop.stop=1;cases.push_back(stop);
  unsigned index=0;
  for(const Case &c:cases){Sim s(old,trace,seed+0x9e3779b9u*++index);s.run(c);}
  // Neither response failure nor cancellation resets the DUT. The following
  // successful submit must initialize the V row offset itself.
  for(bool cancel:{false,true}){
   Sim s(old,trace,seed+0x9e3779b9u*++index);
   Case x;x.local=true;x.v+=0xff0;x.old_cross='V';
   x.name=cancel?"stop_with_second_v_fragment_pending":"response_error_second_v_fragment";
   if(cancel)x.stop=2;else{x.error_path='V';x.error_number=2;}s.run(x);
   Case next;next.local=true;next.name=cancel?"next_submit_after_v_stop":"next_submit_after_v_error";s.run(next);
  }
  std::fclose(trace);
  std::printf("{\"summary\":\"PASS_EXPECTATIONS\",\"mode\":\"%s\",\"max_length\":%u,\"cases\":%zu,\"seed\":%u}\n",old?"v3_expected_negative":"fixed",TEST_MAX_LENGTH,cases.size()+4,seed);
  return 0;
 }catch(const std::exception &e){std::fprintf(stderr,"PV_BOUNDARY_FAIL %s\n",e.what());return 1;}
}
