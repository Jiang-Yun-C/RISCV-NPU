/* Transport control unit test only. This is not an arithmetic RTL substitute. */
#include "coral_linear.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
struct platform {uint32_t control,owner,request[24],result[26],starts,reads,release;uint64_t tick;int mode;};
static uint32_t rd(void *cookie,uint32_t a){
    struct platform *p=cookie;
    if(a==NX_BRIDGE_STATUS){p->reads++;return p->mode==2&&p->starts?5:p->starts&&p->reads<25?0:1;}
    if(a==NX_ACCEL_STATUS)return p->mode==3?2:p->mode==4?0:1;
    if(a==NX_ACCEL_ENTRY)return 0;
    if(a==NX_BRIDGE_CONTROL)return p->owner;
    if(a>=NX_ACCEL_RESULT&&a<NX_ACCEL_RESULT+104)return p->result[(a-NX_ACCEL_RESULT)/4];
    return 0;
}
static void wr(void *cookie,uint32_t a,uint32_t v){
    struct platform *p=cookie;
    if(a==NX_BRIDGE_CONTROL){if(v==0){assert(p->reads>=25);p->release++;}p->owner=v;}
    if(a>=NX_ACCEL_RESULT&&a<NX_ACCEL_RESULT+104)p->result[(a-NX_ACCEL_RESULT)/4]=v;
    if(a>=NX_ACCEL_PARAMS&&a<NX_ACCEL_PARAMS+96)p->request[(a-NX_ACCEL_PARAMS)/4]=v;
    if(a==NX_ACCEL_CONTROL&&v==0){
        p->starts++;struct nx_stream_result r={.abi=NX_LINEAR_ABI,.size=104,.session_lo=1,.sequence_lo=p->mode==1?2:1,.valid=1,.rows=4,.tiles=1,.cycles=10};
        if(p->mode==5){r.status=NX_ENUMERIC;r.valid=0;}
        memcpy(p->result,&r,104);
    }
}
static uint64_t ticks(void *cookie){return ++((struct platform *)cookie)->tick;}
static void fence(void *cookie){(void)cookie;}
int main(void){
    for(int mode=0;mode<6;mode++){
        struct platform p={.mode=mode};nx_context c={.session=1,.initialized=1,.state=NX_ACCEL_RUNNING,.io={.cookie=&p,.read32=rd,.write32=wr,.ticks=ticks,.fence=fence,.tick_hz=1}};
        nx_coral_transport t={.context=&c};nx_call call={.session=1,.sequence=1,.timeout_ticks=100};
        struct nx_stream_request request={.abi=NX_LINEAR_ABI,.size=96,.session_lo=1,.sequence_lo=1,.m=1,.n=4};struct nx_stream_result result;
        int status=nx_coral_linear_execute(&t,&call,&request,&result);
        const int expected[]={0,-8,-11,-8,-7,-9};assert(status==expected[mode]);assert(p.starts==1);
        assert(p.owner==(mode?3:0));assert(p.release==(mode?0:1));
    }
    puts("PASS native transport: late drain, identity, IO, core, timeout, numeric isolation");
}
