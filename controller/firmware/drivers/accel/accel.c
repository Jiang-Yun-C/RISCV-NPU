#include "accel.h"
#include <stddef.h>
#include <limits.h>
/* Single-hart synchronous platform. Interrupt handlers only acknowledge IRQs;
 * they must not submit/initialize work. Reentry after acceptance returns EBUSY. */
static nx_context *owner;
static uint32_t rd(nx_context *c,uint32_t a){return c->io.read32(c->io.cookie,a);}
static void wr(nx_context *c,uint32_t a,uint32_t v){c->io.write32(c->io.cookie,a,v);}
static uint64_t now(nx_context *c){return c->io.ticks(c->io.cookie);}
static void barrier(nx_context *c){c->io.fence(c->io.cookie);}
static int expired(nx_context *c,uint64_t start,uint64_t limit){return now(c)-start>=limit;}
uint32_t nx_accel_crc32(const uint32_t *p,uint32_t bytes){
    uint32_t v=~0u;
    for(uint32_t i=0;i<bytes;i++){
        v^=(p[i/4]>>(8*(i%4)))&255u;
        for(unsigned b=0;b<8;b++)v=(v>>1)^(0xedb88320u& (0u-(v&1u)));
    }
    return ~v;
}
static int region(uint32_t address,uint64_t end,int output){
    if(end>UINT64_C(0x100000000)||end<=address)return 0;
    return (!output&&address>=0x80000000u&&end<=0xa8000000u)||
        (address>=0xa8000000u&&end<=0xac000000u)||
        (address>=0xac000000u&&end<=0xb4000000u)||
        (address>=0xba000000u&&end<=0xbc000000u);
}
nx_status nx_accel_validate_job(const nx_accel_job *j){
    if(!j)return NX_EINVAL;
    if(j->abi!=NX_ACCEL_ABI)return NX_EVERSION;
    if(!j->words)return NX_EINVAL;
    uint64_t bytes=(uint64_t)j->words*4;
    if(!region(j->input,(uint64_t)j->input+bytes,0)||!region(j->output,(uint64_t)j->output+bytes,1)||
       ((uint64_t)j->input<(uint64_t)j->output+bytes&&(uint64_t)j->output<(uint64_t)j->input+bytes))return NX_EBOUNDS;
    if((j->input|j->output)&15)return NX_EALIGN;
    if(j->opcode!=NX_ACCEL_PROBE||j->words>16)return NX_EUNSUPPORTED;
    return NX_OK;
}
static nx_status load(nx_context *c,uint64_t start,uint64_t limit){
    wr(c,NX_ACCEL_CONTROL,3);barrier(c);
    if(rd(c,NX_ACCEL_CONTROL)!=3)return NX_EIO;
    for(uint32_t i=0;i<c->program.bytes/4;i++){
        if(expired(c,start,limit))return NX_ETIMEOUT;
        wr(c,0x20000000u+4*i,c->program.words[i]);
    }
    barrier(c);
    for(uint32_t i=0;i<c->program.bytes/4;i++){
        if(expired(c,start,limit))return NX_ETIMEOUT;
        if(rd(c,0x20000000u+4*i)!=c->program.words[i])return NX_EIO;
    }
    wr(c,NX_ACCEL_ENTRY,c->program.entry);barrier(c);
    if(rd(c,NX_ACCEL_ENTRY)!=c->program.entry||(rd(c,NX_BRIDGE_STATUS)&6))return NX_EIO;
    return NX_OK;
}
static void clear_record(nx_context *c){for(unsigned i=0;i<8;i++)wr(c,NX_ACCEL_RESULT+4*i,0);}
nx_status nx_accel_init(nx_context *c,const nx_accel_io *io,const nx_accel_program *p,uint64_t timeout){
    if(!c||!io||!p||!p->words||!io->read32||!io->write32||!io->ticks||!io->fence||!io->tick_hz||!timeout)return NX_EINVAL;
    if(owner)return NX_EBUSY;
    if(!p->bytes||p->bytes>8192||(p->bytes|p->entry)&3||p->entry>=p->bytes)return NX_EBOUNDS;
    if(nx_accel_crc32(p->words,p->bytes)!=p->crc32)return NX_EIO;
    *c=(nx_context){.io=*io,.program=*p,.state=NX_ACCEL_FAULTED,.initialized=1};
    owner=c;
    uint64_t session;
    return nx_reset_session(c,timeout,&session);
}
nx_status nx_reset_session(nx_context *c,uint64_t timeout,uint64_t *session){
    if(!c||!c->initialized||!session||!timeout)return NX_EINVAL;
    if(c->state==NX_ACCEL_RUNNING||(owner&&owner!=c))return NX_EBUSY;
    if(c->session==UINT64_MAX)return NX_ESTATE;
    owner=c;c->state=NX_ACCEL_FAULTED;
    uint64_t start=now(c);
    /* Isolation blocks NEW transactions. Already accepted AW/W/R/B stay alive. */
    wr(c,NX_BRIDGE_CONTROL,3);barrier(c);
    while(!(rd(c,NX_BRIDGE_STATUS)&1))if(expired(c,start,timeout))return NX_ETIMEOUT;
    wr(c,NX_ACCEL_CONTROL,3);barrier(c);
    wr(c,NX_BRIDGE_CLEAR,1);wr(c,NX_BRIDGE_IRQ,1);
    nx_status s=load(c,start,timeout);
    if(s)return s;
    clear_record(c);barrier(c);
    if(expired(c,start,timeout))return NX_ETIMEOUT;
    if(rd(c,NX_BRIDGE_STATUS)&6)return NX_EIO;
    wr(c,NX_BRIDGE_CONTROL,0);barrier(c);
    if(rd(c,NX_BRIDGE_CONTROL)!=0)return NX_EIO;
    c->session++;c->sequence=0;c->kv_valid=0;c->last=(nx_stats){0};
    c->state=NX_ACCEL_IDLE;c->fault_address=0;owner=NULL;*session=c->session;
    return NX_OK;
}
static nx_status rejected(nx_context *c,const nx_call *call,nx_stats *stats,uint64_t start,nx_status status){
    uint64_t elapsed=now(c)-start;
    *stats=(nx_stats){.session=call->session,.sequence=call->sequence,.tick_hz=c->io.tick_hz,
        .elapsed_ticks=elapsed,.validate_ticks=elapsed,.valid_counters=NX_REFERENCE_TICKS,
        .route=call->route,.status=status,.output_valid=0};
    return status;
}
nx_status nx_accel_run(nx_context *c,const nx_call *call,const nx_accel_job *j,nx_stats *stats){
    if(!c||!c->initialized||!call||!stats)return NX_EINVAL;
    *stats=(nx_stats){0};
    uint64_t start=now(c),validated,uploaded;
    nx_status s=NX_OK;
    if(call->api_version!=NX_API_VERSION)return rejected(c,call,stats,start,NX_EVERSION);
    if(c->state==NX_ACCEL_RUNNING||(owner&&owner!=c))return rejected(c,call,stats,start,NX_EBUSY);
    if(c->state!=NX_ACCEL_IDLE||call->session!=c->session||c->sequence==UINT64_MAX||call->sequence!=c->sequence+1)return rejected(c,call,stats,start,NX_ESTATE);
    if(!call->timeout_ticks)return rejected(c,call,stats,start,NX_EINVAL);
    s=nx_accel_validate_job(j);if(s)return rejected(c,call,stats,start,s);
    if(call->route!=NX_CORAL_RVV)return rejected(c,call,stats,start,NX_EUNSUPPORTED);
    if(expired(c,start,call->timeout_ticks))return rejected(c,call,stats,start,NX_ETIMEOUT); /* Not accepted. */
    validated=now(c);owner=c;c->state=NX_ACCEL_RUNNING;c->sequence=call->sequence;
    /* CPU router serializes all stores through B; the following MMIO read is
     * the platform completion barrier. FENCE never substitutes for cache clean. */
    barrier(c);
    if(rd(c,NX_BRIDGE_STATUS)&6){s=NX_EIO;uploaded=validated;goto finish;}
    wr(c,NX_BRIDGE_CONTROL,1);barrier(c);
    clear_record(c);wr(c,NX_BRIDGE_IRQ,1);
    uint32_t words[12]={NX_ACCEL_ABI,48,(uint32_t)c->session,(uint32_t)(c->session>>32),
        (uint32_t)c->sequence,(uint32_t)(c->sequence>>32),j->opcode,j->input,j->output,j->words,j->xor_mask,0};
    for(unsigned i=0;i<12;i++)wr(c,NX_ACCEL_PARAMS+4*i,words[i]);
    wr(c,NX_ACCEL_ENTRY,c->program.entry);barrier(c);
    if(rd(c,NX_ACCEL_ENTRY)!=c->program.entry||(rd(c,NX_BRIDGE_STATUS)&6)){s=NX_EIO;uploaded=now(c);goto finish;}
    uploaded=now(c);
    if(expired(c,start,call->timeout_ticks)){s=NX_ETIMEOUT;goto finish;}
    wr(c,NX_ACCEL_CONTROL,0);barrier(c);
    for(;;){
        uint32_t bridge=rd(c,NX_BRIDGE_STATUS),status=rd(c,NX_ACCEL_STATUS);
        if(bridge&6){s=NX_EIO;break;}
        if(status&2){s=NX_EFAULT;break;} /* fault always wins over halt */
        if(expired(c,start,call->timeout_ticks)){s=NX_ETIMEOUT;break;}
        if((status&1)&&(bridge&1)){
            uint32_t r[8];for(unsigned i=0;i<8;i++)r[i]=rd(c,NX_ACCEL_RESULT+4*i);
            if(r[0]!=NX_ACCEL_ABI||r[1]!=32||r[2]!=(uint32_t)c->session||r[3]!=(uint32_t)(c->session>>32)||
                r[4]!=(uint32_t)c->sequence||r[5]!=(uint32_t)(c->sequence>>32)||r[6]!=0||r[7]!=1)s=NX_EFAULT;
            if(rd(c,NX_BRIDGE_STATUS)&6)s=NX_EIO;
            if(expired(c,start,call->timeout_ticks))s=NX_ETIMEOUT;
            break;
        }
    }
finish:
    if(s){
        c->state=NX_ACCEL_FAULTED;c->kv_valid=0;
        wr(c,NX_BRIDGE_CONTROL,3);barrier(c);c->fault_address=rd(c,NX_BRIDGE_ADDRESS);
        /* Owner retained until explicit, successful drain + reset. */
    }else{
        wr(c,NX_BRIDGE_CONTROL,0);barrier(c);
        if(rd(c,NX_BRIDGE_CONTROL)!=0||(rd(c,NX_BRIDGE_STATUS)&6)){
            s=NX_EIO;c->state=NX_ACCEL_FAULTED;wr(c,NX_BRIDGE_CONTROL,3);
        }else{c->state=NX_ACCEL_IDLE;owner=NULL;}
    }
    uint64_t end=now(c);
    *stats=(nx_stats){.session=c->session,.sequence=c->sequence,.tick_hz=c->io.tick_hz,
        .elapsed_ticks=end-start,.validate_ticks=validated-start,.upload_ticks=uploaded-validated,
        .execute_ticks=end-uploaded,.valid_counters=NX_REFERENCE_TICKS,.route=NX_CORAL_RVV,
        .status=s,.output_valid=s==NX_OK};
    c->last=*stats;return s;
}
nx_status nx_wait(nx_context *c,uint64_t session,uint64_t sequence,nx_stats *s){
    if(!c||!s||!c->initialized)return NX_EINVAL;
    if(c->state==NX_ACCEL_RUNNING)return NX_EBUSY;
    if(!sequence||session!=c->session||sequence!=c->sequence||c->last.sequence!=sequence)return NX_ESTATE;
    *s=c->last;return s->status;
}
void nx_accel_irq(nx_context *c){if(c&&c->initialized)wr(c,NX_BRIDGE_IRQ,1);}
nx_status nx_query_caps(nx_context *c,uint32_t route,nx_caps *caps){
    if(!c||!c->initialized||!caps)return NX_EINVAL;
    if(route>1 || (route!=NX_CORAL_RVV && !(c->linear_routes&(1u<<route))))return NX_EUNSUPPORTED;
    *caps=(nx_caps){.api_version=1,.route=route,.synchronous=1,.max_inflight=1,.alignment_bytes=16};
    if(c->linear_provider && (c->linear_routes&(1u<<route))) {
        caps->operation_mask=1u<<NX_LINEAR;caps->max_m=512;caps->max_n=151936;
        caps->max_k=4864;caps->group_size=64;caps->numeric_version=1;caps->layout_id=1;
    }
    return NX_OK;
}
nx_status nx_linear_install(nx_context *c,nx_linear_provider fn,void *cookie,uint32_t routes){
    if(!c||!c->initialized||!fn||!cookie||!routes||(routes&~3u))return NX_EINVAL;
    if(c->state!=NX_ACCEL_IDLE||owner)return NX_EBUSY;
    c->linear_provider=fn;c->linear_cookie=cookie;c->linear_routes=routes;return NX_OK;
}
nx_status nx_linear_run(nx_context *c,const nx_call *a,const nx_linear *j,nx_stats *s){
    if(!c||!c->initialized||!a||!j||!s)return NX_EINVAL;
    uint64_t start=now(c);
    if(a->api_version!=1)return rejected(c,a,s,start,NX_EVERSION);
    if(c->state==NX_ACCEL_RUNNING||(owner&&owner!=c))return rejected(c,a,s,start,NX_EBUSY);
    if(c->state!=NX_ACCEL_IDLE||a->session!=c->session||c->sequence==UINT64_MAX||a->sequence!=c->sequence+1)return rejected(c,a,s,start,NX_ESTATE);
    if(!a->timeout_ticks)return rejected(c,a,s,start,NX_EINVAL);
    if(a->route>1||!c->linear_provider||!(c->linear_routes&(1u<<a->route)))return rejected(c,a,s,start,NX_EUNSUPPORTED);
    owner=c;c->state=NX_ACCEL_RUNNING;
    nx_status status=c->linear_provider(c->linear_cookie,a,j,s);
    /* A validated nonzero MAC count marks acceptance; rejected calls still
     * return the requested identity but never consume sequence. */
    int accepted=s->macs!=0 && s->sequence==a->sequence && s->session==a->session;
    if(accepted){c->sequence=a->sequence;c->last=*s;}
    if(accepted && (status==NX_EFAULT||status==NX_EIO||status==NX_ETIMEOUT||status==NX_ENUMERIC)){c->state=NX_ACCEL_FAULTED;c->kv_valid=0;}
    else{c->state=NX_ACCEL_IDLE;owner=NULL;}
    return status;
}
nx_status nx_attention_run(nx_context *c,const nx_call *a,const nx_attention *j,nx_stats *s){(void)c;(void)a;(void)j;(void)s;return NX_EUNSUPPORTED;}
nx_status nx_vector_run(nx_context *c,const nx_call *a,const nx_vector *j,nx_stats *s){(void)c;(void)a;(void)j;(void)s;return NX_EUNSUPPORTED;}
