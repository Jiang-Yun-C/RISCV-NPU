#include <stdint.h>
#include <string.h>
#include <math.h>
#include "nx_reference.h"
#include "inputs.h"
#ifndef BATCH_LAYERS
#define BATCH_LAYERS 1
#endif
extern int nx_opt07_configure(int,int);
extern double __ieee754_exp(double);
extern float __ieee754_expf(float);
static float gate[INPUT_N],up[INPUT_N],y[INPUT_N],scale[(INPUT_N+63)/64];
static int8_t q[INPUT_N];
static volatile uint32_t sink;
static unsigned report_layer;
static void emit(unsigned group,unsigned index,uint32_t v) {
    *(volatile uint32_t *)0x10000080=(group<<16)|index;
    *(volatile uint32_t *)0x10000084=v;
}
static uint32_t bits(float x){uint32_t v;memcpy(&v,&x,4);return v;}
uint64_t nx_port_ticks(void) {
    uint32_t a,b,c;do {__asm__ volatile("csrr %0,mcycleh":"=r"(a));__asm__ volatile("csrr %0,mcycle":"=r"(b));__asm__ volatile("csrr %0,mcycleh":"=r"(c));}while(a!=c);
    return (uint64_t)a<<32|b;
}
static void ticks(unsigned group,unsigned index,uint64_t t){emit(group,index,(uint32_t)t);emit(group,index+1,(uint32_t)(t>>32));}
static void result(int mode,int force) {
    nx_opt07_configure(mode,force);
    uint64_t start=nx_port_ticks();int rc=nx_swiglu(gate,up,INPUT_N,y);uint64_t elapsed=nx_port_ticks()-start;
    unsigned base=100+(force?4:mode)*10+report_layer*100;
    emit(base+4,0,(uint32_t)rc);ticks(base+3,0,elapsed);
    for(int i=0;i<INPUT_N;i++)emit(base,i,bits(y[i]));
    rc=nx_quantize(y,1,INPUT_N,q,scale);emit(base+4,1,(uint32_t)rc);
    for(int i=0;i<INPUT_N;i++)emit(base+1,i,(uint32_t)(int32_t)q[i]);
    for(int i=0;i<(INPUT_N+63)/64;i++)emit(base+2,i,bits(scale[i]));
}
/* The full loop, scan and memory costs are retained in result(). These
 * isolated loops are diagnostic ablations, never added to predict speed. */
__attribute__((noinline)) static void micro(int kind) {
    for(int i=0;i<65;i++) {
        float x=gate[i],v;
        switch(kind) {
        case 0:v=(float)__ieee754_exp(-(double)fabsf(x));break;
        case 1:v=__ieee754_expf(-fabsf(x));break;
        case 2:{volatile double d=(double)x;v=(float)d;break;}
        case 3:v=1.0f/(1.0f+fabsf(x));break;
        case 4:v=(x*0.5f)*up[i];break;
        case 5:v=isfinite(x)&&isfinite(up[i])?1.0f:0.0f;break;
        default:v=x;break;
        }y[i]=v;
    }
    sink=bits(y[32]);
}
uint32_t trap_handler(uint32_t a,uint32_t b,uint32_t c){(void)b;(void)c;emit(999,0,a);*(volatile uint32_t *)0x10000020=0xdead;for(;;){}return 0;}
int main(void) {
    if(BATCH_LAYERS>1) {
        for(report_layer=0;report_layer<BATCH_LAYERS;report_layer++) {
            memcpy(gate,input_gate+report_layer*INPUT_N,sizeof(gate));
            memcpy(up,input_up+report_layer*INPUT_N,sizeof(up));
            result(ONLY_MODE,0);
        }
        *(volatile uint32_t *)0x10000020=0x0700;for(;;){}return 0;
    }
    memcpy(gate,input_gate,sizeof(gate));memcpy(up,input_up,sizeof(up));
    if(ONLY_MODE>=0)result(ONLY_MODE,0);
    else {
        for(int mode=0;mode<4;mode++)result(mode,0);
        result(3,1);
        for(int mode=0;mode<4;mode++) {
            nx_opt07_configure(mode,0);
            for(int i=0;i<24;i++) {
                uint64_t start=nx_port_ticks();int rc=nx_swiglu(gate,up,1,y);uint64_t elapsed=nx_port_ticks()-start;
                emit(500+mode,48+i,(uint32_t)rc);ticks(500+mode,2*i,elapsed);
            }
            for(int field=0;field<2;field++)for(int j=0;j<3;j++) {
                uint32_t bad=0x7f800000u+(j==0?0x400000u:0);if(j==2)bad|=0x80000000u;
                float old=(field?up:gate)[64];memcpy((field?up:gate)+64,&bad,4);
                for(int i=0;i<65;i++)y[i]=123;
                int rc=nx_swiglu(gate,up,65,y);int clean=1;for(int i=0;i<65;i++)if(y[i]!=123)clean=0;
                emit(600+mode,field*6+2*j,(uint32_t)rc);emit(600+mode,field*6+2*j+1,clean);
                (field?up:gate)[64]=old;
            }
        }
        for(int k=0;k<7;k++){uint64_t t=nx_port_ticks();micro(k);ticks(400,k*2,nx_port_ticks()-t);}
        emit(700,0,(uint32_t)nx_opt07_configure(99,0));
        emit(700,1,(uint32_t)nx_opt07_configure(1,2));
        nx_opt07_configure(3,0);emit(700,2,(uint32_t)nx_swiglu(0,up,65,y));
        emit(700,3,(uint32_t)nx_swiglu(gate,up,0,y));
        emit(700,4,(uint32_t)nx_swiglu(gate,up,4865,y));
        emit(700,5,(uint32_t)nx_swiglu(gate,up,65,0));
    }
    *(volatile uint32_t *)0x10000020=0x0700;for(;;){}return 0;
}
