/* Actual CE adapter + actual tensor validation with an explicitly mocked
 * completed device call. Frontend lease minting is checked separately. */
#define _GNU_SOURCE
#include "ce64_backend.h"
#define NX_OK NX_ACCEL_OK
#define NX_LINEAR NX_ACCEL_LINEAR
#define NX_ROPE NX_ACCEL_ROPE
#define NX_SWIGLU NX_ACCEL_SWIGLU
#define nx_linear nx_accel_linear
#include "ce64_linear.h"
#include "opt12.h"
#undef nx_linear
#undef NX_SWIGLU
#undef NX_ROPE
#undef NX_LINEAR
#undef NX_OK
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
static unsigned checks,calls,failure;static uint64_t ticks;
static nx_kv_tail expected;static int lease_live;
static uint32_t output_address,head_words[12],head_cap=CE64_HEAD_ARGMAX_MAGIC;
#define CHECK(x) do{checks++;if(!(x)){fprintf(stderr,"backend line %d: %s\n",__LINE__,#x);exit(1);}}while(0)
uint64_t nx_port_ticks(void){return ticks+=10;}
int nx_kv_tail_valid(const nx_kv_tail *v,const nx_matrix *w,const float *y){
 (void)w;return lease_live&&v&&!memcmp(v,&expected,sizeof(expected))&&v->destination==(uintptr_t)y;
}
static void fence(void *p){(void)p;}
static uint32_t read32(void *p,uint32_t a){(void)p;
 if(a==CE64_MMIO_BASE+CE64_HEAD_ARGMAX_CAPABILITY)return head_cap;
 if(a>=CE64_MMIO_BASE+CE64_HEAD_ARGMAX_BASE&&a<CE64_MMIO_BASE+CE64_HEAD_ARGMAX_BASE+48)return head_words[(a-CE64_MMIO_BASE-CE64_HEAD_ARGMAX_BASE)/4];
 return 0;
}
nx_status nx_opt12_run(nx_ce64_transport*t,const nx_call*c,const nx_opt12_job*j,nx_opt12_view*v,struct nx_stream_result*r){(void)t;(void)c;(void)j;(void)v;(void)r;return NX_EUNSUPPORTED;}
nx_status nx_opt12_run_resident(nx_ce64_transport*t,const nx_call*c,const nx_opt12_job*j,nx_opt12_view*v,struct nx_stream_result*r){return nx_opt12_run(t,c,j,v,r);}
nx_status nx_opt12_run_sealed_norm(nx_ce64_transport*t,const nx_call*c,const nx_opt12_job*j,nx_opt12_view*v,struct nx_stream_result*r){return nx_opt12_run(t,c,j,v,r);}
nx_status nx_opt12_acquire(nx_ce64_context*c,const nx_opt12_view*v){(void)c;(void)v;return NX_EUNSUPPORTED;}
nx_status nx_pv_run(nx_ce64_transport*t,const nx_call*c,uint32_t p,uint32_t v,uint32_t y,uint32_t h,uint32_t l,uint32_t n,struct nx_stream_result*r){(void)t;(void)c;(void)p;(void)v;(void)y;(void)h;(void)l;(void)n;(void)r;return NX_EUNSUPPORTED;}
nx_status nx_pv_window_run(nx_ce64_transport*t,const nx_call*c,const float*p,uint32_t v,uint32_t y,uint32_t h,uint32_t l,uint32_t n,struct nx_stream_result*r){(void)t;(void)c;(void)p;(void)v;(void)y;(void)h;(void)l;(void)n;(void)r;return NX_EUNSUPPORTED;}
nx_status nx_linear_run_v2(nx_ce64_context*c,const nx_call*call,const nx_accel_linear*j,nx_stats*s){
 CHECK(call->session==c->base.session&&call->sequence==c->base.sequence+1);calls++;output_address=j->y.address;
 float *p=(void *)(uintptr_t)j->y.address;unsigned count=j->y.shape[0]*j->y.shape[1];
 for(unsigned i=0;i<count;i++)p[i]=(float)i*.25f;
 *s=(nx_stats){.output_valid=1,.backend_cycles=31};c->base.sequence=call->sequence;c->generation++;
 c->base.last=*s;
 if(failure==1)return NX_EIO;
 if(failure==2)s->output_valid=0;
 if(failure==3)c->epoch++;
 if(failure==4)c->base.session++;
 if(failure==5)c->base.sequence++;
 if(failure==6)ticks+=1000001;
 if(failure==7)c->base.state=NX_ACCEL_FAULTED;
 if(failure==8)lease_live=0;
 return 0;
}
static void map(uintptr_t a,size_t n){CHECK(mmap((void*)a,n,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED_NOREPLACE,-1,0)==(void*)a);}
int main(void){
 map(0xa8000000,15728640);map(0xac000000,2*1024*1024);map(0xba100000,1024*1024);
 nx_weights model={0};
 for(unsigned l=0;l<24;l++)model.layer[l].k=model.layer[l].v=(nx_matrix){.n=128,.k=896,.q=(void*)0x88000000,.s=(void*)0x98000000};
 nx_linear_binding binding={.aq_address=0xba1c0000,.aq_bytes=19456,.sa_address=0xba1c5000,.sa_bytes=1216};
 nx_ce64_context c={.base={.state=NX_ACCEL_IDLE,.session=1,.initialized=1,.io={.fence=fence,.read32=read32}},.epoch=1,.binding=&binding};
 nxr_ce64_backend b={.accelerator=&c,.input=(void*)0xba100000,.output=(void*)0xba120000,
  .input_bytes=77824,.output_bytes=607744,.timeout_ticks=1000000,.kv_arena=0xa8000000,
  .kv_arena_bytes=15728640,.kv_model=&model,.private_output_address=0xac000000,.private_output_bytes=835072};
 float *x=(void*)0xac000000;unsigned nonce=1;
 for(unsigned rows=1;rows<=4;rows++)for(unsigned layer=0;layer<24;layer+=23)for(unsigned value=0;value<2;value++){
  unsigned past=512-rows;float*y=(void*)(uintptr_t)(0xa8000000u+((value*24*640+layer*640+past)*128*4));
  const nx_matrix*w=value?&model.layer[layer].v:&model.layer[layer].k;
  expected=(nx_kv_tail){.owner=(void*)0x1234,.serial=nonce++,.arena=0xa8000000,.destination=(uintptr_t)y,
   .abi=NX_KV_TAIL_ABI,.layer=layer,.value=value,.past=past,.rows=rows,.layers=24,.capacity=640,.width=128};
  lease_live=1;float baseline[512];
  CHECK(!nxr_ce64_linear(&b,x,rows,w,y));CHECK(output_address==0xba120000);memcpy(baseline,y,rows*128*4);
  uint64_t before=b.kv_output_saved_bytes,copy=b.output_copy_bytes;CHECK(!nxr_ce64_linear_kv(&b,x,rows,w,y,&expected));
  CHECK(output_address==(uintptr_t)y&&b.kv_output_saved_bytes==before+rows*128*4&&b.output_copy_bytes==copy);
  CHECK(!memcmp(y,baseline,rows*128*4));
  uint32_t old=b.kv_arena;b.kv_arena+=16;unsigned submitted=calls;
  CHECK(nxr_ce64_linear_kv(&b,x,rows,w,y,&expected)==NX_MEMORY&&calls==submitted);b.kv_arena=old;
  old=b.kv_arena_bytes;b.kv_arena_bytes--;CHECK(nxr_ce64_linear_kv(&b,x,rows,w,y,&expected)==NX_MEMORY&&calls==submitted);b.kv_arena_bytes=old;
 }
 float*y=(void*)(uintptr_t)expected.destination;const nx_matrix*w=&model.layer[expected.layer].v;
 for(failure=1;failure<=8;failure++){
  c.base.state=NX_ACCEL_IDLE;lease_live=1;uint64_t saved=b.kv_output_saved_bytes,done=b.completed;
  uint32_t *prefix=(void*)((uintptr_t)y-4);*prefix=0x12345678;
  CHECK(nxr_ce64_linear_kv(&b,x,expected.rows,w,y,&expected)==NX_STATE);
  CHECK(*prefix==0x12345678&&b.kv_output_saved_bytes==saved&&b.completed==done);
 }
 failure=0;c.base.state=NX_ACCEL_IDLE;c.base.last.output_valid=1;
 for(unsigned corruption=0;corruption<13;corruption++){
  b.head_valid=1;b.head_address=0xac020000;b.head_epoch=c.epoch;b.head_generation=c.generation;
  b.head_session=c.base.session;b.head_sequence=c.base.sequence;
  uint32_t fields[12]={1,123,0x3f800000,151936,c.epoch,c.generation,(uint32_t)c.base.session,
   (uint32_t)(c.base.session>>32),(uint32_t)c.base.sequence,(uint32_t)(c.base.sequence>>32),0xac020000,151936};
  memcpy(head_words,fields,sizeof(fields));if(corruption)head_words[corruption-1]^=1;
  int32_t token=-99;int rc=nxr_ce64_argmax(&b,(void*)0xac020000,151936,&token);
  /* A different finite best value or in-range token is not cryptographically
   * detectable here; those arithmetic facts are checked by independent RTL. */
  if(corruption==2||corruption==3||!corruption)CHECK(!rc&&token==(int32_t)head_words[1]);
  else CHECK(rc==NX_STATE&&token==-99);
 }
 head_cap=0;b.head_valid=1;int32_t token=-99;CHECK(nxr_ce64_argmax(&b,(void*)0xac020000,151936,&token)==NX_UNSUPPORTED&&token==-99);
 printf("{\"status\":\"PASS\",\"checks\":%u,\"mock_submissions\":%u,\"tail_faults\":8,\"scope\":\"actual adapter and tensor validator; mocked completed accelerator\"}\n",checks,calls);
 return 0;
}
