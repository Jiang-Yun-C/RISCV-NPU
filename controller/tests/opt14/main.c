/* Measure the unchanged production nx_greedy and remaining BA -> AC copy.
 * No head/argmax hardware is substituted or claimed by this benchmark. */
#include <stdint.h>
#include <string.h>
#include "nx_reference.h"
#define N 151936u
static volatile uint32_t exit_multiplier=1;
static void emit(unsigned g,unsigned i,uint32_t v){
    *(volatile uint32_t *)0x10000080=(g<<16)|i;
    *(volatile uint32_t *)0x10000084=v;
}
static uint64_t ticks(void){
    uint32_t a,b,c;
    do{__asm__ volatile("csrr %0,mcycleh":"=r"(a));
       __asm__ volatile("csrr %0,mcycle":"=r"(b));
       __asm__ volatile("csrr %0,mcycleh":"=r"(c));}while(a!=c);
    return ((uint64_t)a<<32)|b;
}
uint32_t trap_handler(uint32_t a,uint32_t b,uint32_t c){
    (void)b;(void)c;emit(99,0,a);*(volatile uint32_t *)0x10000020=1;
    for(;;){}return 0;
}
static void scan(unsigned job,float *p){
    int32_t token=123456;
    uint64_t start=ticks();int rc=nx_greedy(p,&token);uint64_t elapsed=ticks()-start;
    emit(job,0,(uint32_t)rc);emit(job,1,(uint32_t)token);
    emit(job,2,(uint32_t)elapsed);emit(job,3,(uint32_t)(elapsed>>32));
}
static uint32_t original(unsigned i){return i==N-1?0x3fc00000u:0x3f000000u+((i*13u)&0x007fffffu);}
int main(void){
    const uint32_t *source=(const uint32_t *)0xba100000;
    uint32_t *out=(uint32_t *)0xac100000;
    uint64_t start=ticks();memcpy(out,source,N*4);uint64_t elapsed=ticks()-start;
    emit(0,0,(uint32_t)elapsed);emit(0,1,(uint32_t)(elapsed>>32));
    for(unsigned i=0;i<N;i++)emit(100+(i>>16),i&65535,out[i]);
    scan(1,(float *)out); /* largest ID, inside final 128 rows */
    out[255]=out[256]=out[151808]=0x40000000u;
    scan(2,(float *)out); /* equal maxima across block/tail boundaries */
    out[255]=original(255);out[256]=original(256);out[151808]=original(151808);
    out[151645]=0x40000000u;scan(3,(float *)out);out[151645]=original(151645);
    out[N-1]=0x7fc00001u;scan(4,(float *)out);out[N-1]=original(N-1);
    out[0]=0x7f800000u;scan(5,(float *)out);out[0]=original(0);
    out[N-1]=0xff800000u;scan(6,(float *)out);out[N-1]=original(N-1);
    /* Signed zero must compare equal and retain the smallest ID. */
    for(unsigned i=0;i<N;i++)out[i]=(i&1)?0u:0x80000000u;
    scan(7,(float *)out);
    *(volatile uint32_t *)0x10000020=0x0800*exit_multiplier;for(;;){}
}
