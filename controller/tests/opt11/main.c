#include "jobs.h"
extern int nx_swiglu(const float *,const float *,int,float *);
extern int nx_quantize(const float *,int,int,int8_t *,float *);
#include <string.h>
#define MM(a) (*(volatile uint32_t *)(uintptr_t)(a))
static nx_ce64_context ctx;
static nx_ce64_transport transport;
static uint32_t mode,stopped;
static void report(uint32_t g,uint32_t i,uint32_t v){MM(0x10000080)=g<<16|i;MM(0x10000084)=v;}
uint32_t trap_handler(uint32_t cause,uint32_t pc,uint32_t v){(void)v;
    if(cause==0x8000000bu){nx_ce64_irq(&ctx);return pc;}
    if(cause==0x80000007u)return pc;
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
    for(uint32_t i=0;i<bytes;i++){h=(h^*(volatile uint8_t *)(uintptr_t)(a+i))*16777619u;}
    return h;}
int main(void){
    nx_accel_io io;nx_accel_target_io(&io);nx_status status=nx_ce64_init(&ctx,&io,2000000);report(1,0,(uint32_t)status);
    if(status){MM(0x10000020)=1;for(;;){}}
    transport=(nx_ce64_transport){.context=&ctx,.wait=wait_tick};
    report(1,1,(uint32_t)nx_opt11_configure(&ctx,2));
    nx_opt11_job bad=jobs[0].job;nx_opt11_view bad_view={.valid=1};struct nx_stream_result bad_result;
    nx_call rejected=next();bad.k=0;
    report(1,2,(uint32_t)nx_opt11_run(&transport,&rejected,&bad,&bad_view,&bad_result));
    report(1,3,(uint32_t)ctx.base.sequence);
    bad=jobs[0].job;bad.aq=bad.gate;
    report(1,4,(uint32_t)nx_opt11_run(&transport,&rejected,&bad,&bad_view,&bad_result));
    report(1,5,bad_view.valid);
    __asm__ volatile("csrw mie,%0;csrsi mstatus,8"::"r"(0x880u):"memory");
    for(unsigned i=0;i<JOB_COUNT;i++){
        const struct test_job *j=&jobs[i];unsigned group=10+i;mode=j->fault;stopped=0;
        MM(0x100000a0)=(mode==9||mode==10)?5:mode;MM(0x100000a4)=mode==3?j->job.gate:j->job.aq;MM(0x100000a8)=j->job.aq;
        nx_call call=next();if(mode==5||mode==10)call.timeout_ticks=1000000;nx_opt11_view view={0};struct nx_stream_result result={0};report(group,20,1);uint64_t started=ticks();
        status=nx_opt11_configure(&ctx,j->mode==2?0:1);
        if(!status)status=nx_opt11_run(&transport,&call,&j->job,&view,&result);
        uint64_t elapsed=ticks()-started;report(group,21,1);
        report(group,0,(uint32_t)status);report(group,1,view.valid);report(group,2,(uint32_t)elapsed);report(group,3,(uint32_t)result.cycles);
        report(group,4,(uint32_t)result.payload_read);report(group,5,(uint32_t)result.payload_write);report(group,6,stopped);
        if(status==NX_OK){
            report(group,7,checksum(j->job.aq,((j->job.k+63)/64)*64));report(group,8,checksum(j->job.sa,((j->job.k+63)/64)*4));
            if(j->job.fp32)report(group,9,checksum(j->job.fp32,j->job.k*4));
            if(j->job.k==65){
                nx_call tail_call=next();struct nx_stream_request tail={.m=1,.n=4,.k=65};
                report(group,17,(uint32_t)nx_opt11_down(&transport,&tail_call,&view,&tail,&result));report(group,18,view.valid);
            }
            if(j->down){
                nx_call down_call=next();struct nx_stream_request request={.m=1,.n=4,.k=j->job.k,.source=j->w,.scales=j->sw,.bias=j->bias,.destination=j->y,.output_stride=16};
                nx_opt11_view stale=view;stale.epoch^=1;
                report(group,19,(uint32_t)nx_opt11_down(&transport,&down_call,&stale,&request,&result));
                started=ticks();status=nx_opt11_down(&transport,&down_call,&view,&request,&result);
                report(group,10,(uint32_t)status);report(group,11,(uint32_t)(ticks()-started));report(group,12,(uint32_t)result.cycles);report(group,13,checksum(j->y,16));
                report(group,14,(uint32_t)nx_opt11_down(&transport,&down_call,&view,&request,&result));
            }
        }else{
            report(group,15,view.valid);MM(0x100000a0)=0;mode=0;
            uint64_t session;status=nx_ce64_reset_session(&ctx,3000000,&session);report(group,16,(uint32_t)status);
            if(status){MM(0x10000020)=2;for(;;){}}
        }
    }
    report(2,0,ctx.base.state);report(2,1,MM(NX_BRIDGE_CONTROL));MM(0x10000020)=0;for(;;)__asm__ volatile("wfi");
}
