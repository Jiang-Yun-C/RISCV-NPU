#define _POSIX_C_SOURCE 200809L
#include <stdint.h>
#define NX_PORTABLE 1
#ifdef HOST
#include <time.h>
#include <stdio.h>
static uint64_t tick(void){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return (uint64_t)t.tv_sec*1000000000ull+t.tv_nsec;}
static uint64_t phase_ticks[11],phase_hits[11];
#else
#define MM(a) (*(volatile uint32_t *)(uintptr_t)(a))
__attribute__((noinline)) uint64_t nx_port_ticks(void){uint32_t h,l,h2;do{__asm__ volatile("csrr %0,mcycleh":"=r"(h));__asm__ volatile("csrr %0,mcycle":"=r"(l));__asm__ volatile("csrr %0,mcycleh":"=r"(h2));}while(h!=h2);return ((uint64_t)h<<32)|l;}
static uint64_t tick(void){return nx_port_ticks();}
#define phase_ticks ((uint64_t *)(uintptr_t)0x20000)
#define phase_hits ((uint64_t *)(uintptr_t)0x20100)
static void report(unsigned g,unsigned i,uint32_t v){MM(0x10000080)=(g<<16)|i;MM(0x10000084)=v;}
static void report64(unsigned g,unsigned i,uint64_t v){report(g,i,(uint32_t)v);report(g,i+1,v>>32);}
uint32_t trap_handler(uint32_t cause,uint32_t pc,uint32_t detail){(void)detail;report(255,0,cause);report(255,1,pc);MM(0x10000020)=1;for(;;){}}
#endif
#define PHASE_BEGIN(n) uint64_t phase_start_##n=tick(); __asm__ volatile("":::"memory")
#define PHASE_END(n) do{__asm__ volatile("":::"memory");uint64_t phase_end=tick();phase_ticks[n]+=phase_end-phase_start_##n;phase_hits[n]++;}while(0)
#include "firmware/runtime/reference/nx_reference.c"
#include "t27/pv_driver.h"
static uint32_t rng=0x270025;
static float sample(void){rng^=rng<<13;rng^=rng>>17;rng^=rng<<5;return (float)((int)(rng&2047)-1024)/1024.0f;}
static nx_session session;
#ifdef HOST
static float host_k[S*KV],host_v[S*KV],host_q[4*H],host_y[4*H];
#else
static const uint32_t control_address=0xb4080000;
#endif
int main(void){
#ifdef HOST
    session.k=(void *)host_k;session.v=(void *)host_v;session.q=host_q;session.a=host_y;
    int first_case=0,last_case=3,first_arm=0,last_arm=1;
#else
    session.k=(void *)0xa8000000;session.v=(void *)0xa8780000;session.q=(void *)0xac000000;session.a=(void *)0xac010000;
    int first_case=MM(control_address),last_case=first_case+1,first_arm=MM(control_address+4),last_arm=first_arm+1;
#endif
#ifndef HOST
    for(unsigned a=0x21000;a<0x22000;a+=4)MM(a)=0x27c0ffee;
#endif
    float *kp=(void *)session.k,*vp=(void *)session.v;
    for(int i=0;i<S*KV;i++){kp[i]=sample();vp[i]=sample();}
    for(int i=0;i<4*H;i++)session.q[i]=sample();
    for(int c=first_case;c<last_case;c++)for(int arm=first_arm;arm<last_arm;arm++){
        int rows=c==2?4:1,past=c==0?32:c==1?44:29;
        for(int repeat=0;repeat<2;repeat++){
            for(int i=0;i<11;i++)phase_ticks[i]=phase_hits[i]=0;
            for(int i=0;i<6;i++)pv_marks[i]=0;pv_calls=pv_muls=pv_adds=0;
            uint64_t begin=tick();
            int rc=attention(&session,0,rows,past);
            uint64_t elapsed=tick()-begin;
#ifdef HOST
            printf("API,%d,%d,%d,%d,%llu\n",c,arm,repeat,rc,(unsigned long long)elapsed);
            for(int i=0;i<11;i++)printf("PHASE,%d,%d,%d,%d,%llu,%llu\n",c,arm,repeat,i,(unsigned long long)phase_ticks[i],(unsigned long long)phase_hits[i]);
            char name[100];snprintf(name,sizeof name,"host-c%d-a%d-r%d.bin",c,arm,repeat);FILE *f=fopen(name,"wb");if(!f)return 2;fwrite(session.a,4,rows*H,f);fclose(f);
#else
            unsigned g=10+repeat;report(g,0,rc);report64(g,1,elapsed);
            for(int i=0;i<11;i++){report64(g,3+4*i,phase_ticks[i]);report64(g,5+4*i,phase_hits[i]);}
            for(int i=0;i<rows*H;i++)report(100+repeat,i,((uint32_t *)session.a)[i]);
#endif
#ifndef HOST
            for(int i=0;i<6;i++)report64(30+repeat,2*i,pv_marks[i]);
            report64(30+repeat,12,pv_calls);report64(30+repeat,14,pv_muls);report64(30+repeat,16,pv_adds);
            for(unsigned a=0x21000;a<0x22000;a+=4)if(MM(a)!=0x27c0ffee){report(255,3,a);return 4;}
#endif
            if(rc)return 3;
        }
    }
#ifdef HOST
    return 0;
#else
    for(int i=0;i<16;i++){uint64_t a=tick(),b=tick();report64(200,2*i,b-a);}
    MM(0x10000020)=0;for(;;)__asm__ volatile("wfi");
#endif
}
