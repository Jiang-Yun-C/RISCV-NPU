#include "ce64_backend.h"
#define NX_OK NX_ACCEL_OK
#define NX_LINEAR NX_ACCEL_LINEAR
#define NX_ROPE NX_ACCEL_ROPE
#define NX_SWIGLU NX_ACCEL_SWIGLU
#define nx_linear nx_accel_linear
#include "ce64_linear.h"
#include "opt12.h"
#undef nx_linear
#undef NX_SWIGLU
#undef NX_ROPE
#undef NX_LINEAR
#undef NX_OK
#include "schedule_jobs.h"
#define MM(a) (*(volatile uint32_t *)(uintptr_t)(a))
static nx_ce64_context c;
static nx_linear_binding binding;
static nx_ce64_transport transport;
static nxr_ce64_backend backend;
static void report(unsigned g,unsigned i,uint32_t v){MM(0x10000080)=(g<<16)|i;MM(0x10000084)=v;}
uint64_t nx_port_ticks(void){return c.base.io.ticks(c.base.io.cookie);}
uint32_t trap_handler(uint32_t cause,uint32_t pc,uint32_t value){
    (void)value;
    if(cause==0x8000000bu){nx_ce64_irq(&c);return pc;}
    if(cause==0x80000007u)return pc;
    report(255,0,cause);report(255,1,pc);MM(0x10000020)=1;for(;;){}
}
static void *resolve(void *p,uint32_t a,uint32_t n,int write){(void)p;(void)n;(void)write;return (void *)(uintptr_t)a;}
static int sealed(void *p,const nx_accel_linear *j){
    (void)p;
    for(unsigned i=0;i<SCHEDULE_JOBS;i++)if(!schedule_jobs[i].mode){
        const struct schedule_job *w=&schedule_jobs[i];
        if(j->wq.address==w->w&&j->wq.shape[0]==w->n&&j->wq.shape[1]==w->k&&j->sw.address==w->sw&&j->bias.address==0)return 1;
    }
    return 0;
}
int main(void){
    nx_accel_io io;nx_accel_target_io(&io);io.tick_hz=125000000;
    int rc=nx_ce64_init(&c,&io,2000000);report(1,0,rc);
    if(rc){MM(0x10000020)=2;for(;;){}}
    transport=(nx_ce64_transport){.context=&c};
    binding=(nx_linear_binding){.cookie=&transport,.resolve=resolve,.execute=nx_ce64_linear_execute,.model_sealed=sealed,
        .aq_address=0xba1c0000,.aq_bytes=4*4864,.sa_address=0xba1c5000,.sa_bytes=4*304};
    rc=nx_ce64_bind(&c,&binding);report(1,1,rc);if(rc){MM(0x10000020)=3;for(;;){}}
    rc=nx_opt12_configure(&c,1);report(1,2,rc);
    backend=(nxr_ce64_backend){.accelerator=&c,.input=(void *)0xba100000,.output=(void *)0xba120000,
        .input_bytes=4*4864*4,.output_bytes=151936*4,.timeout_ticks=20000000,.vector_mask=15,.private_output_address=0xae000000,.private_output_bytes=0x200000,.producer_aq=0xba1d0000,.producer_sa=0xba1d1400};
    __asm__ volatile("csrw mie,%0;csrsi mstatus,8"::"r"(0x880u):"memory");

    const struct schedule_job *j=&schedule_jobs[0];
    float *x=(void *)(uintptr_t)j->x,*y=(void *)(uintptr_t)j->y;
    nx_matrix w={.q=(void *)(uintptr_t)j->w,.s=(void *)(uintptr_t)j->sw,.n=j->n,.k=j->k};
    nxr_ce64_input_v2(&backend,x,1,j->k,1);
    rc=nxr_ce64_linear_private(&backend,x,1,&w,y);report(1,3,rc);report(1,4,((uint32_t *)y)[0]);
    if(rc){MM(0x10000020)=5;for(;;){}}
    for(unsigned s=0;s<10;s++){
        MM(0x100000a0)=0;
        uint64_t completed=backend.completed,saved=backend.private_output_saved_bytes;
        ((volatile uint32_t *)y)[0]=0xa5a5a5a5u;
        uint32_t old_epoch=c.epoch;
        nxr_ce64_input_v2(&backend,x,1,j->k,10+s);
        MM(0x100000a0)=30+s;
        rc=nxr_ce64_linear_private(&backend,x,1,&w,y);
        MM(0x100000a0)=0;
        report(10+s,0,(uint32_t)rc);report(10+s,1,(uint32_t)(backend.completed-completed));
        report(10+s,2,(uint32_t)(backend.private_output_saved_bytes-saved));
        report(10+s,3,((volatile uint32_t *)y)[0]);report(10+s,4,backend.lease_valid);
        if(!rc){MM(0x10000020)=6;for(;;){}}
        uint64_t session;rc=nx_ce64_reset_session(&c,2000000,&session);report(10+s,5,rc);
        if(!rc)rc=nx_ce64_bind(&c,&binding);
        if(!rc)rc=nx_opt12_configure(&c,1);
        nxr_ce64_input_v2(&backend,x,1,j->k,100+s);
        if(!rc)rc=nxr_ce64_linear_private(&backend,x,1,&w,y);
        report(10+s,6,rc);report(10+s,7,((uint32_t *)y)[0]);
        report(10+s,8,c.base.state);report(10+s,9,MM(NX_BRIDGE_CONTROL));
        report(10+s,10,old_epoch);report(10+s,11,c.epoch);
        report(10+s,12,(uint32_t)(backend.completed-completed));
        if(rc){MM(0x10000020)=7;for(;;){}}
    }
    report(2,0,c.base.state);report(2,1,MM(NX_BRIDGE_CONTROL));MM(0x10000020)=0;for(;;)__asm__ volatile("wfi");
}
