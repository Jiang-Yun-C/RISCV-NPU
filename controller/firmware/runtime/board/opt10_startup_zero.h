/* Internal board startup implementation, included once after its actual
 * platform context declarations. No public linear/SFU API authority changes. */
#ifndef NX_OPT10_STARTUP_ZERO_H
#define NX_OPT10_STARTUP_ZERO_H
static const uint32_t startup_bases[7]={0xa8000000u,0xac000000u,0xac0cc000u,
    0xba100000u,0xba120000u,0xba1c0000u,0xba1c5000u};
static const uint32_t startup_spans[7]={15728640u,835072u,607744u,77824u,
    607744u,19456u,1216u};
static uint32_t startup_read(uint32_t offset){
    return context.base.io.read32(context.base.io.cookie,CE64_MMIO_BASE+offset);
}
static void startup_write(uint32_t offset,uint32_t value){
    context.base.io.write32(context.base.io.cookie,CE64_MMIO_BASE+offset,value);
}
static void startup_fail(void){
    context.base.io.write32(context.base.io.cookie,NX_BRIDGE_CONTROL,3);
    startup_write(CE64_CONTROL,CE64_CTL_ISOLATE);
    context.base.io.fence(context.base.io.cookie);
    context.base.kv_valid=0;context.base.state=NX_ACCEL_FAULTED;
}
/* CE generation is monotonic for the entire physical boot. An ordinary
 * drained reset advances epoch/session while preserving that generation. */
static int startup_reset_transport(const nx_accel_io *io){
    if(!context.base.initialized)return nx_ce64_init(&context,io,2000000);
    uint64_t session;return nx_ce64_reset_session(&context,2000000,&session);
}
int nxr_ce64_startup_open(void){
    if(!nxr_boot_ready())return NX_ESTATE;
    nx_accel_io io;nx_accel_target_io(&io);io.tick_hz=125000000;
    int rc=startup_reset_transport(&io);if(rc)return rc;
    model=NULL;transport=(nx_ce64_transport){.context=&context};
    uint32_t state=startup_read(CE64_STARTUP_STATUS);
    if((state&0x7fu)!=1u){startup_fail();return NX_ESTATE;}
    return 0;
}
int nxr_ce64_startup_zero(uint32_t base,uint32_t bytes,unsigned index){
    if(index>=7||base!=startup_bases[index]||bytes!=startup_spans[index])return NX_EBOUNDS;
    if(!nxr_boot_ready()||!context.base.initialized||context.base.state!=NX_ACCEL_IDLE||
       context.base.sequence==UINT64_MAX||transport.context!=&context||context.binding||model)
        return NX_ESTATE;
    uint32_t state=startup_read(CE64_STARTUP_STATUS);
    if((state&0x7fu)!=(1u|(index<<3))||startup_read(CE64_EPOCH)!=context.epoch)return NX_ESTATE;
    uint32_t epoch=context.epoch,generation=context.generation;
    uint64_t session=context.base.session,started=context.base.io.ticks(context.base.io.cookie);
    nx_call call={.api_version=2,.route=NX_CE64,.session=session,
        .sequence=context.base.sequence+1,.timeout_ticks=UINT64_C(900000000)};
    struct nx_stream_request request={.abi=NX_LINEAR_ABI,.size=96,
        .session_lo=(uint32_t)session,.session_hi=(uint32_t)(session>>32),
        .sequence_lo=(uint32_t)call.sequence,.sequence_hi=(uint32_t)(call.sequence>>32),
        .opcode=CE64_PRIVATE_STARTUP_ZERO_OPCODE,.m=1,.n=1,.k=bytes,
        .destination=base,.row_bytes=index};
    struct nx_stream_result result={0};context.base.state=NX_ACCEL_RUNNING;
    int rc=nx_ce64_linear_execute(&transport,&call,&request,&result);
    if(context.generation!=generation)context.base.sequence=call.sequence;
    if(!rc&&(result.payload_read!=bytes||result.payload_write!=bytes||
       context.base.session!=session||context.epoch!=epoch||startup_read(CE64_EPOCH)!=epoch||
       !nxr_boot_ready()||context.base.io.ticks(context.base.io.cookie)-started>=call.timeout_ticks))rc=NX_EFAULT;
    if(!rc){
        uint32_t expected=index==6 ? (2u|(7u<<3)) : (1u|((index+1u)<<3));
        if((startup_read(CE64_STARTUP_STATUS)&0x7fu)!=expected)rc=NX_EFAULT;
    }
    if(!rc){
        context.base.io.fence(context.base.io.cookie);
        startup_write(CE64_ACK,context.acquired_generation);
        context.base.io.fence(context.base.io.cookie);
        context.base.io.write32(context.base.io.cookie,NX_BRIDGE_CONTROL,0);
        context.base.io.fence(context.base.io.cookie);
        if(context.base.io.read32(context.base.io.cookie,NX_BRIDGE_CONTROL)!=0||
           (context.base.io.read32(context.base.io.cookie,NX_BRIDGE_STATUS)&6)||
           context.base.io.ticks(context.base.io.cookie)-started>=call.timeout_ticks)rc=NX_EFAULT;
    }
    if(rc){startup_fail();return rc;}
    context.base.state=NX_ACCEL_IDLE;return 0;
}
int nxr_ce64_startup_close(void){
    if(!context.base.initialized||context.base.state!=NX_ACCEL_IDLE||!nxr_boot_ready()||
       (startup_read(CE64_STARTUP_STATUS)&0x7fu)!=(2u|(7u<<3)))return NX_ESTATE;
    return 0;
}
#endif
