#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <assert.h>
#include <stdint.h>
#include <time.h>
#define HOST 1
#define NX_PORTABLE 1
#define T27_PV_BATCH 1
static uint64_t tick(void){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return t.tv_sec*1000000000ull+t.tv_nsec;}
#include "../firmware/runtime/reference/nx_reference.c"
#include "pv_driver.h"
static int attention_original(nx_session *s,int layer,int rows,int past) {
    const int cached=NX_ATTENTION_GQA_CACHE&&D<=64&&QHEAD/KVHEAD<=7&&past+rows<=512;
    #pragma omp parallel for schedule(static)
    for(int task=0;task<rows*(cached?KVHEAD:QHEAD);task++) {
        float prob[1024],tmp[1024];
        if(cached) {
            int r=task/KVHEAD,kv=task%KVHEAD,len=past+r+1,size=pow2(len);
            int step=len<=128?7:len<=256?4:2;
            for(int first=0;first<QHEAD/KVHEAD;first+=step) {
                int count=QHEAD/KVHEAD-first;
                if(count>step)count=step;
                int base=kv*(QHEAD/KVHEAD)+first;
                float maxima[7];
                /* Q/K and tree share only the original SRAM stack scratch.
                 * Q[0..447], K[448..511], reduction[512..1023]. */
                for(int h=0;h<count;h++) {
                    maxima[h]=-INFINITY;
                    for(int i=0;i<D;i++)tmp[h*D+i]=s->q[r*H+(base+h)*D+i];
                }
                for(int t=0;t<len;t++) {
                    for(int i=0;i<D;i++)tmp[448+i]=s->k[layer][t][kv*D+i];
                    for(int h=0;h<count;h++) {
                        for(int i=0;i<D;i++)tmp[512+i]=tmp[h*D+i]*tmp[448+i];
                        float value=tree(tmp+512,D)*(D==64?0.125f:1.0f/sqrtf((float)D));
                        prob[h*len+t]=value;
                        if(value>maxima[h])maxima[h]=value;
                    }
                }
                for(int h=0;h<count;h++) {
                    for(int t=0;t<len;t++)prob[h*len+t]=(float)exp((double)(prob[h*len+t]-maxima[h]));
                    memcpy(tmp+512,prob+h*len,(size_t)len*sizeof(*prob));
                    memset(tmp+512+len,0,(size_t)(size-len)*sizeof(*tmp));
                    float denom=tree(tmp+512,size);
                    for(int t=0;t<len;t++)prob[h*len+t]=prob[h*len+t]/denom;
                }
                /* Q/K are dead now. Reuse tmp[0..511] for V; preserve the
                 * original complete adjacent-pair PV tree for every head. */
                for(int i=0;i<D;i++) {
                    for(int t=0;t<len;t++)tmp[t]=s->v[layer][t][kv*D+i];
                    for(int h=0;h<count;h++) {
                        memset(tmp+512+len,0,(size_t)(size-len)*sizeof(*tmp));
                        for(int t=0;t<len;t++)tmp[512+t]=prob[h*len+t]*tmp[t];
                        s->a[r*H+(base+h)*D+i]=tree(tmp+512,size);
                    }
                }
            }
            continue;
        }
        int r=task/QHEAD,h=task%QHEAD,kv=h/(QHEAD/KVHEAD),len=past+r+1,size=pow2(len);
        float max=-INFINITY;
        for(int t=0;t<len;t++) {
            for(int i=0;i<D;i++) tmp[i]=s->q[r*H+h*D+i]*s->k[layer][t][kv*D+i];
            prob[t]=tree(tmp,D)*(D==64?0.125f:1.0f/sqrtf((float)D)); if(prob[t]>max) max=prob[t];
        }
        for(int t=0;t<len;t++) prob[t]=(float)exp((double)(prob[t]-max));
        memset(prob+len,0,(size_t)(size-len)*sizeof(*prob));
        memcpy(tmp,prob,(size_t)size*sizeof(*prob)); float denom=tree(tmp,size);
        for(int t=0;t<len;t++) prob[t]=prob[t]/denom;
        for(int i=0;i<D;i++) {
            memset(tmp+len,0,(size_t)(size-len)*sizeof(*tmp));
            for(int t=0;t<len;t++) tmp[t]=prob[t]*s->v[layer][t][kv*D+i];
            s->a[r*H+h*D+i]=tree(tmp,size);
        }
    } return finite_array(s->a,rows*H)?NX_OK:NX_NUMERIC;
}
static nx_session s;static float keys[S*KV],vals[S*KV],q[4*H],y[4*H],want[4*H];
static unsigned rng=2702;static float rnd(void){rng^=rng<<13;rng^=rng>>17;rng^=rng<<5;return ((int)(rng%2048)-1024)/1024.0f;}
int main(void){
 s.k=(void *)keys;s.v=(void *)vals;s.q=q;s.a=y;
 for(unsigned i=0;i<S*KV;i++){keys[i]=rnd();vals[i]=rnd();}for(int i=0;i<4*H;i++)q[i]=rnd();
 const int lengths[]={1,2,3,31,32,33,45,63,64,65,127,128,129,256,512};int cases=0;unsigned words=0;
 for(unsigned c=0;c<sizeof(lengths)/sizeof(lengths[0]);c++)for(int rows=1;rows<=4;rows++){
  int end=lengths[c],past=end-rows;if(past<0)continue;
  assert(!attention_original(&s,0,rows,past));memcpy(want,y,rows*H*4);assert(!attention(&s,0,rows,past));assert(!memcmp(want,y,rows*H*4));cases++;words+=rows*H;
 }
 int rc=attention(&s,0,1,32);assert(!rc);memcpy(want,y,H*4);vals[33*KV]=NAN;assert(!attention(&s,0,1,32)&&!memcmp(want,y,H*4));vals[33*KV]=0;
 vals[32*KV]=NAN;assert(attention(&s,0,1,32)==NX_NUMERIC&&attention_original(&s,0,1,32)==NX_NUMERIC);
 printf("PASS cases=%d FP32_words=%u future-token and finite-negative checks; host semantics only\n",cases,words);return 0;
}
