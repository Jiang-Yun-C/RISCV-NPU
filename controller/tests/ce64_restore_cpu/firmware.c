#include <stdint.h>
#include "input.h"

struct input { int32_t dot; uint32_t sa,sw,acc; };
struct output { int32_t dot; uint32_t p,v,partial; };
static const struct input local_input[GROUPS]=INPUT_DATA;
static volatile struct output local_output[GROUPS];
static inline uint32_t bits(float x) { union {float f;uint32_t u;} v={.f=x};return v.u; }
static inline float fp(uint32_t x) { union {float f;uint32_t u;} v={.u=x};return v.f; }
static inline uint64_t cycle(void) {
    uint32_t hi,lo,again;
    do {__asm__ volatile("csrr %0,mcycleh":"=r"(hi));__asm__ volatile("csrr %0,mcycle":"=r"(lo));
        __asm__ volatile("csrr %0,mcycleh":"=r"(again));}while(hi!=again);
    return ((uint64_t)hi<<32)|lo;
}
static inline uint64_t instret(void) {
    uint32_t hi,lo,again;
    do {__asm__ volatile("csrr %0,minstreth":"=r"(hi));__asm__ volatile("csrr %0,minstret":"=r"(lo));
        __asm__ volatile("csrr %0,minstreth":"=r"(again));}while(hi!=again);
    return ((uint64_t)hi<<32)|lo;
}
static void report(uint32_t mode,uint32_t index,uint32_t value) {
    *(volatile uint32_t *)0x10000080=(mode<<16)|index;
    *(volatile uint32_t *)0x10000084=value;
}
__attribute__((noinline)) static uint32_t restore_loop(const volatile struct input *in,volatile struct output *out) {
    uint32_t bad=0;
    for(uint32_t i=0;i<GROUPS;i++) {
        int32_t d=in[i].dot;
        float sa=fp(in[i].sa),sw=fp(in[i].sw),acc=fp(in[i].acc);
        float p=(float)d*sa;
        float v=p*sw;
        float y=acc+v;
        uint32_t pb=bits(p),vb=bits(v),yb=bits(y);
        bad|=((pb&0x7f800000)==0x7f800000)||((vb&0x7f800000)==0x7f800000)||((yb&0x7f800000)==0x7f800000);
        out[i]=(struct output){d,pb,vb,yb};
    }
    __asm__ volatile("fence rw,rw":::"memory");
    return bad;
}
uint32_t trap_handler(uint32_t cause,uint32_t pc,uint32_t value) {
    report(15,0,cause);report(15,1,pc);report(15,2,value);
    *(volatile uint32_t *)0x10000020=0xbadce640;
    for(;;)__asm__ volatile("nop");
}
int main(void) {
    volatile struct input *uncached=(volatile struct input *)0xac000000;
    volatile struct output *uncached_out=(volatile struct output *)0xba000000;
    for(uint32_t i=0;i<GROUPS;i++)uncached[i]=local_input[i];
    __asm__ volatile("fence rw,rw":::"memory");
    // Warm cache/code before measuring local path. This is an explicit profile,
    // not an unqualified claim about DDR/TCM or CPU+CE contention.
    restore_loop(local_input,local_output);
    for(uint32_t mode=0;mode<2;mode++) {
        const volatile struct input *in=mode?uncached:local_input;
        volatile struct output *out=mode?uncached_out:local_output;
        __asm__ volatile("csrw fcsr,zero":::"memory");
        uint64_t retired0=instret(),start=cycle();
        uint32_t bad=restore_loop(in,out);
        uint64_t elapsed=cycle()-start,retired=instret()-retired0;
        report(mode,0,(uint32_t)elapsed);report(mode,1,(uint32_t)(elapsed>>32));
        report(mode,2,(uint32_t)retired);report(mode,3,(uint32_t)(retired>>32));
        report(mode,4,bad);report(mode,5,GROUPS);
        report(mode,6,GROUPS*sizeof(struct input));report(mode,7,GROUPS*sizeof(struct output));
        for(uint32_t i=0;i<GROUPS;i++) {
            report(mode,0x1000+i*4,(uint32_t)out[i].dot);report(mode,0x1001+i*4,out[i].p);
            report(mode,0x1002+i*4,out[i].v);report(mode,0x1003+i*4,out[i].partial);
        }
    }
    *(volatile uint32_t *)0x10000020=0x600ce640;
    for(;;)__asm__ volatile("nop");
}
