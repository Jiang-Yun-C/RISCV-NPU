#ifndef NX_LINEAR_API_H
#define NX_LINEAR_API_H
#include "accel.h"
#include "linear.h"
#define NX_LINEAR_BINDING_ABI 4u
typedef int (*nx_sealed_norm_read_fn)(void *,uint32_t,uint32_t,uint32_t,uint32_t,uint64_t);
typedef struct {
    uint64_t version, session, requested_version, quantizations, hits, ticks;
    uintptr_t source, requested_source;
    uint32_t m,k,aq,sa,input_address,aq_bytes,sa_bytes,requested_m,requested_k;
    int valid;
    /* valid certifies DDR bytes. resident_valid is an independent, one-use
     * scratch lease and must never grant DDR reuse after the lease expires. */
    uint32_t resident_valid,resident_epoch;
    uint64_t resident_first_sequence;
} nx_input_cache_v2;
typedef struct {
    nx_input_cache_v2 input_cache;
    nx_context *context;
    void *cookie;
    /* Resolve an arena view; on RV32 this validates then casts the physical
     * address. Model loader owns immutable, T10-validated Wq/Sw/bias storage. */
    void *(*resolve)(void *, uint32_t address, uint32_t bytes, int write);
    /* Submit the entire operator to the installed Coral microprogram. */
    nx_status (*execute)(void *, const nx_call *, const struct nx_stream_request *, struct nx_stream_result *);
    uint32_t aq_address,aq_bytes,sa_address,sa_bytes;
    /* Optional platform seal. Return one ONLY for the exact immutable,
     * numerically verified model views installed by the loader. Zero retains
     * the standalone provider's complete numeric scan. Bounds, dynamic input
     * validation and backend numeric checks are always performed. */
    int (*model_sealed)(void *, const nx_linear *);
    /* Optional typed read authority. Exact immutable norm UP only; every call
     * rechecks installed model, true seal, expected epoch and session. NULL
     * preserves all original public and staged vector behavior. ABI4 rebuild. */
    nx_sealed_norm_read_fn sealed_norm_read;
} nx_linear_binding;
void nx_linear_input_v2(nx_linear_binding *,uintptr_t,uint64_t,uint32_t,uint32_t);
void nx_linear_input_invalidate(nx_linear_binding *);
nx_status nx_linear_bind(nx_context *, nx_linear_binding *, uint32_t routes);
nx_status nx_linear_validate(const nx_linear *);
/* Internal provider entry; caller must own and validate the lifecycle. */
nx_status nx_linear_execute_binding(nx_linear_binding *, const nx_call *, const nx_linear *, nx_stats *);
#endif
