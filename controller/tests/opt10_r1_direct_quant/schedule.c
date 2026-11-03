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
    for(unsigned i=0;i<SCHEDULE_JOBS;i++){
        const struct schedule_job *j=&schedule_jobs[i];
        float *x=(void *)(uintptr_t)j->x,*up=(void *)(uintptr_t)j->up,*y=(void *)(uintptr_t)j->y;
        unsigned output=j->rows*(j->mode?j->k:j->n);
        for(unsigned z=0;z<output;z++)((uint32_t *)y)[z]=0xa5a5a5a5u;
        uint64_t direct_aq=backend.producer_direct_aq_bytes,direct_sa=backend.producer_direct_sa_bytes,sa_copy=backend.producer_sa_copy_bytes;
        uint64_t saved=backend.vector_output_saved_bytes,copied=backend.vector_output_copy_bytes,coeff=backend.vector_coefficient_copy_bytes;
        uint64_t start=nx_port_ticks(),before=backend.sfu_calls,sequence=c.base.sequence;
        backend.timeout_ticks=j->mode?100000000:20000000;
        if(j->mode){
            rc=nxr_ce64_vector_private(&backend,j->mode==1?7:j->mode==2?0:2,x,up,j->rows,j->k,y);
        }else{
            nx_matrix w={.q=(void *)(uintptr_t)j->w,.s=(void *)(uintptr_t)j->sw,.n=j->n,.k=j->k};
            nxr_ce64_input_v2(&backend,x,j->rows,j->k,i+1);
            rc=nxr_ce64_linear(&backend,x,j->rows,&w,y);
            /* Q/K/V-like reuse must consume the same versioned producer. */
            for(unsigned repeat=0;repeat<2&&!rc;repeat++)rc=nxr_ce64_linear(&backend,x,j->rows,&w,y);
        }
        report(10+i,0,rc);report(10+i,1,(uint32_t)(nx_port_ticks()-start));
        report(10+i,2,(uint32_t)(backend.sfu_calls-before));report(10+i,3,(uint32_t)(c.base.sequence-sequence));
        report(10+i,4,backend.lease_valid);
        report(10+i,5,(uint32_t)(backend.vector_output_saved_bytes-saved));
        report(10+i,6,(uint32_t)(backend.vector_output_copy_bytes-copied));
        report(10+i,7,(uint32_t)(backend.vector_coefficient_copy_bytes-coeff));
        report(10+i,8,(uint32_t)(backend.producer_direct_aq_bytes-direct_aq));
        report(10+i,9,(uint32_t)(backend.producer_direct_sa_bytes-direct_sa));
        report(10+i,10,(uint32_t)(backend.producer_sa_copy_bytes-sa_copy));
        if(rc){MM(0x10000020)=4;for(;;){}}
        for(unsigned z=0;z<output;z++)report(100+i,z,((uint32_t *)y)[z]);
    }
    report(2,0,c.base.state);report(2,1,MM(NX_BRIDGE_CONTROL));MM(0x10000020)=0;for(;;)__asm__ volatile("wfi");
}
