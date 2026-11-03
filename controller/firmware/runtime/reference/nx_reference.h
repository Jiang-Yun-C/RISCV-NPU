#ifndef NX_REFERENCE_H
#define NX_REFERENCE_H
#include <stdint.h>
#include <stddef.h>
/* Sealed, validated model-pack-v1 views; owner keeps storage alive and immutable. */
typedef struct { const int8_t *q; const float *s, *bias; int n, k; } nx_matrix;
typedef struct { const float *norm1, *norm2; nx_matrix q,k,v,o,gate,up,down; } nx_layer;
typedef struct { nx_matrix embedding; nx_layer layer[24]; const float *norm, *inv_freq; } nx_weights;
typedef struct nx_session nx_session;
#define NX_PREFIX_ABI 1u
#define NX_PREFIX_MAX 512u
/* SHA256 bytes of sealed artifacts/configuration; no text-prefix heuristics.
 * The owner must reconfigure before changing weights, math or backend state. */
typedef struct {
    uint8_t model[32], tokenizer[32], template_version[32], numeric[32], backend[32];
    uint32_t abi, start_position, context_limit, flags;
} nx_prefix_identity;
int nx_prefix_configure(nx_session *,const nx_prefix_identity *);
int nx_prefix_prepare(nx_session *,const nx_prefix_identity *,const int32_t *,size_t);
/* Seal a successfully computed exact prefix at the current logical length.
 * The owner configures identity before computing these same IDs. No KV copy. */
int nx_prefix_capture(nx_session *,const nx_prefix_identity *,const int32_t *,size_t);
/* 1=exact hit; 0=miss and empty reset session. Never copies KV. */
int nx_prefix_restore(nx_session *,const nx_prefix_identity *,const int32_t *,size_t);
void nx_prefix_invalidate(nx_session *);
/* Bounded logical view. Bytes beyond *tokens are not part of this view. */
const float *nx_cache_view(nx_session *,int layer,int value,size_t *tokens);
typedef void (*nx_trace)(int layer, const char *name, const float *data, int rows, int cols);
/* Optional synchronous dispatch for a qualified linear implementation. Return
 * NX_UNSUPPORTED before any work to use the identical C kernel. Other failures
 * invalidate the session; a hardware fault is never hidden by CPU fallback. */
enum { NX_UNSUPPORTED=-100 };
/* Vector ABI v1: modes 0 SwiGLU, 2 residual add, 7 RMSNorm. Unsupported
 * must precede submission; other failures invalidate the model request. */
typedef int (*nx_pv_backend)(void *,const float *,const float *,int,int,int,int,float *);
void nx_bind_pv_backend(nx_session *,nx_pv_backend);
typedef int (*nx_vector_backend)(void *,unsigned,const float *,const float *,int,int,float *);
void nx_bind_vector_backend(nx_session *,nx_vector_backend);
void nx_bind_private_vector_backend(nx_session *,nx_vector_backend);
typedef int (*nx_linear_backend)(void *context,const float *,int,const nx_matrix *,float *);
/* A synchronous, single-use lease for an unpublished K/V tail. The model
 * owner checks the complete view before and after backend execution. This is
 * not a general permission to write the KV arena or an already valid prefix. */
#define NX_KV_TAIL_ABI 1u
typedef struct {
    nx_session *owner;
    uint64_t serial;
    uintptr_t arena, destination;
    uint32_t abi,layer,value,past,rows,layers,capacity,width;
} nx_kv_tail;
typedef int (*nx_kv_linear_backend)(void *,const float *,int,const nx_matrix *,float *,const nx_kv_tail *);
void nx_bind_kv_backend(nx_session *,nx_kv_linear_backend);
int nx_kv_tail_valid(const nx_kv_tail *,const nx_matrix *,const float *);
/* An optional token selection result from a completed full-vocabulary head.
 * Unsupported is permitted only before consuming a candidate. */
typedef int (*nx_argmax_backend)(void *,const float *,uint32_t,int32_t *);
void nx_bind_argmax_backend(nx_session *,nx_argmax_backend);
/* Private-output ABI v1: the callback may dirty only the nominated internal
 * workspace. All borrowed views expire on the next request/reset/rebind.
 * During execution no session view is available; any error invalidates it.
 * K/V and external caller buffers continue through the legacy callback. */
void nx_bind_private_backend(nx_session *,nx_linear_backend);
typedef void (*nx_dispatch_trace)(void *context,int kind,int route,int reason,int status,uint64_t ticks);
#define NX_INPUT_VIEW_ABI 2u
typedef void (*nx_input_observer)(void *,const float *,int,int,uint64_t);
void nx_bind_input_observer(nx_session *,nx_input_observer);
/* Explicit opt-in for a matching private vector/input backend. The callback
 * reserves an unpublished M1/K4864 SwiGLU destination version; it must NOT
 * treat that notification as completed data or grant a valid input lease.
 * Rebinding a backend/observer clears this opt-in. Contexts are single-caller. */
void nx_bind_private_swiglu_reservation(nx_session *,nx_input_observer);
void nx_opt08_counters(nx_session *,uint64_t *,uint64_t *);
/* Candidate ABI v3: 1 or 4 rows, [past,past+rows), <=512 context.
 * next==NULL skips final norm/head; otherwise computes only the last row.
 * Decode must call rows=1. Reconfigure before preparing a prefix. */
int nx_set_prefill_rows(nx_session *,int rows);
int nx_forward_block_v3(nx_session *,const int32_t *,int rows,int past,int32_t *next);
int nx_forward_token_v2(nx_session *,int32_t,int,int32_t *);
const float *nx_logits_v2(nx_session *);
void nx_bind_backend(nx_session *,void *,nx_linear_backend,nx_dispatch_trace,int route);
#ifdef NX_PORTABLE
/* Caller owns nonoverlapping, 16-byte aligned arenas. No malloc, POSIX or OMP. */
nx_session *nx_init_static(const nx_weights *,void *state,size_t state_bytes,
                           void *kv,size_t kv_bytes,void *work,size_t work_bytes);
size_t nx_state_bytes(void);
size_t nx_kv_bytes(void);
size_t nx_work_bytes(void);
uint64_t nx_port_ticks(void);
#endif
enum { NX_OK=0, NX_ARGUMENT=-1, NX_NUMERIC=-2, NX_MEMORY=-3, NX_STATE=-4 };
enum { NX_EMBED, NX_NORM, NX_LINEAR, NX_ROPE, NX_ATTN, NX_SWIGLU, NX_RESIDUAL, NX_HEAD, NX_TIMERS };
int nx_quantize(const float*, int rows, int k, int8_t*, float*);
int nx_linear(const float*, int rows, const nx_matrix*, float*, int32_t *dots);
int nx_norm(const float*, const float*, int rows, int width, float*);
int nx_rope(float*, int rows, int heads, int past, const float*);
int nx_swiglu(const float*, const float*, int count, float*);
nx_session *nx_create(const nx_weights*, int threads);
void nx_destroy(nx_session*);
void nx_reset(nx_session*);
/* Append 1..NX_PREFILL_MAX IDs at exactly past. logits: NULL or [rows,151936].
 * A failure invalidates the cache; logits are published only after success. */
int nx_forward(nx_session*, const int32_t*, int rows, int past, float *logits, nx_trace);
int nx_greedy(const float *logits, int32_t *token);
/* Complete greedy loop in C. stop=1 EOS(151645), stop=2 128-token limit, stop=3 total context 512.
 * count, stop, output_ids are published together only on success. */
int nx_generate(nx_session*, const int32_t *input_ids, int prompt_length,
                int32_t output_ids[128], int *count, int *stop);
const float *nx_cache(nx_session*, int layer, int value);
int nx_length(nx_session*);
size_t nx_memory_bytes(void);
void nx_profile(nx_session*, double seconds[NX_TIMERS], uint64_t calls[NX_TIMERS]);
#ifdef NX_PORTABLE
/* NX_PROFILE_INTEGER=1 keeps hot-path time arithmetic in raw uint64 cycles. */
void nx_profile_ticks(nx_session*, uint64_t ticks[NX_TIMERS], uint64_t calls[NX_TIMERS]);
#endif
#endif
