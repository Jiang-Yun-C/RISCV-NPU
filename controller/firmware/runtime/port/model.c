#include "model.h"
/* Set to 0 for a full-head diagnostic/rollback build. */
#ifndef NX_PREFILL_HEAD_SKIP
#define NX_PREFILL_HEAD_SKIP 1
#endif
static int status(int code) {
    if(code==NX_OK)return 0;
    if(code==NX_ARGUMENT)return NXR_INVALID;
    if(code==NX_STATE)return NXR_STATE;
    if(code==NX_MEMORY)return NXR_BOUNDS;
    return NXR_FAULT;
}
static int forward(void *context,uint32_t id,uint32_t past,uint32_t *next) {
    nxr_model *m=context;int32_t input=(int32_t)id,output=-1;
#if !defined(NX_OPT08_LOGITS) || NX_OPT08_LOGITS
    int rc=nx_forward_token_v2(m->session,input,past,&output);
#else
    int rc=nx_forward(m->session,&input,1,past,m->logits,0);
    if(!rc)rc=nx_greedy(m->logits,&output);
#endif
    if(!rc)*next=(uint32_t)output;
    return status(rc);
}
#if NX_PREFILL_HEAD_SKIP
static int prefill(void *context,uint32_t id,uint32_t past) {
    nxr_model *m=context;int32_t input=(int32_t)id;
    return status(nx_forward(m->session,&input,1,past,0,0));
}
#endif
#ifndef NX_OPT13_M4
#define NX_OPT13_M4 1
#endif
#if NX_OPT13_M4 && NX_PREFILL_HEAD_SKIP
static int prefill_block(void *context,const uint32_t *ids,uint32_t rows,uint32_t past,uint32_t *next) {
    nxr_model *m=context;int32_t output=-1;
    int rc=nx_forward_block_v3(m->session,(const int32_t *)ids,(int)rows,(int)past,next?&output:NULL);
    if(!rc&&next)*next=(uint32_t)output;
    return status(rc);
}
#endif
static int reset(void *context){nx_reset(((nxr_model *)context)->session);return 0;}
static uint64_t clock_ticks(void *context){(void)context;return nx_port_ticks();}
int nxr_attach(nxr_request *r,nxr_model *m,nx_session *s,float *logits,uint32_t vocab) {
    if(!r||!m||!s||!logits)return NXR_INVALID;
    *m=(nxr_model){s,logits};
    int rc=nxr_init(r,m,forward,reset,clock_ticks,0,vocab);
#if NX_PREFILL_HEAD_SKIP
    if(!rc)rc=nxr_set_prefill(r,prefill);
#endif
#if NX_OPT13_M4 && NX_PREFILL_HEAD_SKIP
    if(!rc)rc=nxr_set_prefill_block(r,prefill_block,4);
#endif
    return rc;
}
size_t nxr_request_bytes(void){return sizeof(nxr_request);}
size_t nxr_model_bytes(void){return sizeof(nxr_model);}
int nxr_state(const nxr_request *r){return r?(int)r->state:NXR_INVALID;}
uint32_t nxr_count(const nxr_request *r){return r&&r->state==NXR_STOPPED?r->generated:0;}
uint32_t nxr_reason(const nxr_request *r){return r?r->stop:0;}
uint32_t nxr_output(const nxr_request *r,uint32_t i){return r&&r->state==NXR_STOPPED&&i<r->generated?r->output[i]:UINT32_MAX;}
