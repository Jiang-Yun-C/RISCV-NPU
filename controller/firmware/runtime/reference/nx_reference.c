#define _POSIX_C_SOURCE 200809L
#include "nx_reference.h"
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <float.h>
#include <fenv.h>
#if defined(NX_PORTABLE) && defined(__riscv)
/* Newlib's POSIX wrappers can pull stdio/heap error reporting into bare metal.
 * Inputs/results are checked here; use the same library's IEEE math kernels. */
extern float __ieee754_sqrtf(float);
extern double __ieee754_exp(double);
#define sqrtf __ieee754_sqrtf
#define exp __ieee754_exp
#endif
#ifndef NX_PORTABLE
#include <time.h>
#include <omp.h>
#endif
#if defined(NX_OPT13_TEST)
/* Two complete blocks, 14:2 GQA; numerical/CPU test geometry only. */
#define H 28
#define F 32
#define V 32
#define L 2
#define D 2
#define KV 4
#define KVHEAD 2
#define NORM_SCRATCH 32
#elif defined(NX_OPT09_TEST)
/* Qualification geometry only: two complete blocks, GQA 2:1 and tied head. */
#define H 8
#define F 16
#define V 32
#define L 2
#define D 4
#define KV 4
#define KVHEAD 1
#define NORM_SCRATCH 16
#elif defined(NX_T19_MINI)
/* Test geometry preserves 14 Q : 2 KV heads, the full graph, and shared head.
 * It is explicitly separate from the unchanged production 0.5B geometry. */
#define H 112
#define F 128
#define V 129
#define L 2
#define D 8
#define NORM_SCRATCH 128
#define KV 16
#define KVHEAD 2
#define S 9
#elif defined(NX_SMALL)
#define H 64
#define F 64
#define V 64
#define L 1
#define NORM_SCRATCH 64
#define KV 64
#define KVHEAD 1
#else
#define H 896
#define F 4864
#define V 151936
#ifdef NX_T19_BLOCK
#define L 1
#else
#define L 24
#endif
#define NORM_SCRATCH 8192
#define KV 128
#define KVHEAD 2
#endif
#ifndef S
#define S 640
#endif
#ifndef D
#define D 64
#endif
#ifndef NX_PREFILL_MAX
#define NX_PREFILL_MAX 4
#endif
#if NX_PREFILL_MAX != 1 && NX_PREFILL_MAX != 4
#error NX_PREFILL_MAX must be 1 or 4
#endif
#define M NX_PREFILL_MAX
#ifndef NX_OPT08_REUSE
#define NX_OPT08_REUSE 1
#endif
#define QHEAD (H/D)
#ifndef NX_PROFILE_INTEGER
#define NX_PROFILE_INTEGER 0
#endif
#ifndef NX_PREFIX_CAPTURE
#define NX_PREFIX_CAPTURE 0
#endif
#if defined(NX_PORTABLE) && NX_PROFILE_INTEGER
typedef uint64_t nx_profile_time;
#else
typedef double nx_profile_time;
#endif
struct nx_session {
    nx_weights w; int length, valid;
    nx_prefix_identity prefix_identity;
    int32_t prefix_ids[NX_PREFIX_MAX];
    uint32_t prefix_length, prefix_ready, identity_ready, logits_valid,prefix_observed_length;
    void *backend_context;
    nx_linear_backend backend;
    nx_linear_backend private_backend;
    nx_kv_linear_backend kv_backend;
    nx_argmax_backend argmax_backend;
    nx_kv_tail tail;
    uint64_t tail_serial;
    int tail_active;
    int in_flight;
    nx_vector_backend vector_backend,private_vector_backend;
    nx_pv_backend pv_backend;
    nx_dispatch_trace dispatch_trace;
    int requested_route;
    int prefill_rows;
    nx_input_observer input_observer,private_swiglu_reservation;
    uint64_t input_version, quantized_version, quantizations, quantization_hits;
    int8_t aq[M*(F>H?F:H)];
    float sa[M*(((F>H?F:H)+63)/64)];
#ifdef NX_PORTABLE
    float (*k)[S][KV], (*v)[S][KV];
    float *x,*z,*q,*a,*b,*gate,*up,*logits;
#else
    float k[L][S][KV], v[L][S][KV];
    float x[M*H], z[M*H], q[M*H], a[M*H], b[M*H];
    float gate[M*F], up[M*F], logits[V];
#endif
    nx_profile_time seconds[NX_TIMERS]; uint64_t calls[NX_TIMERS];
};
#ifdef NX_PORTABLE
static nx_profile_time now(void) { return (nx_profile_time)nx_port_ticks(); }
#ifdef __riscv
#define ROUND_OK 1
#else
#define ROUND_OK (fegetround()==FE_TONEAREST)
#endif
#else
static double now(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC,&t); return t.tv_sec+t.tv_nsec*1e-9; }
#define ROUND_OK (fegetround()==FE_TONEAREST)
#endif
static int finite_array(const float *p,size_t n) { for(size_t i=0;i<n;i++) if(!isfinite(p[i])) return 0; return 1; }
/* Adjacent-pair tree; caller provides zero padded scratch. */
static float tree(float *p,int n) { while(n>1) { for(int i=0;i<n/2;i++) p[i]=p[2*i]+p[2*i+1]; n/=2; } return p[0]; }
static int pow2(int n) { int z=1; while(z<n) z*=2; return z; }
int nx_quantize(const float *x,int rows,int k,int8_t *q,float *s) {
    if(!x||!q||!s||rows<1||rows>M||k<1||k>(F>H?F:H)||!ROUND_OK) return NX_ARGUMENT;
    if(!finite_array(x,(size_t)rows*k)) return NX_NUMERIC;
    int g=(k+63)/64;
    for(int r=0;r<rows;r++) for(int j=0;j<g;j++) {
        float peak=0; int end=(j+1)*64<k?(j+1)*64:k;
        for(int i=j*64;i<end;i++) if(fabsf(x[r*k+i])>peak) peak=fabsf(x[r*k+i]);
        float scale=peak==0?0:fmaxf(peak/127.0f,FLT_MIN); s[r*g+j]=scale;
        for(int i=j*64;i<end;i++) q[r*k+i]=scale==0?0:(int8_t)fmaxf(-127,fminf(127,nearbyintf(x[r*k+i]/scale)));
    } return NX_OK;
}
static int dot64(const int8_t *a,const int8_t *b,int n) {
    int32_t d=0;
    #pragma omp simd reduction(+:d)
    for(int i=0;i<n;i++) d+=(int32_t)a[i]*(int32_t)b[i];
    return d;
}
static int linear_quantized(const int8_t *aq,const float *sa,int rows,const nx_matrix *w,float *y,int32_t *dots) {
    int k=w->k,g=(k+63)/64,n=w->n;
    #pragma omp parallel for schedule(static)
    for(int col=0;col<n;col++) {
        for(int r=0;r<rows;r++) {
            float sum=0;
            for(int j=0;j<g;j++) {
                int len=k-j*64<64?k-j*64:64;
                int32_t d=dot64(aq+r*k+j*64,w->q+(size_t)col*g*64+j*64,len);
                if(dots) dots[((size_t)j*rows+r)*n+col]=d;
                float p=(float)d*sa[r*g+j]; float v=p*w->s[col*g+j]; sum=sum+v;
            }
            y[r*n+col]=w->bias?sum+w->bias[col]:sum;
        }
    } return finite_array(y,(size_t)rows*n)?NX_OK:NX_NUMERIC;
}
int nx_linear(const float *x,int rows,const nx_matrix *w,float *y,int32_t *dots) {
    if(!w||!x||!y||!w->q||!w->s||w->n<1||w->n>V||w->k<1||w->k>(F>H?F:H)||rows<1||rows>M) return NX_ARGUMENT;
    int8_t aq[M*(F>H?F:H)]; float sa[M*(((F>H?F:H)+63)/64)]; int k=w->k;
    int status=nx_quantize(x,rows,k,aq,sa); if(status) return status;
    return linear_quantized(aq,sa,rows,w,y,dots);
}
int nx_norm(const float *x,const float *gamma,int rows,int width,float *y) {
    if(!x||!gamma||!y||rows<1||rows>M||width<1||width>(F>H?F:H)) return NX_ARGUMENT;
    if(!finite_array(x,(size_t)rows*width)||!finite_array(gamma,width)) return NX_NUMERIC;
    for(int r=0;r<rows;r++) {
        float tmp[NORM_SCRATCH]; int size=pow2(width);
        for(int i=0;i<width;i++) tmp[i]=x[r*width+i]*x[r*width+i];
        memset(tmp+width,0,(size_t)(size-width)*sizeof(*tmp));
        float var=tree(tmp,size)/(float)width;
        float inv=1.0f/sqrtf(var+1e-6f);
        if(!isfinite(var)||!isfinite(inv)) return NX_NUMERIC;
        for(int i=0;i<width;i++) y[r*width+i]=(x[r*width+i]*inv)*gamma[i];
    } return finite_array(y,(size_t)rows*width)?NX_OK:NX_NUMERIC;
}
int nx_rope(float *x,int rows,int heads,int past,const float *inv) {
    if(!x||!inv||rows<1||rows>M||(heads!=KVHEAD&&heads!=QHEAD)||past<0||past+rows>32768) return NX_ARGUMENT;
    if(!finite_array(x,(size_t)rows*heads*D)||!finite_array(inv,D/2)) return NX_NUMERIC;
    for(int r=0;r<rows;r++) for(int i=0;i<D/2;i++) {
        float angle=(float)(past+r)*inv[i], co=(float)cos((double)angle), si=(float)sin((double)angle);
        for(int h=0;h<heads;h++) { float *p=x+(r*heads+h)*D; float a=p[i],b=p[i+D/2]; p[i]=a*co+(-b)*si; p[i+D/2]=b*co+a*si; }
    } return finite_array(x,(size_t)rows*heads*D)?NX_OK:NX_NUMERIC;
}
#ifndef NX_DISABLE_FORWARD_ROPE_REUSE
/* inv_freq belongs to the sealed, immutable model. This scratch and its ready
 * flag live in one nx_forward call, so nested or interleaved sessions cannot
 * share coefficients. The first call computes each original double cos/sin at
 * the original FP32 angle before applying the unchanged rotation. */
static int rope_forward(float *x,int rows,int heads,int past,const float *inv,float *coeff,int *ready) {
    if(!x||!inv||!coeff||!ready||rows<1||rows>M||(heads!=KVHEAD&&heads!=QHEAD)||past<0||past+rows>32768) return NX_ARGUMENT;
    if(!finite_array(x,(size_t)rows*heads*D)||!finite_array(inv,D/2)) return NX_NUMERIC;
    int cached=*ready;
    for(int r=0;r<rows;r++) for(int i=0;i<D/2;i++) {
        if(!cached) {
            float angle=(float)(past+r)*inv[i];
            coeff[r*D+2*i]=(float)cos((double)angle);
            coeff[r*D+2*i+1]=(float)sin((double)angle);
        }
        float co=coeff[r*D+2*i],si=coeff[r*D+2*i+1];
        if(co==1.0f&&si==0.0f) {
          for(int h=0;h<heads;h++) {
            float *p=x+(r*heads+h)*D; float a=p[i],b=p[i+D/2];
            union { float f; uint32_t bits; } before_a={.f=a},after_a={.f=a*co+(-b)*si};
            if(before_a.bits!=after_a.bits)p[i]=after_a.f;
            union { float f; uint32_t bits; } before_b={.f=b},after_b={.f=b*co+a*si};
            if(before_b.bits!=after_b.bits)p[i+D/2]=after_b.f;
          }
        } else {
          for(int h=0;h<heads;h++) { float *p=x+(r*heads+h)*D; float a=p[i],b=p[i+D/2]; p[i]=a*co+(-b)*si; p[i+D/2]=b*co+a*si; }
        }
    }
    if(!finite_array(x,(size_t)rows*heads*D)) return NX_NUMERIC;
    *ready=1;return NX_OK;
}
#endif
int nx_swiglu(const float *gate,const float *up,int count,float *y) {
    if(!gate||!up||!y||count<1||count>M*F) return NX_ARGUMENT;
    if(!finite_array(gate,count)||!finite_array(up,count)) return NX_NUMERIC;
    for(int i=0;i<count;i++) { float e=(float)exp(-(double)fabsf(gate[i])); float sig=gate[i]>=0?1.0f/(1.0f+e):e/(1.0f+e); y[i]=(gate[i]*sig)*up[i]; }
    return finite_array(y,count)?NX_OK:NX_NUMERIC;
}
#ifndef NX_ATTENTION_GQA_CACHE
#define NX_ATTENTION_GQA_CACHE 1
#endif
#ifndef NX_ATTENTION_QK_BATCH
#define NX_ATTENTION_QK_BATCH 1
#endif
#if NX_ATTENTION_QK_BATCH
/* Preserve every independently rounded FP32 product and the original adjacent
 * pair tree. Eight original eight-leaf subtrees remain in registers until their
 * roots are stored in the caller's existing reduction scratch. No FMA, new
 * tensor storage, KV conversion, or change to scale/max/softmax is permitted. */
static float qk64_tree_batch(const float *q,const float *k,float *work) {
    for(int block=0;block<8;block++) {
        int i=block*8;
        float p0=q[i]*k[i],p1=q[i+1]*k[i+1];
        float p2=q[i+2]*k[i+2],p3=q[i+3]*k[i+3];
        float p4=q[i+4]*k[i+4],p5=q[i+5]*k[i+5];
        float p6=q[i+6]*k[i+6],p7=q[i+7]*k[i+7];
        float a0=p0+p1,a1=p2+p3,a2=p4+p5,a3=p6+p7;
        float b0=a0+a1,b1=a2+a3;
        work[block]=b0+b1;
    }
    return tree(work,8);
}
#endif
#ifndef NX_PV_LONG
#define NX_PV_LONG 0
#endif
#ifndef T27_PV_BATCH
#define T27_PV_BATCH 0
#endif
#ifndef T27_M4_HANDOFF
#define T27_M4_HANDOFF 0
#endif
#if T27_PV_BATCH
extern int t27_pv_batch(const float *,const float *,int,int,int,int,float *);
#endif
static int attention(nx_session *s,int layer,int rows,int past) {
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
                        float value;
#if NX_ATTENTION_QK_BATCH
                        if(D==64) value=qk64_tree_batch(tmp+h*D,tmp+448,tmp+512)*0.125f;
                        else
#endif
                        {
                            for(int i=0;i<D;i++)tmp[512+i]=tmp[h*D+i]*tmp[448+i];
                            value=tree(tmp+512,D)*(D==64?0.125f:1.0f/sqrtf((float)D));
                        }
                        prob[h*len+t]=value;
                        if(value>maxima[h])maxima[h]=value;
                    }
                }
                for(int h=0;h<count;h++) {
                    /* The independently rounded exponential feeds both the
                     * retained probability row and its destructive tree.
                     * Populate both here to avoid rereading the entire row;
                     * exp order, FP32 rounding and the tree stay unchanged. */
                    for(int t=0;t<len;t++) {
                        float value=(float)exp((double)(prob[h*len+t]-maxima[h]));
                        prob[h*len+t]=value;tmp[512+t]=value;
                    }
                    memset(tmp+512+len,0,(size_t)(size-len)*sizeof(*tmp));
                    float denom=tree(tmp+512,size);
                    for(int t=0;t<len;t++)prob[h*len+t]=prob[h*len+t]/denom;
                }
                /* Q/K are dead now. Reuse tmp[0..511] for V; preserve the
                 * original complete adjacent-pair PV tree for every head. */
#if T27_PV_BATCH
                if(D==64&&len<=64&&count<=7){
                    if(t27_pv_batch(prob,&s->v[layer][0][kv*D],KV,count,len,size,&s->a[r*H+base*D]))return (nx_diag_reference(((8u<<16)|__LINE__),s->length,s->valid,s->in_flight,s->input_version,s->tail_serial),NX_STATE);
                    continue;
                }
#endif
                if(s->requested_route&&s->pv_backend&&D==64&&len<=(NX_PV_LONG?512:64)){
                    int rc=s->pv_backend(s->backend_context,prob,&s->v[layer][0][kv*D],KV,count,len,size,&s->a[r*H+base*D]);
                    if(rc!=NX_UNSUPPORTED){if(rc)return rc;continue;}
                }
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
        for(int t=0;t<len;t++) {
            float value=(float)exp((double)(prob[t]-max));
            prob[t]=value;tmp[t]=value;
        }
        /* Only the destructive reduction needs padding. No consumer reads
         * prob[len..size), so avoid writing it and then copying it back. */
        memset(tmp+len,0,(size_t)(size-len)*sizeof(*tmp));
        float denom=tree(tmp,size);
        for(int t=0;t<len;t++) prob[t]=prob[t]/denom;
        for(int i=0;i<D;i++) {
            memset(tmp+len,0,(size_t)(size-len)*sizeof(*tmp));
            for(int t=0;t<len;t++) tmp[t]=prob[t]*s->v[layer][t][kv*D+i];
            s->a[r*H+h*D+i]=tree(tmp,size);
        }
    } return finite_array(s->a,rows*H)?NX_OK:NX_NUMERIC;
}
static int weights_valid(const nx_weights *w) {
    if(!w||!w->inv_freq||!w->norm||!ROUND_OK) return 0;
    if(!w->embedding.q||!w->embedding.s||w->embedding.bias||w->embedding.n!=V||w->embedding.k!=H) return 0;
    for(int l=0;l<L;l++) {
        const nx_layer *p=&w->layer[l];
        const nx_matrix *mat[]={&p->q,&p->k,&p->v,&p->o,&p->gate,&p->up,&p->down};
        const int ns[]={H,KV,KV,H,F,F,H},ks[]={H,H,H,H,H,H,F};
        if(!p->norm1||!p->norm2) return 0;
        for(int i=0;i<7;i++) if(!mat[i]->q||!mat[i]->s||mat[i]->n!=ns[i]||mat[i]->k!=ks[i]||
                               (i<3?!mat[i]->bias:!!mat[i]->bias)) return 0;
    }
    return 1;
}
#ifndef NX_PORTABLE
nx_session *nx_create(const nx_weights *w,int threads) {
    if(threads<1||threads>80||!weights_valid(w))return NULL;
    nx_session *s=calloc(1,sizeof(*s)); if(!s) return NULL;
    s->w=*w; s->valid=1; s->prefill_rows=M; omp_set_dynamic(0); omp_set_num_threads(threads); return s;
}
void nx_destroy(nx_session *s) { free(s); }
#else
size_t nx_state_bytes(void) { return (sizeof(nx_session)+15)&~(size_t)15; }
size_t nx_kv_bytes(void) { return (size_t)2*L*S*KV*4; }
size_t nx_work_bytes(void) { return ((size_t)M*(5*H+2*F)+V)*4; }
nx_session *nx_init_static(const nx_weights *w,void *state,size_t ns,void *kv,size_t nk,void *work,size_t nw) {
    if(!weights_valid(w)||!state||!kv||!work||((uintptr_t)state|(uintptr_t)kv|(uintptr_t)work)&15||
       ns<nx_state_bytes()||nk<nx_kv_bytes()||nw<nx_work_bytes())return NULL;
    uintptr_t a=(uintptr_t)state,b=(uintptr_t)kv,c=(uintptr_t)work;
    if(ns>UINTPTR_MAX-a||nk>UINTPTR_MAX-b||nw>UINTPTR_MAX-c||
       (a<b+nk&&b<a+ns)||(a<c+nw&&c<a+ns)||(b<c+nw&&c<b+nk))return NULL;
    nx_session *s=state;memset(s,0,sizeof(*s));s->w=*w;s->valid=1;s->prefill_rows=M;
    s->k=kv;s->v=(void *)((uint8_t *)kv+nx_kv_bytes()/2);
    float *p=work;s->x=p;p+=M*H;s->z=p;p+=M*H;s->q=p;p+=M*H;s->a=p;p+=M*H;s->b=p;p+=M*H;
    s->gate=p;p+=M*F;s->up=p;p+=M*F;s->logits=p;return s;
}
nx_session *nx_create(const nx_weights *w,int threads) { (void)w;(void)threads;return NULL; }
void nx_destroy(nx_session *s) { (void)s; }
#endif
void nx_bind_backend(nx_session *s,void *context,nx_linear_backend backend,nx_dispatch_trace trace,int route) {
    if(s){nx_reset(s);s->backend_context=context;s->backend=backend;s->pv_backend=NULL;s->private_backend=NULL;s->kv_backend=NULL;s->argmax_backend=NULL;s->private_vector_backend=NULL;s->private_swiglu_reservation=NULL;s->dispatch_trace=trace;s->requested_route=route;}
}
void nx_bind_kv_backend(nx_session *s,nx_kv_linear_backend b){if(s){nx_reset(s);s->kv_backend=b;}}
void nx_bind_argmax_backend(nx_session *s,nx_argmax_backend b){if(s){nx_reset(s);s->argmax_backend=b;}}
int nx_kv_tail_valid(const nx_kv_tail *v,const nx_matrix *w,const float *y){
    if(!v||!v->owner||!w||!y)return 0;
    nx_session *s=v->owner;
    if(!s->valid||!s->in_flight||!s->tail_active||v->abi!=NX_KV_TAIL_ABI||
       !v->serial||v->serial!=s->tail_serial||v->serial!=s->tail.serial||
       v->layers!=L||v->capacity!=S||v->width!=KV||v->layer>=L||v->value>1||
       !v->rows||v->rows>M||v->past>512-v->rows||v->past!=(uint32_t)s->length||
       v->layer!=s->tail.layer||v->value!=s->tail.value||v->past!=s->tail.past||v->rows!=s->tail.rows)return 0;
    uintptr_t arena=(uintptr_t)&s->k[0][0][0];
    uintptr_t destination=(uintptr_t)(v->value?&s->v[v->layer][v->past][0]:&s->k[v->layer][v->past][0]);
    const nx_matrix *expected=v->value?&s->w.layer[v->layer].v:&s->w.layer[v->layer].k;
    return v->arena==arena&&v->destination==destination&&(uintptr_t)y==destination&&w==expected&&w->n==KV;
}
void nx_bind_pv_backend(nx_session *s,nx_pv_backend b){if(s){nx_reset(s);s->pv_backend=b;}}
void nx_bind_private_backend(nx_session *s,nx_linear_backend backend) {
    if(s){nx_reset(s);s->private_backend=backend;s->private_swiglu_reservation=NULL;}
}
void nx_bind_vector_backend(nx_session *s,nx_vector_backend backend) {
    if(s){nx_reset(s);s->vector_backend=backend;s->private_swiglu_reservation=NULL;}
}
void nx_bind_private_vector_backend(nx_session *s,nx_vector_backend backend) {
    if(s){nx_reset(s);s->private_vector_backend=backend;s->private_swiglu_reservation=NULL;}
}
static int dispatched_vector(nx_session *s,unsigned mode,const float *x,const float *u,int rows,int k,float *y) {
    int rc=NX_UNSUPPORTED;
    int owned=s->in_flight&&
        ((mode==7&&y==s->z&&rows*k<=M*H)||
         (mode==2&&y==s->x&&rows*k<=M*H)||
         (mode==0&&y==s->logits&&rows*k<=V));
    nx_vector_backend backend=owned&&s->private_vector_backend?s->private_vector_backend:s->vector_backend;
    if(s->requested_route&&backend)rc=backend(s->backend_context,mode,x,u,rows,k,y);
    if(rc==NX_UNSUPPORTED){
        if(mode==7)rc=nx_norm(x,u,rows,k,y);
        else if(mode==0)rc=nx_swiglu(x,u,rows*k,y);
        else if(mode==2){for(int i=0;i<rows*k;i++)y[i]=x[i]+u[i];rc=finite_array(y,(size_t)rows*k)?NX_OK:NX_NUMERIC;}
        else rc=NX_UNSUPPORTED;
    }
    return rc;
}
void nx_bind_input_observer(nx_session *s,nx_input_observer observer) {
    if(s){if(s->input_observer)s->input_observer(s->backend_context,0,0,0,0);s->input_observer=observer;s->private_swiglu_reservation=NULL;}
}
void nx_bind_private_swiglu_reservation(nx_session *s,nx_input_observer reserve) {
    if(s){nx_reset(s);s->private_swiglu_reservation=
        reserve&&reserve==s->input_observer&&s->private_vector_backend?reserve:NULL;}
}
static void input_invalidate(nx_session *s) {
    s->quantized_version=0;
    if(s->input_observer)s->input_observer(s->backend_context,0,0,0,0);
}
static int input_next(nx_session *s) {
    input_invalidate(s);
    if(s->input_version==UINT64_MAX){s->valid=0;return (nx_diag_reference(((8u<<16)|__LINE__),s->length,s->valid,s->in_flight,s->input_version,s->tail_serial),NX_STATE);}
    s->input_version++;return NX_OK;
}
void nx_opt08_counters(nx_session *s,uint64_t *calls,uint64_t *hits) {
    if(s){if(calls)*calls=s->quantizations;if(hits)*hits=s->quantization_hits;}
}
static int dispatched_linear(nx_session *s,const float *x,int rows,const nx_matrix *w,float *y) {
    int rc=NX_UNSUPPORTED,route=0,reason=s->requested_route?2:3;uint64_t start=(uint64_t)now();
    if(s->input_observer)s->input_observer(s->backend_context,x,rows,w->k,NX_OPT08_REUSE?s->input_version:0);
    /* These are fixed session-owned work buffers, never a public tensor or
     * an already published KV prefix. K/V continue through the staged ABI. */
    int owned=s->in_flight&&
        (((y==s->q||y==s->b)&&rows*w->n<=M*H)||
         ((y==s->gate||y==s->up)&&rows*w->n<=M*F)||
         (y==s->logits&&rows==1&&w->n==V));
    nx_linear_backend backend=owned&&s->private_backend?s->private_backend:s->backend;
    if(s->requested_route&&s->tail_active&&s->kv_backend){
        nx_kv_tail lease=s->tail;
        if(!nx_kv_tail_valid(&lease,w,y))return (nx_diag_reference(((8u<<16)|__LINE__),s->length,s->valid,s->in_flight,s->input_version,s->tail_serial),NX_STATE);
        rc=s->kv_backend(s->backend_context,x,rows,w,y,&lease);
        if(!nx_kv_tail_valid(&lease,w,y))return (nx_diag_reference(((8u<<16)|__LINE__),s->length,s->valid,s->in_flight,s->input_version,s->tail_serial),NX_STATE);
        if(rc!=NX_UNSUPPORTED){route=s->requested_route;reason=0;}
    }
    if(rc==NX_UNSUPPORTED&&s->requested_route&&backend){rc=backend(s->backend_context,x,rows,w,y);if(rc!=NX_UNSUPPORTED){route=s->requested_route;reason=0;}}
    if(rc==NX_UNSUPPORTED){
        if(!NX_OPT08_REUSE){s->quantizations++;rc=nx_linear(x,rows,w,y,NULL);}
        else {
            if(s->quantized_version!=s->input_version){
                s->quantizations++;rc=nx_quantize(x,rows,w->k,s->aq,s->sa);
                if(!rc)s->quantized_version=s->input_version;
            }else {s->quantization_hits++;rc=NX_OK;}
            if(!rc)rc=linear_quantized(s->aq,s->sa,rows,w,y,NULL);
        }
    }
    if(rc)input_invalidate(s);
    if(s->dispatch_trace)s->dispatch_trace(s->backend_context,NX_LINEAR,route,reason,rc,(uint64_t)now()-start);
    return rc;
}
#ifndef NX_KV_TAIL_DIRECT
#define NX_KV_TAIL_DIRECT 0
#endif
static int dispatched_kv(nx_session *s,const float *x,int rows,int layer,int value,int past){
    const nx_matrix *w=value?&s->w.layer[layer].v:&s->w.layer[layer].k;
    float *y=value?&s->v[layer][past][0]:&s->k[layer][past][0];
    if(NX_KV_TAIL_DIRECT&&s->kv_backend){
        if(s->tail_serial==UINT64_MAX)return (nx_diag_reference(((8u<<16)|__LINE__),s->length,s->valid,s->in_flight,s->input_version,s->tail_serial),NX_STATE);
        s->tail=(nx_kv_tail){.owner=s,.serial=++s->tail_serial,.arena=(uintptr_t)&s->k[0][0][0],
            .destination=(uintptr_t)y,.abi=NX_KV_TAIL_ABI,.layer=(uint32_t)layer,.value=(uint32_t)value,
            .past=(uint32_t)past,.rows=(uint32_t)rows,.layers=L,.capacity=S,.width=KV};
        s->tail_active=1;
    }
    int rc=dispatched_linear(s,x,rows,w,y);s->tail_active=0;return rc;
}
void nx_prefix_invalidate(nx_session *s) {
    if(s){s->prefix_ready=0;s->prefix_length=0;s->prefix_observed_length=0;s->logits_valid=0;s->in_flight=0;s->tail_active=0;input_invalidate(s);}
}
void nx_reset(nx_session *s) { if(s) { nx_prefix_invalidate(s);s->length=0;s->valid=1; } }
static int identity_valid(const nx_prefix_identity *key) {
    if(!key||key->abi!=NX_PREFIX_ABI||key->start_position!=0||key->context_limit!=NX_PREFIX_MAX)return 0;
    const uint8_t *digests[5]={key->model,key->tokenizer,key->template_version,key->numeric,key->backend};
    for(int j=0;j<5;j++){unsigned any=0;for(int i=0;i<32;i++)any|=digests[j][i];if(!any)return 0;}
    return 1;
}
int nx_prefix_configure(nx_session *s,const nx_prefix_identity *key) {
    if(!s)return NX_ARGUMENT;
    if(!identity_valid(key)){nx_reset(s);s->identity_ready=0;return NX_ARGUMENT;}
    if(!s->identity_ready||memcmp(&s->prefix_identity,key,sizeof(*key))){
        nx_reset(s);s->prefix_identity=*key;s->identity_ready=1;
    }
    return NX_OK;
}
int nx_prefix_prepare(nx_session *s,const nx_prefix_identity *key,const int32_t *ids,size_t n) {
    if(!s)return NX_ARGUMENT;
    nx_reset(s);
    if(nx_prefix_configure(s,key)||!ids||!n||n>NX_PREFIX_MAX||n>S)return NX_ARGUMENT;
    for(size_t i=0;i<n;i++)if(ids[i]<0||ids[i]>=V)return NX_ARGUMENT;
    for(size_t i=0;i<n;){
        int rows=(int)(n-i)<s->prefill_rows?(int)(n-i):s->prefill_rows;
        int rc=nx_forward(s,ids+i,rows,(int)i,NULL,NULL);
        if(rc){nx_reset(s);return rc;}
        i+=(size_t)rows;
    }
    memcpy(s->prefix_ids,ids,n*sizeof(*ids));s->prefix_length=(uint32_t)n;s->prefix_ready=1;
    return NX_OK;
}
int nx_prefix_capture(nx_session *s,const nx_prefix_identity *key,const int32_t *ids,size_t n) {
    if(!NX_PREFIX_CAPTURE||!s||!identity_valid(key)||!ids||!n||n>NX_PREFIX_MAX||n>S||
       !s->valid||s->in_flight||s->length!=(int)n||s->prefix_observed_length!=n||!s->identity_ready||
       memcmp(&s->prefix_identity,key,sizeof(*key)))return NX_ARGUMENT;
    for(size_t i=0;i<n;i++)if(ids[i]<0||ids[i]>=V)return NX_ARGUMENT;
    if(memcmp(s->prefix_ids,ids,n*sizeof(*ids)))return NX_ARGUMENT;
    memcpy(s->prefix_ids,ids,n*sizeof(*ids));s->prefix_length=(uint32_t)n;
    s->prefix_ready=1;s->logits_valid=0;input_invalidate(s);return NX_OK;
}
#ifndef NX_OPT09_PREFIX
#define NX_OPT09_PREFIX 1
#endif
int nx_prefix_restore(nx_session *s,const nx_prefix_identity *key,const int32_t *ids,size_t n) {
    if(!s)return 0;
    if(!NX_OPT09_PREFIX||!identity_valid(key)||!ids||!n||n>NX_PREFIX_MAX||!s->valid||
       s->in_flight||!s->identity_ready||!s->prefix_ready||s->prefix_length!=n||s->length<(int)n||
       memcmp(&s->prefix_identity,key,sizeof(*key))||memcmp(s->prefix_ids,ids,n*sizeof(*ids))){nx_reset(s);return 0;}
    input_invalidate(s);s->length=(int)n;s->logits_valid=0;return 1;
}
const float *nx_cache_view(nx_session *s,int l,int value,size_t *tokens) {
    if(!tokens)return NULL;
    *tokens=0;const float *p=nx_cache(s,l,value);
    if(p)*tokens=(size_t)s->length;
    return p;
}
const float *nx_cache(nx_session *s,int l,int value) { return (!s||!s->valid||s->in_flight||l<0||l>=L||(value!=0&&value!=1))?NULL:(value?&s->v[l][0][0]:&s->k[l][0][0]); }
int nx_length(nx_session *s) { return s&&s->valid&&!s->in_flight?s->length:-1; }
size_t nx_memory_bytes(void) {
#ifdef NX_PORTABLE
    return nx_state_bytes()+nx_kv_bytes()+nx_work_bytes();
#else
    return sizeof(nx_session);
#endif
}
void nx_profile(nx_session *s,double seconds[NX_TIMERS],uint64_t calls[NX_TIMERS]) {
    for(unsigned i=0;i<NX_TIMERS;i++)seconds[i]=(double)s->seconds[i];
    memcpy(calls,s->calls,sizeof(s->calls));
}
#ifdef NX_PORTABLE
void nx_profile_ticks(nx_session *s,uint64_t ticks[NX_TIMERS],uint64_t calls[NX_TIMERS]) {
    for(unsigned i=0;i<NX_TIMERS;i++)ticks[i]=(uint64_t)s->seconds[i];
    memcpy(calls,s->calls,sizeof(s->calls));
}
#endif
#define TIMED(kind,expr) do { nx_diag_phase(rows,past,diagnostic_layer,kind); nx_profile_time start=now(); int rc=(expr); s->seconds[kind]+=now()-start;s->calls[kind]++;if(rc){s->valid=0;nx_prefix_invalidate(s);return rc;} } while(0)
#define TRACE(name,data,cols) do { if(trace) trace(l,name,data,rows,cols); } while(0)
static int forward_mode(nx_session *s,const int32_t *ids,int rows,int past,float *logits,nx_trace trace,int last_only) {
    if(!s)return NX_ARGUMENT;
    s->logits_valid=0;
    int error=NX_OK;
    if(!ids)error=NX_ARGUMENT;
    else if(!s->valid||s->in_flight||past!=s->length)error=NX_STATE;
    else if(rows<1||rows>M||past<0||past>S-rows)error=NX_ARGUMENT;
    else for(int r=0;r<rows;r++)if(ids[r]<0||ids[r]>=V){error=NX_ARGUMENT;break;}
    if(error){if(error==NX_STATE)nx_diag_reference(((8u<<16)|__LINE__),s->length,s->valid,s->in_flight,s->input_version,s->tail_serial);s->valid=0;nx_prefix_invalidate(s);return error;}
    s->in_flight=1;int diagnostic_layer=-1;
#ifndef NX_DISABLE_FORWARD_ROPE_REUSE
    float rope_coeff[rows*D];int rope_ready=0;
#endif
    nx_profile_time start=now();
    for(int r=0;r<rows;r++) for(int i=0;i<H;i++) s->x[r*H+i]=(float)s->w.embedding.q[(size_t)ids[r]*((H+63)/64)*64+i]*s->w.embedding.s[ids[r]*((H+63)/64)+i/64];
    s->seconds[NX_EMBED]+=now()-start;s->calls[NX_EMBED]++;
    if(trace) trace(-1,"embedding",s->x,rows,H);
    for(int l=0;l<L;l++) {
        diagnostic_layer=l;nx_layer *w=&s->w.layer[l]; TRACE("input",s->x,H);
        if(input_next(s)){nx_prefix_invalidate(s);return (nx_diag_reference(((8u<<16)|__LINE__),s->length,s->valid,s->in_flight,s->input_version,s->tail_serial),NX_STATE);}
        TIMED(NX_NORM,dispatched_vector(s,7,s->x,w->norm1,rows,H,s->z));TRACE("norm1",s->z,H);
        TIMED(NX_LINEAR,dispatched_linear(s,s->z,rows,&w->q,s->q));TRACE("q",s->q,H);
        TIMED(NX_LINEAR,dispatched_kv(s,s->z,rows,l,0,past));TRACE("k",&s->k[l][past][0],KV);
        TIMED(NX_LINEAR,dispatched_kv(s,s->z,rows,l,1,past));TRACE("v",&s->v[l][past][0],KV);
#ifndef NX_DISABLE_FORWARD_ROPE_REUSE
        TIMED(NX_ROPE,rope_forward(s->q,rows,QHEAD,past,s->w.inv_freq,rope_coeff,&rope_ready));TRACE("qr",s->q,H);
        TIMED(NX_ROPE,rope_forward(&s->k[l][past][0],rows,KVHEAD,past,s->w.inv_freq,rope_coeff,&rope_ready));TRACE("kr",&s->k[l][past][0],KV);
#else
        TIMED(NX_ROPE,nx_rope(s->q,rows,QHEAD,past,s->w.inv_freq));TRACE("qr",s->q,H);
        TIMED(NX_ROPE,nx_rope(&s->k[l][past][0],rows,KVHEAD,past,s->w.inv_freq));TRACE("kr",&s->k[l][past][0],KV);
#endif
        TIMED(NX_ATTN,attention(s,l,rows,past));TRACE("attn",s->a,H);
        if(input_next(s)){nx_prefix_invalidate(s);return (nx_diag_reference(((8u<<16)|__LINE__),s->length,s->valid,s->in_flight,s->input_version,s->tail_serial),NX_STATE);}
        TIMED(NX_LINEAR,dispatched_linear(s,s->a,rows,&w->o,s->b));TRACE("o",s->b,H);
        TIMED(NX_RESIDUAL,dispatched_vector(s,2,s->x,s->b,rows,H,s->x));TRACE("res1",s->x,H);
        if(input_next(s)){nx_prefix_invalidate(s);return (nx_diag_reference(((8u<<16)|__LINE__),s->length,s->valid,s->in_flight,s->input_version,s->tail_serial),NX_STATE);}
        TIMED(NX_NORM,dispatched_vector(s,7,s->x,w->norm2,rows,H,s->z));TRACE("norm2",s->z,H);
        TIMED(NX_LINEAR,dispatched_linear(s,s->z,rows,&w->gate,s->gate));TRACE("gate",s->gate,F);
        TIMED(NX_LINEAR,dispatched_linear(s,s->z,rows,&w->up,s->up));TRACE("up",s->up,F);
        /* The production vocabulary workspace exceeds M*F and is unpublished
         * until the final head. Tiny oracle vocabularies retain staged aliasing. */
        float *activation=rows*F<=V?s->logits:s->gate;
        if(input_next(s)){nx_prefix_invalidate(s);return (nx_diag_reference(((8u<<16)|__LINE__),s->length,s->valid,s->in_flight,s->input_version,s->tail_serial),NX_STATE);}
        /* Retire gate/up's input before reserving the next private output.
         * An ordinary observer is never called with unfinished data. Traced
         * calls keep the original re-quantization path; the test-only M4 switch
         * requires a completed certificate for every row. */
        if(NX_OPT08_REUSE&&s->requested_route&&s->private_vector_backend&&
           s->private_swiglu_reservation&&!trace&&(rows==1||T27_M4_HANDOFF)&&F==4864&&activation==s->logits)
            s->private_swiglu_reservation(s->backend_context,activation,rows,F,s->input_version);
        TIMED(NX_SWIGLU,dispatched_vector(s,0,s->gate,s->up,rows,F,activation));TRACE("act",activation,F);
        TIMED(NX_LINEAR,dispatched_linear(s,activation,rows,&w->down,s->b));TRACE("down",s->b,H);
        TIMED(NX_RESIDUAL,dispatched_vector(s,2,s->x,s->b,rows,H,s->x));
        if(!finite_array(s->x,rows*H)) {s->valid=0;nx_prefix_invalidate(s);return NX_NUMERIC;} TRACE("output",s->x,H);
    }
    if(logits) {diagnostic_layer=24;
        /* Only one vocabulary row lives in the session. Diagnostic callers
         * own [rows,V]; each row is committed after its head succeeds. */
        int first=last_only?rows-1:0;
        for(int r=first;r<rows;r++) {
            if(input_next(s)){nx_prefix_invalidate(s);return (nx_diag_reference(((8u<<16)|__LINE__),s->length,s->valid,s->in_flight,s->input_version,s->tail_serial),NX_STATE);}
            TIMED(NX_NORM,dispatched_vector(s,7,s->x+r*H,s->w.norm,1,H,s->z));
            if(trace) trace(24,"final_norm",s->z,1,H);
            TIMED(NX_HEAD,dispatched_linear(s,s->z,1,&s->w.embedding,s->logits));
            float *out=logits+(last_only?0:(size_t)r*V);
            if(out!=s->logits)memcpy(out,s->logits,(size_t)V*sizeof(float));
            if(trace)trace(24,"logits",out,1,V);
        }
    }
    if(NX_PREFIX_CAPTURE&&!s->prefix_ready&&past==(int)s->prefix_observed_length&&(unsigned)(past+rows)<=NX_PREFIX_MAX){
        memcpy(s->prefix_ids+past,ids,(size_t)rows*sizeof(*ids));s->prefix_observed_length+=(uint32_t)rows;
    }
    s->length=past+rows;s->logits_valid=logits!=NULL;input_invalidate(s);s->in_flight=0;return NX_OK;
}
int nx_forward(nx_session *s,const int32_t *ids,int rows,int past,float *logits,nx_trace trace) {
    return forward_mode(s,ids,rows,past,logits,trace,0);
}
int nx_set_prefill_rows(nx_session *s,int rows) {
    if(!s||(rows!=1&&rows!=4)||rows>M)return NX_ARGUMENT;
    /* Changing execution identity revokes the previous prefix and views. */
    if(s->prefill_rows!=rows){nx_reset(s);s->prefill_rows=rows;}
    return NX_OK;
}
#ifndef NX_HEAD_ARGMAX
#define NX_HEAD_ARGMAX 0
#endif
static int select_token(nx_session *s,int32_t *next){
    if(NX_HEAD_ARGMAX&&s->requested_route&&s->argmax_backend){
        int32_t candidate=-1;
        int rc=s->argmax_backend(s->backend_context,s->logits,V,&candidate);
        if(rc!=NX_UNSUPPORTED){
            if(rc)return rc;
            if(candidate<0||candidate>=V)return (nx_diag_reference(((8u<<16)|__LINE__),s->length,s->valid,s->in_flight,s->input_version,s->tail_serial),NX_STATE);
            *next=candidate;return NX_OK;
        }
    }
    return nx_greedy(s->logits,next);
}
int nx_forward_block_v3(nx_session *s,const int32_t *ids,int rows,int past,int32_t *next) {
    if(!s)return NX_ARGUMENT;
    if(rows<1||rows>s->prefill_rows||past<0||past>512-rows){
        s->valid=0;nx_prefix_invalidate(s);return NX_ARGUMENT;
    }
    int rc=forward_mode(s,ids,rows,past,next?s->logits:NULL,NULL,1);
    if(!rc&&next)rc=select_token(s,next);
    if(rc){s->valid=0;nx_prefix_invalidate(s);}return rc;
}

int nx_greedy(const float *logits,int32_t *token) {
    if(!logits||!token) return NX_ARGUMENT;
    /* Validate every logit before publishing, including after the best one.
     * Keep its value in a register instead of rereading logits[best], and
     * merge the finite scan with argmax. Strict > preserves the first tie,
     * including opposite signed zero; a failing call leaves token untouched. */
    float best_value=logits[0];
    if(!isfinite(best_value)) return NX_NUMERIC;
    int best=0;
    for(int i=1;i<V;i++) {
        float value=logits[i];
        if(!isfinite(value)) return NX_NUMERIC;
        if(value>best_value){best=i;best_value=value;}
    }
    *token=best;return NX_OK;
}
int nx_generate(nx_session *s,const int32_t *ids,int length,int32_t output[128],int *count,int *stop) {
    if(!s||!ids||!output||!count||!stop||length<1||length>512) return NX_ARGUMENT;
    for(int i=0;i<length;i++) if(ids[i]<0||ids[i]>=V) return NX_ARGUMENT;
    nx_reset(s);int rc;int32_t generated[128],next=-1;
    for(int lo=0;lo<length;){
        int rows=length-lo<s->prefill_rows?length-lo:s->prefill_rows;
        rc=nx_forward_block_v3(s,ids+lo,rows,lo,lo+rows==length?&next:NULL);
        if(rc)return rc;
        lo+=rows;
    }
    int maximum=512-length<128?512-length:128;
    for(int step=0;step<maximum;step++) {
        generated[step]=next;
        if(next==151645||step+1==maximum){
            memcpy(output,generated,(size_t)(step+1)*sizeof(*output));
            *count=step+1;*stop=next==151645?1:maximum<128?3:2;return NX_OK;
        }
        rc=nx_forward_block_v3(s,&generated[step],1,s->length,&next);if(rc)return rc;
    }
    *count=0;*stop=3;return NX_OK;
}

/* ABI v2: internal logits are exposed read-only, only after complete success.
 * The v1 caller-owned logits buffer remains disjoint and unchanged. */
const float *nx_logits_v2(nx_session *s) {return s&&s->valid&&!s->in_flight&&s->logits_valid?s->logits:NULL;}
int nx_forward_token_v2(nx_session *s,int32_t id,int past,int32_t *next) {
    if(!s||!next)return NX_ARGUMENT;
    int rc=nx_forward(s,&id,1,past,s->logits,NULL);
    if(!rc)rc=select_token(s,next);
    if(rc){s->valid=0;nx_prefix_invalidate(s);}return rc;
}
