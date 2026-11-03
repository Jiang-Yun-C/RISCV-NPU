#include "led_control.h"
#include "irq_events.h"
#include <string.h>
const char nx_led_system_prompt[]=
    "将用户指令编译为JSON程序数组。只支持LED灯，打开为[[\"led\",1]]，关闭为[[\"led\",0]]。"
    "只输出完整JSON，不要解释或代码块。未知设备或不支持的请求输出[[\"reject\",\"UNSUPPORTED\"]]。";
int nx_led_command(const char *s,uint32_t *v,int *write){
    if(!strcmp(s,":led?")){*write=0;return 1;}
    if(!strcmp(s,":led 0")||!strcmp(s,":led 1")){*v=(uint32_t)(s[5]-'0');*write=1;return 1;}
    return !strncmp(s,":led",4)?-1:0;
}
int nx_led_read(const nx_led_io *io,uint32_t *value){
    if(io->read(io->context,NX_LED_ID)!=NX_LED_ABI)return APP_STATE;
    *value=io->read(io->context,NX_LED_STATE);
    return *value<=1?APP_OK:APP_STATE;
}
int nx_led_set(const nx_led_io *io,uint32_t value,uint32_t *observed){
    if(value>1)return APP_RANGE;
#if NX_APP_IRQ
    nx_irq_led_override();
#endif
    uint32_t prior;int rc=nx_led_read(io,&prior);if(rc)return rc;
    io->write(io->context,NX_LED_STATE,value);io->fence(io->context);
    rc=nx_led_read(io,observed);
    return rc?rc:*observed==value?APP_OK:APP_STATE;
}
int nx_led_program(struct app_program *p,const char *json,size_t n,struct app_result *r){
    memset(r,0,sizeof(*r));int rc=app_parse(p,json,n);if(rc)return rc;
    const struct app_token *root=&p->tokens[p->root];
    if(root->count<1)return APP_FORMAT;
    for(int j=root->child;j>=0&&j<root->next;j=p->tokens[j].next){
        const struct app_token *node=&p->tokens[j];int op=node->child;
        if(node->kind!=1||node->count!=2||op<0||p->tokens[op].kind!=2||
           strcmp(p->tokens[op].string,"led"))return APP_UNSUPPORTED;
        int arg=p->tokens[op].next;
        if(arg>=node->next||p->tokens[arg].kind!=3)return APP_FORMAT;
        if(p->tokens[arg].number<0||p->tokens[arg].number>1)return APP_RANGE;
    }
    /* LED-only validation above excludes every sensor/conditional operation;
     * the old evaluator collects actions without consulting any real sensor. */
    const struct app_state no_sensors={0};
    return app_evaluate(p,&no_sensors,0,0,r);
}
int nx_led_final(const nxr_request *q,int complete,int cancelled,uint64_t now){
    if(cancelled)return NXR_CANCELLED;
    if(!q->timeout_ticks||now-q->start_ticks>=q->timeout_ticks)return NXR_TIMEOUT;
    if(!complete||q->state!=NXR_STOPPED||q->error||q->stop!=NXR_STOP_EOS||
       !q->generated||q->generated>NXR_OUTPUT_MAX||q->output[q->generated-1]!=NXR_EOS)return NXR_STATE;
    return 0;
}
int nx_led_execute(const nx_led_io *io,const struct app_result *r,uint32_t *writes,uint32_t *observed){
    *writes=0;
    /* Check the whole pending result again before the first store. */
    if(!r||r->count<1||r->count>APP_ACTION_MAX||r->read_mask)return APP_FORMAT;
    for(uint32_t i=0;i<r->count;i++)
        if(r->actions[i].device||r->actions[i].value>1)return APP_RANGE;
#if NX_APP_IRQ
    nx_irq_led_override();
#endif
    int rc=nx_led_read(io,observed);if(rc)return rc;
    for(uint32_t i=0;i<r->count;i++){
        io->write(io->context,NX_LED_STATE,r->actions[i].value);(*writes)++;
        io->fence(io->context);rc=nx_led_read(io,observed);
        if(!rc&&*observed!=r->actions[i].value)rc=APP_STATE;
        if(rc)return rc; /* already-issued stores are reported, never retried */
    }
    return APP_OK;
}
int nx_led_bank_mask_valid(uint32_t mask){return mask&&!(mask&~NX_LED_BANK_MASK);}
static int bank_number(const char **p,uint32_t *out){
    while(**p==' ')(*p)++;
    if(**p<'0'||**p>'9')return 0;
    uint32_t value=0;
    do{unsigned digit=(unsigned)(*(*p)++-'0');
        if(value>(UINT32_MAX-digit)/10u)return 0;value=value*10u+digit;
    }while(**p>='0'&&**p<='9');
    if(**p&&**p!=' ')return 0;*out=value;return 1;
}
int nx_led_bank_command(const char *s,uint32_t *mask,uint32_t *values,int *kind){
    *mask=*values=0;
    if(!strcmp(s,":ledm?")){*mask=NX_LED_BANK_MASK;*kind=NX_LED_BANK_QUERY_COMMAND;return 1;}
    if(!strncmp(s,":ledm ",6)){
        const char *p=s+6;*kind=NX_LED_BANK_APPLY_COMMAND;
        if(!bank_number(&p,mask)||*p!=' '||!bank_number(&p,values)||*p)return -1;
        return 1;
    }
    if(!strncmp(s,":ledauto ",9)){
        const char *p=s+9;*kind=NX_LED_BANK_RELEASE_COMMAND;
        if(!bank_number(&p,mask)||*p)return -1;return 1;
    }
    return !strncmp(s,":ledm",5)||!strncmp(s,":ledauto",8)?-1:0;
}
int nx_led_bank_read(const nx_led_io *io,uint32_t *values,uint32_t *owned){
    if(!values||!owned)return APP_FORMAT;*values=*owned=UINT32_MAX;
#if NX_LED_BANK
    if(!io||!io->read)return APP_STATE;
    if(io->read(io->context,NX_LED_BANK_ID)!=NX_LED_BANK_ABI||
       io->read(io->context,NX_LED_BANK_CAPS)!=NX_LED_BANK_MASK)return APP_STATE;
    uint32_t v=io->read(io->context,NX_LED_BANK_VALUES),o=io->read(io->context,NX_LED_BANK_OWNED);
    if((v|o)&~NX_LED_BANK_MASK)return APP_STATE;
    *values=v;*owned=o;return APP_OK;
#else
    (void)io;return APP_UNSUPPORTED;
#endif
}
#if NX_LED_BANK
static int bank_store(const nx_led_io *io,uint32_t mask,uint32_t values,int release,
                      uint32_t *writes,uint32_t *observed,uint32_t *owned){
    if(!io||!io->write||!io->fence)return APP_STATE;
#if NX_APP_IRQ
    nx_irq_led_override();
#endif
    uint32_t before_values,before_owned;
    int rc=nx_led_bank_read(io,&before_values,&before_owned);if(rc)return rc;
    uint32_t expect_values=(before_values&~mask)|(release?0:values);
    uint32_t expect_owned=release?(before_owned&~mask):(before_owned|mask);
    io->write(io->context,release?NX_LED_BANK_RELEASE:NX_LED_BANK_APPLY,
               release?mask:(mask<<8)|values);(*writes)++;
    io->fence(io->context);rc=nx_led_bank_read(io,observed,owned);
    if(!rc&&(*observed!=expect_values||*owned!=expect_owned))rc=APP_STATE;
    return rc; /* Failed readback is reported; stores are never retried. */
}
#endif
int nx_led_bank_apply(const nx_led_io *io,uint32_t mask,uint32_t values,
                      uint32_t *writes,uint32_t *observed,uint32_t *owned){
    if(!writes||!observed||!owned)return APP_FORMAT;
    *writes=0;*observed=*owned=UINT32_MAX;
    if(!nx_led_bank_mask_valid(mask)||(values&~mask))return APP_RANGE;
#if NX_LED_BANK
    return bank_store(io,mask,values,0,writes,observed,owned);
#else
    (void)io;return APP_UNSUPPORTED;
#endif
}
int nx_led_bank_release(const nx_led_io *io,uint32_t mask,
                        uint32_t *writes,uint32_t *observed,uint32_t *owned){
    if(!writes||!observed||!owned)return APP_FORMAT;
    *writes=0;*observed=*owned=UINT32_MAX;
    if(!nx_led_bank_mask_valid(mask))return APP_RANGE;
#if NX_LED_BANK
    return bank_store(io,mask,0,1,writes,observed,owned);
#else
    (void)io;return APP_UNSUPPORTED;
#endif
}
int nx_led_bank_execute(const nx_led_io *io,const struct app_result *r,uint32_t mask,
                        uint32_t *writes,uint32_t *observed,uint32_t *owned){
    if(!writes||!observed||!owned)return APP_FORMAT;
    *writes=0;*observed=*owned=UINT32_MAX;
    if(!nx_led_bank_mask_valid(mask))return APP_RANGE;
    if(!r||r->count<1||r->count>APP_ACTION_MAX||r->read_mask)return APP_FORMAT;
    for(uint32_t i=0;i<r->count;i++)
        if(r->actions[i].device||r->actions[i].value>1)return APP_RANGE;
#if NX_LED_BANK
    for(uint32_t i=0;i<r->count;i++){
        int rc=bank_store(io,mask,r->actions[i].value?mask:0,0,writes,observed,owned);
        if(rc)return rc;
    }
    return APP_OK;
#else
    (void)io;return APP_UNSUPPORTED;
#endif
}
