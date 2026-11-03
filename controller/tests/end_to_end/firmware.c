#include "nx_reference.h"
#include "coral_backend.h"
#include "coral_api_compat.h"
#include <string.h>
#include "model_weights.h"
#include "linear_image.h"
#define MM(a) (*(volatile uint32_t *)(uintptr_t)(a))
static nx_context accelerator;
static nx_coral_transport transport;
static nx_weights weights;
static unsigned step,dispatches;
static void report(unsigned group,unsigned index,uint32_t value){MM(0x10000080)=group<<16|index;MM(0x10000084)=value;}
uint64_t nx_port_ticks(void){uint32_t hi,lo,again;do{__asm__ volatile("csrr %0,mcycleh":"=r"(hi));__asm__ volatile("csrr %0,mcycle":"=r"(lo));__asm__ volatile("csrr %0,mcycleh":"=r"(again));}while(hi!=again);return ((uint64_t)hi<<32)|lo;}
uint32_t trap_handler(uint32_t cause,uint32_t pc,uint32_t value){
    (void)value;if(cause==0x8000000bu){nx_accel_irq(&accelerator);return pc;}if(cause==0x80000007u)return pc;
    report(255,0,cause);report(255,1,pc);MM(0x10000020)=cause?cause:1;for(;;){}
}
static void wait_tick(void *p){(void)p;__asm__ volatile("wfi":::"memory");}
static void *resolve(void *p,uint32_t a,uint32_t n,int write){(void)p;(void)n;(void)write;return (void *)(uintptr_t)a;}
static int sealed(void *p,const nx_accel_linear *j){
    (void)p;
    for(unsigned l=0;l<FIXTURE_LAYERS+1;l++){
        const nx_matrix *m[7];unsigned count;
        if(l==FIXTURE_LAYERS){m[0]=&weights.embedding;count=1;}
        else{nx_layer *w=&weights.layer[l];m[0]=&w->q;m[1]=&w->k;m[2]=&w->v;m[3]=&w->o;m[4]=&w->gate;m[5]=&w->up;m[6]=&w->down;count=7;}
        for(unsigned i=0;i<count;i++)if(j->wq.address==(uintptr_t)m[i]->q&&j->wq.shape[0]==(unsigned)m[i]->n&&j->wq.shape[1]==(unsigned)(m[i]->k+63)/64*64&&j->wq.allocation_bytes==(unsigned)m[i]->n*((m[i]->k+63)/64)*64&&j->sw.address==(uintptr_t)m[i]->s&&j->sw.allocation_bytes==(unsigned)m[i]->n*((m[i]->k+63)/64)*4&&j->bias.address==(uintptr_t)m[i]->bias)return 1;
    }return 0;
}
static nx_status execute(void *p,const nx_call *c,const struct nx_stream_request *r,struct nx_stream_result *s){(void)p;return nx_coral_linear_execute(&transport,c,r,s);}
static void dispatch(void *p,int kind,int route,int reason,int status,uint64_t ticks){
    (void)p;report(700+dispatches,0,kind);report(700+dispatches,1,route);report(700+dispatches,2,reason);report(700+dispatches,3,(uint32_t)status);report(700+dispatches,4,(uint32_t)ticks);dispatches++;
}
static const char *names[]={"embedding","input","norm1","q","k","v","qr","kr","attn","o","res1","norm2","gate","up","act","down","output","final_norm","logits","cache_k","cache_v"};
static void trace(int layer,const char *name,const float *data,int rows,int cols){
    unsigned n=0;while(n<21&&strcmp(name,names[n]))n++;if(n==21){MM(0x10000020)=99;for(;;){}}
    unsigned group=1000+step*100+(layer+1)*22+n;
    for(int i=0;i<rows*cols;i++){uint32_t u;memcpy(&u,data+i,4);report(group,i,u);}
}
static void cache_trace(nx_session *s){
    for(unsigned l=0;l<FIXTURE_LAYERS;l++){
        trace(l,"cache_k",nx_cache(s,l,0),nx_length(s),FIXTURE_KV);
        trace(l,"cache_v",nx_cache(s,l,1),nx_length(s),FIXTURE_KV);
    }
}
int main(void){
    nx_accel_io io;nx_accel_target_io(&io);nx_accel_program program={linear_words,sizeof(linear_words),0,LINEAR_CRC};
    int rc=nx_accel_init(&accelerator,&io,&program,2000000);report(1,0,rc);if(rc)goto fail;
    for(unsigned i=0;i<8192;i++)MM(0x20010000+4*i)=linear_data[i];
    fixture_weights(&weights);transport=(nx_coral_transport){.context=&accelerator,.wait=wait_tick};
    nx_linear_binding binding={.resolve=resolve,.execute=execute,.aq_address=0xac000000,.aq_bytes=4864,.sa_address=0xac00a000,.sa_bytes=76*4,.model_sealed=sealed};
    rc=nx_linear_bind(&accelerator,&binding,1u<<NX_CORAL_RVV);report(1,1,rc);if(rc)goto fail;
    MM(NX_BRIDGE_IRQ_ENABLE)=1;__asm__ volatile("li t0,0x880;csrs mie,t0;li t0,8;csrs mstatus,t0":::"t0","memory");
    nx_session *s=nx_init_static(&weights,(void *)0xb4050000,65536,(void *)0xa8000000,nx_kv_bytes(),(void *)0xac300000,nx_work_bytes());
    report(1,2,s!=0);report(1,3,nx_kv_bytes());if(!s)goto fail;
    nxr_coral_backend backend={.accelerator=&accelerator,.input=(void *)0xac010000,.output=(void *)0xac100000,.input_bytes=4864*4,.output_bytes=4864*4,.timeout_ticks=100000000};
    nx_bind_backend(s,&backend,nxr_coral_linear,dispatch,1);
    for(step=0;step<FIXTURE_TOKENS;step++){
        float *logits=(void *)0xac400000;
#ifdef NX_T19_BLOCK
        logits=0;
#endif
        rc=nx_forward(s,tokens+step,1,step,logits,trace);report(100+step,0,rc);report(100+step,1,nx_length(s));if(rc)goto fail;cache_trace(s);
    }
#ifndef NX_T19_BLOCK
#ifndef T19_SMOKE
    /* A tenth actual numerical append must fail before publishing logits or
     * touching KV. The following reset must erase logical visibility. */
    float *logits=(void *)0xac400000;logits[0]=123.0f;int32_t id=7;
    rc=nx_forward(s,&id,1,FIXTURE_CAPACITY,logits,trace);report(2,0,rc);report(2,1,nx_length(s));report(2,2,logits[0]==123.0f);
    uint64_t session;rc=nx_reset_session(&accelerator,2000000,&session);report(2,3,rc);nx_reset(s);report(2,4,nx_length(s));
    for(unsigned j=0;j<2;j++,step++){id=j?0:7;rc=nx_forward(s,&id,1,j,logits,trace);report(100+step,0,rc);report(100+step,1,nx_length(s));if(rc)goto fail;cache_trace(s);}
    logits[0]=123.0f;id=129;report(2,5,nx_forward(s,&id,1,2,logits,trace));report(2,6,logits[0]==123.0f);id=0;report(2,7,nx_forward(s,&id,1,1,logits,trace));
#endif
#endif
    double ticks[NX_TIMERS];uint64_t calls[NX_TIMERS];nx_profile(s,ticks,calls);
    for(unsigned i=0;i<NX_TIMERS;i++){report(4,2*i,(uint32_t)ticks[i]);report(4,2*i+1,(uint32_t)calls[i]);}
    report(1,4,dispatches);MM(0x10000020)=0;for(;;)__asm__ volatile("wfi");
fail:MM(0x10000020)=1;for(;;){}
}
