/* Full-model RV32 entry. T18 supplies the sealed T10 views, compiled tokenizer
 * and a bounded text request in shared_io; T12 qualification uses PRELOAD. */
#include "port/model.h"
#include <string.h>
#include "full_weights.h"
static nx_weights weights;
static unsigned char state[8192] __attribute__((aligned(16)));
static nxt_work token_work;
static nxr_request request;
static nxr_model binding;
static char text[NXT_TEXT_MAX],framed[NXT_TEXT_MAX],output[16384];
uint64_t nx_port_ticks(void){uint32_t hi,lo,again;do{__asm__ volatile("csrr %0,mcycleh":"=r"(hi));__asm__ volatile("csrr %0,mcycle":"=r"(lo));__asm__ volatile("csrr %0,mcycleh":"=r"(again));}while(hi!=again);return (uint64_t)hi<<32|lo;}
static void finish(uint32_t code){__asm__ volatile("fence rw,rw":::"memory");*(volatile uint32_t *)0x10000020=code;}
uint32_t trap_handler(uint32_t cause,uint32_t pc,uint32_t value){(void)pc;(void)value;finish(0xe0000000|cause);for(;;){}return pc;}
int main(void){
    volatile const uint32_t *input=(const uint32_t *)0xba000000;
    /* uint32 LE: magic, text_bytes, max_new, timeout_lo, timeout_hi; UTF-8 text.
     * Caller owns request memory until completion; no unbounded string reads. */
    if(input[0]!=0x3152514e||input[1]>NXT_TEXT_MAX){finish(0xe0000001);return 1;}
    uint32_t n=input[1],maximum=input[2];uint64_t timeout=(uint64_t)input[4]<<32|input[3];
    for(uint32_t i=0;i<n;i++)text[i]=((volatile const char *)(input+5))[i];
    load_full(&weights);
    nx_session *s=nx_init_static(&weights,state,sizeof(state),(void *)0xa8000000,15728640,(void *)0xac000000,664576);
    if(!s){finish(0xe0000002);return 1;}
    nx_bind_backend(s,0,0,0,0); /* Actual installed implementation: CPU_C only. */
    nxt_tokenizer t;int rc=nxt_init(&t,(const void *)0xb8af4d00,TOKENIZER_BYTES);
    rc=rc?rc:nxr_attach(&request,&binding,s,(float *)0xac0a2400,151936);
    nxt_message message={"user",text,n};
    if(!rc)rc=nxr_begin_text(&request,&t,&token_work,&message,1,framed,sizeof(framed),maximum,timeout);
    while(!rc&&(request.state==NXR_PREFILL||request.state==NXR_DECODE))rc=nxr_step(&request);
    nxt_decoder decoder={{0},0};size_t total=0;
    for(uint32_t i=0;!rc&&i<=request.generated;i++){
        size_t produced=0;rc=nxt_decode(&t,&decoder,i==request.generated?UINT32_MAX:request.output[i],1,
            i==request.generated,output+total,sizeof(output)-total,&produced);total+=produced;
    }
    if(rc){finish(0xe1000000|((uint32_t)(-rc)&0xffff));return 1;}
    for(size_t i=0;i<total;i++)*(volatile uint32_t *)0x10000000=(uint8_t)output[i];
    finish(0x1200);return 0;
}
