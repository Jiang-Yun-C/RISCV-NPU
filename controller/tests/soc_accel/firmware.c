#include "coral_linear.h"
#include "fixture_jobs.h"
#include "linear_image.h"
#define MM(a) (*(volatile uint32_t *)(uintptr_t)(a))
static nx_context ctx;
static nx_coral_transport transport;
static volatile uint32_t irq_count,timer_count;
static uint32_t mode;
static void report(uint32_t group,uint32_t item,uint32_t value){MM(0x10000080)=group<<16|item;MM(0x10000084)=value;}
uint32_t trap_handler(uint32_t cause,uint32_t pc,uint32_t value){
    (void)value;
    if(cause==0x8000000bu){irq_count++;nx_accel_irq(&ctx);return pc;}
    if(cause==0x80000007u){timer_count++;return pc;}
    report(255,0,cause);report(255,1,pc);MM(0x10000020)=cause?cause:1;for(;;){}
}
static void wait_tick(void *cookie){(void)cookie;__asm__ volatile("wfi":::"memory");}
static void *resolve(void *cookie,uint32_t address,uint32_t bytes,int write){(void)cookie;(void)bytes;(void)write;return (void *)(uintptr_t)address;}
static int sealed(void *cookie,const nx_linear *job){
    (void)cookie;
    /* The PRELOAD handoff verifies the T10 payload hashes and numeric seal.
     * RTL rejects every write to the weight partition. Trust only these exact
     * physical views, including dimensions, allocation and optional bias. */
    for(unsigned i=0;i<FIXTURE_JOBS;i++){
        const nx_linear *j=&fixture_jobs[i].job;
        if(job->wq.address==j->wq.address&&job->wq.allocation_bytes==j->wq.allocation_bytes&&job->wq.shape[0]==j->wq.shape[0]&&job->wq.shape[1]==j->wq.shape[1]&&
           job->sw.address==j->sw.address&&job->sw.allocation_bytes==j->sw.allocation_bytes&&job->bias.address==j->bias.address&&job->bias.allocation_bytes==j->bias.allocation_bytes)return 1;
    }
    return 0;
}
static nx_status execute(void *cookie,const nx_call *call,const struct nx_stream_request *request,struct nx_stream_result *result){
    (void)cookie;struct nx_stream_request r=*request;
    if(mode==6)r.reserved[1]=1; /* corrupt descriptor in transit, observed by RTL */
    if(mode==7)r.opcode=99; /* backend rejects an unsupported private opcode */
    return nx_coral_linear_execute(&transport,call,&r,result);
}
static nx_call next(uint64_t timeout){return (nx_call){.api_version=1,.route=NX_CORAL_RVV,.session=ctx.session,.sequence=ctx.sequence+1,.timeout_ticks=timeout};}
static void fill(const struct fixture_job *f){
    const uint32_t *x=(const uint32_t *)(uintptr_t)f->input_source;uint32_t *a=(uint32_t *)(uintptr_t)f->job.a.address;
    for(unsigned i=0;i<f->job.a.allocation_bytes/4;i++)a[i]=x[i];
    for(unsigned i=0;i<f->job.y.allocation_bytes/4;i++)MM(f->job.y.address+4*i)=0xa5a5a5a5;
}
int main(void){
    nx_accel_io io;nx_accel_target_io(&io);
    nx_accel_program p={linear_words,sizeof(linear_words),0,LINEAR_CRC};
    nx_status s=nx_accel_init(&ctx,&io,&p,2000000);report(1,0,(uint32_t)s);report(1,1,(uint32_t)ctx.session);
    if(s){MM(0x10000020)=1;for(;;){}}
    /* All DTCM initialization, including stack guards, is CPU native traffic. */
    for(unsigned i=0;i<8192;i++)MM(0x20010000+4*i)=linear_data[i];
    for(unsigned i=0;i<8192;i++)if(MM(0x20010000+4*i)!=linear_data[i]){MM(0x10000020)=2;for(;;){}}
    transport=(nx_coral_transport){.context=&ctx,.wait=wait_tick};
    nx_linear_binding binding={.resolve=resolve,.execute=execute,.aq_address=0xac000000,.aq_bytes=8*4864,.sa_address=0xac00a000,.sa_bytes=8*76*4,.model_sealed=sealed};
    s=nx_linear_bind(&ctx,&binding,1u<<NX_CORAL_RVV);report(1,2,(uint32_t)s);
    MM(NX_BRIDGE_IRQ_ENABLE)=1;
    __asm__ volatile("li t0,0x880;csrs mie,t0;li t0,8;csrs mstatus,t0":::"t0","memory");
    nx_caps caps;report(1,3,(uint32_t)nx_query_caps(&ctx,NX_CORAL_RVV,&caps));report(1,4,caps.operation_mask);
    /* Invalid public views are rejected without a backend start or sequence. */
    for(unsigned i=0;i<4;i++){
        nx_linear bad=fixture_jobs[0].job;
        if(i==0)bad.y.address=0x80000000;
        if(i==1)bad.a.address+=4;
        if(i==2)bad.group_size=32;
        if(i==3)bad.y.allocation_bytes=1;
        nx_call c=next(2000000);nx_stats stats;s=nx_linear_run(&ctx,&c,&bad,&stats);report(2,i,(uint32_t)s);
    }
    report(2,4,(uint32_t)ctx.sequence);
    for(unsigned i=0;i<FIXTURE_JOBS;i++){
        const struct fixture_job *f=&fixture_jobs[i];unsigned group=10+i;mode=f->mode;
        MM(0x100000a0)=mode;MM(0x100000a4)=mode==3?f->job.wq.address:f->job.y.address;MM(0x100000a8)=f->job.y.address+f->job.y.allocation_bytes-4;
        fill(f);nx_call c=next(f->timeout);nx_stats stats,last;uint32_t before=irq_count;
        report(group,20,1);s=nx_linear_run(&ctx,&c,&f->job,&stats);report(group,21,1);
        report(group,0,(uint32_t)s);report(group,1,stats.output_valid);report(group,2,(uint32_t)stats.session);report(group,3,(uint32_t)stats.sequence);
        report(group,4,ctx.state);report(group,5,irq_count-before);report(group,6,(uint32_t)nx_wait(&ctx,c.session,c.sequence,&last));
        report(group,7,last.status==stats.status&&last.output_valid==stats.output_valid);
        report(group,8,(uint32_t)stats.elapsed_ticks);report(group,9,(uint32_t)stats.backend_cycles);
        if(s==NX_OK){
            uint32_t sum=2166136261u;
            for(unsigned z=0;z<f->job.y.allocation_bytes/4;z++)sum=(sum^MM(f->job.y.address+4*z))*16777619u;
            report(group,10,sum);report(group,11,f->job.y.allocation_bytes/4);
        }else{
            nx_call again=next(f->timeout);report(group,12,(uint32_t)nx_linear_run(&ctx,&again,&f->job,&last));
            uint64_t session=0;
            if(mode==5)report(group,13,(uint32_t)nx_reset_session(&ctx,1000,&session));
            /* Leave an accepted late B alive until it genuinely returns. */
            MM(0x100000a0)=0;mode=0;s=nx_reset_session(&ctx,2000000,&session);
            report(group,14,(uint32_t)s);report(group,15,(uint32_t)session);report(group,16,ctx.kv_valid);
            report(group,17,(uint32_t)nx_wait(&ctx,c.session,c.sequence,&last));
            if(s){MM(0x10000020)=3;for(;;){}}
        }
    }
    report(3,0,irq_count);report(3,1,timer_count);report(3,2,(uint32_t)ctx.session);
    MM(0x10000020)=0;for(;;)__asm__ volatile("wfi");
}
