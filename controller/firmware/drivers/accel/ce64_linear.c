#include "../../runtime/board/irq_events.h"
#include "ce64_linear.h"
#include <string.h>
#include <limits.h>
static nx_ce64_context *owner;
static uint32_t rd(nx_ce64_context *c,uint32_t a){return c->base.io.read32(c->base.io.cookie,a);}
static void wr(nx_ce64_context *c,uint32_t a,uint32_t v){c->base.io.write32(c->base.io.cookie,a,v);}
static uint32_t cr(nx_ce64_context *c,uint32_t a){return rd(c,CE64_MMIO_BASE+a);}
static void cw(nx_ce64_context *c,uint32_t a,uint32_t v){wr(c,CE64_MMIO_BASE+a,v);}
static uint64_t now(nx_ce64_context *c){return c->base.io.ticks(c->base.io.cookie);}
static void fence(nx_ce64_context *c){c->base.io.fence(c->base.io.cookie);}
static int expired(nx_ce64_context *c,uint64_t start,uint64_t limit){return now(c)-start>=limit;}
static void isolate(nx_ce64_context *c){
    wr(c,NX_BRIDGE_CONTROL,3);cw(c,CE64_CONTROL,CE64_CTL_ISOLATE);fence(c);
    c->base.fault_address=rd(c,NX_BRIDGE_ADDRESS);c->base.kv_valid=0;
}
nx_status nx_ce64_idle_safe(nx_ce64_context *c){
    if(!c||!c->base.initialized||!c->binding||c->binding->context!=&c->base)return NX_EINVAL;
    /* A synchronous operator must have completed its ACK and owner release
     * before the service may call a cancellation a recoverable user event.
     * acquired_generation deliberately remains nonzero after a good ACK. */
    if(owner||c->base.state!=NX_ACCEL_IDLE)return NX_ESTATE;
    fence(c);
    uint32_t state=cr(c,CE64_STATUS),reset=cr(c,CE64_RESET_STATUS);
    if(!(state&CE64_ST_IDLE)||(state&(CE64_ST_RUNNING|CE64_ST_COMPLETION_PENDING|CE64_ST_FAULTED))||
       (reset&6u)||cr(c,CE64_OUTSTANDING)||cr(c,CE64_EPOCH)!=c->epoch||
       rd(c,NX_BRIDGE_CONTROL)||(rd(c,NX_BRIDGE_STATUS)&7u)!=1u)return NX_EIO;
    return NX_OK;
}
nx_status nx_ce64_reset_session(nx_ce64_context *c,uint64_t limit,uint64_t *session){
    if(!c||!c->base.initialized||!limit||!session)return NX_EINVAL;
    if(c->base.state==NX_ACCEL_RUNNING||(owner&&owner!=c))return NX_EBUSY;
    if(c->base.session==UINT64_MAX)return NX_ESTATE;
    nx_diag_context(11,c);nx_linear_input_invalidate(c->binding);
    owner=c;c->base.state=NX_ACCEL_FAULTED;
    uint64_t start=now(c);uint32_t old=cr(c,CE64_EPOCH);
    if(old==UINT32_MAX||old==0)return NX_ESTATE;
    isolate(c);cw(c,CE64_CONTROL,CE64_CTL_ISOLATE|CE64_CTL_RESET_REQUEST);fence(c);
    for(;;){
        /* A native timeout/loss stays isolated until platform DDR recovery.
         * Neither a consumed AXI error nor an empty guard clears quarantine. */
        if(cr(c,CE64_RESET_STATUS)&2)return NX_EIO;
        uint32_t e=cr(c,CE64_EPOCH),b=rd(c,NX_BRIDGE_STATUS);
        if(e==old+1 && (b&1) && (cr(c,CE64_STATUS)&CE64_ST_DRAINED)){c->epoch=e;break;}
        if(expired(c,start,limit))return NX_ETIMEOUT;
    }
    wr(c,NX_BRIDGE_CLEAR,1);wr(c,NX_BRIDGE_IRQ,1);cw(c,CE64_IRQ_STATUS,1);
    cw(c,CE64_CLEAR_SHADOW,1);fence(c);
    if(rd(c,NX_BRIDGE_STATUS)&6)return NX_EIO;
    if(expired(c,start,limit))return NX_ETIMEOUT;
    wr(c,NX_BRIDGE_CONTROL,0);fence(c);
    if(rd(c,NX_BRIDGE_CONTROL)!=0)return NX_EIO;
    c->base.session++;c->base.sequence=0;c->base.kv_valid=0;
    c->base.last=(nx_stats){0};c->base.state=NX_ACCEL_IDLE;
    c->base.fault_address=0;c->acquired_generation=0;owner=NULL;
    *session=c->base.session;nx_diag_context(12,c);return NX_OK;
}
nx_status nx_ce64_init(nx_ce64_context *c,const nx_accel_io *io,uint64_t limit){
    if(!c||!io||!io->read32||!io->write32||!io->ticks||!io->fence||!io->tick_hz||!limit)return NX_EINVAL;
    if(owner)return NX_EBUSY;
    *c=(nx_ce64_context){.base={.io=*io,.state=NX_ACCEL_FAULTED,.initialized=1}};
    if(cr(c,CE64_ID)!=CE64_DESC_MAGIC||cr(c,CE64_VERSION)!=NX_API_VERSION_V2)return NX_EVERSION;
    uint64_t session;return nx_ce64_reset_session(c,limit,&session);
}
nx_status nx_ce64_bind(nx_ce64_context *c,nx_linear_binding *b){
    if(!c||!c->base.initialized||!b||!b->resolve||!b->execute)return NX_EINVAL;
    if(c->base.state!=NX_ACCEL_IDLE||owner)return NX_EBUSY;
    nx_linear_input_invalidate(b);b->context=&c->base;c->binding=b;return NX_OK;
}
nx_status nx_query_caps_v2(nx_ce64_context *c,uint32_t route,nx_caps_v2 *caps){
    if(!c||!c->base.initialized||!caps)return NX_EINVAL;
    if(route!=NX_CE64)return NX_EUNSUPPORTED;
    *caps=(nx_caps_v2){.base={.api_version=2,.route=2,.synchronous=1,.max_inflight=1,
        .max_m=512,.max_n=151936,.max_k=4864,.group_size=64,.alignment_bytes=16,
        .numeric_version=1,.layout_id=1},.implemented_profiles=c->binding ? 1u : 0u,
        .qualified_profile_mask=c->qualified_profile_mask&cr(c,CE64_CAPS)};
    if(caps->qualified_profile_mask)caps->base.operation_mask=1u<<NX_LINEAR;
    return NX_OK;
}
nx_status nx_ce64_linear_execute(void *cookie,const nx_call *call,const struct nx_stream_request *request,struct nx_stream_result *result){
    nx_ce64_transport *t=cookie;
    if(!t||!t->context||!call||!request||!result)return NX_EINVAL;
    nx_ce64_context *c=t->context;nx_diag_context(10,c);uint64_t start=now(c);nx_status s=NX_OK;
    if(call->route!=NX_CE64||call->api_version!=2||c->base.state!=NX_ACCEL_RUNNING||
       call->session!=c->base.session||c->generation==UINT32_MAX)return NX_ESTATE;
    *result=(struct nx_stream_result){0};c->acquired_generation=0;
    fence(c);
    if((rd(c,NX_BRIDGE_STATUS)&7)!=1){s=NX_EIO;do { nx_diag_capture(((1u<<16)|__LINE__),s,c,call,request); goto fail; } while(0);}
    if(cr(c,CE64_EPOCH)!=c->epoch){s=NX_EFAULT;do { nx_diag_capture(((1u<<16)|__LINE__),s,c,call,request); goto fail; } while(0);}
    wr(c,NX_BRIDGE_CONTROL,1);wr(c,NX_BRIDGE_IRQ,1);
    cw(c,CE64_IRQ_STATUS,1);cw(c,CE64_IRQ_MASK,1);cw(c,CE64_CONTROL,CE64_CTL_RUN_ENABLE);
    cw(c,CE64_CLEAR_SHADOW,1);
    cw(c,CE64_RUN_LIMIT_LO,(uint32_t)call->timeout_ticks);cw(c,CE64_RUN_LIMIT_HI,(uint32_t)(call->timeout_ticks>>32));
    struct ce64_descriptor descriptor={.magic=CE64_DESC_MAGIC,.version=1,.bytes=128,
        .flags=request->reserved[0] ? CE64_FLAG_AUDIT : 0,.epoch=c->epoch,.numeric_profile=1};
    memcpy(&descriptor.body,request,96);
    for(unsigned i=0;i<32;i++){uint32_t v;memcpy(&v,(const unsigned char *)&descriptor+4*i,4);cw(c,CE64_DESCRIPTOR_SHADOW+4*i,v);}
    fence(c);
    if(cr(c,CE64_DESC_WRITTEN_BITMAP)!=UINT32_MAX||(rd(c,NX_BRIDGE_STATUS)&6)){s=NX_EIO;do { nx_diag_capture(((1u<<16)|__LINE__),s,c,call,request); goto fail; } while(0);}
    if(expired(c,start,call->timeout_ticks)){s=NX_ETIMEOUT;do { nx_diag_capture(((1u<<16)|__LINE__),s,c,call,request); goto fail; } while(0);}
#if NX_APP_IRQ
    nx_irq_npu_arm();
#endif
    c->generation++;cw(c,CE64_DOORBELL,c->generation);fence(c);
    if(cr(c,CE64_ACCEPT_GENERATION)!=c->generation){s=NX_EFAULT;do { nx_diag_capture(((1u<<16)|__LINE__),s,c,call,request); goto fail; } while(0);}
    for(;;){
#if NX_APP_IRQ
        if(nx_irq_enabled()&&!nx_irq_npu_notified())nx_irq_npu_wait(0);
        nx_irq_stats.polls++;
#endif
        uint32_t bridge=rd(c,NX_BRIDGE_STATUS),state=cr(c,CE64_STATUS);
        if(bridge&6){s=NX_EIO;do { nx_diag_capture(((1u<<16)|__LINE__),s,c,call,request); goto fail; } while(0);}
        if(cr(c,CE64_RESET_STATUS)&2){s=NX_EIO;do { nx_diag_capture(((1u<<16)|__LINE__),s,c,call,request); goto fail; } while(0);}
        if(expired(c,start,call->timeout_ticks)){s=NX_ETIMEOUT;do { nx_diag_capture(((1u<<16)|__LINE__),s,c,call,request); goto fail; } while(0);}
        if(cr(c,CE64_EPOCH)!=c->epoch){s=NX_EFAULT;do { nx_diag_capture(((1u<<16)|__LINE__),s,c,call,request); goto fail; } while(0);}
        if((state&CE64_ST_COMPLETION_PENDING)&&(bridge&1))break;
        if(t->wait)t->wait(t->wait_cookie);
    }
    uint32_t bank=cr(c,CE64_STATUS)&CE64_ST_COMPLETION_BANK ? CE64_COMPLETION_BANK1 : CE64_COMPLETION_BANK0;
    uint32_t first=cr(c,bank+156);struct ce64_completion completion;
    for(unsigned i=0;i<40;i++){uint32_t v=cr(c,bank+4*i);memcpy((unsigned char *)&completion+4*i,&v,4);}
    uint32_t second=cr(c,bank+156);
    if(cr(c,CE64_EPOCH)!=c->epoch){s=NX_EFAULT;do { nx_diag_capture(((1u<<16)|__LINE__),s,c,call,request); goto fail; } while(0);}
    if(first==0||first!=second||first!=c->generation||completion.commit_generation!=first||
       completion.descriptor_generation!=first||completion.magic!=CE64_RESULT_MAGIC||completion.version!=1||
       completion.bytes!=160||completion.backend_id!=NX_CE64||completion.execution_profile!=CE64_PROFILE_SERIAL||
       completion.epoch!=c->epoch||completion.body.abi!=NX_LINEAR_ABI||completion.body.size!=104||
       completion.body.session_lo!=request->session_lo||completion.body.session_hi!=request->session_hi||
       completion.body.sequence_lo!=request->sequence_lo||completion.body.sequence_hi!=request->sequence_hi){s=NX_EFAULT;do { nx_diag_capture(((1u<<16)|__LINE__),s,c,call,request); goto fail; } while(0);}
    if(completion.body.status||completion.body.valid!=1||!completion.body.cycles||
       completion.body.rows!=request->n*((request->m+3)/4)||completion.body.tiles!=((request->n+127)/128)*((request->m+3)/4)){
        s=completion.body.status==NX_ENUMERIC&&completion.body.valid==0 ? NX_ENUMERIC : NX_EFAULT;do { nx_diag_capture(((1u<<16)|__LINE__),s,c,call,request); goto fail; } while(0);
    }
    if(rd(c,NX_BRIDGE_STATUS)&6){s=NX_EIO;do { nx_diag_capture(((1u<<16)|__LINE__),s,c,call,request); goto fail; } while(0);}
    if(expired(c,start,call->timeout_ticks)){s=NX_ETIMEOUT;do { nx_diag_capture(((1u<<16)|__LINE__),s,c,call,request); goto fail; } while(0);}
    if(cr(c,CE64_EPOCH)!=c->epoch){s=NX_EFAULT;do { nx_diag_capture(((1u<<16)|__LINE__),s,c,call,request); goto fail; } while(0);}
    memcpy(result,&completion.body,104);
    if(cr(c,CE64_EPOCH)!=c->epoch){s=NX_EFAULT;do { nx_diag_capture(((1u<<16)|__LINE__),s,c,call,request); goto fail; } while(0);}
#if NX_APP_IRQ
    nx_irq_consume(NX_EV_NPU);
#endif
    c->acquired_generation=first;
    /* ACK/release belongs to nx_linear_run_v2 AFTER provider total-deadline
     * validation. Successful acquire alone never releases the buffer lease. */
    return NX_OK;
fail:*result=(struct nx_stream_result){0};isolate(c);return s;
}
nx_status nx_linear_run_v2(nx_ce64_context *c,const nx_call *call,const nx_linear *job,nx_stats *stats){
    if(!c||!c->base.initialized||!call||!job||!stats)return NX_EINVAL;
    *stats=(nx_stats){.session=call->session,.sequence=call->sequence,.tick_hz=c->base.io.tick_hz,
        .route=call->route,.valid_counters=NX_REFERENCE_TICKS};
    nx_status s;
    if(call->api_version!=2)s=NX_EVERSION;
    else if(call->route!=NX_CE64||!c->binding)s=NX_EUNSUPPORTED;
    else if(c->base.state==NX_ACCEL_RUNNING||(owner&&owner!=c))s=NX_EBUSY;
    else if(c->base.state!=NX_ACCEL_IDLE||call->session!=c->base.session||c->base.sequence==UINT64_MAX||call->sequence!=c->base.sequence+1)s=NX_ESTATE;
    else if(!call->timeout_ticks)s=NX_EINVAL;
    else {
        owner=c;c->base.state=NX_ACCEL_RUNNING;uint64_t start=now(c);
        s=nx_linear_execute_binding(c->binding,call,job,stats);
        int accepted=stats->macs!=0&&stats->session==call->session&&stats->sequence==call->sequence;
        if(accepted)c->base.sequence=call->sequence;
        if(!s){
            if(!c->acquired_generation||c->acquired_generation!=c->generation){s=NX_EFAULT;}
            else if(rd(c,NX_BRIDGE_STATUS)&6)s=NX_EIO;
            else if(expired(c,start,call->timeout_ticks))s=NX_ETIMEOUT;
            else {
                cw(c,CE64_ACK,c->acquired_generation);fence(c);
                wr(c,NX_BRIDGE_CONTROL,0);fence(c);
                if(rd(c,NX_BRIDGE_CONTROL)!=0||(rd(c,NX_BRIDGE_STATUS)&6))s=NX_EIO;
            }
        }
        if(s)nx_diag_capture(((1u<<16)|__LINE__),s,c,call,0);
        if(accepted&&s){isolate(c);c->base.state=NX_ACCEL_FAULTED;}
        else {c->base.state=NX_ACCEL_IDLE;owner=NULL;}
        if(s)nx_linear_input_invalidate(c->binding);
        stats->status=s;stats->output_valid=accepted&&!s;stats->elapsed_ticks=now(c)-start;
        if(accepted)c->base.last=*stats;
        return s;
    }
    if(s)nx_linear_input_invalidate(c->binding);
    stats->status=s;return s;
}
nx_status nx_ce64_wait(nx_ce64_context *c,uint64_t session,uint64_t sequence,nx_stats *stats){
    if(!c||!stats||!c->base.initialized)return NX_EINVAL;
    if(c->base.state==NX_ACCEL_RUNNING)return NX_EBUSY;
    if(!sequence||session!=c->base.session||sequence!=c->base.sequence||c->base.last.sequence!=sequence)return NX_ESTATE;
    *stats=c->base.last;return stats->status;
}
void nx_ce64_irq(nx_ce64_context *c){if(c&&c->base.initialized){cw(c,CE64_IRQ_STATUS,1);wr(c,NX_BRIDGE_IRQ,1);}}
