/* Adversarial stream controls: scripted callbacks here test failure semantics,
 * never model quality, board timing or a full-model numerical claim. */
#include "stream.h"
#include "model.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define CHECK(x) do { if(!(x)){fprintf(stderr,"line %d: %s\n",__LINE__,#x);return 1;} } while(0)
static uint64_t ticks;
static uint64_t delay_ticks;
static unsigned resets,cursor,count,events[6],fail_kind,delay_kind;
static uint32_t sequence[16];
static char rendered[4096];
static size_t rendered_bytes;
static uint64_t fake_clock(void *p){(void)p;return ++ticks;}
uint64_t nx_port_ticks(void){return ++ticks;}
static int reset_model(void *p){(void)p;resets++;return 0;}
static int forward(void *p,uint32_t token,uint32_t past,uint32_t *next){
    (void)p;(void)token;(void)past;
    if(cursor>=count)return NXR_FAULT;
    *next=sequence[cursor++];return 0;
}
static int sink(void *context,const nxs_event *e){
    (void)context;
    if(e->kind<1||e->kind>5)return NXR_INVALID;
    events[e->kind]++;
    if(e->kind==NXS_TEXT){
        if(!e->bytes||!e->data)return NXR_INVALID;
        if(rendered_bytes+e->bytes>sizeof(rendered))return NXR_BOUNDS;
        memcpy(rendered+rendered_bytes,e->data,e->bytes);rendered_bytes+=e->bytes;
    }
    if(e->kind==delay_kind)ticks+=delay_ticks;
    return e->kind==fail_kind?NXR_FAULT:0;
}
static int begin(nxr_request *r,nxs_stream *s,const nxt_tokenizer *t,char *out,
                 size_t cap,const uint32_t *ids,size_t n){
    cursor=0;count=(unsigned)n;memcpy(sequence,ids,n*4);
    memset(events,0,sizeof(events));rendered_bytes=0;fail_kind=0;delay_kind=0;delay_ticks=0;
    int rc=nxr_init(r,NULL,forward,reset_model,fake_clock,NULL,151936);
    uint32_t prompt=0;
    if(!rc)rc=nxr_begin_ids(r,&prompt,1,(uint32_t)n,1000000);
    if(!rc)rc=nxs_open(s,r,t,out,cap,ticks,1,sink,NULL);
    return rc;
}
int main(int argc,char **argv){
    CHECK(argc==2);FILE *f=fopen(argv[1],"rb");CHECK(f);
    CHECK(fseek(f,0,SEEK_END)==0);long size=ftell(f);CHECK(size>0);rewind(f);
    unsigned char *blob=malloc((size_t)size);CHECK(blob);
    CHECK(fread(blob,1,(size_t)size,f)==(size_t)size);fclose(f);
    nxt_tokenizer tokenizer;CHECK(nxt_init(&tokenizer,blob,(size_t)size)==0);
    nxr_request r;nxs_stream s;char out[4096];

    const uint32_t split[]={100,101,102,106,107,NXR_EOS};
    CHECK(begin(&r,&s,&tokenizer,out,sizeof(out),split,6)==0);
    for(unsigned i=0;i<6;i++){
        CHECK(nxr_step(&r)==0);CHECK(nxs_update(&s)==0);
        if(i<2)CHECK(rendered_bytes==0);
        if(i==2)CHECK(rendered_bytes==3&&memcmp(rendered,"\xe4\xb8\xad",3)==0);
        if(i<5)CHECK(nxr_output(&r,0)==UINT32_MAX);
    }
    CHECK(nxs_finish(&s)==0&&s.bytes==7&&events[NXS_TEXT]==2&&events[NXS_END]==1);
    CHECK(memcmp(rendered,"\xe4\xb8\xad\xf0\x9f\x8c\x8d",7)==0);
    CHECK(nxr_count(&r)==6&&r.stop==NXR_STOP_EOS);

    const uint32_t only_eos[]={NXR_EOS};
    CHECK(begin(&r,&s,&tokenizer,out,sizeof(out),only_eos,1)==0);
    CHECK(nxr_step(&r)==0&&nxs_update(&s)==0&&nxs_finish(&s)==0);
    CHECK(s.bytes==0&&s.first_text==NXS_NULL&&events[NXS_TEXT]==0);

    const uint32_t partial[]={100};
    CHECK(begin(&r,&s,&tokenizer,out,sizeof(out),partial,1)==0);
    CHECK(nxr_step(&r)==0&&nxs_update(&s)==0&&rendered_bytes==0);
    CHECK(nxs_finish(&s)==0&&s.bytes==3&&memcmp(out,"\xef\xbf\xbd",3)==0);

    const uint32_t control[]={104,109,105};
    CHECK(begin(&r,&s,&tokenizer,out,sizeof(out),control,3)==0);
    while(r.state!=NXR_STOPPED){CHECK(nxr_step(&r)==0&&nxs_update(&s)==0);}
    CHECK(nxs_finish(&s)==0&&s.bytes==15);
    CHECK(memcmp(out,"\nT25 READY\n\r\0\tA",15)==0);

    const uint32_t normal[]={105,105,105};
    CHECK(begin(&r,&s,&tokenizer,out,1,normal,3)==0);
    CHECK(nxr_step(&r)==0&&nxs_update(&s)==0);
    CHECK(nxr_step(&r)==0&&nxs_update(&s)==NXR_BOUNDS);
    CHECK(r.state==NXR_FAILED&&r.generated==0&&!s.active&&s.bytes==0);
    CHECK(events[NXS_ABORT]==1&&events[NXS_END]==0&&nxr_count(&r)==0);

    CHECK(begin(&r,&s,&tokenizer,out,sizeof(out),normal,3)==0);
    fail_kind=NXS_TEXT;
    CHECK(nxr_step(&r)==0&&nxs_update(&s)==NXR_FAULT);
    CHECK(r.state==NXR_FAILED&&!s.active&&events[NXS_ABORT]==1&&events[NXS_END]==0);

    CHECK(begin(&r,&s,&tokenizer,out,sizeof(out),normal,3)==0);
    CHECK(nxr_step(&r)==0&&nxs_update(&s)==0);
    ticks=r.start_ticks+r.timeout_ticks;
    CHECK(nxs_update(&s)==NXR_TIMEOUT&&r.state==NXR_FAILED&&r.generated==0);

    CHECK(begin(&r,&s,&tokenizer,out,sizeof(out),normal,3)==0);
    CHECK(nxr_step(&r)==0&&nxs_update(&s)==0);
    unsigned before=resets;
    CHECK(nxs_abort(&s,NXR_FAULT)==NXR_FAULT&&resets==before+1);
    CHECK(!s.active&&s.bytes==0&&r.generated==0&&r.kv_length==0&&events[NXS_END]==0);

    /* END callback failure must revoke even an otherwise completed request. */
    CHECK(begin(&r,&s,&tokenizer,out,sizeof(out),only_eos,1)==0);
    CHECK(nxr_step(&r)==0&&nxs_update(&s)==0);fail_kind=NXS_END;
    CHECK(nxs_finish(&s)==NXR_FAULT&&r.state==NXR_FAILED&&events[NXS_ABORT]==1);

    /* BEGIN failure cannot leave an active stream, valid KV or final output. */
    memset(events,0,sizeof(events));rendered_bytes=0;fail_kind=NXS_BEGIN;
    CHECK(nxr_init(&r,NULL,forward,reset_model,fake_clock,NULL,151936)==0);
    uint32_t prompt=0;
    CHECK(nxr_begin_ids(&r,&prompt,1,1,1000000)==0);
    before=resets;
    CHECK(nxs_open(&s,&r,&tokenizer,out,sizeof(out),ticks,1,sink,NULL)==NXR_FAULT);
    CHECK(events[NXS_BEGIN]==1&&events[NXS_ABORT]==1&&events[NXS_TOKEN]==0);
    CHECK(!s.active&&s.bytes==0&&r.state==NXR_FAILED&&resets==before+1);
    CHECK(r.generated==0&&r.kv_length==0&&nxr_output(&r,0)==UINT32_MAX);

    /* A successful but slow END sink must not turn timeout into success. */
    CHECK(begin(&r,&s,&tokenizer,out,sizeof(out),only_eos,1)==0);
    CHECK(nxr_step(&r)==0&&nxs_update(&s)==0);
    delay_kind=NXS_END;delay_ticks=r.timeout_ticks;
    CHECK(nxs_finish(&s)==NXR_TIMEOUT&&r.state==NXR_FAILED);
    CHECK(events[NXS_END]==1&&events[NXS_ABORT]==1&&!s.active);
    CHECK(r.generated==0&&r.kv_length==0&&s.bytes==0&&nxr_count(&r)==0);

    /* Likewise, TEXT callback delay is caught by the same update call. */
    CHECK(begin(&r,&s,&tokenizer,out,sizeof(out),normal,3)==0);
    delay_kind=NXS_TEXT;delay_ticks=r.timeout_ticks;
    CHECK(nxr_step(&r)==0&&nxs_update(&s)==NXR_TIMEOUT);
    CHECK(events[NXS_TEXT]==1&&events[NXS_ABORT]==1&&events[NXS_END]==0);
    CHECK(!s.active&&r.state==NXR_FAILED&&r.generated==0&&s.bytes==0);

    /* Cancellation discards an incomplete scalar before reuse of the stream. */
    CHECK(begin(&r,&s,&tokenizer,out,sizeof(out),split,6)==0);
    CHECK(nxr_step(&r)==0&&nxs_update(&s)==0&&s.decoder.count==1);
    CHECK(nxs_abort(&s,NXR_FAULT)==NXR_FAULT&&s.decoder.count==0&&s.bytes==0);
    CHECK(begin(&r,&s,&tokenizer,out,sizeof(out),normal,1)==0);
    CHECK(nxr_step(&r)==0&&nxs_update(&s)==0&&nxs_finish(&s)==0);
    CHECK(s.bytes==1&&out[0]=='A'&&rendered_bytes==1&&rendered[0]=='A');
    CHECK(events[NXS_TEXT]==1&&events[NXS_END]==1&&events[NXS_ABORT]==0);

    free(blob);puts("PASS: split UTF-8, EOS, final flush, control text, bounds, sink failure, timeout, abort, failed/slow END, failed BEGIN, slow TEXT, pending-scalar reuse");
    return 0;
}
