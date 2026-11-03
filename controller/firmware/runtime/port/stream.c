#include "stream.h"
#include <string.h>
static uint64_t now(nxs_stream *s){return s->request->clock(s->request->clock_context);}
static int event(nxs_stream *s,uint32_t kind,uint32_t token,const char *data,size_t n,int error){
    if(!s->enabled&&!(s->terminal_abort&&kind==NXS_ABORT))return 0;
    if(!s->sink)return 0; /* disabled previews may have no transport sink */
    uint64_t start=now(s);
    nxs_event e={kind,s->seen,token,error,s->request->session,s->request->sequence,start-s->origin,data,n};
    int rc=s->sink(s->context,&e);s->callback_ticks+=now(s)-start;s->events++;return rc;
}
int nxs_abort(nxs_stream *s,int error){
    if(!s||!s->request)return NXR_INVALID;
    if(!s->aborted&&(s->active||s->terminal_abort)){
        s->aborted=1;
        if(event(s,NXS_ABORT,0,0,0,error))error=NXR_FAULT;
    }
    s->active=0;
    memset(&s->decoder,0,sizeof(s->decoder));s->bytes=0;
    return nxr_cancel(s->request,error?error:NXR_FAULT);
}
int nxs_open(nxs_stream *s,nxr_request *r,const nxt_tokenizer *t,char *out,size_t cap,
             uint64_t origin,int enabled,nxs_sink sink,void *ctx){
    if(!s||!r||!t||!out||!cap||(enabled&&!sink)||r->state!=NXR_PREFILL)return NXR_INVALID;
    memset(s,0,sizeof(*s));s->tokenizer=t;s->request=r;s->output=out;s->capacity=cap;
    s->origin=origin;s->first_text=s->last_text=s->complete=NXS_NULL;
    s->enabled=enabled;s->sink=sink;s->context=ctx;s->active=1;
    int rc=event(s,NXS_BEGIN,0,0,0,0);return rc?nxs_abort(s,rc):0;
}
static int decode(nxs_stream *s,uint32_t token,int final){
    size_t n=0;uint64_t start=now(s);
    int rc=nxt_decode(s->tokenizer,&s->decoder,token,1,final,s->output+s->bytes,s->capacity-s->bytes,&n);
    s->decode_ticks+=now(s)-start;if(rc)return nxs_abort(s,rc);
    if(n){
        const char *fragment=s->output+s->bytes;s->bytes+=n;
        rc=event(s,NXS_TEXT,token,fragment,n,0);if(rc)return nxs_abort(s,rc);
        /* This sample follows the last UART stop bit of the complete frame. */
        if(s->enabled){s->last_text=now(s)-s->origin;if(s->first_text==NXS_NULL)s->first_text=s->last_text;}
    }
    return 0;
}
int nxs_update(nxs_stream *s){
    if(!s||!s->active)return NXR_STATE;
    nxr_request *r=s->request;
    if(r->state==NXR_FAILED)return nxs_abort(s,r->error);
    if((r->state!=NXR_PREFILL&&r->state!=NXR_DECODE&&r->state!=NXR_STOPPED)||
       r->generated<s->seen||r->generated>NXR_OUTPUT_MAX)return nxs_abort(s,nx_diag_runtime(((6u<<16)|__LINE__),NXR_STATE,r));
    while(s->seen<r->generated){
        uint32_t token=r->output[s->seen++];
        int rc=event(s,NXS_TOKEN,token,0,0,0);if(rc)return nxs_abort(s,rc);
        rc=decode(s,token,0);if(rc)return rc;
    }
    if(now(s)-r->start_ticks>=r->timeout_ticks)return nxs_abort(s,NXR_TIMEOUT);
    return 0;
}
int nxs_finish(nxs_stream *s){
    if(!s||!s->active||s->request->state!=NXR_STOPPED||s->seen!=s->request->generated)return NXR_STATE;
    int rc=decode(s,UINT32_MAX,1);if(rc)return rc;
    if(now(s)-s->request->start_ticks>=s->request->timeout_ticks)return nxs_abort(s,NXR_TIMEOUT);
    rc=event(s,NXS_END,0,0,0,0);if(rc)return nxs_abort(s,rc);
    /* A slow final transport callback is inside the request deadline too.
     * END alone never grants final-result authority; ABORT can still revoke it. */
    if(now(s)-s->request->start_ticks>=s->request->timeout_ticks)return nxs_abort(s,NXR_TIMEOUT);
    s->active=0;return 0;
}
static void put(nxs_uart *u,char c){u->put(u->context,c);u->bytes++;}
static void text(nxs_uart *u,const char *p){while(*p)put(u,*p++);}
static void hex(nxs_uart *u,uint64_t v,unsigned digits){for(int i=(int)digits-1;i>=0;i--)put(u,"0123456789abcdef"[(v>>(i*4))&15]);}
static void field(nxs_uart *u,const char *name,uint64_t v){text(u,name);put(u,'=');hex(u,v,16);put(u,' ');}
int nxs_wire(void *ctx,const nxs_event *e){
    nxs_uart *u=ctx;if(!u||!u->put||!e||(e->bytes&&!e->data))return NXR_INVALID;
    static const char *names[]={"INVALID","BEGIN","TOKEN","TEXT","END","ABORT"};
    if(e->kind<NXS_BEGIN||e->kind>NXS_ABORT)return NXR_INVALID;
    text(u,"T25 STREAM 1 ");text(u,names[e->kind]);put(u,' ');
    field(u,"session",e->session);field(u,"sequence",e->sequence);field(u,"index",e->index);
    field(u,"ticks",e->ticks);field(u,"token",e->token);field(u,"error",(uint32_t)e->error);
    text(u,"data=");if(!e->bytes)put(u,'-');else for(size_t i=0;i<e->bytes;i++)hex(u,(uint8_t)e->data[i],2);
    put(u,'\n');if(u->drain)u->drain(u->context);return 0;
}
void nxs_timing(nxs_stream *s,nxs_uart *u){
    uint64_t wire_bytes=u->bytes;nxr_request *r=s->request;text(u,"T25 TIME 1 ");
    field(u,"session",r->session);field(u,"sequence",r->sequence);field(u,"received_at",s->origin);
    field(u,"tokenized",r->tokenized_at-s->origin);
    field(u,"prefill",r->prefill_at?r->prefill_at-s->origin:NXS_NULL);
    field(u,"first_token",r->generated?r->token_at[0]-s->origin:NXS_NULL);
    field(u,"first_text",s->first_text);field(u,"last_text",s->last_text);field(u,"complete",s->complete);
    field(u,"decoder",s->decode_ticks);field(u,"callback",s->callback_ticks);field(u,"events",s->events);
    field(u,"wire_bytes",wire_bytes);field(u,"output_bytes",s->output_wire_bytes);field(u,"legacy",s->legacy_ticks);text(u,"tokens=");
    if(!r->generated)put(u,'-');else for(uint32_t i=0;i<r->generated;i++){
        if(i)put(u,',');hex(u,r->token_at[i]-s->origin,16);
    }
    put(u,'\n');if(u->drain)u->drain(u->context);
}
