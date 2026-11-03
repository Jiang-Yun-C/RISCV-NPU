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
#if CASE_Q
#define CASE_K 896u
#define CASE_W 0x889f2200u
#define CASE_SW 0x88ab6200u
#define CASE_BIAS 0x88ac2600u
#else
#define CASE_K 4864u
#define CASE_W 0x894a5200u
#define CASE_SW 0x898cd200u
#define CASE_BIAS 0u
#endif
static nx_ce64_context context;
static nx_linear_binding binding;
static nx_ce64_transport transport;
static nxr_ce64_backend backend;
static volatile uint32_t fixture_data_anchor=1;
static void report(unsigned g,unsigned i,uint32_t v){MM(0x10000080)=(g<<16)|i;MM(0x10000084)=v;}
static void report64(unsigned g,unsigned i,uint64_t v){report(g,i,(uint32_t)v);report(g,i+1,(uint32_t)(v>>32));}
uint64_t nx_port_ticks(void){uint32_t h,l,h2;do{__asm__ volatile("csrr %0,mcycleh":"=r"(h));__asm__ volatile("csrr %0,mcycle":"=r"(l));__asm__ volatile("csrr %0,mcycleh":"=r"(h2));}while(h!=h2);return ((uint64_t)h<<32)|l;}
uint32_t trap_handler(uint32_t cause,uint32_t pc,uint32_t detail){(void)detail;if(cause==0x8000000bu){nx_ce64_irq(&context);return pc;}if(cause==0x80000007u)return pc;report(255,0,cause);report(255,1,pc);MM(0x10000020)=1;for(;;){}}
static void *resolve(void *p,uint32_t a,uint32_t n,int write){(void)p;(void)n;(void)write;return (void *)(uintptr_t)a;}
/* Exact postload slice authority, independently checked from the real pack.
 * It authorizes neither authenticated loading nor startup/service operation. */
static int fixture_sealed(void *p,const nx_accel_linear *j){(void)p;return
 j->wq.address==CASE_W&&j->wq.allocation_bytes==129u*CASE_K&&j->wq.shape[0]==129&&j->wq.shape[1]==CASE_K&&
 j->sw.address==CASE_SW&&j->sw.allocation_bytes==129u*(CASE_K/64u)*4u&&j->bias.address==CASE_BIAS&&j->bias.allocation_bytes==(CASE_BIAS?129u*4u:0u);}
int main(void){
 if(fixture_data_anchor!=1){MM(0x10000020)=2;for(;;){}}
 nx_accel_io io;nx_accel_target_io(&io);io.tick_hz=125000000;
 int rc=nx_ce64_init(&context,&io,2000000);report(1,0,rc);
 transport=(nx_ce64_transport){.context=&context};
 binding=(nx_linear_binding){.cookie=&transport,.resolve=resolve,.execute=nx_ce64_linear_execute,.model_sealed=fixture_sealed,
  .aq_address=0xba1c0000,.aq_bytes=4*4864,.sa_address=0xba1c5000,.sa_bytes=4*304};
 if(!rc)rc=nx_ce64_bind(&context,&binding);
 report(1,1,rc);
 if(!rc)rc=nx_opt12_configure(&context,1);
 report(1,2,rc);
 if(rc){MM(0x10000020)=3;for(;;){}}
 backend=(nxr_ce64_backend){.accelerator=&context,.input=(void *)0xba100000,.output=(void *)0xba120000,
  .input_bytes=4*4864*4,.output_bytes=151936*4,.timeout_ticks=900000000,.vector_mask=15,
  .private_output_address=0xac000000,.private_output_bytes=835072,.producer_aq=0xba1d0000,.producer_sa=0xba1d1400};
 const float *x=(void *)0xac000000;float *y=(void *)0xac010000;
 nx_matrix matrix={(void *)(uintptr_t)CASE_W,(void *)(uintptr_t)CASE_SW,(void *)(uintptr_t)CASE_BIAS,129,CASE_K};
 nxr_ce64_input_v2(&backend,x,1,CASE_K,1);
 __asm__ volatile("csrw mie,%0;csrsi mstatus,8"::"r"(0x880u):"memory");
 uint64_t start=nx_port_ticks();
 rc=nxr_ce64_linear_private(&backend,x,1,&matrix,y);
 uint64_t end=nx_port_ticks();
 report(2,0,rc);report64(2,1,end-start);report(2,3,context.base.state);report(2,4,(uint32_t)context.base.sequence);
 report64(2,5,start);report64(2,7,end);
 const uint64_t counts[]={backend.calls,backend.completed,backend.sfu_calls,backend.backend_cycles,backend.sfu_cycles,
 backend.staging_bytes,backend.staging_saved_bytes,backend.output_copy_bytes,backend.private_output_saved_bytes,
 backend.producer_direct_aq_bytes,backend.producer_direct_sa_bytes,backend.producer_sa_copy_bytes,backend.staging_ticks};
 for(unsigned i=0;i<sizeof(counts)/sizeof(counts[0]);i++)report64(3,2*i,counts[i]);
 MM(0x10000020)=rc?4:0;for(;;)__asm__ volatile("wfi");
}
