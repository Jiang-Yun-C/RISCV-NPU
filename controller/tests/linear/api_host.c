/* Desktop API consumer. Coral callback below exercises transport identity and
 * failures only; it does not emulate arithmetic or count as RTL evidence. */
#define _POSIX_C_SOURCE 200809L
#include "linear_api.h"
#include <stdlib.h>
#include <string.h>
#include <time.h>
struct arena {const float *x,*sw,*bias;const int8_t *w;float *y,*sa;int8_t *aq;uint32_t m,n,k,control,bridge;uint64_t tick;int mode,submissions;};
static uint64_t ticks(void *p){(void)p;struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return (uint64_t)t.tv_sec*1000000000u+t.tv_nsec;}
static uint32_t read32(void *cookie,uint32_t a){struct arena *p=cookie;if(a==NX_BRIDGE_STATUS)return 1;if(a==NX_ACCEL_CONTROL)return p->control;if(a==NX_BRIDGE_CONTROL)return p->bridge;return 0;}
static void write32(void *cookie,uint32_t a,uint32_t v){struct arena *p=cookie;if(a==NX_ACCEL_CONTROL)p->control=v;if(a==NX_BRIDGE_CONTROL)p->bridge=v;}
static void fence(void *cookie){(void)cookie;}
static void *resolve(void *cookie,uint32_t a,uint32_t bytes,int write){
    (void)bytes;(void)write;struct arena *p=cookie;
    switch(a){case 0xac000000:return (void *)p->x;case 0x80000000:return (void *)p->w;case 0x90000000:return (void *)p->sw;case 0x91000000:return (void *)p->bias;case 0xac100000:return p->y;case 0xac040000:return p->aq;case 0xac050000:return p->sa;default:return NULL;}
}
static nx_status transport(void *cookie,const nx_call *call,const struct nx_stream_request *r,struct nx_stream_result *result){
    (void)call;struct arena *p=cookie;p->submissions++;
    if(r->m!=p->m||r->n!=p->n||r->k!=p->k||r->reserved[0])return NX_EINVAL;
    if(p->mode==1)return NX_EIO;
    if(p->mode==2)return NX_ETIMEOUT;
    *result=(struct nx_stream_result){.abi=NX_LINEAR_ABI,.size=104,.session_lo=r->session_lo,.sequence_lo=r->sequence_lo+1,.valid=1};
    return NX_OK; /* deliberately stale completion is rejected by the adapter */
}
static nx_tensor tensor(uint32_t address,uint32_t m,uint32_t n,uint32_t dtype){
    uint32_t size=dtype==NX_I8?1:4;
    return (nx_tensor){.address=address,.allocation_bytes=m*n*size,.dtype=dtype,.rank=2,.layout_id=1,.shape={m,n},.stride_bytes={n*size,size}};
}
int api_run(const float *x,const int8_t *w,const float *sw,const float *bias,float *y,uint32_t m,uint32_t n,uint32_t k,int mode,nx_stats *stats,int8_t *aq,float *sa){
    struct arena p={.x=x,.w=w,.sw=sw,.bias=bias,.y=y,.sa=sa,.aq=aq,.m=m,.n=n,.k=k,.mode=mode};
    nx_context ctx={.initialized=1,.state=NX_ACCEL_IDLE,.session=1,.io={.cookie=&p,.ticks=ticks,.read32=read32,.write32=write32,.fence=fence,.tick_hz=1000000000}};
    nx_linear_binding binding={.cookie=&p,.resolve=resolve,.execute=transport,.aq_address=0xac040000,.aq_bytes=m*k,.sa_address=0xac050000,.sa_bytes=m*(k/64)*4};
    nx_linear job={.a=tensor(0xac000000,m,k,NX_F32),.wq=tensor(0x80000000,n,k,NX_I8),.sw=tensor(0x90000000,n,k/64,NX_F32),.y=tensor(0xac100000,m,n,NX_F32),.group_size=64};
    if(bias)job.bias=(nx_tensor){.address=0x91000000,.allocation_bytes=n*4,.dtype=NX_F32,.rank=1,.layout_id=1,.shape={n},.stride_bytes={4}};
    int status=nx_linear_bind(&ctx,&binding,3);if(status)return status;
    nx_caps caps;status=nx_query_caps(&ctx,mode?NX_CORAL_RVV:NX_CPU_C,&caps);if(status||caps.operation_mask!=(1u<<NX_LINEAR))return 100;
    nx_call call={.api_version=1,.route=mode?NX_CORAL_RVV:NX_CPU_C,.session=1,.sequence=1,.timeout_ticks=UINT64_C(10000000000)};
    status=nx_linear_run(&ctx,&call,&job,stats);
    if(mode && p.submissions!=1)return 101;
    if(status==NX_OK){nx_stats saved;if(nx_wait(&ctx,1,1,&saved)||memcmp(stats,&saved,sizeof saved))return 102;}
    if(stats->elapsed_ticks!=stats->validate_ticks+stats->quantize_ticks+stats->execute_ticks+stats->fallback_ticks+stats->other_ticks)return 103;
    if(ctx.state==NX_ACCEL_FAULTED){uint64_t session;if(nx_reset_session(&ctx,1000000000,&session))return 104;}
    return status;
}
