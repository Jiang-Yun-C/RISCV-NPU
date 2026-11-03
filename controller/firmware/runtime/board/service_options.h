/* Included by production main after its UART helpers. All enhancements are
 * selected explicitly at build time; baseline builds keep their old wire. */
#ifndef T27_SERVICE_OPTIONS_H
#define T27_SERVICE_OPTIONS_H
#include "prefix.h"
#include "control.h"
#include "t27_runtime_identity.h"
#include "request_pmu.h"
#define T27_CORE_HZ UINT64_C(125000000)
/* Preserve the deployed conservative limit until real workload measurements
 * justify a different default. :timeout allows 1..86400 seconds explicitly. */
#ifndef NX_T27_TIMEOUT_SECONDS
#define NX_T27_TIMEOUT_SECONDS 86400u
#endif
_Static_assert(NX_T27_TIMEOUT_SECONDS>=1&&NX_T27_TIMEOUT_SECONDS<=86400,"request timeout range");
static uint64_t service_timeout_ticks=T27_CORE_HZ*NX_T27_TIMEOUT_SECONDS;
static nxp_cache service_prefix;
static nx_prefix_identity service_key;
static uint32_t service_prefix_ids[NXR_INPUT_MAX];
static size_t service_prefix_count;
/* One resident KV prefix, two exact token sequences. Switching templates is
 * a cache miss; these small ID arrays are not extra KV arenas. */
static uint32_t service_action_prefix_ids[NXR_INPUT_MAX];
static size_t service_action_prefix_count;
static int service_prefix_enabled=1,service_prefix_captured;
static uint64_t service_prefix_prepare_ticks;
static size_t service_prefix_tokens;
static nxc_control service_control;
/* The last terminal request, distinct from an otherwise unused idle session. */
static uint64_t service_finished_session;
typedef struct {uint64_t ticks[NX_TIMERS],calls[NX_TIMERS];} service_profile;
static service_profile profile_begin,profile_prefill,profile_end;
#ifdef NX_T25_CE64
static uint64_t service_transfer_start[10];
static void service_transfer_snapshot(uint64_t values[10]){
    values[0]=backend.staging_bytes;values[1]=backend.staging_saved_bytes;
    values[2]=backend.output_copy_bytes;values[3]=backend.private_output_saved_bytes;
    values[4]=backend.staging_ticks;values[5]=backend.output_copy_ticks;
    values[6]=backend.backend_cycles;values[7]=backend.completed;
    values[8]=values[9]=0;
#if NX_KV_TAIL_DIRECT
    values[8]=backend.kv_output_saved_bytes;
#endif
#if NX_HEAD_ARGMAX
    values[9]=backend.head_read_saved_bytes;
#endif
}
#endif
static void service_transfer_begin(void){
#ifdef NX_T25_CE64
    service_transfer_snapshot(service_transfer_start);
#endif
}
static void service_transfer_print(void){
#ifdef NX_T25_CE64
    uint64_t end[10];service_transfer_snapshot(end);
    static const char *names[10]={"input_staged_bytes=","input_saved_bytes=","output_copy_bytes=","output_saved_bytes=",
        "input_staging_ticks=","output_copy_ticks=","backend_cycles=","completed_calls=",
        "kv_output_saved_bytes=","head_read_saved_bytes="};
    text("T25 TRANSFER 1 ");value("session=",request.session);
    for(unsigned i=0;i<10;i++)value(names[i],end[i]-service_transfer_start[i]);put('\n');
#endif
}
static int service_key_digest(uint8_t out[32],const char *hexadecimal){
    if(strlen(hexadecimal)!=64)return NXR_INVALID;
    for(unsigned i=0;i<32;i++){
        unsigned value=0;
        for(unsigned j=0;j<2;j++){
            unsigned c=(unsigned char)hexadecimal[i*2+j];
            if(c>='0'&&c<='9')c-='0';else if(c>='a'&&c<='f')c=c-'a'+10;else return NXR_INVALID;
            value=value*16+c;
        }out[i]=(uint8_t)value;
    }return 0;
}
static uint32_t service_pmu_read(void *cookie,uint32_t address){(void)cookie;return *(volatile uint32_t *)(uintptr_t)address;}
static void service_pmu_write(void *cookie,uint32_t address,uint32_t value){(void)cookie;*(volatile uint32_t *)(uintptr_t)address=value;}
static void service_pmu_fence(void *cookie){(void)cookie;
#ifdef __riscv
    __asm__ volatile("fence iorw,iorw" ::: "memory");
#endif
}
static const nx_request_pmu_io service_pmu_io={0,service_pmu_read,service_pmu_write,service_pmu_fence};
static nx_request_pmu_snapshot service_pmu_prefill,service_pmu_end;
static int service_pmu_active,service_pmu_valid,service_pmu_has_prefill,service_pmu_supported;
static void service_pmu_begin(void){
    service_pmu_has_prefill=0;service_pmu_valid=0;service_pmu_active=0;
    service_pmu_supported=nx_request_pmu_available(&service_pmu_io);
    if(!service_pmu_supported||request.session>UINT32_MAX)return;
    service_pmu_valid=nx_request_pmu_begin(&service_pmu_io,(uint32_t)request.session);
    service_pmu_active=service_pmu_valid==1;
}
static void service_pmu_prefill_done(void){
    if(service_pmu_active){
        service_pmu_valid=nx_request_pmu_capture(&service_pmu_io,0,(uint32_t)request.session,&service_pmu_prefill);
        service_pmu_has_prefill=service_pmu_valid==1;
    }
}
static void service_pmu_stop(void){
    if(service_pmu_active){
        int rc=nx_request_pmu_capture(&service_pmu_io,1,(uint32_t)request.session,&service_pmu_end);
        if(rc!=1)service_pmu_valid=-1;
        if(!service_pmu_has_prefill)service_pmu_prefill=service_pmu_end;
        service_pmu_active=0;
    }
}
static void service_pmu_print(void){
    static const char *names[NX_REQUEST_PMU_COUNTERS]={"cycles=","retired=","execute_stall=","branches=","mispredicts=",
        "i_ar=","i_r_beats=","i_r_bytes=","i_address_blocked=","d_ar=","d_r_beats=","d_r_bytes=",
        "d_aw=","d_w_beats=","d_w_bytes=","d_address_blocked=","ce_ar=","ce_r_beats=","ce_r_bytes=",
        "ce_aw=","ce_w_beats=","ce_w_bytes=","ce_address_blocked=","response_errors="};
    text("T25 PMU 1 STATUS ");value("session=",request.session);value("available=",service_pmu_supported);
    value("valid=",service_pmu_valid==1);put('\n');
    if(service_pmu_valid!=1)return;
    for(unsigned phase=0;phase<3;phase++){
        text("T25 PMU 1 ");text(phase==0?"REQUEST ":phase==1?"PREFILL ":"DECODE ");
        value("session=",request.session);value("tag=",service_pmu_end.tag);
        value("sequence=",phase==1?service_pmu_prefill.sequence:service_pmu_end.sequence);
        for(unsigned i=0;i<NX_REQUEST_PMU_COUNTERS;i++)value(names[i],phase==0?service_pmu_end.count[i]:
            phase==1?service_pmu_prefill.count[i]:service_pmu_end.count[i]-service_pmu_prefill.count[i]);
        put('\n');
    }
}
static int service_prepare(nx_session *s){
    service_key=(nx_prefix_identity){.abi=NX_PREFIX_ABI,.context_limit=NX_PREFIX_MAX};
    int rc=service_key_digest(service_key.model,T25_MODEL_SHA256);
    if(!rc)rc=service_key_digest(service_key.tokenizer,T25_TOKENIZER_SHA256);
    if(!rc)rc=service_key_digest(service_key.template_version,T27_TEMPLATE_SHA256);
    if(!rc)rc=service_key_digest(service_key.numeric,T27_NUMERIC_SHA256);
    if(!rc)rc=service_key_digest(service_key.backend,T27_BACKEND_SHA256);
    if(!rc)rc=nx_prefix_configure(s,&service_key);
    if(!rc)rc=nxp_init(&service_prefix,&request,s);
    size_t bytes=0;const char *prefix=nxt_system_prefix(&bytes);
    if(!rc)rc=nxt_encode(&tokenizer,&token_work,prefix,bytes,service_prefix_ids,NXR_INPUT_MAX,&service_prefix_count);
    /* Construct the action prefix with the production template itself. Its
     * system text and the full two-message request remain byte-identical. */
    nxt_message action_system={"system",nx_led_system_prompt,strlen(nx_led_system_prompt)};
    if(!rc)rc=nxt_template(&action_system,1,0,framed,sizeof(framed),&bytes);
    if(!rc)rc=nxt_encode(&tokenizer,&token_work,framed,bytes,service_action_prefix_ids,
                        NXR_INPUT_MAX,&service_action_prefix_count);
    return rc;
}
static void service_take_profile(nx_session *s,service_profile *p){nx_profile_ticks(s,p->ticks,p->calls);}
static void service_print_profile(const char *phase,const service_profile *from,const service_profile *to){
    text("T25 PROFILE 1 ");text(phase);put(' ');value("session=",request.session);
    for(unsigned i=0;i<NX_TIMERS;i++){
        hex(i);put(' ');value("ticks=",to->ticks[i]-from->ticks[i]);value("calls=",to->calls[i]-from->calls[i]);
    }put('\n');
}
static void service_phase(const char *stage){
    text("T25 PHASE 1 ");value("session=",request.session);text("stage=");text(stage);put('\n');
}
static int service_begin_messages(nx_session *s,const nxt_message *messages,size_t message_count,
                                  const uint32_t *prefix_ids,size_t prefix_count,
                                  uint32_t maximum,uint64_t received){
    size_t bytes=0,count=0;uint64_t start=nx_port_ticks();
    int rc=nxt_template(messages,message_count,1,framed,sizeof(framed),&bytes);
    if(!rc)rc=nxt_encode(&tokenizer,&token_work,framed,bytes,ids,NXR_INPUT_MAX,&count);
    uint64_t tokenized=nx_port_ticks(),elapsed=tokenized-start;
    if(rc)return rc;
    if(tokenized-received>=service_timeout_ticks)return NXR_TIMEOUT;
    /* Compare the full encoded request to the separately encoded prefix.
     * A tokenizer boundary mismatch falls back to cold inference. */
    size_t prefix=service_prefix_enabled&&prefix_count&&prefix_count<count&&
        !memcmp(ids,prefix_ids,prefix_count*sizeof(*ids))?prefix_count:0;
    service_prefix_tokens=prefix;
    rc=nx_prefix_configure(s,&service_key);if(rc)return rc;
    rc=nxp_begin(&service_prefix,&service_key,ids,count,prefix,maximum,service_timeout_ticks);
    if(rc)return rc;
    request.start_ticks=received;request.tokenizer_ticks=elapsed;request.tokenized_at=tokenized;
    service_prefix_captured=0;service_prefix_prepare_ticks=0;
    request.prefill_boundary=prefix&&!service_prefix.last_hit?(uint32_t)prefix:0;
    return 0;
}
static int service_begin_text(nx_session *s,const nxt_message *message,uint32_t maximum,uint64_t received){
    return service_begin_messages(s,message,1,service_prefix_ids,service_prefix_count,maximum,received);
}
static int service_poll_control(void){
    /* Each check is bounded. Execution is synchronous; receipt is acted upon at
     * a completed block/token boundary, never in the middle of a DMA result. */
    int cancelled=0;
    for(unsigned i=0;i<128;i++){
        int c;
#ifdef NX_T25_SERVICE_TEST
        extern int nx_t25_test_poll_byte(void);c=nx_t25_test_poll_byte();
#else
#if NX_APP_IRQ
        c=nx_irq_rx_pop();
        if(c==-2){service_control=(nxc_control){0};return NXR_INVALID;}
#else
        c=(REG(4)&2)?(int)(REG(0xc0)&255u):-1;
#endif
#endif
        if(c<0)break;
        uint64_t target=0;int event=nxc_feed(&service_control,(unsigned char)c,request.session,&target);
        if(event){
            text("T25 CONTROL 1 ");value("session=",target);
            int active=request.state==NXR_PREFILL||request.state==NXR_DECODE||action_pending;
            const char *status=event==NXC_CANCEL?(active?"accepted":"finished"):event==NXC_STALE?"stale":"rejected";
            text("status=");text(status);put('\n');
            if(event==NXC_CANCEL){
#if NX_APP_IRQ
                REG(0x420)=active?0x301u:0x304u;
                nx_irq_consume(NX_EV_UART);
#endif
                cancelled=active;
                /* Stop at this LF. A duplicate command remains a complete
                 * line for the idle loop, instead of losing a partially
                 * consumed prefix when the terminated request is reset. */
                break;
            }
        }
    }
    /* Do not reset the model here. The terminal path must inspect the health
     * gates, close the old stream, and only then create a new idle session. */
    return cancelled?NXR_CANCELLED:0;
}
static void service_idle_control_reply(int valid,uint64_t target){
    text("T25 CONTROL 1 ");value("session=",valid?target:0);
    text(!valid?"status=rejected\n":target==service_finished_session?"status=finished\n":"status=stale\n");
}
static void service_finish_partial_control(const char *suffix,int count){
    uint64_t target=0;int event=NXC_REJECTED;
    if(count>=0){
        for(int i=0;i<count;i++)(void)nxc_feed(&service_control,(unsigned char)suffix[i],request.session,&target);
        event=nxc_feed(&service_control,'\n',request.session,&target);
    }else service_control=(nxc_control){0};
    service_idle_control_reply(event==NXC_CANCEL||event==NXC_STALE,target);
}
static int service_health(void){
    uint32_t peak=0;int rc=stack_peak(&peak);if(rc)return rc;
    if(request.busy)return NXR_BUSY;
#ifndef NX_T25_UART
    /* Existing platform/BIST faults plus native quarantine remain fatal. */
    if(REG(0x208)&0x78u)return NXR_FAULT;
#endif
#ifdef NX_T25_CE64
    rc=nxr_ce64_platform_idle();if(rc)return rc;
#endif
    return 0;
}
static int service_recover(nx_session *s){
    nx_prefix_invalidate(s);
    uint32_t peak=0;int rc=stack_peak(&peak);if(rc)return rc;
#ifndef NX_T25_UART
    if(REG(0x208)&0x78u)return NXR_FAULT;
#endif
#ifdef NX_T25_CE64
    /* This is the existing epoch/drain/quarantine protocol, not a fixed wait
     * or a software-only reset. It retains ownership on failure. */
    rc=nxr_ce64_platform_reset();
    if(rc)return rc;
#endif
    rc=nxr_reset(&request);if(rc)return rc;
    if(request.state!=NXR_IDLE||request.busy||request.error||request.generated||request.kv_length)return NXR_STATE;
    return service_health();
}
static int service_end_request(nx_session *s,int reason){
    if((reason!=NXR_CANCELLED&&reason!=NXR_TIMEOUT)||stream.request!=&request||
       !request.session||request.session==UINT64_MAX)return NXR_STATE;
    const uint64_t old_session=request.session;
    action_pending=0;memset(&led_pending,0,sizeof(led_pending));nx_prefix_invalidate(s);
    /* Capture health before nxs_abort's model invalidation. Never let reset
     * hide a backend fault, held completion/owner or a broken stack guard. */
    int health=service_health();
    if(!health&&request.state==NXR_FAILED&&request.error!=reason)
        health=request.error?request.error:NXR_STATE;
    int aborted=nxs_abort(&stream,reason);
    error(reason);
    if(health)return health;
    if(aborted!=reason||stream.active||!stream.aborted||request.state!=NXR_FAILED||request.error!=reason)
        return aborted&&aborted!=reason?aborted:NXR_STATE;
    int rc=service_recover(s);if(rc)return rc;
    if(request.session!=old_session+1)return NXR_STATE;
    /* A partial control line may have arrived just before a timeout. Keep
     * it for the idle-loop handoff; never reinterpret its suffix as a new
     * model or device command. A completed cancel already consumed its LF. */
    service_finished_session=old_session;
    /* next_session names the recovered idle session. The next model begin
     * may advance again; it must not reuse the terminated request identity. */
    text("T25 REQUEST_END 1 ");value("session=",old_session);value("next_session=",request.session);
    text("status=");text(reason==NXR_CANCELLED?"cancelled":"timeout");put('\n');
    return 0;
}
#endif
