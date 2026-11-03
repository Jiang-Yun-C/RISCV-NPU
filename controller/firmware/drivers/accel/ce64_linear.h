#ifndef NX_CE64_LINEAR_H
#define NX_CE64_LINEAR_H
#include "backend_v2.h"
#include "linear_api.h"
#include "ce64_abi_v1.h"
typedef struct {
    nx_context base;
    nx_linear_binding *binding;
    uint32_t epoch, generation, acquired_generation;
    uint32_t qualified_profile_mask;
} nx_ce64_context;
typedef struct {
    nx_ce64_context *context;
    void (*wait)(void *);
    void *wait_cookie;
} nx_ce64_transport;
nx_status nx_ce64_init(nx_ce64_context *,const nx_accel_io *,uint64_t);
nx_status nx_ce64_reset_session(nx_ce64_context *,uint64_t,uint64_t *);
/* Read-only boundary check before a cooperative request is recovered. This
 * does not clear a fault, ACK a completion, release an owner or prove global
 * native drain; nx_ce64_reset_session must still obtain the real reset grant. */
nx_status nx_ce64_idle_safe(nx_ce64_context *);
nx_status nx_ce64_bind(nx_ce64_context *,nx_linear_binding *);
nx_status nx_query_caps_v2(nx_ce64_context *,uint32_t,nx_caps_v2 *);
nx_status nx_linear_run_v2(nx_ce64_context *,const nx_call *,const nx_linear *,nx_stats *);
nx_status nx_ce64_wait(nx_ce64_context *,uint64_t,uint64_t,nx_stats *);
nx_status nx_ce64_linear_execute(void *,const nx_call *,const struct nx_stream_request *,struct nx_stream_result *);
void nx_ce64_irq(nx_ce64_context *);
#endif
