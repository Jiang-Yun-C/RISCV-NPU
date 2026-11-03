/* CONTROL_ONLY scripted next-ID callback; production runtime, decoder and
 * stream wire code execute on real VexRiscv; no model speed/numeric claim. */
#include "stream.h"
#include <string.h>
#include "inputs.h"
#define REG(o) (*(volatile uint32_t *)(uintptr_t)(0x10000000u+(o)))
extern const unsigned char t25_tokenizer[],t25_tokenizer_end[];
static nxt_tokenizer tokenizer;static nxt_work work;static nxr_request request;static nxs_stream stream;
static char output[16384],framed[4096];static uint32_t prompt[512];
static const fixture *current;static unsigned index;static uint64_t wire_bytes;
uint64_t nx_port_ticks(void){uint32_t a,b,c;do{__asm__ volatile("csrr %0,mcycleh":"=r"(a));__asm__ volatile("csrr %0,mcycle":"=r"(b));__asm__ volatile("csrr %0,mcycleh":"=r"(c));}while(a!=c);return (uint64_t)a<<32|b;}
static uint64_t clock_fn(void *p){(void)p;return nx_port_ticks();}
static void put(void *p,char c){(void)p;while(REG(4)&1){}REG(0)=(uint8_t)c;wire_bytes++;}
static void drain(void *p){(void)p;while(REG(4)&1){}}
static void text(const char *p){while(*p)put(0,*p++);}
static void hex(uint64_t v,unsigned n){for(int i=(int)n-1;i>=0;i--)put(0,"0123456789abcdef"[(v>>(i*4))&15]);}
static int reset_fn(void *p){(void)p;index=0;return 0;}
static int forward(void *p,uint32_t token,uint32_t past,uint32_t *next){
    (void)p;(void)token;
    if(past+1<request.prompt_length){*next=0;return 0;}
    if(index==1&&current->fault==1)return NXR_FAULT;
    if(index==1&&current->fault==2){uint64_t start=nx_port_ticks();while(nx_port_ticks()-start<300000){}}
    *next=current->ids[index<current->count?index:current->count-1];index++;return 0;
}
uint32_t trap_handler(uint32_t a,uint32_t b,uint32_t c){(void)b;(void)c;REG(0x20)=a;for(;;){}return 0;}
int main(void){
    int rc=nxt_init(&tokenizer,t25_tokenizer,(size_t)(t25_tokenizer_end-t25_tokenizer));
    if(rc){REG(0x20)=1;for(;;){}}
    nxr_init(&request,0,forward,reset_fn,clock_fn,0,151936);
    text("OPT06 READY\n");
    /* An external UART byte starts each request; origin is after complete RX. */
    for(unsigned i=0;i<sizeof(fixtures)/sizeof(fixtures[0]);i++){
        while(!(REG(4)&2)){}unsigned command=REG(8);uint64_t received=nx_port_ticks();
        if(command!=i){REG(0x20)=2;for(;;){}}
        current=&fixtures[i];nxr_reset(&request);
        uint64_t timeout=current->fault==2?200000:UINT64_C(1000000000);
        if(current->text){nxt_message m={"user",current->text,strlen(current->text)};rc=nxr_begin_text(&request,&tokenizer,&work,&m,1,framed,sizeof(framed),current->maximum,timeout);}
        else rc=nxr_begin_ids(&request,prompt,current->prompt,current->maximum,timeout);
        wire_bytes=0;nxs_uart wire={put,0,drain,0};
        if(!rc)rc=nxs_open(&stream,&request,&tokenizer,output,current->capacity,received,current->enabled,nxs_wire,&wire);
        while(!rc&&(request.state==NXR_PREFILL||request.state==NXR_DECODE)){
            rc=nxr_step(&request);if(!rc)rc=nxs_update(&stream);
            uint64_t print_start=nx_port_ticks();
            if(current->prompt<500){text("T25 STEP ");hex(request.prefilled,8);put(0,' ');hex(request.generated,8);put(0,'\n');}
            drain(0);stream.legacy_ticks+=nx_port_ticks()-print_start;
            if(!rc&&current->fault==3&&stream.seen==1)rc=nxs_abort(&stream,NXR_FAULT);
        }
        if(!rc)rc=nxs_finish(&stream);
        if(rc){if(stream.active)nxs_abort(&stream,rc);text("T25 ERROR ");hex((uint32_t)rc,8);put(0,'\n');}
        else{
            uint64_t print_start=nx_port_ticks();
            text("T25 IDS ");for(unsigned j=0;j<request.generated;j++){hex(request.output[j],8);put(0,' ');}put(0,'\n');
            text("T25 TEXTLEN 1 bytes=");hex(stream.bytes,16);put(0,' ' );put(0,'\n');
            text("T25 TEXT ");for(size_t j=0;j<stream.bytes;j++)put(0,output[j]);put(0,'\n');drain(0);
            stream.legacy_ticks+=nx_port_ticks()-print_start;stream.output_wire_bytes=wire_bytes;
            if(!current->enabled&&stream.bytes)stream.first_text=stream.last_text=nx_port_ticks()-received;
            stream.complete=nx_port_ticks()-received;nxs_timing(&stream,&wire);
        }
        text("OPT06 RESULT ");hex(i,8);put(0,' ');hex(request.state,8);put(0,' ');hex(request.stop,8);put(0,' ');hex(request.generated,8);put(0,' ');hex(request.prompt_length,8);put(0,'\n');
        if(current->prompt>500){
            unsigned checksum=0;for(unsigned j=0;j<request.prompt_length;j++)checksum|=request.prompt[j];
            text("OPT06 PROMPT_ZERO ");hex(request.prompt_length,8);put(0,' ');hex(checksum,8);put(0,'\n');
        }else{text("OPT06 PROMPT ");for(unsigned j=0;j<request.prompt_length;j++){hex(request.prompt[j],8);put(0,' ');}put(0,'\n');}
        text("T25 READY\n");drain(0);
    }
    REG(0x24)=0x0600;for(;;){}
}
