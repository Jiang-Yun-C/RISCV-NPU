#ifndef NXR_STREAM_H
#define NXR_STREAM_H
#include "runtime.h"
#define NXS_NULL UINT64_MAX
enum { NXS_BEGIN=1,NXS_TOKEN,NXS_TEXT,NXS_END,NXS_ABORT };
/* Preview events confer no semantic/action authority. Only STOPPED plus all
 * final checks permits nxr_output/final publication. TEXT bytes are valid UTF-8. */
typedef struct {
    uint32_t kind,index,token; int error;
    uint64_t session,sequence,ticks;
    const char *data; size_t bytes;
} nxs_event;
typedef int (*nxs_sink)(void *,const nxs_event *);
typedef struct {
    nxt_decoder decoder; const nxt_tokenizer *tokenizer; nxr_request *request;
    char *output; size_t capacity,bytes; uint32_t seen,active,enabled,aborted,terminal_abort;
    uint64_t origin,first_text,last_text,complete,decode_ticks,callback_ticks,events,legacy_ticks,output_wire_bytes;
    nxs_sink sink; void *context;
} nxs_stream;
int nxs_open(nxs_stream *,nxr_request *,const nxt_tokenizer *,char *,size_t,
             uint64_t received_at,int enabled,nxs_sink,void *);
int nxs_update(nxs_stream *);
int nxs_finish(nxs_stream *);
/* terminal_abort opts into one control ABORT even after END or with previews
 * disabled. The board enables it only for the enhanced recovery protocol. */
int nxs_abort(nxs_stream *,int error);
/* Common wire encoder; sink drains the actual transport before returning. */
typedef void (*nxs_put)(void *,char);
int nxs_wire(void *,const nxs_event *);
typedef struct { nxs_put put; void *context; void (*drain)(void *); uint64_t bytes; } nxs_uart;
void nxs_timing(nxs_stream *,nxs_uart *);
#endif
