#include "runtime.h"
#include <string.h>
#include <limits.h>
#ifdef __riscv
_Static_assert(sizeof(size_t)==4&&sizeof(uintptr_t)==4&&sizeof(void *)==4,"RV32 ILP32 pointers required");
#endif
int nxr_file_span(uint64_t off,uint64_t count,uint64_t item,uint64_t size,uint64_t *end) {
    if(!end||!item)return NXR_INVALID;
    if(count>UINT64_MAX/item)return NXR_BOUNDS;
    uint64_t len=count*item;if(off>size||len>size-off)return NXR_BOUNDS;
    *end=off+len;return 0;
}
int nxr_arena_init(nxr_arena *a,void *base,uint32_t address,uint32_t capacity) {
    static const uint32_t starts[]={0xa8000000,0xac000000,0xb4800000,0xba000000};
    static const uint32_t limits[]={15728640,65249664,8388608,4600000};
    if(!a||!base||!capacity||((uintptr_t)base&15)||address&15)return NXR_INVALID;
    int valid=0;for(unsigned i=0;i<4;i++)if(address>=starts[i]&&(uint64_t)address+capacity<=(uint64_t)starts[i]+limits[i])valid=1;
    uint64_t available=(uint64_t)UINTPTR_MAX-(uint64_t)(uintptr_t)base;
    if(!valid||(uint64_t)capacity>available)return NXR_BOUNDS;
    *a=(nxr_arena){base,address,capacity,0,0};return 0;
}
int nxr_alloc(nxr_arena *a,uint64_t count,uint64_t item,uint32_t align,void **out,uint32_t *address) {
    if(!a||!out||!address||!count||!item||align<16||align>4096||(align&(align-1)))return NXR_INVALID;
    if(((uintptr_t)a->base-(uintptr_t)a->address)&(align-1))return NXR_INVALID;
    if(a->used>a->capacity||count>UINT64_MAX/item)return NXR_BOUNDS;
    uint64_t at=((uint64_t)a->address+a->used+align-1)&~(uint64_t)(align-1),offset=at-a->address,len=count*item;
    if(offset>a->capacity||len>a->capacity-offset||at>UINT32_MAX)return NXR_BOUNDS;
    *out=a->base+offset;*address=(uint32_t)at;a->used=(uint32_t)(offset+len);if(a->used>a->peak)a->peak=a->used;return 0;
}
void nxr_arena_rewind(nxr_arena *a) {if(a)a->used=0;}
int nxr_init(nxr_request *r,void *model,nxr_forward_fn forward,nxr_reset_fn reset,nxr_clock_fn clock,void *ctx,uint32_t vocab) {
    if(!r||!forward||!reset||!clock||!vocab||vocab>151936)return NXR_INVALID;
    memset(r,0,sizeof(*r));r->model=model;r->forward=forward;r->reset=reset;r->clock=clock;r->clock_context=ctx;r->vocab=vocab;
    return nxr_reset(r);
}
int nxr_set_prefill(nxr_request *r,nxr_prefill_fn prefill) {
    if(!r||!r->forward)return NXR_INVALID;
    if(r->busy||r->state==NXR_PREFILL||r->state==NXR_DECODE)return NXR_BUSY;
    r->prefill=prefill;return 0;
}
int nxr_set_prefill_block(nxr_request *r,nxr_prefill_block_fn block,uint32_t rows) {
    if(!r||!r->forward||(rows!=1&&rows!=4)||(!block&&rows!=1))return NXR_INVALID;
    if(r->busy||r->state==NXR_PREFILL||r->state==NXR_DECODE)return NXR_BUSY;
    r->prefill_block=block;r->prefill_rows=rows;return 0;
}
int nxr_reset(nxr_request *r) {
    if(!r||!r->reset)return NXR_INVALID;
    if(r->busy||r->state==NXR_PREFILL||r->state==NXR_DECODE)return NXR_BUSY;
    if(r->session==UINT64_MAX)return NXR_STATE;
    int rc=r->reset(r->model);if(rc){r->state=NXR_FAILED;r->error=rc;return rc;}
    r->session++;r->sequence=0;r->state=NXR_IDLE;r->stop=0;r->error=0;
    r->prompt_length=r->prefilled=r->generated=r->kv_length=r->prefill_boundary=0;
    r->tokenizer_ticks=r->prefill_ticks=r->decode_ticks=r->total_ticks=0;
    r->tokenized_at=r->prefill_at=0;memset(r->token_at,0,sizeof(r->token_at));
    return 0;
}
int nxr_begin_ids(nxr_request *r,const uint32_t *ids,size_t n,uint32_t maximum,uint64_t timeout) {
    if(!r||!ids)return NXR_INVALID;
    if(r->busy||r->state==NXR_PREFILL||r->state==NXR_DECODE)return NXR_BUSY;
    if(r->state!=NXR_IDLE||r->sequence==UINT64_MAX)return NXR_STATE;
    if(!n||n>NXR_INPUT_MAX||!maximum||maximum>NXR_OUTPUT_MAX||!timeout)return NXR_BOUNDS;
    for(size_t i=0;i<n;i++)if(ids[i]>=r->vocab)return NXR_INVALID;
    memcpy(r->prompt,ids,n*4);r->prompt_length=n;r->max_new=maximum;r->timeout_ticks=timeout;
    r->start_ticks=r->clock(r->clock_context);r->tokenized_at=r->start_ticks;r->sequence++;r->state=NXR_PREFILL;return 0;
}
int nxr_begin_text(nxr_request *r,const nxt_tokenizer *t,nxt_work *w,const nxt_message *messages,size_t n,
                   char *buffer,size_t cap,uint32_t maximum,uint64_t timeout) {
    if(!r||!t||!w||!buffer)return NXR_INVALID;
    if(r->busy||r->state==NXR_PREFILL||r->state==NXR_DECODE)return NXR_BUSY;
    if(r->state!=NXR_IDLE)return NXR_STATE;
    uint64_t start=r->clock(r->clock_context);size_t len=0,count=0;uint32_t ids[NXR_INPUT_MAX];
    int rc=nxt_template(messages,n,1,buffer,cap,&len);if(rc)return rc;
    rc=nxt_encode(t,w,buffer,len,ids,NXR_INPUT_MAX,&count);if(rc)return rc;
    uint64_t elapsed=r->clock(r->clock_context)-start;
    if(!timeout||elapsed>=timeout)return NXR_TIMEOUT;
    rc=nxr_begin_ids(r,ids,count,maximum,timeout);if(rc)return rc;
    r->start_ticks=start;r->tokenizer_ticks=elapsed;return 0;
}
static int fail(nxr_request *r,int error) {
    /* Timeout and preview/transport abort also revoke a previously good prefix. */
    int reset_error=r->reset(r->model);
    /* A failed invalidation is a fault, never a successful user cancellation.
     * Preserve its error instead of masking it behind CANCELLED/TIMEOUT. */
    if(reset_error)error=(reset_error==NXR_CANCELLED||reset_error==NXR_TIMEOUT)?NXR_FAULT:reset_error;
    r->state=NXR_FAILED;r->error=error;r->kv_length=0;r->generated=0;
    memset(r->output,0,sizeof(r->output));memset(r->token_at,0,sizeof(r->token_at));
    r->total_ticks=r->clock(r->clock_context)-r->start_ticks;return error;
}
int nxr_restart_ids(nxr_request *r,const uint32_t *ids,size_t n,uint32_t maximum,uint64_t timeout,
                    nxr_restore_fn restore,void *context) {
    if(!r||!ids||!restore||!r->forward||!r->clock)return NXR_INVALID;
    if(r->busy||r->state==NXR_PREFILL||r->state==NXR_DECODE)return NXR_BUSY;
    if(r->session==UINT64_MAX)return NXR_STATE;
    if(!n||n>NXR_INPUT_MAX||!maximum||maximum>NXR_OUTPUT_MAX||!timeout)return NXR_BOUNDS;
    for(size_t i=0;i<n;i++)if(ids[i]>=r->vocab)return NXR_INVALID;
    uint64_t start=r->clock(r->clock_context);uint32_t past=0;
    int rc=restore(context,ids,n,&past);
    if(rc||past>=n)return fail(r,rc?rc:NXR_STATE);
    /* Clear all per-request publication/timing state; preserve callback setup. */
    r->session++;r->sequence=0;r->state=NXR_IDLE;r->stop=0;r->error=0;
    r->prompt_length=r->prefilled=r->generated=r->kv_length=r->last=r->prefill_boundary=0;
    memset(r->output,0,sizeof(r->output));memset(r->token_at,0,sizeof(r->token_at));
    r->tokenizer_ticks=r->prefill_ticks=r->decode_ticks=r->total_ticks=0;
    r->tokenized_at=r->prefill_at=0;
    rc=nxr_begin_ids(r,ids,n,maximum,timeout);
    if(rc)return fail(r,rc);
    r->start_ticks=start;r->prefilled=r->kv_length=past;
    return 0;
}
int nxr_cancel(nxr_request *r,int error) {
    if(!r||!error)return NXR_INVALID;
    if(r->busy)return NXR_BUSY;
    /* Repeated ABORT cleanup must not overwrite an earlier hardware or reset
     * failure with a softer CANCELLED/TIMEOUT reason. */
    if(r->state==NXR_FAILED&&r->error&&r->error!=NXR_CANCELLED&&r->error!=NXR_TIMEOUT&&
       (error==NXR_CANCELLED||error==NXR_TIMEOUT))return r->error;
    return fail(r,error);
}
int nxr_step(nxr_request *r) {
    if(!r)return NXR_INVALID;
    if(r->busy)return NXR_BUSY;
    if(r->state!=NXR_PREFILL&&r->state!=NXR_DECODE)return NXR_STATE;
    uint64_t start=r->clock(r->clock_context);
    if(start-r->start_ticks>=r->timeout_ticks)return fail(r,NXR_TIMEOUT);
    int prefill=r->state==NXR_PREFILL;uint32_t next=UINT32_MAX;
    uint32_t token=prefill?r->prompt[r->prefilled]:r->last;
    /* Every prompt token still advances the model by one position. Keep the
     * final prompt head even for a full context: diagnostics may inspect its
     * logits. Legacy callbacks retain their original non-NULL-next path. */
    int advance_only=prefill&&r->prefill&&r->prefilled+1<r->prompt_length;
    uint32_t rows=1;
    if(prefill&&r->prefill_block){
        uint32_t remaining=r->prompt_length-r->prefilled;
        rows=remaining<r->prefill_rows?remaining:r->prefill_rows;
    }
    if(prefill&&r->prefill_boundary>r->prefilled&&
       rows>r->prefill_boundary-r->prefilled)rows=r->prefill_boundary-r->prefilled;
    nx_diag_runtime(((5u<<16)|__LINE__),0,r);r->busy=1;
    int rc=prefill&&r->prefill_block?
        r->prefill_block(r->model,r->prompt+r->prefilled,rows,r->kv_length,
                        r->prefilled+rows==r->prompt_length?&next:NULL):
        advance_only?r->prefill(r->model,token,r->kv_length):
        r->forward(r->model,token,r->kv_length,&next);
    r->busy=0;
    uint64_t elapsed=r->clock(r->clock_context)-start;
    if(prefill)r->prefill_ticks+=elapsed;else r->decode_ticks+=elapsed;
    r->total_ticks=r->clock(r->clock_context)-r->start_ticks;
    if(rc)return fail(r,nx_diag_runtime(((5u<<16)|__LINE__),rc,r));
    if(r->total_ticks>=r->timeout_ticks)return fail(r,NXR_TIMEOUT);
    r->kv_length+=rows;
    if(prefill){r->prefilled+=rows;if(r->prefilled<r->prompt_length)return 0;}
    if(prefill)r->prefill_at=r->clock(r->clock_context);
    r->state=NXR_DECODE;
    if(r->prompt_length+r->generated==NXR_TOTAL_MAX){r->state=NXR_STOPPED;r->stop=NXR_STOP_CONTEXT;return 0;}
    if(next>=r->vocab)return fail(r,NXR_FAULT);
    r->token_at[r->generated]=r->clock(r->clock_context);
    r->last=next;r->output[r->generated++]=next;
    if(next==NXR_EOS){r->state=NXR_STOPPED;r->stop=NXR_STOP_EOS;}
    else if(r->prompt_length+r->generated==NXR_TOTAL_MAX){r->state=NXR_STOPPED;r->stop=NXR_STOP_CONTEXT;}
    else if(r->generated==r->max_new){r->state=NXR_STOPPED;r->stop=NXR_STOP_OUTPUT;}
    return 0;
}
