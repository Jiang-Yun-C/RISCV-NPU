#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <limits.h>
#include "runtime.h"
#include "nx_reference.h"
#include "model.h"
#ifdef HOST_TEST
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#endif
#include "text_inputs.h"
#include "t11_tile.h"
#ifdef NX_SMALL
#include "small_weights.h"
#endif
static void emit(unsigned group,unsigned index,uint32_t value) {
#ifdef HOST_TEST
    printf("%u %u %u\n",group,index,value);
#else
    *(volatile uint32_t *)0x10000080=(group<<16)|index;
    *(volatile uint32_t *)0x10000084=value;
#endif
}
static void bytes(unsigned group,const void *data,size_t len) {emit(group,0,(uint32_t)len);for(size_t i=0;i<len;i++)emit(group,i+1,((const uint8_t *)data)[i]);}
static uint32_t bits(float x){uint32_t v;memcpy(&v,&x,4);return v;}
uint64_t nx_port_ticks(void) {
#ifdef HOST_TEST
    struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return (uint64_t)t.tv_sec*1000000000+t.tv_nsec;
#else
    uint32_t hi,lo,again;do{__asm__ volatile("csrr %0,mcycleh":"=r"(hi));__asm__ volatile("csrr %0,mcycle":"=r"(lo));__asm__ volatile("csrr %0,mcycleh":"=r"(again));}while(hi!=again);return (uint64_t)hi<<32|lo;
#endif
}
static volatile unsigned bss_probe[16];
static unsigned char arena_memory[4096] __attribute__((aligned(16)));
static nxt_work token_work;
static uint32_t token_ids[1024];
static char decoded[8192],framed[4096];
static nxr_request request;
static uint32_t prompt[513];
static uint64_t clock_value;
static unsigned fake_mode;
static int nested_status;
static uint64_t fake_clock(void *p){(void)p;return ++clock_value;}
static int fake_reset(void *p){(void)p;return 0;}
/* Explicit CONTROL_ONLY fixture: tests scheduling, never reported as model
 * numerics. The separate NX_SMALL and T11 paths execute the actual C kernels. */
static int fake_forward(void *p,uint32_t token,uint32_t past,uint32_t *next){
    (void)p;(void)token;(void)past;if(fake_mode==2)return NXR_FAULT;
    if(fake_mode==4)nested_status=nxr_step(&request);
    *next=fake_mode==0?NXR_EOS:fake_mode==3?151936:7;return 0;
}
static int run_request(void){int rc=0;for(unsigned i=0;i<1024&&(request.state==NXR_PREFILL||request.state==NXR_DECODE);i++)if((rc=nxr_step(&request)))return rc;return rc;}
static void controls(void) {
    unsigned v=0;for(unsigned i=0;i<16;i++)v|=bss_probe[i];emit(100,1,v);
    emit(100,2,sizeof(size_t)>=4&&sizeof(uintptr_t)==sizeof(void *));
    nxr_arena arena;void *a=0,*b=0;uint32_t address=0;uint64_t end=0;
    int rc=nxr_arena_init(&arena,arena_memory,0xb4800000,sizeof(arena_memory));
    rc|=nxr_alloc(&arena,2,16,16,&a,&address);emit(100,3,rc!=0||address!=0xb4800000);
    rc=nxr_alloc(&arena,UINT64_MAX,2,16,&b,&address);emit(100,4,rc!=NXR_BOUNDS||arena.used!=32);
    rc=nxr_file_span(UINT64_C(0x100000000),8,4,UINT64_C(0x100000020),&end);emit(100,5,rc==0&&end==UINT64_C(0x100000020));
    emit(100,6,nxr_file_span(UINT64_MAX-7,16,1,UINT64_MAX,&end)!=NXR_BOUNDS);
    emit(100,7,nxr_arena_init(&arena,arena_memory,0xbc000000,4096)!=NXR_BOUNDS);
    nxr_arena_rewind(&arena);rc=nxr_alloc(&arena,2,16,16,&b,&address);emit(100,8,rc!=0||b!=a||arena.peak!=32);
    emit(100,9,nxr_init(&request,0,fake_forward,fake_reset,fake_clock,0,151936));
    for(unsigned i=0;i<513;i++)prompt[i]=1;
    emit(100,10,nxr_begin_ids(&request,prompt,513,128,100000)!=NXR_BOUNDS);
    emit(100,11,request.state!=NXR_IDLE||request.sequence!=0);
    emit(100,12,nxr_begin_ids(&request,prompt,1,128,100000));
    emit(100,13,nxr_begin_ids(&request,prompt,1,128,100000)!=NXR_BUSY);
    emit(100,14,nxr_reset(&request)!=NXR_BUSY);
    fake_mode=0;rc=run_request();emit(100,15,rc||request.stop!=NXR_STOP_EOS||request.generated!=1||request.output[0]!=NXR_EOS);
    uint64_t session=request.session;rc=nxr_reset(&request);emit(100,16,rc||request.session!=session+1||request.kv_length||request.generated);
    fake_mode=1;rc=nxr_begin_ids(&request,prompt,511,128,100000);rc|=run_request();emit(100,17,rc||request.stop!=NXR_STOP_CONTEXT||request.generated!=1||request.kv_length!=511);
    nxr_reset(&request);rc=nxr_begin_ids(&request,prompt,512,128,100000);rc|=run_request();emit(100,18,rc||request.stop!=NXR_STOP_CONTEXT||request.generated||request.kv_length!=512);
    nxr_reset(&request);rc=nxr_begin_ids(&request,prompt,1,128,100000);rc|=run_request();emit(100,19,rc||request.stop!=NXR_STOP_OUTPUT||request.generated!=128);
    nxr_reset(&request);fake_mode=2;nxr_begin_ids(&request,prompt,1,128,100000);rc=nxr_step(&request);emit(100,20,rc!=NXR_FAULT||request.state!=NXR_FAILED||request.generated||request.kv_length);
    emit(100,21,nxr_begin_ids(&request,prompt,1,128,100000)!=NXR_STATE);
    nxr_reset(&request);fake_mode=3;nxr_begin_ids(&request,prompt,1,128,100000);emit(100,22,nxr_step(&request)!=NXR_FAULT);
    nxr_reset(&request);fake_mode=1;nxr_begin_ids(&request,prompt,1,128,2);clock_value+=3;emit(100,23,nxr_step(&request)!=NXR_TIMEOUT||request.state!=NXR_FAILED);
    nxr_reset(&request);prompt[0]=151936;emit(100,24,nxr_begin_ids(&request,prompt,1,128,100000)!=NXR_INVALID);prompt[0]=1;
    fake_mode=4;nxr_begin_ids(&request,prompt,1,1,100000);rc=run_request();emit(100,25,rc||nested_status!=NXR_BUSY);
    nxr_reset(&request);emit(100,26,nxr_begin_ids(&request,prompt,1,129,1000)!=NXR_BOUNDS);
    emit(100,27,nxr_file_span(1,UINT64_MAX,2,UINT64_MAX,&end)!=NXR_BOUNDS);
    emit(100,28,nxr_alloc(&arena,1,1,3,&b,&address)!=NXR_INVALID);
    request.session=UINT64_MAX;emit(100,29,nxr_reset(&request)!=NXR_STATE);
    request.session=2;request.sequence=UINT64_MAX;emit(100,30,nxr_begin_ids(&request,prompt,1,1,1000)!=NXR_STATE);
}
static void text_tests(const void *table,size_t size) {
    nxt_tokenizer t;int rc=nxt_init(&t,table,size);emit(101,0,rc);if(rc)return;
    for(unsigned i=0;i<TEXT_CASES;i++){
        size_t count=0;rc=nxt_encode(&t,&token_work,(const char *)text_cases[i],text_sizes[i],token_ids,1024,&count);emit(200+i,0,rc);
        emit(200+i,1,count);for(size_t j=0;j<count;j++)emit(200+i,j+2,token_ids[j]);
        nxt_decoder decoder={{0},0};size_t total=0;
        for(size_t j=0;j<=count;j++){size_t n=0;int status=nxt_decode(&t,&decoder,j==count?UINT32_MAX:token_ids[j],0,j==count,decoded+total,sizeof(decoded)-total,&n);rc|=status;total+=n;}
        emit(300+i,0,rc);bytes(400+i,decoded,total);
    }
    nxt_message messages[]={{"system","你是控制助手。",21},{"user","如果温度高于28度，打开风扇。",44}};
    messages[0].length=strlen(messages[0].text);messages[1].length=strlen(messages[1].text);
    size_t len=0;rc=nxt_template(messages,2,1,framed,sizeof(framed),&len);emit(101,1,rc);bytes(500,framed,len);
    uint32_t sentinel=0xdeadbeef;size_t count=17;
    rc=nxt_encode(&t,&token_work,"abc",3,&sentinel,0,&count);emit(101,2,rc!=NXT_BOUNDS||sentinel!=0xdeadbeef||count!=17);
    rc=nxt_encode(&t,&token_work,"\xc0\x80",2,&sentinel,1,&count);emit(101,3,rc!=NXT_UTF8||sentinel!=0xdeadbeef);
    rc=nxt_encode(&t,&token_work,"\xf0\x9f",2,&sentinel,1,&count);emit(101,4,rc!=NXT_UTF8);
    nxt_decoder d={{0},0};len=23;rc=nxt_decode(&t,&d,151936,0,1,decoded,sizeof(decoded),&len);emit(101,5,rc!=NXT_ARGUMENT||len!=23||d.count);
    nxr_init(&request,0,fake_forward,fake_reset,fake_clock,0,151936);fake_mode=0;
    rc=nxr_begin_text(&request,&t,&token_work,messages,2,framed,sizeof(framed),128,1000000);emit(101,6,rc);
    emit(501,0,request.prompt_length);for(unsigned i=0;i<request.prompt_length;i++)emit(501,i+1,request.prompt[i]);
    rc|=run_request();emit(101,7,rc||request.stop!=NXR_STOP_EOS||request.generated!=1);
    /* Raw byte tokens for Chinese/emoji sequences come from the generated
     * official byte alphabet, so boundaries intentionally split UTF-8. */
    static const uint8_t raw[]={0xe4,0xb8,0xad,0xf0,0x9f,0x8c,0x8d,0xe4,0x41,0xff};
    d=(nxt_decoder){{0},0};size_t total=0;
    const uint8_t *p=table;uint32_t off=(uint32_t)p[44]|(uint32_t)p[45]<<8|(uint32_t)p[46]<<16|(uint32_t)p[47]<<24;
    for(unsigned i=0;i<=sizeof(raw);i++){
        uint32_t id=UINT32_MAX;if(i<sizeof(raw)){const uint8_t *b=p+off+4*raw[i];id=(uint32_t)b[0]|(uint32_t)b[1]<<8|(uint32_t)b[2]<<16|(uint32_t)b[3]<<24;}
        size_t n=0;rc=nxt_decode(&t,&d,id,0,i==sizeof(raw),decoded+total,sizeof(decoded)-total,&n);emit(502,i,rc);total+=n;
    }
    bytes(503,decoded,total);
    nxr_reset(&request);nxt_message boundary={"user",text_boundary,sizeof(text_boundary)-1};
    rc=nxr_begin_text(&request,&t,&token_work,&boundary,1,framed,sizeof(framed),128,1000000);
    emit(101,8,rc||request.prompt_length!=512);rc=rc?rc:run_request();emit(101,9,rc||request.stop!=NXR_STOP_CONTEXT||request.generated);
    nxr_reset(&request);char over[sizeof(text_boundary)+1];memcpy(over,text_boundary,sizeof(text_boundary)-1);over[sizeof(text_boundary)-1]='1';boundary.text=over;boundary.length=sizeof(text_boundary);
    rc=nxr_begin_text(&request,&t,&token_work,&boundary,1,framed,sizeof(framed),128,1000000);
    emit(101,10,rc!=NXR_BOUNDS||request.state!=NXR_IDLE||request.sequence);
}
static uint64_t dispatch_calls,dispatch_ticks;static unsigned unsupported_mode;
static int provider(void *ctx,const float *x,int rows,const nx_matrix *w,float *y){(void)ctx;(void)x;(void)rows;(void)w;(void)y;return unsupported_mode?NX_MEMORY:NX_UNSUPPORTED;}
static void dispatch(void *ctx,int kind,int route,int reason,int status,uint64_t ticks){(void)ctx;(void)kind;(void)status;dispatch_calls++;dispatch_ticks+=ticks;if(!unsupported_mode&&(route!=0||reason!=2))emit(999,1,1);}
#ifdef NX_SMALL
static unsigned char state_memory[8192] __attribute__((aligned(16)));
#ifdef HOST_TEST
static unsigned char kv_memory[327680] __attribute__((aligned(16)));
static unsigned char work_memory[2048] __attribute__((aligned(16)));
#else
#define kv_memory ((void *)0xa8000000u)
#define work_memory ((void *)0xac000000u)
#endif
static float logits[64];
static void small_model(const unsigned char *blob) {
    nx_weights w;load_small(&w,blob);
    nx_session *s=nx_init_static(&w,state_memory,sizeof(state_memory),kv_memory,327680,work_memory,2048);
    emit(600,0,s==NULL);if(!s)return;
    nx_bind_backend(s,0,provider,dispatch,1);const int32_t ids[]={1,7,19};
    for(unsigned step=0;step<3;step++){
        int rc=nx_forward(s,ids+step,1,step,logits,NULL);emit(600,step+1,rc);
        for(unsigned i=0;i<64;i++)emit(610+step,i,bits(logits[i]));
        for(unsigned i=0;i<64;i++){emit(620+step,i,bits(nx_cache(s,0,0)[step*64+i]));emit(630+step,i,bits(nx_cache(s,0,1)[step*64+i]));}
        int32_t best=-1;nx_greedy(logits,&best);emit(600,step+4,best);
    }
    emit(600,7,dispatch_calls);emit(600,8,dispatch_ticks>0);emit(600,9,nx_length(s));
    nx_reset(s);emit(600,10,nx_length(s));
    unsupported_mode=1;for(unsigned i=0;i<64;i++)logits[i]=17;
    int rc=nx_forward(s,ids,1,0,logits,NULL);emit(600,11,rc!=NX_MEMORY||nx_length(s)!=-1||logits[0]!=17);
    unsupported_mode=0;nx_reset(s);rc=nx_forward(s,ids,1,0,logits,NULL);emit(600,12,rc);for(unsigned i=0;i<64;i++)emit(640,i,bits(logits[i]));
    emit(600,13,nx_state_bytes());emit(600,14,nx_kv_bytes());emit(600,15,nx_work_bytes());
    emit(600,16,nx_init_static(&w,state_memory,sizeof(state_memory),state_memory,327680,work_memory,2048)!=NULL);
    nxr_model binding;rc=nxr_attach(&request,&binding,s,logits,64);uint32_t input=1;
    rc=rc?rc:nxr_begin_ids(&request,&input,1,1,1000000000);emit(600,17,rc);
    rc=rc?rc:run_request();emit(600,18,rc||request.generated!=1||request.stop!=NXR_STOP_OUTPUT);
    emit(600,19,nxr_output(&request,0));
}
#else
static void t11_tile(const unsigned char *blob){
    const float *x=(const float *)(blob+TILE_X);nx_matrix w={(const int8_t *)(blob+TILE_Q),(const float *)(blob+TILE_S),(const float *)(blob+TILE_BIAS),4,896};
    float y[4],sa[14],gamma[896],norm[896];int8_t aq[896];int32_t dots[56];
    int rc=nx_quantize(x,1,896,aq,sa);emit(700,0,rc);for(unsigned i=0;i<896;i++)emit(701,i,(uint8_t)aq[i]);for(unsigned i=0;i<14;i++)emit(702,i,bits(sa[i]));
    rc=nx_linear(x,1,&w,y,dots);emit(700,1,rc);for(unsigned i=0;i<4;i++)emit(703,i,bits(y[i]));for(unsigned i=0;i<56;i++)emit(704,i,(uint32_t)dots[i]);
    emit(700,2,nx_state_bytes());emit(700,3,nx_kv_bytes());emit(700,4,nx_work_bytes());
    for(unsigned i=0;i<896;i++)gamma[i]=1;
    rc=nx_norm(x,gamma,1,896,norm);emit(700,5,rc);for(unsigned i=0;i<896;i++)emit(705,i,bits(norm[i]));
    float ties[]={127,-127,.5f,-.5f,1.5f,-1.5f,2.5f,-2.5f};
    rc=nx_quantize(ties,1,8,aq,sa);emit(700,6,rc);for(unsigned i=0;i<8;i++)emit(706,i,(uint8_t)aq[i]);
}
#endif
#ifdef HOST_TEST
static void *read_file(const char *name,size_t *size){FILE *f=fopen(name,"rb");if(!f)exit(2);fseek(f,0,SEEK_END);long n=ftell(f);rewind(f);void *p=malloc(n);if(!p||fread(p,1,n,f)!=(size_t)n)exit(2);fclose(f);*size=n;return p;}
int main(int argc,char **argv){if(argc!=3)return 2;size_t size,blob_size;void *table=read_file(argv[1],&size),*blob=read_file(argv[2],&blob_size);(void)blob_size;
#else
uint32_t trap_handler(uint32_t cause,uint32_t pc,uint32_t tval){emit(998,0,cause);emit(998,1,pc);emit(998,2,tval);*(volatile uint32_t *)0x10000020=0xdead0012;for(;;){}return pc;}
int main(void){const void *table=(const void *)0xb8af4d00u;size_t size=TOKENIZER_BYTES;const unsigned char *blob=(const void *)0x80000000u;
#endif
    uint64_t start=nx_port_ticks();
#ifdef NX_SMALL
    (void)table;(void)size;small_model(blob);
#else
    controls();text_tests(table,size);t11_tile(blob);
#endif
    emit(900,0,(uint32_t)(nx_port_ticks()-start));
#ifndef HOST_TEST
    __asm__ volatile("fence rw,rw":::"memory");*(volatile uint32_t *)0x10000020=0x1200;for(;;){}
#endif
    return 0;
}
