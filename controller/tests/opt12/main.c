#include "jobs.h"
extern int nx_opt12_attention_probe(int);
#define MM(a) (*(volatile uint32_t *)(uintptr_t)(a))
static nx_ce64_context ctx;static nx_ce64_transport transport;
static uint32_t mode,stopped;
static void report(uint32_t g,uint32_t i,uint32_t v){MM(0x10000080)=g<<16|i;MM(0x10000084)=v;}
uint32_t trap_handler(uint32_t cause,uint32_t pc,uint32_t v){(void)v;
    if(cause==0x8000000bu){nx_ce64_irq(&ctx);return pc;}if(cause==0x80000007u)return pc;
    report(255,0,cause);report(255,1,pc);MM(0x10000020)=cause;for(;;){}
}
static void wait_tick(void *p){(void)p;
    if((mode==9||mode==10)&&!stopped&&MM(CE64_MMIO_BASE+CE64_OUTSTANDING)){
        MM(CE64_MMIO_BASE+CE64_CONTROL)=mode==9?CE64_CTL_ISOLATE:CE64_CTL_RESET_REQUEST;stopped=1;
    }
}
static nx_call next(void){return (nx_call){.api_version=2,.route=NX_CE64,.session=ctx.base.session,.sequence=ctx.base.sequence+1,.timeout_ticks=100000000};}
static uint64_t ticks(void){return ctx.base.io.ticks(ctx.base.io.cookie);}
static uint32_t checksum(uint32_t a,uint32_t bytes){uint32_t h=2166136261u;
    for(uint32_t i=0;i<bytes;i++){h=(h^*(volatile uint8_t *)(uintptr_t)(a+i))*16777619u;}return h;}
int main(void){
    nx_accel_io io;nx_accel_target_io(&io);nx_status status=nx_ce64_init(&ctx,&io,2000000);report(1,0,(uint32_t)status);
    if(status){MM(0x10000020)=1;for(;;){}}
    transport=(nx_ce64_transport){.context=&ctx,.wait=wait_tick};
    report(1,1,(uint32_t)nx_opt12_configure(&ctx,2));
    nx_opt12_job bad=jobs[0].job;nx_opt12_view invalid={.valid=1};struct nx_stream_result invalid_result;nx_call rejected=next();
    bad.k=0;report(1,2,(uint32_t)nx_opt12_run(&transport,&rejected,&bad,&invalid,&invalid_result));report(1,3,(uint32_t)ctx.base.sequence);
    bad=jobs[0].job;bad.fp32=bad.gate+16;report(1,4,(uint32_t)nx_opt12_run(&transport,&rejected,&bad,&invalid,&invalid_result));report(1,5,invalid.valid);
    __asm__ volatile("csrw mie,%0;csrsi mstatus,8"::"r"(0x880u):"memory");
    nx_opt12_view previous={0};
    for(unsigned i=0;i<JOB_COUNT;i++){
        const struct test_job *j=&jobs[i];unsigned group=10+i;mode=j->fault;stopped=0;
        MM(0x100000a0)=(mode==9||mode==10)?5:mode;MM(0x100000a4)=mode==3?j->job.gate:(j->job.aq?j->job.aq:j->job.fp32);MM(0x100000a8)=j->job.aq?j->job.aq:j->job.fp32;
        nx_call call=next();if(mode==5||mode==10)call.timeout_ticks=1000000;
        nx_opt12_view view={0};struct nx_stream_result result={0};report(group,20,1);uint64_t started=ticks();
        status=nx_opt12_configure(&ctx,j->hardware);
        if(!status)status=nx_opt12_run(&transport,&call,&j->job,&view,&result);
        uint64_t elapsed=ticks()-started;report(group,21,1);
        report(group,0,(uint32_t)status);report(group,1,view.valid);report(group,2,(uint32_t)elapsed);report(group,3,(uint32_t)result.cycles);
        report(group,4,(uint32_t)result.payload_read);report(group,5,(uint32_t)result.payload_write);report(group,6,stopped);
        if(status==NX_OK){
            report(group,15,(uint32_t)nx_opt12_acquire(&ctx,&view));
            if(previous.valid)report(group,16,(uint32_t)nx_opt12_acquire(&ctx,&previous));
            previous=view;
            if(j->job.aq)report(group,7,checksum(j->job.aq,((j->job.k+63)/64)*64));
            if(j->job.sa)report(group,8,checksum(j->job.sa,((j->job.k+63)/64)*4));
            if(j->job.fp32)report(group,9,checksum(j->job.fp32,(j->job.mode==5||j->job.mode==6)?4:j->job.k*4));
            if(j->down){
                nx_call down_call=next();struct nx_stream_request request={.m=1,.n=4,.k=j->job.k,.source=j->w,.scales=j->sw,.bias=j->bias,.destination=j->y,.output_stride=16};
                started=ticks();status=nx_opt11_down(&transport,&down_call,&view.quantized,&request,&result);
                report(group,10,(uint32_t)status);report(group,11,(uint32_t)(ticks()-started));report(group,12,(uint32_t)result.cycles);report(group,13,checksum(j->y,16));
                report(group,14,(uint32_t)nx_opt11_down(&transport,&down_call,&view.quantized,&request,&result));
            }
        }else{
            report(group,15,view.valid);MM(0x100000a0)=0;mode=0;previous.valid=0;
            uint64_t session;status=nx_ce64_reset_session(&ctx,3000000,&session);report(group,16,(uint32_t)status);
            if(status){MM(0x10000020)=2;for(;;){}}
        }
    }
#if OPT12_LONG
    for(unsigned p=0;p<2;p++){
        uint64_t begin=ticks();int rc=nx_opt12_attention_probe(p?255:127);
        report(3,p*3,(uint32_t)rc);report(3,p*3+1,(uint32_t)(ticks()-begin));
        report(3,p*3+2,checksum(0xaf002000,896*4));
    }
#endif
    report(2,0,ctx.base.state);report(2,1,MM(NX_BRIDGE_CONTROL));MM(0x10000020)=0;for(;;)__asm__ volatile("wfi");
}
