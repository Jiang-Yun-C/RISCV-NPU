#include <stdint.h>
#include <string.h>
static volatile uint32_t sink=1;
static void emit(unsigned i,uint32_t v){*(volatile uint32_t *)0x10000080=i;*(volatile uint32_t *)0x10000084=v;}
static uint64_t ticks(void){uint32_t a,b,c;do{__asm__ volatile("csrr %0,mcycleh":"=r"(a));__asm__ volatile("csrr %0,mcycle":"=r"(b));__asm__ volatile("csrr %0,mcycleh":"=r"(c));}while(a!=c);return (uint64_t)a<<32|b;}
uint32_t trap_handler(uint32_t a,uint32_t b,uint32_t c){(void)b;(void)c;emit(99,a);*(volatile uint32_t *)0x10000020=1;for(;;){}return 0;}
int main(void){
    uint32_t *source=(uint32_t *)0xac00de00,*destination=(uint32_t *)0xac0a2400;
    for(unsigned i=0;i<151936;i++)source[i]=0x3f000000u+(i*13u&0x007fffffu);
    uint64_t start=ticks();memcpy(destination,source,151936*4);uint64_t elapsed=ticks()-start;
    emit(0,(uint32_t)elapsed);emit(1,elapsed>>32);
    uint32_t h=2166136261u,errors=0;
    for(unsigned i=0;i<151936;i++){uint32_t actual=destination[i];if(actual!=source[i])errors++;h=(h^actual)*16777619u;emit(((1+(i>>16))<<16)|(i&65535),actual);}
    emit(2,151936);sink=h;emit(3,sink);emit(4,errors);*(volatile uint32_t *)0x10000020=0x0800;for(;;){}
}
