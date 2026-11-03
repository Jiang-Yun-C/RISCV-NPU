#include "ce64_linear.h"
#include "fixture_jobs.h"
#ifdef NX_CE_BOARD_BOOT
#include "ce64_board_boot.h"
#endif

#define MM(a) (*(volatile uint32_t *)(uintptr_t)(a))
#ifdef NX_CE_BOARD_BOOT
uint32_t ce_board_profile;
#endif
static nx_ce64_context cectx;
#define ctx (cectx.base)
static nx_ce64_transport transport;
static volatile uint32_t irq_count,timer_count;
static uint32_t mode,stop_requested;
static uint32_t pressure,pressure_cursor,pressure_errors;
#ifdef NX_CE_BOARD_BOOT
static uint32_t competition_cursor,competition_errors,competition_active;
/* Caller-owned, read-only input view. The original DDR tensor is written and
 * independently read back before this tag is published. No output/model data
 * is cached here; each new fill invalidates the previous input version. */
static uint32_t input_read_view[8*896] __attribute__((aligned(16)));
static uint32_t input_read_address,input_read_bytes,input_read_valid;
#endif
static void report(uint32_t group,uint32_t item,uint32_t value){MM(0x10000080)=group<<16|item;MM(0x10000084)=value;}
uint32_t trap_handler(uint32_t cause,uint32_t pc,uint32_t value){
    (void)value;
    if(cause==0x8000000bu){irq_count++;nx_ce64_irq(&cectx);return pc;}
    if(cause==0x80000007u){timer_count++;return pc;}
    report(255,0,cause);report(255,1,pc);MM(0x10000020)=cause?cause:1;for(;;){}
}
static void wait_tick(void *cookie){
    (void)cookie;
    if(pressure){
        uint32_t address=0xb4200000u+4*(pressure_cursor++&255u);
        uint32_t expected=address^0xa5a55a5au;
        if(MM(address)!=expected)pressure_errors++;
        MM(address)=expected;
    }
#ifdef NX_CE_BOARD_BOOT
    if(competition_active){
        uint32_t address=0xb4000000u+4*(competition_cursor++&16383u);
        uint32_t expected=address^0xa5a55a5au;
        if(MM(address)!=expected)competition_errors++;
        MM(address)=expected;
        return;
    }
#endif
    if(mode==9){
        if(!stop_requested && MM(CE64_MMIO_BASE+CE64_OUTSTANDING)){
            MM(CE64_MMIO_BASE+CE64_CONTROL)=CE64_CTL_ISOLATE;
            __asm__ volatile("fence iorw,iorw":::"memory");stop_requested=1;
        }
        return;
    }
    if(!pressure)__asm__ volatile("wfi":::"memory");
}
static void *resolve(void *cookie,uint32_t address,uint32_t bytes,int write){
    (void)cookie;
#ifdef NX_CE_BOARD_BOOT
    if(!write&&input_read_valid&&address==input_read_address&&bytes==input_read_bytes)return input_read_view;
#else
    (void)bytes;(void)write;
#endif
    return (void *)(uintptr_t)address;
}
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
    if(mode==8)r.reserved[0]=0xba200000u;
    if(mode==6)r.reserved[1]=1; /* corrupt descriptor in transit, observed by RTL */
    if(mode==7)r.opcode=99; /* backend rejects an unsupported private opcode */
    return nx_ce64_linear_execute(&transport,call,&r,result);
}
static nx_call next(uint64_t timeout){return (nx_call){.api_version=2,.route=NX_CE64,.session=ctx.session,.sequence=ctx.sequence+1,.timeout_ticks=timeout};}
static void fill(const struct fixture_job *f){
    const uint32_t *x=(const uint32_t *)(uintptr_t)f->input_source;uint32_t *a=(uint32_t *)(uintptr_t)f->job.a.address;
#ifdef NX_CE_BOARD_BOOT
    input_read_valid=0;
    int keep=f->job.a.allocation_bytes<=sizeof(input_read_view);
#endif
    for(unsigned i=0;i<f->job.a.allocation_bytes/4;i++){
        uint32_t value=x[i];a[i]=value;
#ifdef NX_CE_BOARD_BOOT
        if(keep)input_read_view[i]=value;
#endif
    }
#ifdef NX_CE_BOARD_BOOT
    __asm__ volatile("fence iorw,iorw":::"memory");
    if(keep){
        for(unsigned i=0;i<f->job.a.allocation_bytes/4;i++)if(MM(f->job.a.address+4*i)!=input_read_view[i]){
            report(255,0,0x494e5054u);report(255,1,f->job.a.address+4*i);MM(0x10000020)=6;for(;;){}
        }
        __asm__ volatile("fence iorw,iorw":::"memory");
        input_read_address=f->job.a.address;input_read_bytes=f->job.a.allocation_bytes;input_read_valid=1;
    }
#endif
    for(unsigned i=0;i<f->job.y.allocation_bytes/4;i++)MM(f->job.y.address+4*i)=0xa5a5a5a5;
}
#ifdef NX_CE_BOARD_BOOT
static uint64_t board_ticks(void){
    uint32_t hi,lo,again;
    do{hi=MM(0x1000000c);lo=MM(0x10000008);again=MM(0x1000000c);}while(hi!=again);
    return (uint64_t)hi<<32|lo;
}
static void telemetry(void){
    nx_ce64_board_telemetry();
}
static void pressure(void){
    const struct fixture_job *f=&fixture_jobs[0];
    for(unsigned i=0;i<16384;i++)MM(0xb4000000u+4*i)=(0xb4000000u+4*i)^0xa5a55a5au;
    competition_active=1;
    uint64_t begin=board_ticks();uint32_t iteration=0;
    telemetry();report(4,0,0);
    do{
        fill(f);nx_call c=next(f->timeout);nx_stats stats;
        nx_status s=nx_linear_run_v2(&cectx,&c,&f->job,&stats);
        report(4,1,(uint32_t)s);report(4,2,stats.output_valid);
        if(s||!stats.output_valid||competition_errors){report(4,5,competition_errors);MM(0x10000020)=5;for(;;){}}
        for(unsigned z=0;z<f->job.y.allocation_bytes/4;z++){
            uint32_t actual=MM(f->job.y.address+4*z);MM(0x10000088)=z;MM(0x1000008c)=actual;
        }
        iteration++;report(4,3,iteration);
        if((iteration&127)==0)telemetry();
    }while(board_ticks()-begin<UINT64_C(450625000000));
    telemetry();report(4,4,iteration);
}
#endif
int main(void){
#ifdef NX_CE_BOARD_BOOT
    if(nx_ce64_board_load()){MM(0x10000020)=4;for(;;){}}
    ce_board_profile=MM(0x100000e8);
#endif
    nx_accel_io io;nx_accel_target_io(&io);io.tick_hz=125000000;
    nx_status s=nx_ce64_init(&cectx,&io,2000000);report(1,0,(uint32_t)s);report(1,1,(uint32_t)ctx.session);
    if(s){MM(0x10000020)=1;for(;;){}}
    transport=(nx_ce64_transport){.context=&cectx,.wait=wait_tick};
    nx_linear_binding binding={.resolve=resolve,.execute=execute,.aq_address=0xac000000,.aq_bytes=8*4864,.sa_address=0xac00a000,.sa_bytes=8*76*4,.model_sealed=sealed};
    s=nx_ce64_bind(&cectx,&binding);report(1,2,(uint32_t)s);
    MM(NX_BRIDGE_IRQ_ENABLE)=1;
    __asm__ volatile("li t0,0x880;csrs mie,t0;li t0,8;csrs mstatus,t0":::"t0","memory");
    nx_caps_v2 caps;report(1,3,(uint32_t)nx_query_caps_v2(&cectx,NX_CE64,&caps));report(1,4,caps.base.operation_mask);
    /* Invalid public views are rejected without a backend start or sequence. */
    for(unsigned i=0;i<4;i++){
        nx_linear bad=fixture_jobs[0].job;
        if(i==0)bad.y.address=0x80000000;
        if(i==1)bad.a.address+=4;
        if(i==2)bad.group_size=32;
        if(i==3)bad.y.allocation_bytes=1;
        nx_call c=next(2000000);nx_stats stats;s=nx_linear_run_v2(&cectx,&c,&bad,&stats);report(2,i,(uint32_t)s);
    }
    report(2,4,(uint32_t)ctx.sequence);
    for(unsigned i=0;i<FIXTURE_JOBS;i++){
        const struct fixture_job *f=&fixture_jobs[i];unsigned group=10+i;mode=f->mode;stop_requested=0;
        pressure=f->pressure;pressure_cursor=0;pressure_errors=0;
        if(pressure)for(unsigned z=0;z<256;z++){uint32_t a=0xb4200000u+4*z;MM(a)=a^0xa5a55a5au;}
        MM(0x100000a0)=mode;MM(0x100000a4)=mode==3?f->job.wq.address:f->job.y.address;MM(0x100000a8)=f->job.y.address+f->job.y.allocation_bytes-4;
        fill(f);nx_call c=next(f->timeout);nx_stats stats,last;uint32_t before=irq_count;
        report(group,20,1);s=nx_linear_run_v2(&cectx,&c,&f->job,&stats);report(group,21,1);
        report(group,0,(uint32_t)s);report(group,1,stats.output_valid);report(group,2,(uint32_t)stats.session);report(group,3,(uint32_t)stats.sequence);
        report(group,4,ctx.state);report(group,5,irq_count-before);report(group,6,(uint32_t)nx_ce64_wait(&cectx,c.session,c.sequence,&last));
        report(group,7,last.status==stats.status&&last.output_valid==stats.output_valid);
        report(group,8,(uint32_t)stats.elapsed_ticks);report(group,9,(uint32_t)stats.backend_cycles);
        report(group,22,(uint32_t)stats.validate_ticks);report(group,23,(uint32_t)stats.quantize_ticks);
        report(group,24,(uint32_t)stats.execute_ticks);report(group,25,stats.fallback_reason);
        report(group,26,pressure_cursor);report(group,27,pressure_errors);
        if(s==NX_OK){
            uint32_t sum=2166136261u;
            for(unsigned z=0;z<f->job.y.allocation_bytes/4;z++){
                uint32_t actual=MM(f->job.y.address+4*z);sum=(sum^actual)*16777619u;
#ifdef NX_CE_BOARD_BOOT
                MM(0x10000088)=z;MM(0x1000008c)=actual;
#endif
            }
            report(group,10,sum);report(group,11,f->job.y.allocation_bytes/4);
        }else{
            nx_call again=next(f->timeout);report(group,12,(uint32_t)nx_linear_run_v2(&cectx,&again,&f->job,&last));
            uint64_t session=0;
            if(mode==5)report(group,13,(uint32_t)nx_ce64_reset_session(&cectx,1000,&session));
            /* Leave an accepted late B alive until it genuinely returns. */
            MM(0x100000a0)=0;mode=0;s=nx_ce64_reset_session(&cectx,2000000,&session);
            report(group,14,(uint32_t)s);report(group,15,(uint32_t)session);report(group,16,ctx.kv_valid);
            report(group,17,(uint32_t)nx_ce64_wait(&cectx,c.session,c.sequence,&last));
            if(s){MM(0x10000020)=3;for(;;){}}
        }
    }
    report(3,0,irq_count);report(3,1,timer_count);report(3,2,(uint32_t)ctx.session);
#ifdef NX_CE_BOARD_BOOT
    if(ce_board_profile==2)pressure();
#endif
    MM(0x10000020)=0;
#ifdef NX_CE_BOARD_BOOT
    __asm__ volatile("csrw mie,zero;csrci mstatus,8":::"memory");
    /* A subsequent CRC-checked reset frame performs platform DDR recovery.
     * Stay in the real loader; no CPU-only reset can clear native quarantine. */
    for(;;)nx_ce64_board_load();
#else
    for(;;)__asm__ volatile("wfi");
#endif
}
