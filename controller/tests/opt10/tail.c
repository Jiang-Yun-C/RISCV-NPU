/* Private transport component coverage. Public API intentionally rejects K65-67.
 * CPU uses the production transport, with frozen prequantized input. */
#include "ce64_linear.h"
#include "tail_inputs.h"
#define MM(a) (*(volatile uint32_t *)(uintptr_t)(a))
static nx_ce64_context ctx;
static void report(unsigned g,unsigned i,unsigned v){MM(0x10000080)=g<<16|i;MM(0x10000084)=v;}
uint32_t trap_handler(uint32_t cause,uint32_t pc,uint32_t value){(void)value;if(cause==0x8000000bu){nx_ce64_irq(&ctx);return pc;}if(cause==0x80000007u)return pc;report(255,0,cause);MM(0x10000020)=99;for(;;){} }
static void wait_tick(void *p){(void)p;__asm__ volatile("wfi":::"memory");}
int main(void){
    nx_accel_io io;nx_accel_target_io(&io);io.tick_hz=125000000;
    int rc=nx_ce64_init(&ctx,&io,2000000);if(rc){MM(0x10000020)=1;for(;;){}}
    MM(NX_BRIDGE_IRQ_ENABLE)=1;__asm__ volatile("li t0,0x880;csrs mie,t0;li t0,8;csrs mstatus,t0":::"t0","memory");
    nx_ce64_transport transport={.context=&ctx,.wait=wait_tick};
    for(unsigned i=0;i<sizeof(tail_cases)/sizeof(tail_cases[0]);i++){
        const struct tail_case *f=tail_cases+i;
        for(unsigned z=0;z<f->m*128;z++)*(volatile unsigned char *)(uintptr_t)(0xac000000+z)=*(const unsigned char *)(uintptr_t)(f->aq+z);
        for(unsigned z=0;z<f->m*2;z++)MM(0xac00a000+4*z)=MM(f->sa+4*z);
        struct nx_stream_request r={.abi=0x4c4e3135,.size=96,.session_lo=ctx.base.session,.sequence_lo=i+1,.opcode=2,
            .m=f->m,.n=f->n,.k=f->k,.source=f->w,.destination=0xac100000,.scales=f->sw,.aq=0xac000000,.sa=0xac00a000,.output_stride=f->n*4};
        nx_call call={.api_version=2,.route=NX_CE64,.session=ctx.base.session,.sequence=i+1,.timeout_ticks=2000000};
        struct nx_stream_result result;ctx.base.state=NX_ACCEL_RUNNING;
        rc=nx_ce64_linear_execute(&transport,&call,&r,&result);report(400+i,0,rc);
        if(rc){MM(0x10000020)=2;for(;;){}}
        MM(CE64_MMIO_BASE+CE64_ACK)=ctx.acquired_generation;__asm__ volatile("fence iorw,iorw":::"memory");
        MM(NX_BRIDGE_CONTROL)=0;__asm__ volatile("fence iorw,iorw":::"memory");ctx.base.state=NX_ACCEL_IDLE;
        for(unsigned z=0;z<f->m*f->n;z++)report(400+i,100+z,MM(0xac100000+4*z));
    }
    MM(0x10000020)=0;for(;;)__asm__ volatile("wfi");
}
