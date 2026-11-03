#ifndef NXR_CE64_BACKEND_H
#define NXR_CE64_BACKEND_H
#include "nx_reference.h"
/* The platform owns the CE context and disjoint uncached staging arenas.
 * This adapter grants no board/profile qualification. */
typedef struct {
    void *accelerator;
    float *input, *output;
    uint32_t input_bytes, output_bytes;
    uint64_t timeout_ticks, calls, completed, backend_cycles;
    const float *source;
    uint64_t version, staged_version, staging_bytes, staging_saved_bytes, output_copy_bytes, staging_ticks, output_copy_ticks;
    uint32_t source_rows,source_k;
    /* Single-item ablations: quantize/norm/SwiGLU/residual, bits 0..3. */
    uint32_t vector_mask,lease_valid,lease_epoch;
    uint64_t lease_session,lease_sequence,sfu_calls,sfu_cycles;
    uint32_t producer_aq,producer_sa;
    /* Explicit unpublished model workspace; excludes public logits and KV. */
    uint32_t private_output_address,private_output_bytes;
    uint64_t private_output_saved_bytes;
    uint64_t vector_output_saved_bytes,vector_output_copy_bytes,vector_coefficient_copy_bytes;
    uint64_t producer_direct_aq_bytes,producer_direct_sa_bytes,producer_sa_copy_bytes;
    /* Successful private sealed-norm coefficient reads and avoided CPU copy.
     * These counters do not replace independent bus/cycle qualification. */
    uint64_t vector_coefficient_direct_bytes,vector_coefficient_saved_bytes;
    /* Every input notification advances this saturating serial. A producer
     * may publish a lease only if no intervening notification revoked it.
     * The counter records certificates, not measured API cycle savings. */
    uint64_t input_serial,swiglu_quantized_handoffs;
    /* Model-owned K/V arena. A write still needs a live exact tail lease. */
    uint32_t kv_arena,kv_arena_bytes;
    const nx_weights *kv_model;
    uint64_t kv_output_saved_bytes,kv_direct_calls;
    uint32_t head_valid,head_epoch,head_generation,head_address;
    uint64_t head_session,head_sequence,head_argmax_calls,head_read_saved_bytes;
    int last_status;
} nxr_ce64_backend;
int nxr_ce64_linear_kv(void *,const float *,int,const nx_matrix *,float *,const nx_kv_tail *);
int nxr_ce64_argmax(void *,const float *,uint32_t,int32_t *);
int nxr_ce64_pv(void *,const float *,const float *,int,int,int,int,float *);
void nxr_ce64_input_v2(void *,const float *,int,int,uint64_t);
int nxr_ce64_vector(void *,unsigned,const float *,const float *,int,int,float *);
/* Same revoked-view contract as private linear; disjoint SwiGLU output. */
int nxr_ce64_vector_private(void *,unsigned,const float *,const float *,int,int,float *);
int nxr_ce64_linear(void *,const float *,int,const nx_matrix *,float *);
/* Private-output ABI: caller owns the entire destination and revokes all
 * views until success. Failure may dirty it and must invalidate the session.
 * Never use this entry for caller-owned/public output. */
int nxr_ce64_linear_private(void *,const float *,int,const nx_matrix *,float *);
#endif
