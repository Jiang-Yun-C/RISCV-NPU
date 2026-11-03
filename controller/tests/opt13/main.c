#include "prefix.h"
#include "inputs.h"
#include <string.h>
#include <math.h>
#ifndef __riscv
#include <stdio.h>
#include <time.h>
#endif
static _Alignas(16) unsigned char state[16384];
#ifndef __riscv
static _Alignas(16) unsigned char host_kv[40960],host_work[4096];
#endif
static nx_weights weights;static nx_session *s;static nxr_request request;static nxp_cache cache;
static nx_prefix_identity key;static uint32_t ids[513];static unsigned checks;
static int force_error;
static void emit(unsigned g,unsigned i,uint32_t v){
#ifdef __riscv
 *(volatile uint32_t *)0x10000080=(g<<16)|i;*(volatile uint32_t *)0x10000084=v;
#else
 printf("%u %u %u\n",g,i,v);
#endif
}
static void check(int b){emit(200,checks++,!!b);}
uint64_t nx_port_ticks(void){
#ifdef __riscv
 uint32_t a,b,c;do{__asm__ volatile("csrr %0,mcycleh":"=r"(a));__asm__ volatile("csrr %0,mcycle":"=r"(b));__asm__ volatile("csrr %0,mcycleh":"=r"(c));}while(a!=c);return (uint64_t)a<<32|b;
#else
 struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return (uint64_t)t.tv_sec*1000000000u+t.tv_nsec;
#endif
}
static void ticks(unsigned g,unsigned i,uint64_t v){emit(g,i,(uint32_t)v);emit(g,i+1,(uint32_t)(v>>32));}
static uint64_t clock_fn(void *p){(void)p;return nx_port_ticks();}
static int reset_fn(void *p){nx_reset(p);return 0;}
static int forward_fn(void *p,uint32_t id,uint32_t past,uint32_t *next){int32_t out=-1;int rc=nx_forward_block_v3(p,(int32_t *)&id,1,(int)past,&out);if(!rc)*next=(uint32_t)out;return rc;}
static int block_fn(void *p,const uint32_t *id,uint32_t rows,uint32_t past,uint32_t *next){int32_t out=-1;int rc=nx_forward_block_v3(p,(const int32_t *)id,(int)rows,(int)past,next?&out:NULL);if(!rc&&next)*next=(uint32_t)out;return rc;}
static int backend(void *p,const float *x,int rows,const nx_matrix *w,float *y){(void)p;(void)x;(void)rows;(void)w;(void)y;return force_error?NX_STATE:NX_UNSUPPORTED;}
static uint32_t bits(float x){uint32_t u;memcpy(&u,&x,4);return u;}
static void snapshot(unsigned i){
 unsigned g=1000+10*i;const float *y=nx_logits_v2(s);check(y!=NULL);
 for(unsigned j=0;j<32;j++)emit(g,j,bits(y[j]));
 for(int l=0;l<2;l++)for(int v=0;v<2;v++){size_t n=0;const float *p=nx_cache_view(s,l,v,&n);check(p&&n==request.kv_length);for(size_t j=0;j<n*4;j++)emit(g+1+l*2+v,(unsigned)j,bits(p[j]));}
 for(unsigned j=0;j<request.generated;j++)emit(g+5,j,request.output[j]);
 ticks(g+6,0,request.prefill_ticks);ticks(g+6,2,request.decode_ticks);ticks(g+6,4,request.token_at[0]-request.start_ticks);ticks(g+6,6,request.total_ticks);
}
static uint32_t bp,batch_calls,single_calls;static int eos;
static int breset(void *p){(void)p;bp=0;batch_calls=single_calls=0;return 0;}
static int bforward(void *p,uint32_t id,uint32_t past,uint32_t *next){(void)p;(void)id;if(past!=bp||past>=512)return NXR_STATE;bp++;single_calls++;*next=eos?NXR_EOS:1;return 0;}
static int bblock(void *p,const uint32_t *id,uint32_t n,uint32_t past,uint32_t *next){(void)p;(void)id;if(n<1||n>4||past!=bp||past+n>512)return NXR_STATE;bp+=n;batch_calls++;if(next)*next=eos?NXR_EOS:1;return 0;}
static int run(void){int rc=0;while(!rc&&(request.state==NXR_PREFILL||request.state==NXR_DECODE))rc=nxr_step(&request);return rc;}
uint32_t trap_handler(uint32_t a,uint32_t b,uint32_t c){(void)b;(void)c;emit(999,0,a);
#ifdef __riscv
 *(volatile uint32_t *)0x10000020=0xdead;for(;;){}
#endif
 return 0;}
int main(void){
 weights.embedding=(nx_matrix){&qe[0][0],&se[0][0],NULL,32,28};weights.norm=norm;weights.inv_freq=inv;
 for(int l=0;l<2;l++){nx_layer *p=&weights.layer[l];p->norm1=n1[l];p->norm2=n2[l];nx_matrix *m[]={&p->q,&p->k,&p->v,&p->o,&p->gate,&p->up,&p->down};const int ns[]={28,4,4,28,32,32,28},ks[]={28,28,28,28,28,28,32};for(int j=0;j<7;j++)*m[j]=(nx_matrix){&wq[l][j][0][0],&sw[l][j][0][0],j<3?bias[l][j]:NULL,ns[j],ks[j]};}
#ifdef __riscv
 s=nx_init_static(&weights,state,sizeof(state),(void *)0xa8000000,nx_kv_bytes(),(void *)0xac000000,nx_work_bytes());
#else
 s=nx_init_static(&weights,state,sizeof(state),host_kv,sizeof(host_kv),host_work,sizeof(host_work));
#endif
 check(s!=NULL);if(!s)return 1;
 memset(&key,1,sizeof(key));key.abi=1;key.start_position=0;key.context_limit=512;key.flags=0;
 for(unsigned j=0;j<513;j++)ids[j]=(j+1)%32;
 nx_bind_backend(s,NULL,backend,NULL,2);
 unsigned label=0;const unsigned lengths[]={1,3,4,5,7,8,9,9};
 for(int width=1;width<=4;width+=3){check(nx_set_prefill_rows(s,width)==0);check(nxr_init(&request,s,forward_fn,reset_fn,clock_fn,NULL,32)==0);check(nxr_set_prefill_block(&request,block_fn,width)==0);check(nxp_init(&cache,&request,s)==0);
  for(unsigned j=0;j<8;j++,label++){
   unsigned prefix=j==7?3:0;
   if(prefix){check(nxp_prepare(&cache,&key,(int32_t *)ids,prefix)==0);
    for(int l=0;l<2;l++)for(int v=0;v<2;v++){float *p=(float *)nx_cache(s,l,v);for(int k=3*4;k<640*4;k++)p[k]=NAN;}}
   else {check(nxr_reset(&request)==0);}
   check(nxp_begin(&cache,&key,ids,lengths[j],prefix,2,UINT64_C(10000000000))==0);
   check(cache.last_hit==!!prefix);check(run()==0);check(request.generated==2&&request.kv_length==lengths[j]+1);snapshot(label);
  }
 }
 check(nxp_prepare(&cache,&key,(int32_t *)ids,3)==0);force_error=1;
 check(nxp_begin(&cache,&key,ids,9,3,2,UINT64_C(10000000000))==0);check(nxr_step(&request)!=0);force_error=0;
 check(nx_logits_v2(s)==NULL&&request.generated==0&&nx_prefix_restore(s,&key,(int32_t *)ids,3)==0);
 check(nxp_prepare(&cache,&key,(int32_t *)ids,3)==0);check(nxp_begin(&cache,&key,ids,9,3,2,1)==0);check(nxr_step(&request)==NXR_TIMEOUT);check(nx_prefix_restore(s,&key,(int32_t *)ids,3)==0);
 check(nxr_reset(&request)==0);check(nxr_begin_ids(&request,ids,9,2,UINT64_C(10000000000))==0);check(nxr_set_prefill_block(&request,block_fn,1)==NXR_BUSY);check(nxr_cancel(&request,NXR_FAULT)==NXR_FAULT);check(nx_logits_v2(s)==NULL);
 for(unsigned n=511;n<=512;n++){check(nxr_init(&request,NULL,bforward,breset,clock_fn,NULL,151936)==0);check(nxr_set_prefill_block(&request,bblock,4)==0);check(nxr_begin_ids(&request,ids,n,128,UINT64_C(1000000000))==0);check(run()==0);check(request.generated==512-n&&request.stop==NXR_STOP_CONTEXT&&bp==n&&batch_calls==128&&single_calls==0);}
 eos=1;check(nxr_reset(&request)==0);check(nxr_begin_ids(&request,ids,5,128,UINT64_C(1000000000))==0);check(run()==0&&request.generated==1&&request.stop==NXR_STOP_EOS&&bp==5);
 emit(300,0,checks);emit(300,1,(uint32_t)nx_state_bytes());emit(300,2,(uint32_t)nx_kv_bytes());emit(300,3,(uint32_t)nx_work_bytes());
#ifdef __riscv
 *(volatile uint32_t *)0x10000020=0x1300;for(;;){}
#endif
 return 0;
}
