/* Real two-block model/FP32 arithmetic; callback plumbing is a native fixture.
 * This is not a hardware backend or a production-model accuracy result. */
#include "nx_reference.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "full_weights.h"
static _Alignas(16) unsigned char state[32768],other[32768],kv[40960],kv_other[40960],work[4096],work_other[4096];
static nx_session *s,*baseline;
static nx_weights weights;
static unsigned checks,tail_calls,head_calls,mutations,fail_tail,fail_head,reenter;
static unsigned prefix_captures,prefix_hits,prefix_revocations,joint_compares,integer_profile_checks;
static nx_kv_tail last;
static const nx_matrix *last_matrix;
static float *last_destination;
#define CHECK(x) do{checks++;if(!(x)){fprintf(stderr,"callback line %d: %s\n",__LINE__,#x);exit(1);}}while(0)
/* The selected integer hot path must retain single ticks beyond double's
 * exact-integer range while all four enhancements are exercised together. */
uint64_t nx_port_ticks(void){static uint64_t t=UINT64_C(1)<<54;return ++t;}
static int linear(void *cookie,const float *x,int rows,const nx_matrix *w,float *y){(void)cookie;return nx_linear(x,rows,w,y,NULL);}
static int tail(void *cookie,const float *x,int rows,const nx_matrix *w,float *y,const nx_kv_tail *lease){
 (void)cookie;tail_calls++;CHECK(nx_kv_tail_valid(lease,w,y));CHECK(lease->rows==(unsigned)rows);
 CHECK(!nx_cache(s,0,0)&&nx_length(s)==-1&&!nx_logits_v2(s));
 last=*lease;last_matrix=w;last_destination=y;
 for(unsigned f=0;f<11;f++){
  nx_kv_tail bad=*lease;
  switch(f){case 0:bad.serial++;break;case 1:bad.arena+=16;break;case 2:bad.destination+=16;break;
   case 3:bad.abi++;break;case 4:bad.layer^=1;break;case 5:bad.value^=1;break;
   case 6:bad.past++;break;case 7:bad.rows++;break;case 8:bad.layers++;break;
   case 9:bad.capacity++;break;case 10:bad.width++;break;}
  CHECK(!nx_kv_tail_valid(&bad,w,y));mutations++;
 }
 if(tail_calls==fail_tail){y[0]=12345.0f;return NX_STATE;}
 int rc=nx_linear(x,rows,w,y,NULL);
 if(reenter){nx_reset(s);reenter=0;}
 return rc;
}
static int head(void *cookie,const float *logits,uint32_t n,int32_t *next){
 (void)cookie;CHECK(n==32);head_calls++;if(fail_head)return NX_STATE;return nx_greedy(logits,next);
}
static void compare(int n){
 CHECK(nx_length(s)==n&&nx_length(baseline)==n);
 CHECK(!memcmp(nx_logits_v2(s),nx_logits_v2(baseline),32*4));
 for(int l=0;l<2;l++)for(int v=0;v<2;v++)CHECK(!memcmp(nx_cache(s,l,v),nx_cache(baseline,l,v),(size_t)n*4*4));
}
static void prefix_equal(const unsigned char *before,int n){
 for(unsigned plane=0;plane<4;plane++)CHECK(!memcmp(kv+plane*640*4*4,before+plane*640*4*4,(size_t)n*4*4));
}
static void capture_five(const nx_prefix_identity *key,const int32_t *ids){
 nx_reset(s);CHECK(!nx_prefix_configure(s,key));CHECK(!nx_set_prefill_rows(s,4));
 CHECK(!nx_forward_block_v3(s,ids,4,0,NULL));
 CHECK(!nx_forward_block_v3(s,ids+4,1,4,NULL));
 CHECK(!nx_prefix_capture(s,key,ids,5));prefix_captures++;
 CHECK(nx_length(s)==5&&!nx_logits_v2(s));
}
static int32_t cold_eight(const int32_t *ids){
 int32_t next=-1;nx_reset(baseline);CHECK(!nx_set_prefill_rows(baseline,4));
 CHECK(!nx_forward_block_v3(baseline,ids,4,0,NULL));
 CHECK(!nx_forward_block_v3(baseline,ids+4,4,4,&next));return next;
}
static void prefix_callback_integration(const int32_t *ids){
 /* Explicit synthetic identity, bound before any model computation. The
  * five-token prefix crosses an M4 boundary; the cold path groups 4+4. */
 nx_prefix_identity key={.abi=NX_PREFIX_ABI,.context_limit=NX_PREFIX_MAX};
 key.model[0]=1;key.tokenizer[0]=2;key.template_version[0]=3;key.numeric[0]=4;key.backend[0]=5;
 capture_five(&key,ids);
 unsigned char before[sizeof(kv)];memcpy(before,kv,sizeof(kv));
 int32_t a=-11,b=-22;
 CHECK(!nx_forward_block_v3(s,ids+5,3,5,&a));b=cold_eight(ids);
 CHECK(a==b);compare(8);joint_compares++;prefix_equal(before,5);

 CHECK(nx_prefix_restore(s,&key,ids,5)==1);prefix_hits++;
 CHECK(nx_length(s)==5&&!nx_logits_v2(s));
 int32_t changed[8];memcpy(changed,ids,5*sizeof(*ids));
 changed[5]=19;changed[6]=7;changed[7]=23;
 CHECK(!nx_forward_block_v3(s,changed+5,3,5,&a));b=cold_eight(changed);
 CHECK(a==b);compare(8);joint_compares++;prefix_equal(before,5);
 /* Continue actual greedy generation after warm-prefix prefill. */
 for(int past=8;past<10;past++){
  int32_t input=a;a=-11;b=-22;
  CHECK(!nx_forward_token_v2(s,input,past,&a));
  CHECK(!nx_forward_token_v2(baseline,input,past,&b));
  CHECK(a==b);compare(past+1);joint_compares++;prefix_equal(before,5);
 }
 CHECK(nx_prefix_restore(s,&key,ids,5)==1);prefix_hits++;
 /* nxr cancellation's model reset callback uses this public reset operation.
  * Actual UART cancellation is covered by the production service fixture. */
 nx_reset(s);CHECK(nx_prefix_restore(s,&key,ids,5)==0);prefix_revocations++;
 CHECK(nx_length(s)==0&&!nx_logits_v2(s));
#if NX_KV_TAIL_DIRECT
 capture_five(&key,ids);memcpy(before,kv,sizeof(kv));
 fail_tail=tail_calls+1;a=-777;
 CHECK(nx_forward_token_v2(s,29,5,&a)==NX_STATE);fail_tail=0;
 CHECK(a==-777&&nx_length(s)==-1&&!nx_logits_v2(s));prefix_equal(before,5);
 CHECK(nx_prefix_restore(s,&key,ids,5)==0);prefix_revocations++;
 CHECK(nx_length(s)==0);
#endif
#if NX_HEAD_ARGMAX
 capture_five(&key,ids);memcpy(before,kv,sizeof(kv));
 fail_head=1;a=-888;
 CHECK(nx_forward_token_v2(s,17,5,&a)==NX_STATE);fail_head=0;
 CHECK(a==-888&&nx_length(s)==-1&&!nx_logits_v2(s));prefix_equal(before,5);
 CHECK(nx_prefix_restore(s,&key,ids,5)==0);prefix_revocations++;
 CHECK(nx_length(s)==0);
#endif
 for(unsigned which=0;which<2;which++){
  uint64_t ticks[NX_TIMERS],calls[NX_TIMERS];nx_profile_ticks(which?baseline:s,ticks,calls);
  /* Embedding has exactly its two clock reads and no nested timed call. */
  CHECK(calls[NX_EMBED]>0&&ticks[NX_EMBED]==calls[NX_EMBED]);
  for(unsigned i=0;i<NX_TIMERS;i++)CHECK(calls[i]>0&&ticks[i]>=calls[i]);
  integer_profile_checks++;
 }
}
int main(void){
 load_full(&weights);s=nx_init_static(&weights,state,sizeof(state),kv,sizeof(kv),work,sizeof(work));
 baseline=nx_init_static(&weights,other,sizeof(other),kv_other,sizeof(kv_other),work_other,sizeof(work_other));CHECK(s&&baseline);
 nx_bind_backend(s,NULL,linear,NULL,2);nx_bind_private_backend(s,linear);nx_bind_kv_backend(s,tail);nx_bind_argmax_backend(s,head);
 int32_t ids[512];for(unsigned i=0;i<512;i++)ids[i]=(i*7+1)%32;
 for(int width=1;width<=4;width+=3){
  nx_reset(s);nx_reset(baseline);CHECK(!nx_set_prefill_rows(s,width)&&!nx_set_prefill_rows(baseline,width));
  for(int past=0;past<132;){int rows=132-past<width?132-past:width;int32_t a=-77,b=-88;
   CHECK(!nx_forward_block_v3(s,ids+past,rows,past,&a));CHECK(!nx_forward_block_v3(baseline,ids+past,rows,past,&b));
   CHECK(a==b);past+=rows;compare(past);CHECK(!nx_kv_tail_valid(&last,last_matrix,last_destination));
  }
 }
 prefix_callback_integration(ids);
#if NX_KV_TAIL_DIRECT
 CHECK(tail_calls>0&&mutations==tail_calls*11);
 for(unsigned target=1;target<=4;target++){
  nx_reset(s);int32_t next=-1;CHECK(!nx_forward_block_v3(s,ids,4,0,&next));
  unsigned char before[sizeof(kv)];memcpy(before,kv,sizeof(kv));
  fail_tail=tail_calls+target;next=-999;
  CHECK(nx_forward_block_v3(s,ids+4,3,4,&next)==NX_STATE);
  CHECK(next==-999&&nx_length(s)==-1&&!nx_logits_v2(s)&&!nx_cache(s,0,0));prefix_equal(before,4);fail_tail=0;
 }
 nx_reset(s);reenter=1;int32_t next=-999;CHECK(nx_forward_block_v3(s,ids,1,0,&next)==NX_STATE);CHECK(next==-999);
#else
 CHECK(tail_calls==0);
#endif
#if NX_HEAD_ARGMAX
 CHECK(head_calls>0);nx_reset(s);fail_head=1;int32_t failed=-333;
 CHECK(nx_forward_token_v2(s,1,0,&failed)==NX_STATE&&failed==-333&&!nx_logits_v2(s));
#else
 CHECK(head_calls==0);
#endif
 printf("{\"status\":\"PASS\",\"checks\":%u,\"tail_calls\":%u,\"head_calls\":%u,\"lease_mutations\":%u,"
        "\"prefix_captures\":%u,\"prefix_hits\":%u,\"prefix_revocations\":%u,\"joint_compares\":%u,\"integer_profile_checks\":%u,"
        "\"scope\":\"native real reduced model and callback fixture; no hardware or production-model accuracy claim\"}\n",
        checks,tail_calls,head_calls,mutations,prefix_captures,prefix_hits,prefix_revocations,joint_compares,integer_profile_checks);
 return 0;
}
