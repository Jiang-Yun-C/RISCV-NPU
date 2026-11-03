#include "runtime.h"
#ifndef BASELINE
#include "stream.h"
#endif
#include <string.h>
static nxr_request r;static uint64_t ticks;static const uint32_t *ids;static unsigned length,pos;
static uint64_t clk(void *p){(void)p;return ++ticks;}
static int reset(void *p){(void)p;pos=0;return 0;}
static int forward(void *p,uint32_t token,uint32_t past,uint32_t *next){(void)p;(void)token;(void)past;ticks+=100;*next=ids[pos<length?pos++:length-1];return 0;}
static char wire[200000];static unsigned wire_n;
#ifndef BASELINE
static void put(void *p,char c){(void)p;if(wire_n<sizeof(wire)-1)wire[wire_n++]=c;ticks+=3;}
static void drain(void *p){(void)p;ticks+=5;}
#endif
/* Return request state/reason/IDs and final bytes through explicit test ABI. */
int replay(const void *table,unsigned table_n,const uint32_t *tokens,unsigned n,unsigned prompt,unsigned maximum,unsigned capacity,int enabled,char *out,unsigned *meta){
    ids=tokens;length=n;ticks=0;wire_n=0;wire[0]=0;
    int rc=nxr_init(&r,0,forward,reset,clk,0,151936);uint32_t input[512]={0};
    if(!rc)rc=nxr_begin_ids(&r,input,prompt,maximum,1000000000);
#ifndef BASELINE
    nxt_tokenizer t;nxs_stream s;nxs_uart uart={put,0,drain,0};
    if(!rc)rc=nxt_init(&t,table,table_n);
    if(!rc)rc=nxs_open(&s,&r,&t,out,capacity,0,enabled,nxs_wire,&uart);
#endif
    while(!rc&&(r.state==NXR_PREFILL||r.state==NXR_DECODE)){
        rc=nxr_step(&r);
#ifndef BASELINE
        if(!rc)rc=nxs_update(&s);
#endif
    }
#ifndef BASELINE
    if(!rc)rc=nxs_finish(&s);
    meta[4]=(unsigned)s.bytes;wire[wire_n]=0;
    meta[5]=s.first_text!=NXS_NULL;
#else
    (void)table;(void)table_n;(void)capacity;(void)enabled;(void)out;
#endif
    meta[0]=r.state;meta[1]=r.stop;meta[2]=r.generated;meta[3]=r.kv_length;
    for(unsigned i=0;i<r.generated;i++)meta[8+i]=r.output[i];
    return rc;
}
const char *events(void){return wire;}
