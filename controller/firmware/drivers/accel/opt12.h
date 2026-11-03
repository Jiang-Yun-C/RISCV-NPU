#ifndef NX_OPT12_H
#define NX_OPT12_H
#include "opt11.h"
enum { NX_VEC_SWIGLU=0,NX_VEC_QUANTIZE=1,NX_VEC_ADD=2,NX_VEC_MUL=3,
       NX_VEC_SCALE=4,NX_VEC_SUM=5,NX_VEC_MAX=6,NX_VEC_RMSNORM=7 };
typedef struct {uint32_t gate,up,aq,sa,fp32,k,mode,quantize,scalar;
    /* Only nx_opt12_run_resident accepts these private fields. */
    uint32_t resident_rows,resident_row,resident_fp_base;
    uint64_t resident_first_sequence;
} nx_opt12_job;
typedef struct {nx_opt11_view quantized;uint32_t valid,epoch,fp32,k;
    uint64_t session,sequence;
    uint32_t resident_valid,resident_rows,resident_row,resident_fp_base;
    uint64_t resident_first_sequence;
} nx_opt12_view;
nx_status nx_opt12_configure(nx_ce64_context *,uint32_t);
nx_status nx_opt12_run(nx_ce64_transport *,const nx_call *,const nx_opt12_job *,nx_opt12_view *,struct nx_stream_result *);
/* Internal private-workspace path only. The public nx_opt12_run legal set
 * remains unchanged; this entry requires typed live norm authority. */
nx_status nx_opt12_run_sealed_norm(nx_ce64_transport *,const nx_call *,const nx_opt12_job *,nx_opt12_view *,struct nx_stream_result *);
/* Private mode0/K4864 scratch producer. Quantized DDR view stays invalid;
 * explicit resident identity below is consumed only by the private provider. */
nx_status nx_opt12_run_resident(nx_ce64_transport *,const nx_call *,const nx_opt12_job *,nx_opt12_view *,struct nx_stream_result *);
nx_status nx_opt12_acquire(nx_ce64_context *,const nx_opt12_view *);
/* Private serial PV: P pitch is64 for len<=64; otherwise padded (<=512).
 * Long PV requires capability, 512-byte P and 256-byte V alignment.
 * The original private P window remains the <=64 low-latency path.
 * Reuses CE64 descriptors, shared scratch and original completion/ACK. */
nx_status nx_pv_run(nx_ce64_transport *,const nx_call *,uint32_t p,uint32_t v,uint32_t y,
                   uint32_t heads,uint32_t len,uint32_t padded,struct nx_stream_result *);
/* Compact CPU-owned P has heads*len elements. Padding is written directly to
 * the 2KiB private window, sealed to this call, and consumed through ACK.
 * A missing capability returns unsupported before staging or submission. */
nx_status nx_pv_window_run(nx_ce64_transport *,const nx_call *,const float *p,uint32_t v,uint32_t y,
                          uint32_t heads,uint32_t len,uint32_t padded,struct nx_stream_result *);
#endif
