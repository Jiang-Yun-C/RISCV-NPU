#include "application.h"
#include <string.h>
#define MMIO(a) (*(volatile uint32_t *)(uintptr_t)(a))
static char text[4097],intent[4097],header[128];static struct app_program program;
static uint32_t tick(void){uint32_t t;__asm__ volatile("csrr %0,mcycle":"=r"(t));return t;}
static void delay(void){uint32_t t=tick();while((uint32_t)(tick()-t)<64u){}}
static void tx(char c){while(MMIO(0x10000004)&1u){}MMIO(0x10000000)=(unsigned char)c;}
static void put(const char *s){while(*s)tx(*s++);}
static void number(uint32_t n){char s[10];unsigned k=0;do{s[k++]=(char)('0'+n%10u);n/=10u;}while(n);while(k)tx(s[--k]);}
static void signed_number(int32_t n){if(n<0){tx('-');number(0u-(uint32_t)n);}else number((uint32_t)n);}
static int rx(void){uint32_t start=tick();while(!(MMIO(0x10000004)&2u))if((uint32_t)(tick()-start)>20000000u)return -1;return (int)MMIO(0x10000008);}
static void quoted(const char *s){static const char hex[]="0123456789abcdef";tx('"');for(;*s;s++){unsigned char c=(unsigned char)*s;if(c=='"'||c=='\\'){tx('\\');tx((char)c);}else if(c<32){put("\\u00");tx(hex[c>>4]);tx(hex[c&15]);}else tx((char)c);}tx('"');}
static int line(char *s,size_t capacity){size_t n=0;for(;;){int c=rx();if(c<0)return -1;if(c=='\n'){s[n]=0;return 0;}if(n+1>=capacity)return -1;s[n++]=(char)c;}}
static int payload(char *s,uint32_t n){for(uint32_t i=0;i<n;i++){int c=rx();if(c<=0)return -1;s[i]=(char)c;}s[n]=0;return rx()=='\n'?0:-1;}
static void pins(uint32_t n){MMIO(0x10001100)=n;delay();}
static int high(uint32_t sda){pins(1u|(sda<<1));uint32_t t=tick();while(!(MMIO(0x10001104)&1u))if((uint32_t)(tick()-t)>10000u)return APP_TIMEOUT;return APP_OK;}
static void stop(void){pins(0);pins(1);pins(3);}
static int sensor_read(struct app_state *state){
    uint8_t data[16];int rc=0;pins(3);pins(1);pins(0);uint32_t address=0x91;
    for(int b=7;b>=0;b--){uint32_t bit=(address>>(unsigned)b)&1u;pins(bit<<1);rc=high(bit);if(rc)goto done;pins(bit<<1);}
    pins(2);rc=high(1);if(rc)goto done;rc=(MMIO(0x10001104)&2u)?APP_NACK:APP_OK;pins(2);if(rc)goto done;
    for(unsigned k=0;k<16;k++){
        unsigned v=0;for(int b=7;b>=0;b--){rc=high(1);if(rc)goto done;v=(v<<1)|((MMIO(0x10001104)>>1)&1u);pins(2);}data[k]=(uint8_t)v;
        pins(k==15?2:0);rc=high(k==15);if(rc)goto done;pins(2);
    }
    memcpy(state,data,sizeof(*state));
done:stop();return rc;
}
uint32_t trap_handler(uint32_t cause,uint32_t pc,uint32_t value){(void)pc;(void)value;MMIO(0x10001200)=0xdead0000u|cause;for(;;){}return 0;}
int main(void){
    uint32_t last=0;put("READY T20 UART_INTENT_REPLAY\n");
    for(;;){
        if(line(header,sizeof(header)))break;if(!strcmp(header,"END"))break;
        char *p=header;uint32_t fields[4]={0};int bad=0;
        for(unsigned k=0;k<4;k++){if(*p<'0'||*p>'9'){bad=1;break;}
            while(*p>='0'&&*p<='9'){uint32_t d=(uint32_t)(*p++-'0');if(fields[k]>(UINT32_MAX-d)/10u){bad=1;break;}fields[k]=fields[k]*10u+d;}
            if(bad||(k<3?*p!=' ':*p!=0)){bad=1;break;}p++;
        }
        if(bad||fields[2]>4096||fields[3]>4096)break;
        uint32_t id=(uint32_t)fields[0],epoch=(uint32_t)fields[1];
        if(payload(text,(uint32_t)fields[2])||payload(intent,(uint32_t)fields[3]))break;
        MMIO(0x10001008)=id;
        struct app_result result={0};struct app_state state={0};int rc=APP_REQUEST_ID;
        if(id>last&&id!=UINT32_MAX){last=id;rc=app_parse(&program,intent,(size_t)fields[3]);
            if(!rc)rc=sensor_read(&state);if(!rc)rc=app_evaluate(&program,&state,epoch,tick(),&result);
            if(!rc)for(uint32_t k=0;k<result.count;k++)MMIO(result.actions[k].device?0x10001004:0x10001000)=result.actions[k].value;
        }
        put("{\"id\":");number(id);put(",\"text\":");quoted(text);put(",\"intent\":");quoted(intent);
        put(",\"intent_fnv32\":");number(app_fingerprint(intent,(size_t)fields[3]));
        put(",\"temperature\":");signed_number(state.temperature);put(",\"light\":");number(state.light);
        put(",\"epoch\":");number(state.epoch);put(",\"sampled_at\":");number(state.sampled_at);
        put(",\"validation\":");quoted(app_status_name(rc));put(",\"actions\":[");
        for(uint32_t k=0;k<result.count;k++){if(k)tx(',');put("[");quoted(result.actions[k].device?"pwm":"led");tx(',');number(result.actions[k].value);tx(']');}
        put("],\"readings\":{");if(result.read_mask&1){put("\"temperature\":");signed_number(state.temperature);}if(result.read_mask&2){if(result.read_mask&1)tx(',');put("\"light\":");number(state.light);}put("}}\n");
        put("RESULT ");number(id);tx(' ');put(app_status_name(rc));tx('\n');
    }
    put("DONE T20\n");MMIO(0x10001200)=0x2000;for(;;){}return 0;
}
