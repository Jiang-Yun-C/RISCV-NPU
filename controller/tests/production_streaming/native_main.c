/* Run the actual production main/model/runtime/tokenizer/stream functions.
 * Only board I/O, clock and stack-canary observation are host substitutes.
 * Reduced real-model geometry and synthetic assets are NOT board evidence. */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <setjmp.h>
#include <sys/mman.h>
#include "runtime.h"
#define NX_T25_LED_MMIO_TEST 1
#if NX_T27_SERVICE_ENHANCEMENTS
/* Scope-limited callback injection for explicit action-gate test modes.
 * Ordinary numerical tests continue to use the untouched model callbacks. */
static int fixture_set_prefill_block(nxr_request *,nxr_prefill_block_fn,uint32_t);
#define nxr_set_prefill_block fixture_set_prefill_block
#endif
#define main t25_service_main
#include "../../firmware/runtime/board/main.c"
#undef main
#if NX_T27_SERVICE_ENHANCEMENTS
#undef nxr_set_prefill_block
#endif

static jmp_buf fixture_exit;
static uint64_t fixture_ticks;
static unsigned fixture_commands,fixture_stack_failure,fixture_final_timeout,fixture_text_prefix;
static unsigned fixture_bank_missing,fixture_bank_bad_caps,fixture_bank_bad_readback;
static unsigned fixture_bank_stores,fixture_legacy_stores;
static unsigned fixture_main_entries;
#if NX_T27_SERVICE_ENHANCEMENTS
static const char *fixture_cancel_mode;
static unsigned fixture_cancel_sent,fixture_cancel_at,fixture_capture_contract;
static unsigned fixture_action_gate,fixture_commit_timeout,fixture_executing_prefix;
static unsigned fixture_program_token=30,fixture_without_eos;
static unsigned fixture_recovery_mode,fixture_cancel_phase,fixture_duplicate_cancel,fixture_stale_replay;
static unsigned fixture_timeout_phase,fixture_timeout_injected,fixture_injected_phase;
static unsigned fixture_model_fault,fixture_reset_fault,fixture_reset_after_cancel,fixture_reset_calls;
static int fixture_reset_fault_code=NXR_FAULT,fixture_reset_error_observed;
static unsigned fixture_reset_error_at;
static unsigned fixture_partial_mode,fixture_partial_limit;
static uint64_t fixture_cancel_target;
static nxr_forward_fn fixture_real_forward;
static nxr_prefill_block_fn fixture_real_block;
static nxr_reset_fn fixture_real_reset;
static char fixture_cancel_wire[128];
static int fixture_reset_model(void *model){
    fixture_reset_calls++;
    int rc=fixture_real_reset(model);
    if((fixture_cancel_sent||fixture_timeout_injected)&&fixture_reset_fault&&
       ++fixture_reset_after_cancel==fixture_reset_fault){
        fixture_reset_error_observed=fixture_reset_fault_code;
        fixture_reset_error_at=fixture_reset_after_cancel;
        return fixture_reset_fault_code;
    }
    return rc;
}
static int fixture_action_forward(void *model,uint32_t token,uint32_t past,uint32_t *next){
    int rc=fixture_real_forward(model,token,past,next);
    if(!rc&&fixture_model_fault){fixture_model_fault=0;return NXR_FAULT;}
    if(!rc&&next)*next=fixture_without_eos?fixture_program_token:NXR_EOS;
    return rc;
}
static int fixture_action_block(void *model,const uint32_t *tokens,uint32_t rows,uint32_t past,uint32_t *next){
    int rc=fixture_real_block(model,tokens,rows,past,next);
    if(!rc&&fixture_model_fault&&past){fixture_model_fault=0;return NXR_FAULT;}
    if(!rc&&next)*next=fixture_program_token;
    return rc;
}
static int fixture_set_prefill_block(nxr_request *r,nxr_prefill_block_fn fn,uint32_t rows){
    if(!fixture_action_gate)return nxr_set_prefill_block(r,fn,rows);
    if(r->forward!=fixture_action_forward)fixture_real_forward=r->forward;
    if(r->reset!=fixture_reset_model)fixture_real_reset=r->reset;
    if(fixture_recovery_mode)r->reset=fixture_reset_model;
    r->forward=fixture_action_forward;fixture_real_block=fn;
    return nxr_set_prefill_block(r,fn?fixture_action_block:NULL,rows);
}
int nx_t25_test_poll_byte(void){
    if(fixture_cancel_wire[fixture_cancel_at]){
        if(fixture_partial_limit&&fixture_cancel_at>=fixture_partial_limit){
            if(fixture_partial_mode==2&&!fixture_timeout_injected){
                fixture_timeout_injected=1;fixture_ticks=request.start_ticks+request.timeout_ticks;
            }
            return -1;
        }
        return fixture_cancel_wire[fixture_cancel_at++];
    }
    int prefill=request.state==NXR_PREFILL&&request.prefilled>0&&request.generated==0;
    int decode=request.state==NXR_DECODE&&stream.seen>0;
    if(fixture_partial_mode&&!fixture_cancel_sent&&decode){
        fixture_cancel_target=request.session;fixture_injected_phase=2;
        snprintf(fixture_cancel_wire,sizeof(fixture_cancel_wire),":cancel %016llx\n",(unsigned long long)request.session);
        fixture_partial_limit=fixture_partial_mode==3?24u:16u;
        fixture_cancel_sent=1;fixture_cancel_at=1;return fixture_cancel_wire[0];
    }
    if(fixture_timeout_phase&&!fixture_timeout_injected&&
       ((fixture_timeout_phase==1&&prefill)||(fixture_timeout_phase==2&&decode))){
        fixture_timeout_injected=1;fixture_injected_phase=fixture_timeout_phase;
        fixture_ticks=request.start_ticks+request.timeout_ticks;return -1;
    }
    if(fixture_stale_replay&&fixture_cancel_sent&&request.session!=fixture_cancel_target&&decode){
        snprintf(fixture_cancel_wire,sizeof(fixture_cancel_wire),":cancel %016llx\n",(unsigned long long)fixture_cancel_target);
        fixture_stale_replay=0;fixture_cancel_at=1;return fixture_cancel_wire[0];
    }
    if(!fixture_cancel_mode||fixture_cancel_sent)return -1;
    if(fixture_cancel_phase==1&&!prefill)return -1;
    if(fixture_cancel_phase==2&&!decode)return -1;
    if(!fixture_cancel_phase&&request.generated<1)return -1;
    if(!strcmp(fixture_cancel_mode,"cancel-final")&&(stream.active||request.generated<2))return -1;
    unsigned long long target=(unsigned long long)(request.session+(!strcmp(fixture_cancel_mode,"stale")?9u:0u));
    fixture_cancel_target=(uint64_t)target;
    if(fixture_duplicate_cancel)snprintf(fixture_cancel_wire,sizeof(fixture_cancel_wire),":cancel %016llx\n:cancel %016llx\n",target,target);
    else snprintf(fixture_cancel_wire,sizeof(fixture_cancel_wire),":cancel %016llx\n",target);
    fixture_injected_phase=fixture_cancel_phase?fixture_cancel_phase:!strcmp(fixture_cancel_mode,"cancel-final")?3u:2u;
    fixture_cancel_sent=1;fixture_cancel_at=1;return fixture_cancel_wire[0];
}
static void capture_contract(void){
    nx_session *s=binding.session;const int32_t ids[3]={1,2,3},wrong[3]={1,2,4},invalid=-1;
    nx_prefix_identity changed=service_key;changed.numeric[0]^=1;
#define VERIFY_CAPTURE(expression) do{if(!(expression)){fputs("PREFIX_CAPTURE_CONTRACT_FAIL\n",stderr);exit(3);}}while(0)
    nx_reset(s);
    VERIFY_CAPTURE(nx_forward(s,ids,2,0,NULL,NULL)==0);
    VERIFY_CAPTURE(nx_prefix_capture(s,&service_key,ids,3)==NX_ARGUMENT);
    VERIFY_CAPTURE(nx_forward(s,ids+2,1,2,NULL,NULL)==0);
    VERIFY_CAPTURE(nx_prefix_capture(s,&service_key,wrong,3)==NX_ARGUMENT);
    VERIFY_CAPTURE(nx_prefix_capture(s,&changed,ids,3)==NX_ARGUMENT);
    VERIFY_CAPTURE(nx_prefix_capture(s,&service_key,ids,3)==0);
    VERIFY_CAPTURE(nx_prefix_restore(s,&service_key,ids,3)==1);
    VERIFY_CAPTURE(nx_forward(s,&invalid,1,3,NULL,NULL)==NX_ARGUMENT);
    VERIFY_CAPTURE(nx_prefix_capture(s,&service_key,ids,3)==NX_ARGUMENT);
    VERIFY_CAPTURE(nx_prefix_restore(s,&service_key,ids,3)==0);
    VERIFY_CAPTURE(nx_prefix_configure(s,&changed)==0);
    VERIFY_CAPTURE(nx_forward(s,ids,3,0,NULL,NULL)==0);
    VERIFY_CAPTURE(nx_prefix_capture(s,&service_key,ids,3)==NX_ARGUMENT);
    VERIFY_CAPTURE(nx_prefix_configure(s,&service_key)==0);
    nx_reset(s);fputs("PREFIX_CAPTURE_CONTRACT_PASS\n",stdout);
#undef VERIFY_CAPTURE
}
#endif
uint32_t nx_t25_test_led_read(uint32_t address){
#if !NX_LED_BANK
    if(address>=NX_LED_BANK_ID&&address<=NX_LED_BANK_RELEASE){
        fputs("UNEXPECTED_BANK_READ_IN_LEGACY_BUILD\n",stderr);exit(4);
    }
#endif
    return *(volatile uint32_t *)(uintptr_t)address;
}
void nx_t25_test_led_write(uint32_t address,uint32_t value){
    if(address==NX_LED_STATE){
        if(value>1){fputs("INVALID_LEGACY_LED_STORE\n",stderr);exit(4);}
        fixture_legacy_stores++;
        *(volatile uint32_t *)NX_LED_STATE=value;
#if NX_LED_BANK
        *(volatile uint32_t *)NX_LED_BANK_VALUES=(*(volatile uint32_t *)NX_LED_BANK_VALUES&~1u)|value;
        *(volatile uint32_t *)NX_LED_BANK_OWNED|=1u;
#endif
        return;
    }
#if NX_LED_BANK
    uint32_t mask=address==NX_LED_BANK_APPLY?(value>>8)&255u:value;
    if((address!=NX_LED_BANK_APPLY&&address!=NX_LED_BANK_RELEASE)||!nx_led_bank_mask_valid(mask)||
       (address==NX_LED_BANK_APPLY&&((value>>16)||((value&255u)&~mask)))){
        fputs("INVALID_ATOMIC_BANK_STORE\n",stderr);exit(4);
    }
    fixture_bank_stores++;
    if(fixture_bank_bad_readback){fixture_bank_bad_readback=0;return;}
    if(address==NX_LED_BANK_APPLY){
        *(volatile uint32_t *)NX_LED_BANK_VALUES=(*(volatile uint32_t *)NX_LED_BANK_VALUES&~mask)|(value&mask);
        *(volatile uint32_t *)NX_LED_BANK_OWNED|=mask;
    }else{
        *(volatile uint32_t *)NX_LED_BANK_VALUES&=~mask;
        *(volatile uint32_t *)NX_LED_BANK_OWNED&=~mask;
    }
    *(volatile uint32_t *)NX_LED_STATE=(*(volatile uint32_t *)NX_LED_BANK_VALUES&
                                     *(volatile uint32_t *)NX_LED_BANK_OWNED)&1u;
#else
    (void)value;fputs("UNEXPECTED_BANK_STORE_IN_LEGACY_BUILD\n",stderr);exit(4);
#endif
}
uint64_t nx_t25_test_ticks(void){return ++fixture_ticks;}
void nx_t25_test_put(char ch){
    static const char prefix[]="T25 TEXT ";
    fputc((unsigned char)ch,stdout);fixture_ticks++;
    if(ch==prefix[fixture_text_prefix])fixture_text_prefix++;
    else fixture_text_prefix=ch=='T'?1u:0u;
    if(fixture_text_prefix==sizeof(prefix)-1){
        fixture_text_prefix=0;
        if(fixture_final_timeout){
            fixture_ticks=request.start_ticks+request.timeout_ticks;
            fixture_final_timeout=0;
        }
    }
#if NX_T27_SERVICE_ENHANCEMENTS
    static const char executing[]="stage=executing\n";
    if(ch==executing[fixture_executing_prefix])fixture_executing_prefix++;
    else fixture_executing_prefix=ch=='s'?1u:0u;
    if(fixture_executing_prefix==sizeof(executing)-1){
        fixture_executing_prefix=0;
        if(fixture_commit_timeout){
            fixture_ticks=request.start_ticks+request.timeout_ticks;
            fixture_commit_timeout=0;
        }
    }
#endif
}
int nx_t25_test_stack_peak(uint32_t *peak){
    *peak=1024;return fixture_stack_failure?NXR_FAULT:0;
}
static uint64_t hash_bytes(uint64_t hash,const void *ptr,size_t bytes){
    const unsigned char *p=ptr;
    for(size_t i=0;i<bytes;i++)hash=(hash^p[i])*UINT64_C(1099511628211);
    return hash;
}
static void snapshot(void){
    if(!fixture_commands)return;
    uint64_t hash=UINT64_C(1469598103934665603);
    if(request.state==NXR_STOPPED){
        const float *logits=nx_logits_v2(binding.session);
        if(logits)hash=hash_bytes(hash,logits,32*sizeof(float));
        for(unsigned layer=0;layer<2;layer++)for(unsigned value=0;value<2;value++)
            hash=hash_bytes(hash,nx_cache(binding.session,layer,value),
                            (size_t)nx_length(binding.session)*4*sizeof(float));
    }
    fprintf(stderr,"{\"state\":%u,\"generated\":%u,\"stop\":%u,\"kv\":%u,\"numeric_hash\":\"%016llx\",\"bank_stores\":%u,\"legacy_stores\":%u",
        request.state,request.generated,request.stop,request.kv_length,(unsigned long long)hash,
        fixture_bank_stores,fixture_legacy_stores);
#if NX_T27_SERVICE_ENHANCEMENTS
    if(fixture_recovery_mode)fprintf(stderr,",\"fixture_main_entries\":%u,\"fixture_model_loads\":%u,\"fixture_commands\":%u,\"fixture_injected_phase\":%u,\"fixture_reset_calls\":%u,\"session\":%llu,\"control_partial_used\":%u,\"fixture_partial_limit\":%u,\"fixture_reset_error\":%d,\"fixture_reset_error_at\":%u",
        fixture_main_entries,fixture_model_load_count,fixture_commands,fixture_injected_phase,fixture_reset_calls,(unsigned long long)request.session,
        service_control.used,fixture_partial_limit,fixture_reset_error_observed,fixture_reset_error_at);
#endif
    fputs("}\n",stderr);
}
#if NX_T27_SERVICE_ENHANCEMENTS
void nx_t25_test_halt(void){snapshot();longjmp(fixture_exit,1);}
#endif
int nx_t25_test_read_line(char *buffer,size_t capacity){
#if NX_T27_SERVICE_ENHANCEMENTS
    if(fixture_capture_contract){fixture_capture_contract=0;capture_contract();}
#endif
    snapshot();
#if NX_T27_SERVICE_ENHANCEMENTS
    /* poll_byte and read_line are two readers of the same UART in production.
     * A complete duplicate cancel left after poll's LF must be consumed by
     * the idle command reader, not secretly held until the next model starts. */
    if(fixture_cancel_wire[fixture_cancel_at]){
        size_t used=0;
        while(fixture_cancel_wire[fixture_cancel_at]&&fixture_cancel_wire[fixture_cancel_at]!='\n'){
            if(used+1>=capacity){fputs("FIXTURE_CONTROL_LINE_OVERFLOW\n",stderr);exit(5);}
            buffer[used++]=fixture_cancel_wire[fixture_cancel_at++];
        }
        if(fixture_cancel_wire[fixture_cancel_at]=='\n')fixture_cancel_at++;
        buffer[used]=0;fixture_commands++;return (int)used;
    }
#endif
    if(!fgets(buffer,(int)capacity,stdin))longjmp(fixture_exit,1);
    size_t size=strlen(buffer);
    if(size&&buffer[size-1]=='\n')buffer[--size]=0;
    if(size&&buffer[size-1]=='\r')buffer[--size]=0;
    fixture_commands++;return (int)size;
}
static void map_region(uintptr_t address,size_t bytes){
    void *p=mmap((void *)address,bytes,PROT_READ|PROT_WRITE,
                MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED_NOREPLACE,-1,0);
    if(p==MAP_FAILED){perror("test mmap");exit(2);}
}
int main(int argc,char **argv){
    fixture_stack_failure=argc>1&&strcmp(argv[1],"stack-failure")==0;
    fixture_final_timeout=argc>1&&strcmp(argv[1],"final-timeout")==0;
    fixture_bank_missing=argc>1&&strcmp(argv[1],"bank-missing")==0;
    fixture_bank_bad_caps=argc>1&&strcmp(argv[1],"bank-bad-caps")==0;
    fixture_bank_bad_readback=argc>1&&strcmp(argv[1],"bank-readback-fail")==0;
#if NX_T27_SERVICE_ENHANCEMENTS
    if(argc>1&&(!strcmp(argv[1],"cancel")||!strcmp(argv[1],"stale")))fixture_cancel_mode=argv[1];
    if(argc>1&&!strcmp(argv[1],"integer-clock"))fixture_ticks=UINT64_C(1)<<54;
    if(argc>1&&!strcmp(argv[1],"capture-contract"))fixture_capture_contract=1;
    if(argc>1&&(!strcmp(argv[1],"led-eos")||!strcmp(argv[1],"led-final-timeout")||!strcmp(argv[1],"led-final-cancel"))){
        fixture_action_gate=1;
        fixture_commit_timeout=!strcmp(argv[1],"led-final-timeout");
        if(!strcmp(argv[1],"led-final-cancel"))fixture_cancel_mode="cancel-final";
    }
    if(argc>1&&(!strcmp(argv[1],"bank-multi-eos")||!strcmp(argv[1],"bank-invalid-eos")||!strcmp(argv[1],"bank-duplicate-eos")||
                !strcmp(argv[1],"bank-off-eos")||!strcmp(argv[1],"bank-no-eos"))){
        fixture_action_gate=1;
        fixture_program_token=!strcmp(argv[1],"bank-multi-eos")?29u:
                              !strcmp(argv[1],"bank-duplicate-eos")?27u:
                              !strcmp(argv[1],"bank-invalid-eos")?31u:
                              !strcmp(argv[1],"bank-off-eos")?28u:30u;
        fixture_without_eos=!strcmp(argv[1],"bank-no-eos");
    }
    if(argc>1&&!strncmp(argv[1],"recovery-",9)){
        const char *mode=argv[1]+9;
        fixture_recovery_mode=1;fixture_action_gate=1;
        if(!strcmp(mode,"prefill")||!strcmp(mode,"stack-failure")||!strcmp(mode,"reset-failure")||!strcmp(mode,"recover-failure")||!strcmp(mode,"recover-cancel-code")){
            fixture_cancel_mode="cancel";fixture_cancel_phase=1;
        }else if(!strcmp(mode,"decode")||!strcmp(mode,"duplicate")){
            fixture_cancel_mode="cancel";fixture_cancel_phase=2;
            fixture_duplicate_cancel=fixture_stale_replay=!strcmp(mode,"duplicate");
        }else if(!strcmp(mode,"final"))fixture_cancel_mode="cancel-final";
        else if(!strcmp(mode,"stale")){fixture_cancel_mode="stale";fixture_cancel_phase=2;}
        else if(!strcmp(mode,"partial-eos"))fixture_partial_mode=1;
        else if(!strcmp(mode,"partial-timeout"))fixture_partial_mode=2;
        else if(!strcmp(mode,"partial-lf"))fixture_partial_mode=3;
        else if(!strcmp(mode,"timeout-prefill"))fixture_timeout_phase=1;
        else if(!strcmp(mode,"recover-timeout-code"))fixture_timeout_phase=1;
        else if(!strcmp(mode,"timeout-decode"))fixture_timeout_phase=2;
        else if(!strcmp(mode,"timeout-final"))fixture_commit_timeout=1;
        else if(!strcmp(mode,"timeout-text"))fixture_final_timeout=1;
        else if(!strcmp(mode,"model-fault"))fixture_model_fault=1;
        else if(strcmp(mode,"none")){fputs("UNKNOWN_RECOVERY_FIXTURE_MODE\n",stderr);return 2;}
        fixture_stack_failure=!strcmp(mode,"stack-failure");
        fixture_reset_fault=!strcmp(mode,"reset-failure")?1u:!strcmp(mode,"recover-failure")?2u:0u;
        if(!strcmp(mode,"recover-cancel-code")){fixture_reset_fault=2;fixture_reset_fault_code=NXR_CANCELLED;}
        if(!strcmp(mode,"recover-timeout-code")){fixture_reset_fault=3;fixture_reset_fault_code=NXR_TIMEOUT;}
    }
#endif
    map_region(0x10000000u,4096);
    map_region(0xa8000000u,15728640);
    map_region(0xac000000u,2*1024*1024);
    map_region(0xba080000u,4096);
    *(volatile uint32_t *)0x100000e0u=2;
    *(volatile uint32_t *)NX_LED_ID=NX_LED_ABI;
    *(volatile uint32_t *)NX_LED_BANK_ID=fixture_bank_missing?0:NX_LED_BANK_ABI;
    *(volatile uint32_t *)NX_LED_BANK_CAPS=fixture_bank_bad_caps?255u:NX_LED_BANK_MASK;
    *(volatile uint32_t *)NX_LED_BANK_OWNED=1;
    if(!setjmp(fixture_exit)){fixture_main_entries++;t25_service_main();}
    return 0;
}
