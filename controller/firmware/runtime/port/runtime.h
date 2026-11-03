#ifndef NXR_RUNTIME_H
#define NXR_RUNTIME_H
#include <stdint.h>
#include <stddef.h>
#include "tokenizer.h"
#define NXR_INPUT_MAX 512u
#define NXR_TOTAL_MAX 512u
#define NXR_OUTPUT_MAX 128u
#define NXR_EOS 151645u
enum { NXR_OK=0,NXR_INVALID=-1,NXR_BOUNDS=-4,NXR_BUSY=-6,NXR_TIMEOUT=-7,NXR_FAULT=-8,NXR_STATE=-10,NXR_CANCELLED=-11 };
enum { NXR_IDLE,NXR_PREFILL,NXR_DECODE,NXR_STOPPED,NXR_FAILED };
enum { NXR_STOP_NONE,NXR_STOP_EOS,NXR_STOP_OUTPUT,NXR_STOP_CONTEXT };
typedef struct { uint8_t *base; uint32_t address,capacity,used,peak; } nxr_arena;
int nxr_arena_init(nxr_arena *,void *,uint32_t address,uint32_t capacity);
int nxr_alloc(nxr_arena *,uint64_t count,uint64_t item,uint32_t alignment,void **,uint32_t *address);
int nxr_file_span(uint64_t offset,uint64_t count,uint64_t item,uint64_t file_bytes,uint64_t *end);
void nxr_arena_rewind(nxr_arena *);
typedef int (*nxr_forward_fn)(void *,uint32_t token,uint32_t past,uint32_t *next);
/* Optional prompt-only state advance. Same KV/error contract as forward, but
 * no next token is requested. The existing forward callback always receives
 * a non-NULL next pointer, including when this optimization is disabled. */
typedef int (*nxr_prefill_fn)(void *,uint32_t token,uint32_t past);
/* Prompt-only atomic block; final block requests one last-row head. */
typedef int (*nxr_prefill_block_fn)(void *,const uint32_t *,uint32_t rows,uint32_t past,uint32_t *next);
typedef int (*nxr_reset_fn)(void *);
typedef uint64_t (*nxr_clock_fn)(void *);
typedef struct {
    uint32_t state,stop,prompt_length,prefilled,generated,kv_length,last;
    uint32_t max_new,vocab,route,busy;
    uint32_t prompt[NXR_INPUT_MAX],output[NXR_OUTPUT_MAX];
    uint64_t session,sequence,start_ticks,timeout_ticks,tokenizer_ticks,prefill_ticks,decode_ticks,total_ticks;
    int error;
    void *model,*clock_context;
    nxr_forward_fn forward;
    nxr_reset_fn reset;
    nxr_clock_fn clock;
    nxr_prefill_fn prefill;
    nxr_prefill_block_fn prefill_block;
    uint32_t prefill_rows;
    /* Optional prompt boundary; a block never crosses it. Zero disables it. */
    uint32_t prefill_boundary;
    /* Absolute mcycle samples before any UART/preview work. Rebuild consumers. */
    uint64_t tokenized_at,prefill_at,token_at[NXR_OUTPUT_MAX];
} nxr_request;
int nxr_init(nxr_request *,void *,nxr_forward_fn,nxr_reset_fn,nxr_clock_fn,void *,uint32_t vocab);
/* Set while no request is active. NULL restores the legacy forward-only
 * path. nxr_init disables this callback; nxr_reset preserves the setting.
 * The appended callback changes sizeof(nxr_request): rebuild all consumers. */
int nxr_set_prefill(nxr_request *,nxr_prefill_fn);
int nxr_set_prefill_block(nxr_request *,nxr_prefill_block_fn,uint32_t rows);
int nxr_reset(nxr_request *);
int nxr_begin_ids(nxr_request *,const uint32_t *,size_t,uint32_t max_new,uint64_t timeout_ticks);
/* Synchronous verified KV restore. A miss must reset the attached model and
 * publish past=0. A hit publishes an exact prefix shorter than the prompt. */
typedef int (*nxr_restore_fn)(void *,const uint32_t *,size_t,uint32_t *past);
int nxr_restart_ids(nxr_request *,const uint32_t *,size_t,uint32_t,uint64_t,
                    nxr_restore_fn,void *);
int nxr_begin_text(nxr_request *,const nxt_tokenizer *,nxt_work *,const nxt_message *,size_t,
                   char *text_buffer,size_t capacity,uint32_t max_new,uint64_t timeout_ticks);
/* One synchronous prefill/decode step; returns 0 with state STOPPED on success.
 * Output is valid only when state==STOPPED. Failed KV cannot be resumed. */
int nxr_step(nxr_request *);
/* Preview/transport failure invalidates KV and final publication. */
int nxr_cancel(nxr_request *,int error);
#endif
