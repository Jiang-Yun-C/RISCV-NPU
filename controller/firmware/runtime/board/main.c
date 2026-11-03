/* Full 24-layer service entered ONLY by the authenticated SD loader. No model,
 * logits, tokenizer execution or text generation is delegated to the host. */
#include "model.h"
#include "stream.h"
#include <string.h>
#include "full_weights.h"
#include "t25_identity.h"
#include "boot_status.h"
#include "led_control.h"
#include "irq_events.h"
static struct app_program led_program;
static struct app_result led_pending;
static int action_pending;
#ifndef NX_T27_SERVICE_ENHANCEMENTS
#define NX_T27_SERVICE_ENHANCEMENTS 0
#endif
#ifdef NX_T25_CE64
#include "ce64_platform.h"
static nxr_ce64_backend backend;
#endif
#define REG(o) (*(volatile uint32_t *)(uintptr_t)(0x10000000u+(o)))
extern const unsigned char t25_tokenizer[],t25_tokenizer_end[];
extern uint32_t __stack_bottom[],__stack_top[];
static nx_weights weights;
static unsigned char state[32768] __attribute__((aligned(16)));
static nxt_work token_work;
static nxr_request request;
static nxr_model binding;
static nxt_tokenizer tokenizer;
static nxs_stream stream;
static char line[NXT_TEXT_MAX+1],framed[NXT_TEXT_MAX],output[16384];
static uint32_t ids[NXR_INPUT_MAX];
static uint64_t route_calls[3],fallback_calls,dispatch_ticks,wire_bytes;
#ifdef NX_T25_SERVICE_TEST
/* Host integration tests replace only the board boundary. The service loop,
 * tokenizer, runtime and model adapter below remain the production code. */
extern uint64_t nx_t25_test_ticks(void);
extern void nx_t25_test_put(char);
extern int nx_t25_test_read_line(char *,size_t);
extern int nx_t25_test_stack_peak(uint32_t *);
#endif
uint64_t nx_port_ticks(void){
#ifdef NX_T25_SERVICE_TEST
    return nx_t25_test_ticks();
#else
    uint32_t hi,lo,again;
    do{__asm__ volatile("csrr %0,mcycleh":"=r"(hi));__asm__ volatile("csrr %0,mcycle":"=r"(lo));__asm__ volatile("csrr %0,mcycleh":"=r"(again));}while(hi!=again);
    return (uint64_t)hi<<32|lo;
#endif
}
static void put(char c){
#ifdef NX_T25_SERVICE_TEST
    nx_t25_test_put(c);
#else
    while(REG(4)&1){}REG(0)=(uint8_t)c;
#endif
    wire_bytes++;
}
static void stream_put(void *context,char c){(void)context;put(c);}
/* The status bit is t03_uart_tx.busy, including the final stop bit. */
static void stream_drain(void *context){(void)context;while(REG(4)&1){}}
static void text(const char *s){while(*s)put(*s++);}
static void hex(uint32_t v){for(int i=7;i>=0;i--)put("0123456789abcdef"[(v>>(4*i))&15]);}
static void value(const char *name,uint64_t v){text(name);hex(v>>32);hex((uint32_t)v);put(' ');}
static void error(int rc){text("T25 ERROR ");hex((uint32_t)rc);put('\n');}
uint32_t trap_handler(uint32_t cause,uint32_t pc,uint32_t detail){
#if NX_APP_IRQ
    if(cause==0x8000000bu||cause==0x80000007u)return nx_irq_handler(cause,pc);
#endif
    text("T25 TRAP ");hex(cause);put(' ');hex(pc);put(' ');hex(detail);put('\n');for(;;){}return pc;
}
static int read_line(void){
#ifdef NX_T25_SERVICE_TEST
    return nx_t25_test_read_line(line,sizeof(line));
#else
    size_t n=0;int overflow=0;
    for(;;){int byte;
#if NX_APP_IRQ
        do{byte=nx_irq_rx_pop();}while(byte==-1);
        if(byte==-2){overflow=1;n=0;continue;}
#else
        while(!(REG(4)&2)){}byte=(int)(REG(0xc0)&255u);
#endif
        char c=(char)byte;
        if(c=='\r')continue;
        if(c=='\n'){line[n]=0;return overflow?NXR_BOUNDS:(int)n;}
        if(c=='\b'||c==127){if(n)n--;continue;}
        if(!c)overflow=1;
        else if(n<NXT_TEXT_MAX)line[n++]=c;
        else overflow=1;
    }
#endif
}
static int number(const char **p,uint32_t *out){
    while(**p==' ')(*p)++;
    if(**p<'0'||**p>'9')return NXR_INVALID;
    uint32_t v=0;do{unsigned digit=(unsigned)(*(*p)++-'0');
        if(v>(UINT32_MAX-digit)/10)return NXR_BOUNDS;v=v*10+digit;
    }while(**p>='0'&&**p<='9');
    if(**p&&**p!=' ')return NXR_INVALID;*out=v;return 0;
}
static void dispatch(void *cookie,int kind,int route,int reason,int rc,uint64_t ticks){
    (void)cookie;(void)kind;(void)rc;
    if(route>=0&&route<3)route_calls[route]++;
    if(reason==2)fallback_calls++;dispatch_ticks+=ticks;
}
static int stack_peak(uint32_t *peak){
#ifdef NX_T25_SERVICE_TEST
    return nx_t25_test_stack_peak(peak);
#else
    uint32_t *p=__stack_bottom;
    for(unsigned i=0;i<4;i++)if(p[i]!=0xa5a5a5a5)return NXR_FAULT;
    while(p<__stack_top&&*p==0xa5a5a5a5)p++;
    *peak=(uint32_t)((uintptr_t)__stack_top-(uintptr_t)p);return 0;
#endif
}
static void dump(nx_session *s,int diagnostic){
    /* Hex binary32 words allow an independent host to compare every element.
     * This command is read-only and valid only after a completed request. */
    if(request.state!=NXR_STOPPED&&!(diagnostic&&(request.state==NXR_PREFILL||request.state==NXR_DECODE))){error(NXR_STATE);return;}
    if(!nx_logits_v2(s)){error(NXR_STATE);return;}
    text("T25 LOGITS\n");
    for(unsigned i=0;i<151936;i++){uint32_t bits;memcpy(&bits,nx_logits_v2(s)+i,4);hex(bits);put((i&7)==7?'\n':' ');}
    unsigned length=(unsigned)nx_length(s);
    for(unsigned l=0;l<24;l++)for(unsigned v=0;v<2;v++){
        text("T25 KV ");hex(l);put(' ');hex(v);put(' ');hex(length);put('\n');
        const float *cache=nx_cache(s,(int)l,(int)v);
        for(unsigned i=0;i<length*128;i++){uint32_t bits;memcpy(&bits,cache+i,4);hex(bits);put((i&7)==7?'\n':' ');}
    }
    text("T25 DUMP END\n");
}
#ifndef NX_T25_UART
#include "diagnostics.h"
#endif
#if NX_T27_SERVICE_ENHANCEMENTS
#include "service_options.h"
#endif
static uint32_t led_read_mmio(void *c,uint32_t a){(void)c;
#ifdef NX_T25_LED_MMIO_TEST
    extern uint32_t nx_t25_test_led_read(uint32_t);return nx_t25_test_led_read(a);
#else
    return *(volatile uint32_t *)(uintptr_t)a;
#endif
}
static void led_write_mmio(void *c,uint32_t a,uint32_t v){(void)c;
#ifdef NX_T25_LED_MMIO_TEST
    extern void nx_t25_test_led_write(uint32_t,uint32_t);nx_t25_test_led_write(a,v);
#else
    *(volatile uint32_t *)(uintptr_t)a=v;
#endif
}
static void led_fence(void *c){(void)c;
#ifdef __riscv
    __asm__ volatile("fence iorw,iorw" ::: "memory");
#endif
}
static const nx_led_io led_io={0,led_read_mmio,led_write_mmio,led_fence};
static void led_result(const char *kind,int status,uint32_t writes,uint32_t observed){
    text(kind);value("session=",request.session);text("status=");text(app_status_name(status));put(' ');
    value("writes=",writes);value("state=",observed);put('\n');
}
static void led_bank_result(const char *kind,const char *status,uint32_t writes,
                            uint32_t mask,uint32_t values,uint32_t owned){
    text(kind);value("session=",request.session);text("status=");text(status);put(' ');
    value("writes=",writes);value("mask=",mask);value("values=",values);value("owned=",owned);put('\n');
}
static int begin_led_action(nx_session *s,const char *input,uint64_t received){
    nxt_message messages[2]={{"system",nx_led_system_prompt,strlen(nx_led_system_prompt)},
                             {"user",input,strlen(input)}};
#if NX_T27_SERVICE_ENHANCEMENTS
    /* Preserve the same model prompt and complete EOS/parse/commit gate.
     * Only already-computed, exact system-prefix KV may be reused. */
    return service_begin_messages(s,messages,2,service_action_prefix_ids,
                                  service_action_prefix_count,128,received);
#else
    (void)s;
    int rc=nxr_begin_text(&request,&tokenizer,&token_work,messages,2,framed,sizeof(framed),128,
                          UINT64_C(10800000000000));
    if(!rc)request.start_ticks=received;return rc;
#endif
}
int main(void){
    nx_diag_init();
    if(!nxr_boot_ready()){error(NXR_STATE);for(;;){}}
#ifndef NX_T25_UART
    int memrc=memory_initialize();
#ifdef NX_T25_CE64
    if(!memrc)memrc=nxr_ce64_startup_open();
#endif
    const uint32_t regions[][3]={{0xa8000000,15728640,6},{0xac000000,835072,7},
        {0xac0cc000,607744,8},{0xba100000,77824,9},{0xba120000,607744,10},
        {0xba1c0000,19456,11},{0xba1c5000,1216,12}};
    for(unsigned i=0;!memrc&&i<sizeof(regions)/sizeof(regions[0]);i++)
        memrc=memory_commit(regions[i][0],regions[i][1],regions[i][2]);
#ifdef NX_T25_CE64
    if(!memrc)memrc=nxr_ce64_startup_close();
#endif
    if(memrc){error(memrc);for(;;){}}
    memory_report();
#endif
    load_full(&weights);
    nx_session *s=nx_init_static(&weights,state,sizeof(state),(void *)0xa8000000,15728640,(void *)0xac000000,835072);
    int rc=s?nxt_init(&tokenizer,t25_tokenizer,(size_t)(t25_tokenizer_end-t25_tokenizer)):NXR_FAULT;
    if(!rc)rc=nxr_attach(&request,&binding,s,(float *)0xac0cc000,151936);
#ifdef NX_T25_CE64
    if(!rc)rc=nxr_ce64_platform_open(&backend,&weights);
    if(!rc){nx_bind_backend(s,&backend,nxr_ce64_linear,dispatch,2);nx_bind_input_observer(s,nxr_ce64_input_v2);nx_bind_vector_backend(s,nxr_ce64_vector);nx_bind_private_backend(s,nxr_ce64_linear_private);nx_bind_private_vector_backend(s,nxr_ce64_vector_private);nx_bind_private_swiglu_reservation(s,nxr_ce64_input_v2);
#if NX_PV_SHARED
    nx_bind_pv_backend(s,nxr_ce64_pv);
#endif
#if NX_KV_TAIL_DIRECT
    nx_bind_kv_backend(s,nxr_ce64_linear_kv);
#endif
#if NX_HEAD_ARGMAX
    nx_bind_argmax_backend(s,nxr_ce64_argmax);
#endif
    }
    const char *route="CE64_CANDIDATE_UNQUALIFIED";
#else
    if(!rc)nx_bind_backend(s,0,0,dispatch,0);
    const char *route="CPU_C";
#endif
    if(rc){error(rc);for(;;){}}
    /* :verify exposes logits after every prompt step. Keep that diagnostic
     * path complete, then restore the selected service path per request. */
    nxr_prefill_fn service_prefill=request.prefill;
    nxr_prefill_block_fn service_block=request.prefill_block;
    uint32_t service_rows=request.prefill_rows;
    int stream_enabled=1;
#if NX_T27_SERVICE_ENHANCEMENTS
    rc=service_prepare(s);if(rc){error(rc);for(;;){}}
    int service_blocked=0;
#endif
#if NX_APP_IRQ
    nx_irq_start();
#endif
    text("T25 SERVICE v1 ");text(route);text(" total=512 max_new=128\n");
    text("T25 MODEL ");text(T25_MODEL_SHA256);text(" TOKENIZER ");text(T25_TOKENIZER_SHA256);put('\n');
    uint64_t loaded=(uint64_t)*(volatile uint32_t *)0xba080004<<32|*(volatile uint32_t *)0xba080000;
    text("T25 LOAD ");value("ticks=",nx_port_ticks()-loaded);put('\n');
    for(;;){
        action_pending=0;
        /* Retain the service identity; negotiate extensions here. Ordinary
         * requests require the accompanying stream-aware console (no STEP). */
#if NX_T27_SERVICE_ENHANCEMENTS
        if(service_blocked){
            text("T25 NOT_READY recovery=failed\n");int n=read_line();
            if(n>0&&!strcmp(line,":reset"))service_blocked=service_recover(s)!=0;
            else if(n>0&&!strcmp(line,":reload")){while(REG(4)&1){}REG(0xec)=0x52535432;for(;;){}}
            else error(NXR_STATE);
            continue;
        }
        text("T25 CAPABILITIES stream=1 text_max=1 cancel=1 prefix=1 profile=1 timeout=1 identity=1\n");
#else
        text("T25 CAPABILITIES stream=1 text_max=1\n");
#endif
        text("T27 LED_CAPABILITIES 1 direct=1 action=1 abi=LED1 pin=A20 active_high=1\n");
#if NX_LED_BANK
        /* Only a firmware paired with the new CSR map may probe this bank.
         * Unknown CSR reads can fault on old hardware; default builds do none. */
        uint32_t bank_values,bank_owned;
        if(nx_led_bank_read(&led_io,&bank_values,&bank_owned)==APP_OK){
            text("T27 LED_BANK_CAPABILITIES 1 ");value("mask=",NX_LED_BANK_MASK);
            text("atomic=1 targets=explicit\n");
        }
#endif
#if NX_APP_IRQ
        REG(0x420)=0x302u;
#endif
        text("T25 READY\n");
#if NX_T27_SERVICE_ENHANCEMENTS
        /* A bounded nonblocking poll may have consumed only half a cancel
         * before EOS/timeout. READY is still immediate; the normal idle read
         * completes that control line without executing its suffix. */
        int partial_control=service_control.used||service_control.overflow;
#endif
        int n=read_line();uint64_t received=nx_port_ticks();
#if NX_T27_SERVICE_ENHANCEMENTS
        if(partial_control){service_finish_partial_control(line,n);continue;}
#endif
        if(n<0){error(n);continue;}if(!n)continue;
        uint32_t bank_mask=0,bank_requested_values=0;int bank_kind=0;
#if NX_APP_IRQ
        if(!strncmp(line,":blink ",7)){
            const char *bp=line+7;uint32_t mask,period,edges;
            int br=number(&bp,&mask);if(!br)br=number(&bp,&period);if(!br)br=number(&bp,&edges);
            if(br||*bp||nx_irq_blink(mask,period,edges)){error(NXR_INVALID);continue;}
            text("T27 BLINK 1 source=direct status=started\n");continue;
        }
        if(!strcmp(line,":blinkstop")){nx_irq_led_stop();text("T27 BLINK 1 source=direct status=stopped\n");continue;}
#endif
        int bank_direct=nx_led_bank_command(line,&bank_mask,&bank_requested_values,&bank_kind);
        if(bank_direct){
            uint32_t observed=UINT32_MAX,owned=UINT32_MAX,writes=0;int status=APP_FORMAT;
            if(bank_direct>0){
                if(bank_kind==NX_LED_BANK_APPLY_COMMAND)
                    status=nx_led_bank_apply(&led_io,bank_mask,bank_requested_values,&writes,&observed,&owned);
                else if(bank_kind==NX_LED_BANK_RELEASE_COMMAND)
                    status=nx_led_bank_release(&led_io,bank_mask,&writes,&observed,&owned);
                else status=nx_led_bank_read(&led_io,&observed,&owned);
            }
            led_bank_result("T27 LED_BANK 1 ",app_status_name(status),writes,bank_mask,observed,owned);
            continue;
        }
        uint32_t led_value=0;int led_write=0;
        int direct=nx_led_command(line,&led_value,&led_write);
        if(direct){
            uint32_t observed=UINT32_MAX;
            uint32_t writes=0;int status=APP_FORMAT;
            if(direct>0){
                if(led_write){struct app_result one={.count=1,.actions={{0,led_value}}};status=nx_led_execute(&led_io,&one,&writes,&observed);}
                else status=nx_led_read(&led_io,&observed);
            }
            led_result("T27 LED 1 ",status,writes,observed);
            continue;
        }
        int action_bank_request=!strncmp(line,":actm ",6);
        int action_request=action_bank_request||!strncmp(line,":act ",5);
        uint32_t action_mask=1;const char *action_text=action_request?line+5:NULL;
        if(action_bank_request){
            const char *p=line+6;rc=number(&p,&action_mask);
            if(rc||!nx_led_bank_mask_valid(action_mask)||*p!=' '||!p[1]){error(NXR_INVALID);continue;}
            uint32_t observed,owned;
            if(nx_led_bank_read(&led_io,&observed,&owned)!=APP_OK){error(NXR_STATE);continue;}
            action_text=p+1; /* Explicit target is protocol metadata, not model output. */
        }
        if(action_request&&!*action_text){error(NXR_INVALID);continue;}
        if(!strcmp(line,":stream 0")||!strcmp(line,":stream 1")){
            stream_enabled=line[8]=='1';continue;
        }
        if(!strcmp(line,":reload")){text("T25 RELOAD\n");while(REG(4)&1){}REG(0xec)=0x52535432;for(;;){}}
        if(!strcmp(line,":dump")){dump(s,0);continue;}
#if NX_T27_SERVICE_ENHANCEMENTS
        if(!strcmp(line,":identity")){
            text("T25 MODEL ");text(T25_MODEL_SHA256);text(" TOKENIZER ");text(T25_TOKENIZER_SHA256);put('\n');
            continue;
        }
        if(!strncmp(line,":cancel ",8)){
            uint64_t target=0;int valid=nxc_parse_cancel(line,&target);
            service_idle_control_reply(valid,target);
            continue;
        }
        if(!strncmp(line,":timeout ",9)){
            const char *p=line+9;uint32_t seconds=0;rc=number(&p,&seconds);
            if(rc||*p||!seconds||seconds>86400){error(NXR_BOUNDS);continue;}
            service_timeout_ticks=T27_CORE_HZ*seconds;
            text("T25 CONFIG 1 ");value("timeout_ticks=",service_timeout_ticks);put('\n');continue;
        }
        if(!strcmp(line,":prefix 0")||!strcmp(line,":prefix 1")){
            service_prefix_enabled=line[8]=='1';nx_prefix_invalidate(s);
            text("T25 CONFIG 1 ");value("prefix=",service_prefix_enabled);put('\n');continue;
        }
#endif
#ifndef NX_T25_UART
        if(!strcmp(line,":telemetry")){telemetry_report();continue;}
        if(!strcmp(line,":memory")){memory_report();continue;}
        if(!strcmp(line,":pressure on")||!strcmp(line,":pressure off")){
            rc=pressure_set(!strcmp(line,":pressure on"));if(rc)error(rc);continue;
        }
#endif
        if(line[0]==':'&&strcmp(line,":reset")&&strncmp(line,":ids ",5)&&strncmp(line,":verify ",8)&&strncmp(line,":text ",6)&&!action_request){
            error(NXR_INVALID);continue;
        }
#if NX_T27_SERVICE_ENHANCEMENTS
        /* This acknowledges only a received complete request line. Session
         * acceptance and model output are separate events below. */
        if(strcmp(line,":reset")){
            text("T25 RECEIVED 1 kind=");text(action_request?"action":"text");put('\n');
        }
#endif
        /* Failed hardware must drain/reset successfully before a new session. */
#ifndef NX_T25_UART
        if(REG(0x208)&0x38u){error(NXR_FAULT);
#if NX_T27_SERVICE_ENHANCEMENTS
            service_blocked=service_recover(s)!=0;
#endif
            continue;}
#endif
#ifdef NX_T25_CE64
        rc=nxr_ce64_platform_reset();if(rc){error(rc);
#if NX_T27_SERVICE_ENHANCEMENTS
            nx_prefix_invalidate(s);service_blocked=1;
#endif
            continue;}
#endif
#if NX_T27_SERVICE_ENHANCEMENTS
        int text_request=line[0]!=':'||!strncmp(line,":text ",6);
        if(!text_request&&!action_request){rc=nxr_reset(&request);if(rc){error(rc);continue;}}
#else
        rc=nxr_reset(&request);if(rc){error(rc);continue;}
#endif
        if(!strcmp(line,":reset")){text("T25 RESET\n");continue;}
        memset(route_calls,0,sizeof(route_calls));fallback_calls=dispatch_ticks=0;
        wire_bytes=0;
        int diagnostic=!strncmp(line,":verify ",8);
        rc=nxr_set_prefill(&request,diagnostic?0:service_prefill);
        if(!rc)rc=nxr_set_prefill_block(&request,diagnostic?NULL:service_block,diagnostic?1:service_rows);
        if(rc){error(rc);continue;}
#if NX_T27_SERVICE_ENHANCEMENTS
        service_take_profile(s,&profile_begin);profile_prefill=profile_begin;
        service_transfer_begin();
        int prefill_profile_taken=0,decode_phase_sent=0,request_announced=0;
        service_prefix.last_hit=0;service_prefix_captured=0;service_prefix_prepare_ticks=0;
        service_prefix_tokens=0;
#endif
        /* A tokenizer/begin failure has no current stream. Do not let its
         * cleanup refer to the previous request's completed stream/sink. */
        memset(&stream,0,sizeof(stream));
        if(action_request){
            action_pending=1;
            rc=begin_led_action(s,action_text,received);
        }else if(diagnostic||!strncmp(line,":ids ",5)){
            const char *p=line+(diagnostic?8:5);uint32_t maximum=0,count=0;
            rc=number(&p,&maximum);
            while(!rc&&*p){while(*p==' ')p++;if(!*p)break;if(count==NXR_INPUT_MAX){rc=NXR_BOUNDS;break;}rc=number(&p,&ids[count]);if(!rc)count++;}
            if(!rc)rc=nxr_begin_ids(&request,ids,count,maximum,
#if NX_T27_SERVICE_ENHANCEMENTS
                service_timeout_ticks
#else
                UINT64_C(10800000000000)
#endif
            );
        }else{
            const char *p=line;uint32_t maximum=128;
            if(!strncmp(line,":text ",6)){
                p=line+6;rc=number(&p,&maximum);
                if(!rc&&(!maximum||maximum>NXR_OUTPUT_MAX))rc=NXR_BOUNDS;
                /* Consume the separator only; preserve leading text spaces. */
                if(!rc){if(*p!=' '||!p[1])rc=NXR_INVALID;else p++;}
            }
            nxt_message message={"user",p,strlen(p)};
            if(!rc){
#if NX_T27_SERVICE_ENHANCEMENTS
                rc=service_begin_text(s,&message,maximum,received);
#else
                rc=nxr_begin_text(&request,&tokenizer,&token_work,&message,1,framed,sizeof(framed),maximum,UINT64_C(10800000000000));
#endif
            }
        }
#if NX_T27_SERVICE_ENHANCEMENTS
        if(!rc){request_announced=1;text("T25 REQUEST 1 ");value("session=",request.session);
            value("timeout_ticks=",request.timeout_ticks);value("prefix_hit=",service_prefix.last_hit);
            value("prefix_tokens=",service_prefix.last_hit?request.prefilled:request.prefill_boundary);put('\n');
            service_phase("prefill");}
        if(!rc)service_pmu_begin();
#endif
        nxs_uart wire={stream_put,0,stream_drain,0};
        /* :verify keeps its complete STEP/dump transcript; ordinary requests
         * decode each generated ID once and publish only UTF-8-complete text. */
        if(!rc)rc=nxs_open(&stream,&request,&tokenizer,output,sizeof(output),received,
                           stream_enabled&&!diagnostic,nxs_wire,&wire);
#if NX_T27_SERVICE_ENHANCEMENTS
        /* ABORT is a control record even when token previews are disabled.
         * It may revoke END once, until final publication/LED commit. */
        if(stream.request==&request)stream.terminal_abort=1;
#endif
        while(!rc&&(request.state==NXR_PREFILL||request.state==NXR_DECODE)){
#if NX_T27_SERVICE_ENHANCEMENTS
            rc=service_poll_control();if(rc)break;
#endif
            rc=nxr_step(&request);
#if NX_T27_SERVICE_ENHANCEMENTS
            if(!rc&&request.prefill_boundary&&request.prefilled==request.prefill_boundary){
                rc=nx_prefix_capture(s,&service_key,(const int32_t *)request.prompt,request.prefill_boundary);
                if(!rc){service_prefix_captured=1;service_prefix_prepare_ticks=request.prefill_ticks;request.prefill_boundary=0;}
            }
            if(!prefill_profile_taken&&request.prefilled==request.prompt_length){
                service_take_profile(s,&profile_prefill);prefill_profile_taken=1;
                service_pmu_prefill_done();
            }
            if(!rc)rc=service_poll_control();
#endif
            if(!rc)rc=nxs_update(&stream);
#if NX_T27_SERVICE_ENHANCEMENTS
            /* Publish the first model text before descriptive phase bytes. */
            if(!rc&&!decode_phase_sent&&request.state==NXR_DECODE){
                service_phase("decode");decode_phase_sent=1;
            }
#endif
            if(diagnostic){
                uint64_t print_start=nx_port_ticks();
                text("T25 STEP ");hex(request.prefilled);put(' ');hex(request.generated);put('\n');
                if(!rc)dump(s,1);
                stream_drain(0);stream.legacy_ticks+=nx_port_ticks()-print_start;
            }
        }
        /* END is a preview terminator. Final publication additionally requires
         * STOPPED and the application checks, including the stack guard. */
#if NX_T27_SERVICE_ENHANCEMENTS
        service_pmu_stop();
#endif
        uint32_t peak=0;if(!rc)rc=stack_peak(&peak);
        if(!rc)rc=nxs_finish(&stream);
#if NX_T27_SERVICE_ENHANCEMENTS
request_failure:
        if(rc&&(rc==NXR_CANCELLED||rc==NXR_TIMEOUT)&&request_announced&&stream.request==&request){
            int recovery=service_end_request(s,rc);
            if(!recovery)continue; /* Only this checked path returns to READY. */
            /* Only the original request reason may be a soft termination.
             * Driver NX_EIO/NX_ETIMEOUT reuse CANCELLED/TIMEOUT values; any
             * failed health/recovery gate is a hard fault, never a second
             * soft UART diagnostic. The D27 context retains driver detail. */
            rc=(recovery==NXR_CANCELLED||recovery==NXR_TIMEOUT)?NXR_FAULT:recovery;
        }
#endif
        if(rc){action_pending=0;nx_diag_runtime(((7u<<16)|__LINE__),rc,&request);nx_diag_dump(put);
            if(stream.active
#if NX_T27_SERVICE_ENHANCEMENTS
               ||(request_announced&&stream.request==&request&&!stream.aborted)
#endif
            )nxs_abort(&stream,rc);error(rc);
#if NX_T27_SERVICE_ENHANCEMENTS
            int diagnostic_recovery=service_recover(s);service_blocked=diagnostic_recovery!=0;nx_diag_recovery(diagnostic_recovery);
            text("D27 RECOVERY ");hex((uint32_t)diagnostic_recovery);put('\n');nx_diag_dump(put);
            text("D27 HALTED\n");stream_drain(0);
#ifdef NX_T25_SERVICE_TEST
            /* Host tests observe the same fail-stop boundary without executing
             * a RISC-V instruction on the native test machine. */
            extern void nx_t25_test_halt(void);nx_t25_test_halt();for(;;){}
#else
            for(;;)__asm__ volatile("wfi");
#endif
#endif
            continue;}
        uint64_t first=request.generated?request.token_at[0]-request.start_ticks:0;
        uint64_t print_start=nx_port_ticks();
        text("T25 IDS ");for(unsigned i=0;i<request.generated;i++){hex(nxr_output(&request,i));put(' ');}put('\n');
        text("T25 TEXTLEN 1 ");value("bytes=",stream.bytes);put('\n');
        text("T25 TEXT ");for(size_t i=0;i<stream.bytes;i++)put(output[i]);put('\n');stream_drain(0);
        stream.legacy_ticks+=nx_port_ticks()-print_start;stream.output_wire_bytes=wire_bytes;
#if NX_T27_SERVICE_ENHANCEMENTS
        service_phase("validating");
#endif
        /* Final compatibility bytes are inside the publication deadline too.
         * END and even a complete TEXT do not permit success without METRICS. */
        if(nx_port_ticks()-request.start_ticks>=request.timeout_ticks){
            action_pending=0;
#if NX_T27_SERVICE_ENHANCEMENTS
            rc=NXR_TIMEOUT;goto request_failure;
#else
            nxs_abort(&stream,NXR_TIMEOUT);error(NXR_TIMEOUT);
            continue;
#endif
        }
        if(action_request){
            uint32_t observed=UINT32_MAX,owned=UINT32_MAX,writes=0;
            int status=nx_led_program(&led_program,output,stream.bytes,&led_pending);
#if NX_T27_SERVICE_ENHANCEMENTS
            /* The phase is not an execution receipt. It precedes the final
             * cancel/deadline check, so UART time cannot bypass that gate. */
            if(status==APP_OK)service_phase("executing");
#endif
            /* Cancellation is honored even after EOS until this commit point. */
            int control=0;
#if NX_T27_SERVICE_ENHANCEMENTS
            control=service_poll_control();
#endif
            int final=nx_led_final(&request,!stream.active,control==NXR_CANCELLED,nx_port_ticks());
            if(final){
                const char *failure=final==NXR_CANCELLED?"CANCELLED":final==NXR_TIMEOUT?"TIMEOUT":"INCOMPLETE";
                if(action_bank_request){
                    (void)nx_led_bank_read(&led_io,&observed,&owned);
                    led_bank_result("T27 ACTION_BANK 1 ",failure,0,action_mask,observed,owned);
                }else{
                    text("T27 ACTION 1 ");value("session=",request.session);
                    text("status=");text(failure);text(" writes=0000000000000000\n");
                }
                action_pending=0;
#if NX_T27_SERVICE_ENHANCEMENTS
                if(final==NXR_CANCELLED||final==NXR_TIMEOUT){rc=final;goto request_failure;}
                /* A normal output/context limit is an incomplete program,
                 * not a backend fault. Every other invalid final state keeps
                 * the same fail-stop boundary as a computation failure. */
                if(final!=NXR_STATE||request.state!=NXR_STOPPED||request.error||request.busy||stream.active||
                   (request.stop!=NXR_STOP_OUTPUT&&request.stop!=NXR_STOP_CONTEXT)){
                    rc=final;goto request_failure;
                }
                service_finished_session=request.session;
#endif
                error(final);continue;
            }
            action_pending=0; /* linearization: no preview token can reach MMIO */
            if(action_bank_request){
                if(status==APP_OK)status=nx_led_bank_execute(&led_io,&led_pending,action_mask,&writes,&observed,&owned);
                else (void)nx_led_bank_read(&led_io,&observed,&owned);
                led_bank_result("T27 ACTION_BANK 1 ",app_status_name(status),writes,action_mask,observed,owned);
            }else{
                if(status==APP_OK)status=nx_led_execute(&led_io,&led_pending,&writes,&observed);
                else (void)nx_led_read(&led_io,&observed);
                led_result("T27 ACTION 1 ",status,writes,observed);
            }
        }
        if(!stream.enabled&&stream.bytes)stream.first_text=stream.last_text=nx_port_ticks()-received;
        stream.complete=nx_port_ticks()-received;nxs_timing(&stream,&wire);
        text("T25 METRICS ");value("session=",request.session);value("prompt=",request.prompt_length);
        value("generated=",request.generated);value("stop=",request.stop);value("kv=",request.kv_length);
        value("tokenizer_ticks=",request.tokenizer_ticks);value("prefill_ticks=",request.prefill_ticks);
        value("decode_ticks=",request.decode_ticks);value("total_ticks=",request.total_ticks);
        value("first_token_ticks=",first);value("stack_peak_bytes=",peak);
        value("cpu_calls=",route_calls[0]);value("ce_calls=",route_calls[2]);value("fallback_calls=",fallback_calls);
        value("dispatch_ticks=",dispatch_ticks);put('\n');
#if NX_T27_SERVICE_ENHANCEMENTS
        service_take_profile(s,&profile_end);
        if(!prefill_profile_taken)profile_prefill=profile_end;
        service_print_profile("REQUEST",&profile_begin,&profile_end);
        service_print_profile("PREFILL",&profile_begin,&profile_prefill);
        service_print_profile("DECODE",&profile_prefill,&profile_end);
        text("T25 PREFIX 1 ");value("session=",request.session);value("hit=",service_prefix.last_hit);
        value("captured=",service_prefix_captured);value("tokens=",service_prefix_tokens);
        value("prepare_ticks=",service_prefix_prepare_ticks);value("restore_ticks=",(text_request||action_request)?service_prefix.restore_ticks:0);put('\n');
        service_profile zero={0};service_print_profile("CUMULATIVE",&zero,&profile_end);
        service_pmu_print();
        service_transfer_print();
        service_finished_session=request.session;
#else
        double ticks[NX_TIMERS];uint64_t calls[NX_TIMERS];nx_profile(s,ticks,calls);
        text("T25 PROFILE CUMULATIVE ");for(unsigned i=0;i<NX_TIMERS;i++){hex(i);put(' ');value("ticks=",(uint64_t)ticks[i]);value("calls=",calls[i]);}put('\n');
#endif
    }
}
