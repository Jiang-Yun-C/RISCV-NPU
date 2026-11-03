#include "coral_linear.h"
#include <string.h>
static uint32_t rd(nx_context *c,uint32_t a){return c->io.read32(c->io.cookie,a);}
static void wr(nx_context *c,uint32_t a,uint32_t v){c->io.write32(c->io.cookie,a,v);}
static void fence(nx_context *c){c->io.fence(c->io.cookie);}
static int expired(nx_context *c,uint64_t start,uint64_t limit){return c->io.ticks(c->io.cookie)-start>=limit;}
nx_status nx_coral_linear_execute(void *cookie,const nx_call *call,const struct nx_stream_request *request,struct nx_stream_result *result){
    nx_coral_transport *t=cookie;
    if(!t||!t->context||!call||!request||!result)return NX_EINVAL;
    nx_context *c=t->context;nx_status s=NX_OK;uint64_t start=c->io.ticks(c->io.cookie);
    if(c->state!=NX_ACCEL_RUNNING||call->session!=c->session||request->abi!=NX_LINEAR_ABI||request->size!=96||
       request->session_lo!=(uint32_t)call->session||request->session_hi!=(uint32_t)(call->session>>32)||
       request->sequence_lo!=(uint32_t)call->sequence||request->sequence_hi!=(uint32_t)(call->sequence>>32))return NX_ESTATE;
    *result=(struct nx_stream_result){0};
    fence(c);
    if((rd(c,NX_BRIDGE_STATUS)&7)!=1){s=NX_EIO;goto fail;}
    /* Reset the halted core before each request; memories retain the uploaded
     * microprogram. CPU MMIO is serialized through the actual write response. */
    wr(c,NX_ACCEL_CONTROL,3);wr(c,NX_BRIDGE_CONTROL,1);wr(c,NX_BRIDGE_IRQ,1);
    for(unsigned i=0;i<26;i++)wr(c,NX_ACCEL_RESULT+4*i,0);
    for(unsigned i=0;i<24;i++){uint32_t v;memcpy(&v,(const unsigned char *)request+4*i,4);wr(c,NX_ACCEL_PARAMS+4*i,v);}
    wr(c,NX_ACCEL_ENTRY,c->program.entry);fence(c);
    if(rd(c,NX_ACCEL_ENTRY)!=c->program.entry||(rd(c,NX_BRIDGE_STATUS)&6)){s=NX_EIO;goto fail;}
    if(expired(c,start,call->timeout_ticks)){s=NX_ETIMEOUT;goto fail;}
    wr(c,NX_ACCEL_CONTROL,0);fence(c);
    for(;;){
        uint32_t bridge=rd(c,NX_BRIDGE_STATUS),status=rd(c,NX_ACCEL_STATUS);
        if(bridge&6){s=NX_EIO;goto fail;}
        if(status&2){s=NX_EFAULT;goto fail;}
        if(expired(c,start,call->timeout_ticks)){s=NX_ETIMEOUT;goto fail;}
        if((status&1)&&(bridge&1))break;
        if(t->wait)t->wait(t->wait_cookie);
    }
    for(unsigned i=0;i<26;i++){uint32_t v=rd(c,NX_ACCEL_RESULT+4*i);memcpy((unsigned char *)result+4*i,&v,4);}
    if(result->abi!=NX_LINEAR_ABI||result->size!=104||result->session_lo!=request->session_lo||result->session_hi!=request->session_hi||
       result->sequence_lo!=request->sequence_lo||result->sequence_hi!=request->sequence_hi){s=NX_EFAULT;goto fail;}
    if(result->status||result->valid!=1||
       !result->cycles||result->rows!=request->n*((request->m+3)/4)||result->tiles!=((request->n+127)/128)*((request->m+3)/4)){
        s=result->status==NX_ENUMERIC&&result->valid==0?NX_ENUMERIC:NX_EFAULT;goto fail;
    }
    if(rd(c,NX_BRIDGE_STATUS)&6){s=NX_EIO;goto fail;}
    if(expired(c,start,call->timeout_ticks)){s=NX_ETIMEOUT;goto fail;}
    wr(c,NX_BRIDGE_CONTROL,0);fence(c);
    if(rd(c,NX_BRIDGE_CONTROL)!=0||(rd(c,NX_BRIDGE_STATUS)&6)){s=NX_EIO;goto fail;}
    return NX_OK;
fail:
    wr(c,NX_BRIDGE_CONTROL,3);fence(c);c->fault_address=rd(c,NX_BRIDGE_ADDRESS);c->kv_valid=0;
    return s;
}
