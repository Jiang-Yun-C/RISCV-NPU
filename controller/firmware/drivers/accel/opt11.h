#ifndef NX_OPT11_H
#define NX_OPT11_H
#include "ce64_linear.h"
/* Private versioned producer lease. Valid only in this epoch/session and until
 * the next command/reset or producer buffer write. All storage is uncached. */
typedef struct {
    uint32_t version,valid,epoch,aq,sa,k;
    uint64_t session,sequence;
} nx_opt11_view;
typedef struct {uint32_t gate,up,aq,sa,fp32,k,quantize_only;} nx_opt11_job;
/* Default is the original software route. Configure only while idle. The
 * software route requires the diagnostic FP32 workspace in the job. */
nx_status nx_opt11_configure(nx_ce64_context *,uint32_t enabled);
nx_status nx_opt11_run(nx_ce64_transport *,const nx_call *,const nx_opt11_job *,nx_opt11_view *,struct nx_stream_result *);
/* The model loader must seal the same Wq/Sw/bias request as the CE64 provider.
 * This entry consumes the producer's Aq/Sa directly, without CPU re-quantize. */
nx_status nx_opt11_down(nx_ce64_transport *,const nx_call *,nx_opt11_view *,const struct nx_stream_request *,struct nx_stream_result *);
#endif
