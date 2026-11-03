#include "stream.h"
#define REG(o) (*(volatile uint32_t *)(uintptr_t)(0x10000000u+(o)))
static uint64_t ticks(void *cookie){
    (void)cookie;uint32_t hi,lo,again;
    do{__asm__ volatile("csrr %0,mcycleh":"=r"(hi));__asm__ volatile("csrr %0,mcycle":"=r"(lo));__asm__ volatile("csrr %0,mcycleh":"=r"(again));}while(hi!=again);
    return (uint64_t)hi<<32|lo;
}
static int get(void *cookie,uint64_t deadline,uint8_t *out){
    (void)cookie;while(!(REG(4)&2)){if(deadline&&ticks(0)>=deadline)return 0;}*out=(uint8_t)REG(0xc0);return 1;
}
static void put(void *cookie,const uint8_t *p,unsigned n){
    (void)cookie;while(n--){while(REG(4)&1){}REG(0)=*p++;}while(REG(4)&1){}
}
static void text(const char *p){while(*p)put(0,(const uint8_t *)p++,1);}
static int seal(void *cookie){
    (void)cookie;REG(0xe0)=0x5345414c;__asm__ volatile("fence iorw,iorw":::"memory");
    return REG(0xe0)&2?0:NX_UART_STATE;
}
static void reset(void *cookie){(void)cookie;REG(0xec)=0x52535432;for(;;){}}
void nx_uart_observe_model(int32_t dot,uint32_t entries){(void)dot;(void)entries;}
void nx_uart_enter(uint32_t address){((void (*)(void))(uintptr_t)address)();for(;;){}}
int main(void){
    uint64_t begin=ticks(0);
    while(!(REG(0xe0)&1))if(ticks(0)-begin>=UINT64_C(15000000000)){text("T25 UART DDR TIMEOUT\n");for(;;){}}
    *(volatile uint32_t *)0xba080000=(uint32_t)begin;
    *(volatile uint32_t *)0xba080004=(uint32_t)(begin>>32);
    nx_uart_io io={.get=get,.put=put,.ticks=ticks,.seal=seal,.reset=reset,.frame_ticks=1250000000};
    nx_uart_init(&io);text("T25 UART BOOT v1\n");
    uint32_t rc=nx_uart_boot();nx_uart_reject(rc?rc:NX_UART_STATE);
    text("T25 UART REJECTED; reset required\n");
    // No new application is accepted after a failed pack or a sealed session.
    // A real platform reset recalibrates DDR and clears the hardware seal.
    for(;;){uint8_t v;if(get(0,0,&v)&&v=='r')reset(0);}
}
