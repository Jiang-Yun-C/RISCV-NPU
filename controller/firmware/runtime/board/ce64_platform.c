#include "ce64_platform.h"
#include "boot_status.h"
#include "irq_events.h"
#include "opt10_norm_catalog.h"
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
static nx_ce64_context context;
static nx_ce64_transport transport;
static nx_linear_binding binding;
static const nx_weights *model;
#include "opt10_startup_zero.h"
static void *resolve(void *cookie,uint32_t address,uint32_t bytes,int write){
    (void)cookie;(void)bytes;(void)write;return (void *)(uintptr_t)address;
}
static int same_matrix(const nx_accel_linear *j,const nx_matrix *m){
    return j->wq.address==(uintptr_t)m->q&&j->wq.allocation_bytes==(uint32_t)m->n*m->k&&
        j->wq.shape[0]==(uint32_t)m->n&&j->wq.shape[1]==(uint32_t)m->k&&
        j->sw.address==(uintptr_t)m->s&&j->sw.allocation_bytes==(uint32_t)m->n*(m->k/64)*4&&
        j->bias.address==(uintptr_t)m->bias&&
        j->bias.allocation_bytes==(m->bias?(uint32_t)m->n*4:0);
}
static int sealed(void *cookie,const nx_accel_linear *job){
    (void)cookie;
    /* The new SD shell must seal BOTH the verified loader and hardware guard.
     * Only exact immutable T10 matrix views may bypass the numeric rescan. */
    if(!model||!nxr_boot_ready())return 0;
    if(same_matrix(job,&model->embedding))return 1;
    for(unsigned i=0;i<24;i++){
        const nx_layer *l=&model->layer[i];
        const nx_matrix *m[]={&l->q,&l->k,&l->v,&l->o,&l->gate,&l->up,&l->down};
        for(unsigned j=0;j<7;j++)if(same_matrix(job,m[j]))return 1;
    }
    return 0;
}
static int norm_model_matches(void){
    if(!model||(uintptr_t)model->norm!=nx_opt10_norm_addresses[48])return 0;
    for(unsigned i=0;i<24;i++)
        if((uintptr_t)model->layer[i].norm1!=nx_opt10_norm_addresses[2*i]||
           (uintptr_t)model->layer[i].norm2!=nx_opt10_norm_addresses[2*i+1])return 0;
    return 1;
}
static int sealed_norm_read(void *cookie,uint32_t address,uint32_t bytes,uint32_t k,uint32_t epoch,uint64_t session){
    if(cookie!=&transport||transport.context!=&context||context.binding!=&binding||
       binding.context!=&context.base||context.base.state!=NX_ACCEL_IDLE||
       context.epoch!=epoch||context.base.session!=session||!nxr_boot_ready())return 0;
    return nx_opt10_norm_member(address,bytes,k)&&norm_model_matches();
}
int nxr_ce64_platform_reset(void){
    uint64_t session;return nx_ce64_reset_session(&context,2000000,&session);
}
int nxr_ce64_platform_idle(void){return nx_ce64_idle_safe(&context);}
int nxr_ce64_platform_open(nxr_ce64_backend *b,const nx_weights *w){
    if(!b||!w)return NX_ARGUMENT;
    nx_accel_io io;nx_accel_target_io(&io);io.tick_hz=125000000;
    int rc=startup_reset_transport(&io);if(rc)return rc;
    model=w;transport=(nx_ce64_transport){.context=&context};
#if NX_APP_IRQ
    transport.wait=nx_irq_npu_wait;
#endif
    binding=(nx_linear_binding){.cookie=&transport,.resolve=resolve,
        .execute=nx_ce64_linear_execute,.model_sealed=sealed,.sealed_norm_read=sealed_norm_read,
        .aq_address=0xba1c0000,.aq_bytes=4*4864,.sa_address=0xba1c5000,.sa_bytes=4*304};
    rc=nx_ce64_bind(&context,&binding);if(rc)return rc;
    rc=nx_opt12_configure(&context,1);if(rc)return rc;
    *b=(nxr_ce64_backend){.accelerator=&context,.input=(float *)0xba100000,
        .output=(float *)0xba120000,.input_bytes=4*4864*4,.output_bytes=151936*4,
        .timeout_ticks=900000000,.vector_mask=15,
        .private_output_address=0xac000000,.private_output_bytes=835072,
        .kv_arena=0xa8000000,.kv_arena_bytes=15728640,.kv_model=w,
        .producer_aq=0xba1d0000,.producer_sa=0xba1d1400};
    return 0;
}
