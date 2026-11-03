// Actual candidate backend control code. Transport mock only: no numeric or timing claims.
#include <assert.h>
#include <stdio.h>
#include "../firmware/runtime/port/ce64_backend.c"
static nx_ce64_context ctx;static nx_linear_binding provider;static nxr_ce64_backend b;
static int fault,target,calls,m0,m1,linear_calls,fences;
uint64_t nx_port_ticks(void){static uint64_t t;return ++t;}
static void fence_mock(void *p){(void)p;fences++;if(fault==20&&fences==1)nxr_ce64_input_v2(&b,0,0,0,0);if(fault==21&&fences==1)provider.aq_bytes--;}
void nx_linear_input_v2(nx_linear_binding *p,uintptr_t source,uint64_t version,uint32_t m,uint32_t k){
 nx_input_cache_v2 *c=&p->input_cache;
 if(!version||!source||!m||!k){c->valid=0;c->requested_version=0;return;}
 if(c->requested_version!=version||c->requested_source!=source||c->requested_m!=m||c->requested_k!=k)c->valid=0;
 c->requested_version=version;c->requested_source=source;c->requested_m=m;c->requested_k=k;
}
nx_status nx_opt12_run(nx_ce64_transport *t,const nx_call *call,const nx_opt12_job *j,nx_opt12_view *v,struct nx_stream_result *r){
 calls++;if(j->mode==0)m0++;if(j->mode==1)m1++;
 if(j->mode==0&&j->aq>=provider.aq_address&&j->aq<provider.aq_address+4*4864)assert(j->aq==provider.aq_address+(m0-1)*4864&&j->sa==provider.sa_address+(m0-1)*304);
 if(calls==target&&fault==1)return NX_EIO;
 t->context->base.sequence=call->sequence;t->context->base.state=NX_ACCEL_IDLE;
 *r=(struct nx_stream_result){.valid=1,.cycles=7};
 *v=(nx_opt12_view){.valid=1,.epoch=ctx.epoch,.fp32=j->fp32,.k=j->k,.session=call->session,.sequence=call->sequence,
 .quantized={.version=1,.valid=1,.epoch=ctx.epoch,.aq=j->aq,.sa=j->sa,.k=j->k,.session=call->session,.sequence=call->sequence}};
 if(calls==target)switch(fault){
  case 2:v->quantized.aq+=16;break;case 3:v->quantized.sa+=16;break;case 4:v->fp32+=16;break;
  case 5:v->quantized.valid=0;break;case 6:v->quantized.sequence--;break;case 7:v->quantized.epoch++;break;
  case 8:v->quantized.session++;break;case 9:v->quantized.k-=64;break;
  case 10:ctx.epoch++;break;case 11:ctx.base.session++;break;case 12:ctx.base.sequence++;break;
  case 13:nxr_ce64_input_v2(&b,0,0,0,0);break;
 }
 return NX_ACCEL_OK;
}
nx_status nx_opt12_run_sealed_norm(nx_ce64_transport *t,const nx_call *c,const nx_opt12_job *j,nx_opt12_view *v,struct nx_stream_result *r){return nx_opt12_run(t,c,j,v,r);}
nx_status nx_opt12_acquire(nx_ce64_context *c,const nx_opt12_view *v){return v->valid&&v->epoch==c->epoch&&v->session==c->base.session&&v->sequence==c->base.sequence&&c->base.state==NX_ACCEL_IDLE?NX_ACCEL_OK:NX_ESTATE;}
nx_status nx_linear_validate(const nx_accel_linear *j){(void)j;return NX_ACCEL_OK;}
nx_status nx_linear_run_v2(nx_ce64_context *c,const nx_call *call,const nx_accel_linear *j,nx_stats *s){
 (void)j;linear_calls++;assert(provider.input_cache.valid);*s=(nx_stats){.output_valid=1};c->base.sequence=call->sequence;return NX_ACCEL_OK;
}
static void init(int rows){
 ctx=(nx_ce64_context){.epoch=2,.base={.session=3,.state=NX_ACCEL_IDLE,.initialized=1}};ctx.base.io.fence=fence_mock;
 provider=(nx_linear_binding){.context=&ctx.base,.aq_address=0xba1c0000,.aq_bytes=4*4864,.sa_address=0xba1c5000,.sa_bytes=4*304};ctx.binding=&provider;
 b=(nxr_ce64_backend){.accelerator=&ctx,.input=(void *)0xba100000,.output=(void *)0xba120000,.input_bytes=4*4864*4,.output_bytes=151936*4,.timeout_ticks=50000000,.vector_mask=15,.private_output_address=0xac000000,.private_output_bytes=835072,.producer_aq=0xba1d0000,.producer_sa=0xba1d1400};
 fault=target=calls=m0=m1=linear_calls=fences=0;nxr_ce64_input_v2(&b,(void *)0xac040000,rows,4864,5);
}
static int producer(int rows){return nxr_ce64_vector_private(&b,0,(void *)0xac000000,(void *)0xac020000,rows,4864,(void *)0xac040000);}
static int consumer(int rows,uint64_t version){nx_matrix w={(void *)0x88201000,(void *)0x88210000,0,8,4864};nxr_ce64_input_v2(&b,(void *)0xac040000,rows,4864,version);return nxr_ce64_linear_private(&b,(void *)0xac040000,rows,&w,(void *)0xac060000);}
int main(void){int checks=0;
 for(int rows=1;rows<=4;rows++){init(rows);assert(!producer(rows)&&m0==rows&&b.lease_valid&&provider.input_cache.m==(unsigned)rows);assert(!consumer(rows,5)&&m1==0&&linear_calls==1);checks++;}
 for(int rows=1;rows<=4;rows++)for(int f=1;f<=13;f++)for(int row=1;row<=rows;row++){
  init(rows);fault=f;target=row;assert(producer(rows)!=0);assert(!b.lease_valid&&!provider.input_cache.valid);assert(linear_calls==0);assert(calls==row);checks++;
 }
 for(int f=20;f<=21;f++){init(4);fault=f;assert(producer(4)!=0&&!b.lease_valid&&!provider.input_cache.valid);checks++;}
 for(int change=0;change<6;change++){
  init(4);assert(!producer(4));
  if(change==0){assert(!consumer(4,6)&&m1==4);}
  if(change==1){nxr_ce64_input_v2(&b,0,0,0,0);assert(!consumer(4,5)&&m1==4);}
  if(change==2){b.lease_epoch++;assert(!consumer(4,5)&&m1==4);}
  if(change==3){b.lease_session++;assert(!consumer(4,5)&&m1==4);}
  if(change==4){b.lease_sequence++;assert(!consumer(4,5)&&m1==4);}
  if(change==5){b.input_serial=UINT64_MAX;assert(!producer(4)&&!b.lease_valid);}
  checks++;
 }
 for(int problem=0;problem<4;problem++){
  init(4);if(problem==0)provider.aq_bytes=3*4864;if(problem==1)provider.sa_bytes=3*304;if(problem==2)provider.sa_address+=4;if(problem==3)provider.aq_address=(uint32_t)0xac000000;
  assert(!producer(4)&&m0==4&&!b.lease_valid);checks++;
 }
 printf("PASS %d actual-backend lifecycle checks; mock transport, no numeric/timing claim\n",checks);return 0;
}
