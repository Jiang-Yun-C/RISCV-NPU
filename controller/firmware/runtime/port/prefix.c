#include "prefix.h"
typedef struct {nxp_cache *cache;const nx_prefix_identity *identity;size_t tokens;} restore_context;
static int active(nxr_request *r){return r->busy||r->state==NXR_PREFILL||r->state==NXR_DECODE;}
int nxp_init(nxp_cache *p,nxr_request *r,nx_session *s){
    if(!p||!r||!s||!r->forward||!r->reset||!r->clock)return NXR_INVALID;
    *p=(nxp_cache){.request=r,.session=s};return 0;
}
int nxp_prepare(nxp_cache *p,const nx_prefix_identity *key,const int32_t *ids,size_t n){
    if(!p||!p->request)return NXR_INVALID;
    if(active(p->request))return NXR_BUSY;
    int rc=nxr_reset(p->request);if(rc)return rc;
    uint64_t start=p->request->clock(p->request->clock_context);
    rc=nx_prefix_prepare(p->session,key,ids,n);
    p->prepare_ticks=p->request->clock(p->request->clock_context)-start;
    p->prefix_tokens=rc?0:(uint32_t)n;p->last_hit=0;
    return rc?NXR_FAULT:0;
}
static int restore(void *cookie,const uint32_t *ids,size_t n,uint32_t *past){
    restore_context *ctx=cookie;nxp_cache *p=ctx->cache;
    uint64_t start=p->request->clock(p->request->clock_context);
    int hit=0;
    /* No cached head/logits: an all-prefix prompt takes the full cold path. */
    if(ctx->tokens&&ctx->tokens<n)
        hit=nx_prefix_restore(p->session,ctx->identity,(const int32_t *)ids,ctx->tokens);
    else nx_reset(p->session);
    p->restore_ticks=p->request->clock(p->request->clock_context)-start;
    p->last_hit=(uint32_t)hit;if(hit)p->hits++;else p->misses++;
    *past=hit?(uint32_t)ctx->tokens:0;return 0;
}
int nxp_begin(nxp_cache *p,const nx_prefix_identity *key,const uint32_t *ids,size_t n,
              size_t prefix_tokens,uint32_t maximum,uint64_t timeout){
    if(!p||!p->request)return NXR_INVALID;
    restore_context ctx={p,key,prefix_tokens};
    return nxr_restart_ids(p->request,ids,n,maximum,timeout,restore,&ctx);
}
