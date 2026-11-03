#ifndef NEXUSRV_BACKEND_V1_H
#define NEXUSRV_BACKEND_V1_H
#include <stdint.h>

/* Source-level API only. Never memcpy these structs into a model pack or TCM. */
#define NX_API_VERSION 1u
#define NX_LAYOUT_LOGICAL_ROW_MAJOR 1u
#define NX_GROUP_SIZE 64u
#define NX_MAX_INPUT_TOKENS 512u
#define NX_KV_CAPACITY 640u
#define NX_MAX_RANK 4u

typedef int32_t nx_status;
enum { NX_OK=0, NX_EINVAL=-1, NX_EVERSION=-2, NX_EUNSUPPORTED=-3,
       NX_EBOUNDS=-4, NX_EALIGN=-5, NX_EBUSY=-6, NX_ETIMEOUT=-7,
       NX_EFAULT=-8, NX_ENUMERIC=-9, NX_ESTATE=-10, NX_EIO=-11 };
enum { NX_I8=1, NX_F32=2, NX_U32=3 };
enum { NX_CPU_C=0, NX_CORAL_RVV=1 };
enum { NX_LINEAR=1, NX_ATTENTION=2, NX_VECTOR=3 };
enum { NX_EMBEDDING=1, NX_RMSNORM=2, NX_ROPE=3, NX_KV_APPEND=4,
       NX_ADD=5, NX_SWIGLU=6, NX_ARGMAX=7, NX_QUANTIZE=8 };
enum { NX_REFERENCE_TICKS=1u, NX_BACKEND_CYCLES=2u, NX_AXI_BYTES=4u };
enum { NX_FALLBACK_NONE=0, NX_FALLBACK_BASELINE_CPU=1,
       NX_FALLBACK_UNSUPPORTED=2, NX_FALLBACK_CPU_REQUEST=3 };

/* All addresses are unsigned SoC physical addresses, including on a host.
 * Host implementations resolve them through an arena; they are not pointers.
 * Zero-filled tensor is the sole absent-tensor encoding. */
typedef struct {
    uint32_t address, allocation_bytes, dtype, rank, layout_id;
    uint32_t shape[NX_MAX_RANK], stride_bytes[NX_MAX_RANK];
} nx_tensor;

typedef struct {
    uint32_t api_version, route;
    uint64_t session, sequence, timeout_ticks;
} nx_call;

typedef struct {
    nx_tensor a, wq, sw, bias, y;
    uint32_t group_size;
} nx_linear;

/* KV already contains this chunk. q[M,14,64], k/v[capacity,2,64]. */
typedef struct {
    nx_tensor q, k, v, y;
    uint32_t past, capacity;
} nx_attention;

/* Input/output slot conventions are normative in backend-contract-v1.md. */
typedef struct {
    uint32_t opcode, input_count, output_count, past, capacity;
    nx_tensor inputs[3], outputs[2];
} nx_vector;

typedef struct {
    uint32_t api_version, route, operation_mask, vector_mask;
    uint32_t max_m, max_n, max_k, max_context, group_size, alignment_bytes;
    uint32_t synchronous, max_inflight, numeric_version, layout_id;
    /* Masks reflect installed/qualified implementations, not intended support. */
} nx_caps;

typedef struct {
    uint64_t session, sequence, tick_hz, elapsed_ticks;
    uint64_t validate_ticks, quantize_ticks, upload_ticks, execute_ticks;
    uint64_t download_ticks, fallback_ticks, other_ticks;
    uint64_t backend_cycles, axi_read_bytes, axi_write_bytes;
    uint64_t upload_bytes, download_bytes, macs;
    uint32_t valid_counters, route, fallback_reason, output_valid;
    nx_status status;
} nx_stats;

typedef struct nx_context nx_context;
nx_status nx_query_caps(nx_context *, uint32_t route, nx_caps *);
nx_status nx_linear_run(nx_context *, const nx_call *, const nx_linear *, nx_stats *);
nx_status nx_attention_run(nx_context *, const nx_call *, const nx_attention *, nx_stats *);
nx_status nx_vector_run(nx_context *, const nx_call *, const nx_vector *, nx_stats *);
nx_status nx_wait(nx_context *, uint64_t session, uint64_t sequence, nx_stats *);
nx_status nx_reset_session(nx_context *, uint64_t timeout_ticks, uint64_t *new_session);
#endif
