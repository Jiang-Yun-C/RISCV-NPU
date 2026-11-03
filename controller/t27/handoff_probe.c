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
#include <stdint.h>
#define MM(a) (*(volatile uint32_t *)(uintptr_t)(a))

static nx_ce64_context context;
static nx_linear_binding binding;
static nx_ce64_transport transport;
static nxr_ce64_backend backend;
static void report(unsigned g,unsigned i,uint32_t v){MM(0x10000080)=(g<<16)|i;MM(0x10000084)=v;}
static void report64(unsigned g,unsigned i,uint64_t v){report(g,i,(uint32_t)v);report(g,i+1,(uint32_t)(v>>32));}
uint64_t nx_port_ticks(void){uint32_t h,l,h2;do{__asm__ volatile("csrr %0,mcycleh":"=r"(h));__asm__ volatile("csrr %0,mcycle":"=r"(l));__asm__ volatile("csrr %0,mcycleh":"=r"(h2));}while(h!=h2);return ((uint64_t)h<<32)|l;}
uint32_t trap_handler(uint32_t cause,uint32_t pc,uint32_t detail){(void)detail;if(cause==0x8000000bu){nx_ce64_irq(&context);return pc;}if(cause==0x80000007u)return pc;report(255,0,cause);report(255,1,pc);MM(0x10000020)=1;for(;;){}}
static void *resolve(void *p,uint32_t a,uint32_t n,int write){(void)p;(void)n;(void)write;return (void *)(uintptr_t)a;}
/* Scoped offline immutable fixture authority, never boot authentication. */
static int fixture_sealed(void *p,const nx_accel_linear *j){(void)p;uint32_t k=j->a.shape[1];return
 (k==896||k==4864)&&j->wq.address==(k==896?0x88001000u:0x88201000u)&&j->wq.allocation_bytes==8*k&&
 j->wq.shape[0]==8&&j->wq.shape[1]==k&&j->sw.address==(k==896?0x88010000u:0x88210000u)&&
 j->sw.allocation_bytes==8*(k/64)*4&&j->bias.address==0&&j->bias.allocation_bytes==0;}
#if T27_PARENT
#include "parent/nx_reference.c"
#else
#include "../firmware/runtime/reference/nx_reference.c"
#endif
static nx_session local={.requested_route=1,.in_flight=1,.backend_context=&backend,
   .private_vector_backend=nxr_ce64_vector_private,.private_backend=nxr_ce64_linear_private,
   .input_observer=nxr_ce64_input_v2,.private_swiglu_reservation=nxr_ce64_input_v2,
   .gate=(void *)0xac000000,.up=(void *)0xac020000,.logits=(void *)0xac040000,.b=(void *)0xac060000};
int main(void){
 /* Test guard setup outside the measured API; same stores in every arm. */
 for(volatile uint32_t *g=(volatile uint32_t *)0x21000;g<(volatile uint32_t *)0x22000;g++)*g=0xa5a5a5a5;
 nx_accel_io io;nx_accel_target_io(&io);io.tick_hz=125000000;
 int rc=nx_ce64_init(&context,&io,2000000);report(1,0,rc);
 transport=(nx_ce64_transport){.context=&context};
 binding=(nx_linear_binding){.cookie=&transport,.resolve=resolve,.execute=nx_ce64_linear_execute,.model_sealed=fixture_sealed,
  .aq_address=0xba1c0000,.aq_bytes=4*4864,.sa_address=0xba1c5000,.sa_bytes=4*304};
 if(!rc)rc=nx_ce64_bind(&context,&binding);report(1,1,rc);
 if(!rc)rc=nx_opt12_configure(&context,1);report(1,2,rc);
 if(rc){MM(0x10000020)=2;for(;;){}}
 backend=(nxr_ce64_backend){.accelerator=&context,.input=(void *)0xba100000,.output=(void *)0xba120000,
  .input_bytes=4*4864*4,.output_bytes=151936*4,.timeout_ticks=50000000,.vector_mask=15,
  .private_output_address=0xac000000,.private_output_bytes=835072,.producer_aq=0xba1d0000,.producer_sa=0xba1d1400};
 __asm__ volatile("csrw mie,%0;csrsi mstatus,8"::"r"(0x880u):"memory");
 unsigned rows=MM(0xb4080000),k=4864;

 nx_session *s=&local;float *activation=s->logits;nx_trace trace=0;
 nx_matrix matrix={(void *)0x88201000u,(void *)0x88210000u,0,8,k};
 uint64_t start=nx_port_ticks();
 rc=input_next(s);
        if(NX_OPT08_REUSE&&s->requested_route&&s->private_vector_backend&&
           s->private_swiglu_reservation&&!trace&&(rows==1||(!T27_PARENT&&T27_M4_HANDOFF))&&F==4864&&activation==s->logits)
            s->private_swiglu_reservation(s->backend_context,activation,rows,F,s->input_version);
 if(!rc)rc=dispatched_vector(s,0,s->gate,s->up,rows,k,activation);
#if T27_OBSERVE
 uint64_t producer_end=nx_port_ticks();
#endif
 if(!rc)rc=dispatched_linear(s,activation,rows,&matrix,s->b);
 uint64_t finish=nx_port_ticks();
 report(10,0,rc);report64(10,1,finish-start);
#if T27_OBSERVE
 report64(10,3,producer_end-start);report64(10,5,finish-producer_end);
#endif
 report(10,7,context.base.state);report(10,8,(uint32_t)context.base.sequence);report(10,9,backend.lease_valid);
 report64(10,10,backend.swiglu_quantized_handoffs);report64(10,12,backend.sfu_calls);report64(10,14,backend.sfu_cycles);report64(10,16,backend.backend_cycles);
 if(rc){MM(0x10000020)=3;for(;;){}}
 MM(0x10000020)=0;for(;;)__asm__ volatile("wfi");
}
