#ifndef NXP_PREFIX_H
#define NXP_PREFIX_H
#include "runtime.h"
#include "nx_reference.h"
/* This controller is attached to the same session/model as request callbacks.
 * Synchronous use only, like nxr_step. No KV or logits buffers are allocated. */
typedef struct {
    nxr_request *request;
    nx_session *session;
    uint64_t prepare_ticks, restore_ticks, hits, misses;
    uint32_t prefix_tokens, last_hit;
} nxp_cache;
int nxp_init(nxp_cache *,nxr_request *,nx_session *);
int nxp_prepare(nxp_cache *,const nx_prefix_identity *,const int32_t *,size_t);
int nxp_begin(nxp_cache *,const nx_prefix_identity *,const uint32_t *,size_t,
              size_t prefix_tokens,uint32_t max_new,uint64_t timeout);
#endif
