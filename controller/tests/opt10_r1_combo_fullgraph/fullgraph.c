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
#include <string.h>
#include "full_weights.h"
#include "opt10_norm_catalog.h"
#define MM(a) (*(volatile uint32_t *)(uintptr_t)(a))
static nx_ce64_context context;
static nx_linear_binding binding;
static nx_ce64_transport transport;
static nxr_ce64_backend backend;
static nx_weights weights;
static unsigned char state[32768] __attribute__((aligned(16)));
static uint32_t routes[3],fallbacks,dispatches;
static void report(unsigned g,unsigned i,uint32_t v){MM(0x10000080)=(g<<16)|i;MM(0x10000084)=v;}
static void report64(unsigned g,unsigned i,uint64_t v){report(g,i,(uint32_t)v);report(g,i+1,(uint32_t)(v>>32));}
uint64_t nx_port_ticks(void){
    uint32_t h,l,h2;
    do{__asm__ volatile("csrr %0,mcycleh":"=r"(h));__asm__ volatile("csrr %0,mcycle":"=r"(l));__asm__ volatile("csrr %0,mcycleh":"=r"(h2));}while(h!=h2);
    return (uint64_t)h<<32|l;
}
uint32_t trap_handler(uint32_t cause,uint32_t pc,uint32_t detail){
    (void)detail;
    if(cause==0x8000000bu){nx_ce64_irq(&context);return pc;}
    if(cause==0x80000007u)return pc;
    report(255,0,cause);report(255,1,pc);MM(0x10000020)=1;for(;;){}
}
static void *resolve(void *p,uint32_t a,uint32_t n,int write){(void)p;(void)n;(void)write;return (void *)(uintptr_t)a;}
static int same_matrix(const nx_accel_linear *j,const nx_matrix *m){
    return j->wq.address==(uintptr_t)m->q&&j->wq.allocation_bytes==(uint32_t)m->n*m->k&&
        j->wq.shape[0]==(uint32_t)m->n&&j->wq.shape[1]==(uint32_t)m->k&&
        j->sw.address==(uintptr_t)m->s&&j->sw.allocation_bytes==(uint32_t)m->n*(m->k/64)*4&&
        j->bias.address==(uintptr_t)m->bias&&j->bias.allocation_bytes==(m->bias?(uint32_t)m->n*4:0);
}
/* Post-load simulation fixture: the runner independently verifies the entire
 * frozen nxpack and preloads exact physical views. Accept only its immutable
 * matrix metadata. This is separate from authenticated boot/boot_ready and
 * cannot qualify either of those production gates. No arithmetic is stubbed. */
static int fixture_sealed(void *p,const nx_accel_linear *j){
    (void)p;
    if(same_matrix(j,&weights.embedding))return 1;
    for(unsigned l=0;l<24;l++){
        const nx_layer *w=&weights.layer[l];
        const nx_matrix *m[]={&w->q,&w->k,&w->v,&w->o,&w->gate,&w->up,&w->down};
        for(unsigned i=0;i<7;i++)if(same_matrix(j,m[i]))return 1;
    }
    return 0;
}
/* Postload model fixture authority, never production SD-loader authentication. */
static int fixture_norm_read(void *cookie,uint32_t address,uint32_t bytes,uint32_t k,uint32_t epoch,uint64_t session){
    if(cookie!=&transport||transport.context!=&context||context.binding!=&binding||
       binding.context!=&context.base||context.base.state!=NX_ACCEL_IDLE||
       context.epoch!=epoch||context.base.session!=session||!(MM(0x100000e0)&2)||
       !nx_opt10_norm_member(address,bytes,k)||(uintptr_t)weights.norm!=nx_opt10_norm_addresses[48])return 0;
    for(unsigned i=0;i<24;i++)if((uintptr_t)weights.layer[i].norm1!=nx_opt10_norm_addresses[2*i]||
       (uintptr_t)weights.layer[i].norm2!=nx_opt10_norm_addresses[2*i+1])return 0;
    return 1;
}
static void dispatch(void *p,int kind,int route,int reason,int rc,uint64_t ticks){
    (void)p;(void)kind;(void)rc;(void)ticks;
    dispatches++;if(route>=0&&route<3)routes[route]++;if(reason==2)fallbacks++;
}
int main(void){
    uintptr_t current_sp;__asm__ volatile("mv %0,sp":"=r"(current_sp));
    for(volatile uint32_t *p=(void *)0x20000;(uintptr_t)p<current_sp-512;p++)*p=0xa5a5a5a5u;
    load_full(&weights);
    nx_session *session=nx_init_static(&weights,state,sizeof(state),(void *)0xa8000000,15728640,(void *)0xac000000,835072);
    if(!session){MM(0x10000020)=2;for(;;){}}
    nx_accel_io io;nx_accel_target_io(&io);io.tick_hz=125000000;
    int rc=nx_ce64_init(&context,&io,2000000);report(1,0,rc);
    transport=(nx_ce64_transport){.context=&context};
    binding=(nx_linear_binding){.cookie=&transport,.resolve=resolve,.execute=nx_ce64_linear_execute,.model_sealed=fixture_sealed,.sealed_norm_read=fixture_norm_read,
        .aq_address=0xba1c0000,.aq_bytes=4*4864,.sa_address=0xba1c5000,.sa_bytes=4*304};
    if(!rc)rc=nx_ce64_bind(&context,&binding);
    report(1,1,rc);
    if(!rc)rc=nx_opt12_configure(&context,1);
    report(1,2,rc);
    if(rc){MM(0x10000020)=3;for(;;){}}
    backend=(nxr_ce64_backend){.accelerator=&context,.input=(void *)0xba100000,.output=(void *)0xba120000,
        .input_bytes=4*4864*4,.output_bytes=151936*4,.timeout_ticks=900000000,.vector_mask=15,
        .private_output_address=0xac000000,.private_output_bytes=835072,.producer_aq=0xba1d0000,.producer_sa=0xba1d1400};
    nx_bind_backend(session,&backend,nxr_ce64_linear,dispatch,2);
    nx_bind_input_observer(session,nxr_ce64_input_v2);
    nx_bind_vector_backend(session,nxr_ce64_vector);
    nx_bind_private_backend(session,nxr_ce64_linear_private);
    nx_bind_private_vector_backend(session,nxr_ce64_vector_private);
    __asm__ volatile("csrw mie,%0;csrsi mstatus,8"::"r"(0x880u):"memory");
    int32_t next=-1;
    uint64_t start=nx_port_ticks();
    rc=nx_forward_token_v2(session,FULLGRAPH_TOKEN,0,&next);
    uint64_t elapsed=nx_port_ticks()-start;
    report(2,0,rc);report64(2,1,elapsed);report(2,3,(uint32_t)next);
    report(2,4,context.base.state);report(2,5,MM(NX_BRIDGE_CONTROL));report(2,6,(uint32_t)nx_length(session));
    report(2,7,(uint32_t)(uintptr_t)nx_logits_v2(session));report(2,8,dispatches);report(2,9,routes[2]);report(2,10,fallbacks);
    if(rc){MM(0x10000020)=4;for(;;){}}
    const uint64_t values[]={backend.calls,backend.completed,backend.sfu_calls,backend.private_output_saved_bytes,
        backend.output_copy_bytes,backend.vector_output_saved_bytes,backend.vector_output_copy_bytes,
        backend.vector_coefficient_copy_bytes,backend.producer_direct_aq_bytes,backend.producer_direct_sa_bytes,
        backend.producer_sa_copy_bytes,backend.backend_cycles,backend.sfu_cycles,
        backend.vector_coefficient_direct_bytes,backend.vector_coefficient_saved_bytes};
    for(unsigned i=0;i<sizeof(values)/sizeof(values[0]);i++)report64(3,i*2,values[i]);
    for(int l=0;l<24;l++)for(int v=0;v<2;v++)report(4,l*2+v,(uint32_t)(uintptr_t)nx_cache(session,l,v));
    double ticks[NX_TIMERS];uint64_t calls[NX_TIMERS];nx_profile(session,ticks,calls);
    for(unsigned i=0;i<NX_TIMERS;i++){report64(5,i*4,(uint64_t)ticks[i]);report64(5,i*4+2,calls[i]);}
    unsigned bad=0;volatile uint32_t *p=(void *)0x20000;
    for(;p<(volatile uint32_t *)0x22000;p++)if(*p!=0xa5a5a5a5u)bad++;
    for(p=(void *)0x20000;p<(volatile uint32_t *)(current_sp-512)&&*p==0xa5a5a5a5u;p++){}
    report(6,0,bad);report(6,1,0x30000u-(uint32_t)(uintptr_t)p);report(6,2,(uint32_t)current_sp);
    MM(0x10000020)=bad?5:0;for(;;)__asm__ volatile("wfi");
}
