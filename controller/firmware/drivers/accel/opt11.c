#include "opt11.h"
#include <stddef.h>
extern int nx_swiglu(const float *,const float *,int,float *);
extern int nx_opt11_software_quantize(const float *,uint32_t,uint32_t,int8_t *,float *);
extern int nx_quantize(const float *,int,int,int8_t *,float *);
static uint32_t hardware_enabled;
nx_status nx_opt11_configure(nx_ce64_context *c,uint32_t enabled){
    if(!c||!c->base.initialized||enabled>1)return NX_EINVAL;
    if(c->base.state!=NX_ACCEL_IDLE)return NX_ESTATE;
    hardware_enabled=enabled;return NX_OK;
}
static int region(uint32_t a,uint32_t n){uint64_t end=(uint64_t)a+n;
    return n&&end<=UINT64_C(0x100000000)&&!(a&15)&&
      ((a>=0xac000000u&&end<=0xb4000000u)||(a>=0xba000000u&&end<=0xbc000000u));}
static nx_status begin(nx_ce64_transport *t,const nx_call *call){
    if(!t||!t->context||!call)return NX_EINVAL;
    nx_ce64_context *c=t->context;
    if(!c->base.initialized||c->base.state!=NX_ACCEL_IDLE||call->session!=c->base.session||
       c->base.sequence==UINT64_MAX||call->sequence!=c->base.sequence+1)return NX_ESTATE;
    if(call->api_version!=2||call->route!=NX_CE64||!call->timeout_ticks)return NX_EINVAL;
    c->base.state=NX_ACCEL_RUNNING;return NX_OK;
}
static nx_status finish(nx_ce64_transport *t,const nx_call *call,const struct nx_stream_request *request,struct nx_stream_result *result){
    nx_ce64_context *c=t->context;uint32_t before=c->generation;
    uint64_t started=c->base.io.ticks(c->base.io.cookie);
    nx_status status=nx_ce64_linear_execute(t,call,request,result);
    if(c->generation!=before)c->base.sequence=call->sequence;
    if(!status&&c->base.io.ticks(c->base.io.cookie)-started>=call->timeout_ticks)status=NX_ETIMEOUT;
    if(!status){
        c->base.io.fence(c->base.io.cookie);
        c->base.io.write32(c->base.io.cookie,CE64_MMIO_BASE+CE64_ACK,c->acquired_generation);
        c->base.io.fence(c->base.io.cookie);
        c->base.io.write32(c->base.io.cookie,NX_BRIDGE_CONTROL,0);
        c->base.io.fence(c->base.io.cookie);
        if(c->base.io.read32(c->base.io.cookie,NX_BRIDGE_CONTROL)!=0||
           (c->base.io.read32(c->base.io.cookie,NX_BRIDGE_STATUS)&6))status=NX_EIO;
    }
    if(status){
        c->base.io.write32(c->base.io.cookie,NX_BRIDGE_CONTROL,3);
        c->base.io.write32(c->base.io.cookie,CE64_MMIO_BASE+CE64_CONTROL,CE64_CTL_ISOLATE);
        c->base.io.fence(c->base.io.cookie);c->base.state=NX_ACCEL_FAULTED;
    }else c->base.state=NX_ACCEL_IDLE;
    return status;
}
nx_status nx_opt11_run(nx_ce64_transport *t,const nx_call *call,const nx_opt11_job *j,nx_opt11_view *view,struct nx_stream_result *result){
    if(!j||!view||!result)return NX_EINVAL;
    *view=(nx_opt11_view){0};*result=(struct nx_stream_result){0};
    if(!j->k||j->k>4864||j->quantize_only>1)return NX_EINVAL;
    uint32_t a[5]={j->gate,j->up,j->aq,j->sa,j->fp32};
    uint32_t n[5]={j->k*4,j->k*4,((j->k+63)/64)*64,((j->k+63)/64)*4,j->k*4};
    for(unsigned i=0;i<5;i++)if(i!=4||a[i]){
        if(!region(a[i],n[i]))return NX_EBOUNDS;
        for(unsigned k=0;k<i;k++)if((uint64_t)a[i]<(uint64_t)a[k]+n[k]&&(uint64_t)a[k]<(uint64_t)a[i]+n[i])return NX_EBOUNDS;
    }
    if(!hardware_enabled&&!j->fp32)return NX_EINVAL;
    nx_status status=begin(t,call);if(status)return status;
    if(!hardware_enabled){
        uint64_t started=t->context->base.io.ticks(t->context->base.io.cookie);
        float *output=(void *)(uintptr_t)j->fp32;
        if(j->quantize_only){
            /* The original quantizer validates finite input before accepting
             * the view. Output workspace is diagnostic and private. */
            for(uint32_t i=0;i<j->k;i++)output[i]=((const float *)(uintptr_t)j->gate)[i];
        }else if(nx_swiglu((void *)(uintptr_t)j->gate,(void *)(uintptr_t)j->up,(int)j->k,output))status=NX_ENUMERIC;
        if(!status){
            int quantized=j->k%64 ? nx_quantize(output,1,(int)j->k,(void *)(uintptr_t)j->aq,(void *)(uintptr_t)j->sa) :
                nx_opt11_software_quantize(output,1,j->k,(void *)(uintptr_t)j->aq,(void *)(uintptr_t)j->sa);
            if(quantized)status=NX_ENUMERIC;
        }
        if(!status)for(uint32_t i=j->k;i<((j->k+63)/64)*64;i++)((uint8_t *)(uintptr_t)j->aq)[i]=0;
        t->context->base.io.fence(t->context->base.io.cookie);
        result->cycles=t->context->base.io.ticks(t->context->base.io.cookie)-started;
        if(!status&&result->cycles>=call->timeout_ticks)status=NX_ETIMEOUT;
        t->context->base.sequence=call->sequence;t->context->base.state=NX_ACCEL_IDLE;
        if(!status)*view=(nx_opt11_view){.version=1,.valid=1,.epoch=t->context->epoch,.aq=j->aq,.sa=j->sa,.k=j->k,.session=call->session,.sequence=call->sequence};
        result->valid=!status;result->status=status;return status;
    }
    struct nx_stream_request request={.abi=NX_LINEAR_ABI,.size=96,.session_lo=(uint32_t)call->session,.session_hi=(uint32_t)(call->session>>32),
        .sequence_lo=(uint32_t)call->sequence,.sequence_hi=(uint32_t)(call->sequence>>32),.opcode=3,.m=1,.n=1,.k=j->k,
        .source=j->gate,.scales=j->up,.destination=j->fp32,.aq=j->aq,.sa=j->sa,.output_stride=j->quantize_only};
    status=finish(t,call,&request,result);
    if(!status)*view=(nx_opt11_view){.version=1,.valid=1,.epoch=t->context->epoch,.aq=j->aq,.sa=j->sa,.k=j->k,.session=call->session,.sequence=call->sequence};
    return status;
}
nx_status nx_opt11_down(nx_ce64_transport *t,const nx_call *call,nx_opt11_view *view,const struct nx_stream_request *sealed,struct nx_stream_result *result){
    if(!t||!t->context||!call||!view||!sealed||!result)return NX_EINVAL;
    if(view->version!=1||!view->valid||view->epoch!=t->context->epoch||view->session!=call->session||
       view->sequence!=t->context->base.sequence||call->sequence!=view->sequence+1)return NX_ESTATE;
    if(sealed->m!=1||sealed->k!=view->k||(view->k!=896&&view->k!=4864))return NX_EUNSUPPORTED;
    nx_status status=begin(t,call);if(status)return status;
    struct nx_stream_request request=*sealed;
    request.abi=NX_LINEAR_ABI;request.size=96;request.opcode=2;request.aq=view->aq;request.sa=view->sa;
    request.session_lo=(uint32_t)call->session;request.session_hi=(uint32_t)(call->session>>32);
    request.sequence_lo=(uint32_t)call->sequence;request.sequence_hi=(uint32_t)(call->sequence>>32);
    view->valid=0;return finish(t,call,&request,result);
}
