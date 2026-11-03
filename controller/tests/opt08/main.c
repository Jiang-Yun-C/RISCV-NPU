#include "ce64_backend.h"
#define NX_OK NX_ACCEL_OK
#define NX_LINEAR NX_ACCEL_LINEAR
#define NX_ROPE NX_ACCEL_ROPE
#define NX_SWIGLU NX_ACCEL_SWIGLU
#define nx_linear nx_accel_linear
#include "ce64_linear.h"
#undef nx_linear
#undef NX_SWIGLU
#undef NX_ROPE
#undef NX_LINEAR
#undef NX_OK
#include "inputs.h"
#include <string.h>
#define MM(a) (*(volatile uint32_t *)(uintptr_t)(a))
static nx_ce64_context ctx;static nx_ce64_transport transport;static nx_linear_binding binding;
static nxr_ce64_backend b;static unsigned mode;
uint64_t nx_port_ticks(void){uint32_t hi,lo,again;do{__asm__ volatile("csrr %0,mcycleh":"=r"(hi));__asm__ volatile("csrr %0,mcycle":"=r"(lo));__asm__ volatile("csrr %0,mcycleh":"=r"(again));}while(hi!=again);return (uint64_t)hi<<32|lo;}
static void report(unsigned g,unsigned i,unsigned v){MM(0x10000080)=g<<16|i;MM(0x10000084)=v;}
uint32_t trap_handler(uint32_t cause,uint32_t pc,uint32_t value){(void)value;if(cause==0x8000000bu){nx_ce64_irq(&ctx);return pc;}if(cause==0x80000007u)return pc;report(255,0,cause);report(255,1,pc);MM(0x10000020)=99;for(;;){} }
static void wait_tick(void *p){(void)p;__asm__ volatile("wfi":::"memory");}
static void *resolve(void *p,uint32_t a,uint32_t n,int write){(void)p;(void)n;(void)write;return (void *)(uintptr_t)a;}
static int sealed(void *p,const nx_accel_linear *j){(void)p;return j->wq.address==0x88000000||j->wq.address==0x88100000;}
int main(void){
    nx_accel_io io;nx_accel_target_io(&io);io.tick_hz=125000000;
    int rc=nx_ce64_init(&ctx,&io,2000000);if(rc){MM(0x10000020)=1;for(;;){}}
    transport=(nx_ce64_transport){.context=&ctx,.wait=wait_tick};
    binding=(nx_linear_binding){.cookie=&transport,.resolve=resolve,.execute=nx_ce64_linear_execute,.aq_address=0xac000000,.aq_bytes=8*4864,.sa_address=0xac00a000,.sa_bytes=8*76*4,.model_sealed=sealed};
    rc=nx_ce64_bind(&ctx,&binding);if(rc){MM(0x10000020)=2;for(;;){}}
    b=(nxr_ce64_backend){.accelerator=&ctx,.input=(float *)0xba100000,.output=(float *)0xba110000,.input_bytes=8*4864*4,.output_bytes=128,.timeout_ticks=20000000};
    MM(NX_BRIDGE_IRQ_ENABLE)=1;__asm__ volatile("li t0,0x880;csrs mie,t0;li t0,8;csrs mstatus,t0":::"t0","memory");
    unsigned previous=0,previous_m=0,previous_k=0,previous_direct=0,previous_offset=0;
    for(unsigned i=0;i<sizeof(cases)/sizeof(cases[0]);i++){
        const struct opt08_case *f=cases+i;unsigned g=100+f->id;
        if(f->reset==2){MM(0xac000000)=0xdeadbeef;nx_linear_input_invalidate(&binding);report(g,20,0);}
        if(f->reset==1){uint64_t session;rc=nx_ce64_reset_session(&ctx,2000000,&session);report(g,20,rc);if(rc){MM(0x10000020)=3;for(;;){}}}
        float *x=(float *)(uintptr_t)(f->direct?0xba300000:0xac400000);x+=f->offset;
        /* Keep the input pinned for repeated versions. Changed values always
         * receive a new version, even at the same physical address. */
        if(i==0||previous!=f->version||previous_m!=f->m||previous_k!=f->k||previous_direct!=f->direct||previous_offset!=f->offset){const float *raw=(float *)0xb4100000+f->offset;for(unsigned z=0;z<f->m*f->k;z++)x[z]=raw[z]*(float)f->sign;}
        previous=f->version;previous_m=f->m;previous_k=f->k;previous_direct=f->direct;previous_offset=f->offset;
        float *y=(float *)0xac100000;for(unsigned z=0;z<f->m*4;z++)((uint32_t *)y)[z]=0xa5a5a5a5;
        unsigned base=f->k==896?0x88000000:0x88100000;
        nx_matrix w={(const int8_t *)(uintptr_t)base,(float *)(uintptr_t)(base+0x10000),(float *)(uintptr_t)(base+0x11000),4,(int)f->k};
        mode=f->error;MM(0x100000a0)=mode;MM(0x100000a4)=base;MM(0x100000a8)=0xba110000+f->m*16-4;
        nxr_ce64_input_v2(&b,x,f->m,f->k,f->version);
        uint64_t start=nx_port_ticks();rc=nxr_ce64_linear(&b,x,f->m,&w,y);uint64_t elapsed=nx_port_ticks()-start;
        report(g,0,(uint32_t)rc);report(g,1,(uint32_t)elapsed);report(g,2,binding.input_cache.quantizations);report(g,3,binding.input_cache.hits);
        report(g,4,b.staging_bytes);report(g,5,b.staging_saved_bytes);report(g,6,ctx.base.session);report(g,7,ctx.base.sequence);
        if(rc){MM(0x100000a0)=0;mode=0;uint64_t session;int recovery=nx_ce64_reset_session(&ctx,2000000,&session);report(g,21,recovery);if(recovery){MM(0x10000020)=4;for(;;){}}}
        for(unsigned z=0;z<f->m*4;z++)report(g,100+z,((uint32_t *)y)[z]);
        MM(0x100000a0)=0;mode=0;
    }
    /* Reject partial aliases and unsupported K65 before touching output. */
    nx_matrix w={(int8_t *)0x88000000,(float *)0x88010000,(float *)0x88011000,4,896};
    nxr_ce64_input_v2(&b,0,0,0,0);
    report(200,0,nxr_ce64_linear(&b,b.input+1,1,&w,(float *)0xac100000));
    w.k=65;report(200,1,nxr_ce64_linear(&b,(float *)0xac400000,1,&w,(float *)0xac100000));
    report(200,2,b.calls);report(200,3,b.completed);report(200,4,(uint32_t)b.staging_ticks);report(200,5,(uint32_t)b.output_copy_ticks);
    report(200,6,nx_state_bytes());report(200,7,nx_work_bytes());report(200,8,nx_kv_bytes());
    MM(0x10000020)=0;for(;;)__asm__ volatile("wfi");
}
