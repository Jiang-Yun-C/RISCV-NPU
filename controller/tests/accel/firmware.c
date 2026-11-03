#include "accel.h"
#include "probe_image.h"
#define MM(a) (*(volatile uint32_t *)(uintptr_t)(a))
#define INPUT 0xac000000u
#define OUTPUT 0xba000000u
static nx_context ctx;
static volatile uint32_t irq_count;
static void report(unsigned group,unsigned item,uint32_t value){MM(0x10000080)=(group<<16)|item;MM(0x10000084)=value;}
uint32_t trap_handler(uint32_t cause,uint32_t pc,uint32_t value){
    (void)value;
    if(cause==0x8000000b){irq_count++;nx_accel_irq(&ctx);return pc;}
    report(999,0,cause);MM(0x10000020)=0xdead0013;for(;;){}
}
static void mode(unsigned m){MM(0x100000a0)=m;__asm__ volatile("fence iorw,iorw":::"memory");}
static nx_call call(void){return (nx_call){.api_version=1,.route=NX_CORAL_RVV,.session=ctx.session,.sequence=ctx.sequence+1,.timeout_ticks=100000};}
static void fill(unsigned salt){for(unsigned i=0;i<16;i++){MM(INPUT+4*i)=0x12340000u+salt*0x100u+i;MM(OUTPUT+4*i)=0xdeadbeefu;}}
int main(void){
    nx_accel_io io;nx_accel_target_io(&io);
    nx_accel_program p={probe_words,sizeof(probe_words),0,PROBE_CRC};
    nx_status s=nx_accel_init(&ctx,&io,&p,100000);report(1,0,(uint32_t)s);report(1,1,(uint32_t)ctx.session);
    if(s){MM(0x10000020)=1;for(;;){}}
    MM(NX_BRIDGE_IRQ_ENABLE)=1;
    __asm__ volatile("li t0,0x800;csrs mie,t0;li t0,8;csrs mstatus,t0":::"t0","memory");
    nx_accel_job j={1,NX_ACCEL_PROBE,INPUT,OUTPUT,16,0x55aa12efu};
    nx_stats stats,query;
    /* Native 32->128 lane/strobe checks at all four lanes, plus byte/halfword. */
    for(unsigned i=0;i<4;i++)MM(0x20010200+4*i)=0x12345600u+i;
    *(volatile uint8_t *)(uintptr_t)0x20010205=0xab;
    *(volatile uint16_t *)(uintptr_t)0x2001020a=0xcdef;
    for(unsigned i=0;i<4;i++)report(2,i,MM(0x20010200+4*i));
    /* Reject without a launch, output write, or sequence consumption. */
    for(unsigned k=0;k<8;k++){
        nx_accel_job bad=j;nx_call c=call();
        switch(k){case 0:bad.output=0x80000000;break;case 1:bad.words=0xffffffffu;break;
          case 2:bad.opcode=7;break;case 3:bad.words=17;break;case 4:bad.input=INPUT+4;break;
          case 5:bad.output=INPUT;break;case 6:c.sequence=2;break;case 7:bad.abi=2;break;}
        s=nx_accel_run(&ctx,&c,&bad,&stats);report(3,k,(uint32_t)s);
    }
    report(3,8,(uint32_t)ctx.sequence);
    /* Modes are EXTERNAL test environment controls, absent from the driver ABI. */
    const unsigned modes[]={0,0,1,6,7,2,3,4,5,8,9,10};
    for(unsigned k=0;k<sizeof(modes)/sizeof(modes[0]);k++){
        unsigned group=10+k;mode(modes[k]);fill(k);nx_call c=call();
        if(modes[k]==3||modes[k]==10)c.timeout_ticks=10000;
        uint32_t before=irq_count;
        s=nx_accel_run(&ctx,&c,&j,&stats);
        report(group,0,(uint32_t)s);report(group,1,stats.output_valid);report(group,2,(uint32_t)stats.session);
        report(group,3,(uint32_t)stats.sequence);report(group,4,ctx.state);report(group,5,irq_count-before);
        report(group,6,(uint32_t)nx_wait(&ctx,c.session,c.sequence,&query));
        report(group,7,query.status==stats.status&&query.output_valid==stats.output_valid);
        report(group,8,stats.elapsed_ticks==stats.validate_ticks+stats.upload_ticks+stats.execute_ticks);
        if(s==0){for(unsigned i=0;i<16;i++)report(group,32+i,MM(OUTPUT+4*i));}
        else{
            nx_call again=call();report(group,9,(uint32_t)nx_accel_run(&ctx,&again,&j,&query));
            uint64_t session=0;
            if(modes[k]==10)report(group,10,(uint32_t)nx_reset_session(&ctx,300,&session));
            /* Keep the outstanding response under test control until it drains. */
            if(modes[k]!=10)mode(0);
            report(group,11,(uint32_t)nx_reset_session(&ctx,150000,&session));
            mode(0);report(group,12,(uint32_t)session);report(group,13,ctx.kv_valid);
            report(group,14,(uint32_t)nx_wait(&ctx,c.session,c.sequence,&query));
        }
    }
    mode(0);fill(99);nx_call c=call();s=nx_accel_run(&ctx,&c,&j,&stats);
    report(30,0,(uint32_t)s);report(30,1,(uint32_t)ctx.session);
    for(unsigned i=0;i<16;i++)report(30,32+i,MM(OUTPUT+4*i));
    /* Sealed model/tokenizer, aperture holes, unmapped addresses cannot write. */
    const uint32_t forbidden[]={0x80000000,0xb8000000,0xbc000000,0x20002000,0x20018000,0x10001000};
    for(unsigned i=0;i<6;i++){
        MM(forbidden[i])=0xabcdef01;__asm__ volatile("fence iorw,iorw":::"memory");
        report(40,i,MM(NX_BRIDGE_STATUS)&2);MM(NX_BRIDGE_CLEAR)=1;
    }
    mode(12);uint64_t session;
    report(41,0,(uint32_t)nx_reset_session(&ctx,100000,&session));
    report(41,1,ctx.state);mode(0);
    report(41,2,(uint32_t)nx_reset_session(&ctx,100000,&session));
    nx_caps caps;report(42,0,(uint32_t)nx_query_caps(&ctx,NX_CORAL_RVV,&caps));report(42,1,caps.operation_mask);
    report(42,2,irq_count);report(42,3,(uint32_t)ctx.session);
    MM(0x10000020)=0;for(;;)__asm__ volatile("wfi");
}
