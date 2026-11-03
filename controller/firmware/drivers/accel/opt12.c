#include "opt12.h"
#include "opt10_norm_catalog.h"
#include <math.h>
extern int nx_norm(const float *,const float *,int,int,float *);
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
static nx_status call_ready(nx_ce64_transport *t,const nx_call *call){
    if(!t||!t->context||!call)return NX_EINVAL;
    nx_ce64_context *c=t->context;
    if(!c->base.initialized||c->base.state!=NX_ACCEL_IDLE||call->session!=c->base.session||
       c->base.sequence==UINT64_MAX||call->sequence!=c->base.sequence+1)return NX_ESTATE;
    if(call->api_version!=2||call->route!=NX_CE64||!call->timeout_ticks)return NX_EINVAL;
    return NX_OK;
}
static nx_status begin(nx_ce64_transport *t,const nx_call *call){
    nx_status status=call_ready(t,call);if(status)return status;
    t->context->base.state=NX_ACCEL_RUNNING;return NX_OK;
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
        nx_diag_capture(((4u<<16)|__LINE__),status,c,call,request);
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
        .source=j->gate,.scales=j->quantize_only?0:j->up,.destination=j->fp32,.aq=j->aq,.sa=j->sa,.output_stride=j->quantize_only};
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

/* Explicit candidate selection; default CPU mode survives reset/reload. */
nx_status nx_opt12_configure(nx_ce64_context *c,uint32_t enabled){return nx_opt11_configure(c,enabled);}
nx_status nx_opt12_acquire(nx_ce64_context *c,const nx_opt12_view *v){
    if(!c||!v)return NX_EINVAL;
    return v->valid&&v->epoch==c->epoch&&v->session==c->base.session&&
        v->sequence==c->base.sequence&&c->base.state==NX_ACCEL_IDLE ? NX_OK : NX_ESTATE;
}
static int vec_finite(float x){union{float f;uint32_t u;}v={.f=x};return (v.u&0x7f800000u)!=0x7f800000u;}
static float vec_work[8192];
static int sealed_norm_authorized(nx_ce64_transport *t,const nx_call *call,const nx_opt12_job *j){
    if(!t||!t->context||!call||!j||j->mode!=7||j->quantize||j->scalar||
       !nx_opt10_norm_member(j->up,j->k*4,j->k))return 0;
    nx_ce64_context *c=t->context;nx_linear_binding *b=c->binding;
    return c->base.initialized&&c->base.state==NX_ACCEL_IDLE&&b&&b->context==&c->base&&
        b->sealed_norm_read&&b->sealed_norm_read(b->cookie,j->up,j->k*4,j->k,c->epoch,call->session);
}
static int resident_fields(const nx_opt12_job *j){
    return j->resident_rows||j->resident_row||j->resident_fp_base||j->resident_first_sequence;
}
static int resident_authorized(nx_ce64_transport *t,const nx_call *call,const nx_opt12_job *j){
    if(!t||!t->context||!call||!j||!hardware_enabled||j->mode||j->quantize||j->scalar||j->k!=4864||
       j->resident_rows<1||j->resident_rows>4||j->resident_row>=j->resident_rows||
       !j->resident_first_sequence||j->resident_first_sequence>UINT64_MAX-j->resident_rows||
       call->sequence!=j->resident_first_sequence+j->resident_row)return 0;
    nx_ce64_context *c=t->context;nx_linear_binding *b=c->binding;
    uint32_t bytes=j->resident_rows*4864u;
    if(!c->base.initialized||c->base.state!=NX_ACCEL_IDLE||call->session!=c->base.session||
       !b||b->context!=&c->base||b->aq_bytes<bytes||b->sa_bytes<j->resident_rows*304u||
       !region(b->aq_address,b->aq_bytes)||!region(b->sa_address,b->sa_bytes)||
       b->aq_address<0xba000000u||b->sa_address<0xba000000u||
       j->aq!=b->aq_address+j->resident_row*4864u||j->sa!=b->sa_address+j->resident_row*304u||
       !region(j->resident_fp_base,bytes*4u)||j->resident_fp_base<0xac000000u||j->resident_fp_base>=0xb4000000u||
       j->fp32!=j->resident_fp_base+j->resident_row*4864u*4u)return 0;
    return c->base.io.read32(c->base.io.cookie,CE64_MMIO_BASE+CE64_AQSA_CAPABILITY)==CE64_AQSA_MAGIC;
}
static nx_status opt12_run(nx_ce64_transport *t,const nx_call *call,const nx_opt12_job *j,nx_opt12_view *view,struct nx_stream_result *result,int sealed_norm,int resident){
    if(!j||!view||!result)return NX_EINVAL;
    *view=(nx_opt12_view){0};*result=(struct nx_stream_result){0};
    if((!resident&&resident_fields(j))||(resident&&!resident_authorized(t,call,j)))return NX_EINVAL;
    if(!j->k||j->k>4864||j->mode>7||j->quantize>1||
       ((j->mode==5||j->mode==6)&&j->quantize)||
       (j->mode==4 ? (j->scalar&0x7f800000u)==0x7f800000u : j->scalar!=0))return NX_EINVAL;
    uint32_t quant=j->mode<2||j->quantize,needs_up=j->mode==0||j->mode==2||j->mode==3||j->mode==7;
    if(!j->fp32&&!quant)return NX_EINVAL;
    if(sealed_norm&&!sealed_norm_authorized(t,call,j))return NX_EBOUNDS;
    nx_linear_binding *authority=(sealed_norm||resident)?t->context->binding:NULL;
    nx_sealed_norm_read_fn authorize=sealed_norm?authority->sealed_norm_read:NULL;
    void *authority_cookie=sealed_norm?authority->cookie:NULL;
    uint32_t authority_epoch=(sealed_norm||resident)?t->context->epoch:0;
    uint32_t a[5]={j->gate,j->up,j->aq,j->sa,j->fp32};
    uint32_t n[5]={j->k*4,needs_up?j->k*4:0,quant?((j->k+63)/64)*64:0,quant?((j->k+63)/64)*4:0,
        j->fp32?((j->mode==5||j->mode==6)?4:j->k*4):0};
    for(unsigned i=0;i<5;i++){
        if(!n[i]){if(a[i])return NX_EBOUNDS;continue;}
        if(!region(a[i],n[i])&&!(sealed_norm&&i==1&&
            nx_opt10_norm_member(a[i],n[i],j->k)))return NX_EBOUNDS;
        for(unsigned k=0;k<i;k++)if(n[k]&&(uint64_t)a[i]<(uint64_t)a[k]+n[k]&&(uint64_t)a[k]<(uint64_t)a[i]+n[i]){
            if(i==4&&(k==0||k==1)&&j->mode>=2&&j->mode!=5&&j->mode!=6&&a[i]==a[k])continue;
            return NX_EBOUNDS;
        }
    }
    if(!hardware_enabled&&!j->fp32)return NX_EINVAL;
    nx_status status=begin(t,call);if(status)return status;
    if(hardware_enabled){
        struct nx_stream_request request={.abi=NX_LINEAR_ABI,.size=96,.session_lo=(uint32_t)call->session,.session_hi=(uint32_t)(call->session>>32),
            .sequence_lo=(uint32_t)call->sequence,.sequence_hi=(uint32_t)(call->sequence>>32),.opcode=3,.m=1,.n=1,.k=j->k,
            .source=j->gate,.scales=j->up,.destination=j->fp32,.aq=j->aq,.sa=j->sa,.output_stride=j->mode,.row_bytes=j->quantize,.source_stride=j->scalar};
        if(resident){
            request.destination_stride=CE64_AQSA_PRODUCER|((j->resident_rows-1u)<<2)|j->resident_row;
            request.reserved[1]=(uint32_t)j->resident_first_sequence;
            request.reserved[2]=(uint32_t)(j->resident_first_sequence>>32);
            request.reserved[3]=j->resident_fp_base;
        }
        status=finish(t,call,&request,result);
    }else{
        uint64_t started=t->context->base.io.ticks(t->context->base.io.cookie);
        const float *g=(void *)(uintptr_t)j->gate,*u=(void *)(uintptr_t)j->up;
        float *y=(void *)(uintptr_t)j->fp32;union{uint32_t u;float f;}scale={.u=j->scalar};
        for(uint32_t i=0;i<j->k;i++)if(!vec_finite(g[i])||(needs_up&&!vec_finite(u[i])))status=NX_ENUMERIC;
        if(!status){
            if(j->mode==0){if(nx_swiglu(g,u,(int)j->k,y))status=NX_ENUMERIC;}
            else if(j->mode==7){if(nx_norm(g,u,1,(int)j->k,y))status=NX_ENUMERIC;}
            else if(j->mode==5||j->mode==6){
                uint32_t size=1;while(size<j->k)size*=2;
                for(uint32_t i=0;i<size;i++)vec_work[i]=i<j->k?g[i]:(j->mode==6?-INFINITY:0);
                while(size>1){for(uint32_t i=0;i<size/2;i++)vec_work[i]=j->mode==6?fmaxf(vec_work[2*i],vec_work[2*i+1]):vec_work[2*i]+vec_work[2*i+1];size/=2;}
                y[0]=vec_work[0];
            }else for(uint32_t i=0;i<j->k;i++)y[i]=j->mode==1?g[i]:j->mode==2?g[i]+u[i]:j->mode==3?g[i]*u[i]:g[i]*scale.f;
            uint32_t count=j->mode==5||j->mode==6?1:j->k;
            for(uint32_t i=0;i<count;i++)if(!vec_finite(y[i]))status=NX_ENUMERIC;
            if(!status&&quant){
                int rc=j->k%64 ? nx_quantize(y,1,(int)j->k,(void *)(uintptr_t)j->aq,(void *)(uintptr_t)j->sa) :
                    nx_opt11_software_quantize(y,1,j->k,(void *)(uintptr_t)j->aq,(void *)(uintptr_t)j->sa);
                if(rc)status=NX_ENUMERIC;
            }
            if(!status&&quant)for(uint32_t i=j->k;i<((j->k+63)/64)*64;i++)((uint8_t *)(uintptr_t)j->aq)[i]=0;
        }
        t->context->base.io.fence(t->context->base.io.cookie);
        result->cycles=t->context->base.io.ticks(t->context->base.io.cookie)-started;
        if(!status&&result->cycles>=call->timeout_ticks)status=NX_ETIMEOUT;
        t->context->base.sequence=call->sequence;t->context->base.state=NX_ACCEL_IDLE;
        result->valid=!status;result->status=status;
    }
    if(!status&&sealed_norm){
        nx_ce64_context *c=t->context;
        if(c->binding!=authority||authority->sealed_norm_read!=authorize||authority->cookie!=authority_cookie||
           c->epoch!=authority_epoch||c->base.session!=call->session||c->base.sequence!=call->sequence||
           !sealed_norm_authorized(t,call,j)){
            status=NX_ESTATE;result->status=status;result->valid=0;
            c->base.io.write32(c->base.io.cookie,NX_BRIDGE_CONTROL,3);
            c->base.io.write32(c->base.io.cookie,CE64_MMIO_BASE+CE64_CONTROL,CE64_CTL_ISOLATE);
            c->base.io.fence(c->base.io.cookie);c->base.kv_valid=0;c->base.state=NX_ACCEL_FAULTED;
        }
    }
    if(!status&&resident){
        nx_ce64_context *c=t->context;
        if(c->binding!=authority||c->epoch!=authority_epoch||c->base.session!=call->session||
           c->base.sequence!=call->sequence||!resident_authorized(t,call,j)){
            status=NX_ESTATE;result->status=status;result->valid=0;
            c->base.io.write32(c->base.io.cookie,NX_BRIDGE_CONTROL,3);
            c->base.io.write32(c->base.io.cookie,CE64_MMIO_BASE+CE64_CONTROL,CE64_CTL_ISOLATE);
            c->base.io.fence(c->base.io.cookie);c->base.kv_valid=0;c->base.state=NX_ACCEL_FAULTED;
        }
    }
    if(!status){
        *view=(nx_opt12_view){.valid=1,.epoch=t->context->epoch,.fp32=j->fp32,.k=j->k,.session=call->session,.sequence=call->sequence};
        if(resident){
            view->resident_valid=1;view->resident_rows=j->resident_rows;view->resident_row=j->resident_row;
            view->resident_fp_base=j->resident_fp_base;view->resident_first_sequence=j->resident_first_sequence;
        }
        if(quant)view->quantized=(nx_opt11_view){.version=1,.valid=!resident,.epoch=t->context->epoch,.aq=j->aq,.sa=j->sa,.k=j->k,.session=call->session,.sequence=call->sequence};
    }
    return status;
}

nx_status nx_opt12_run(nx_ce64_transport *t,const nx_call *call,const nx_opt12_job *j,nx_opt12_view *view,struct nx_stream_result *result){
    return opt12_run(t,call,j,view,result,0,0);
}
nx_status nx_opt12_run_sealed_norm(nx_ce64_transport *t,const nx_call *call,const nx_opt12_job *j,nx_opt12_view *view,struct nx_stream_result *result){
    return opt12_run(t,call,j,view,result,1,0);
}

nx_status nx_opt12_run_resident(nx_ce64_transport *t,const nx_call *call,const nx_opt12_job *j,nx_opt12_view *view,struct nx_stream_result *result){
    return opt12_run(t,call,j,view,result,0,1);
}

nx_status nx_pv_run(nx_ce64_transport *t,const nx_call *call,uint32_t p,uint32_t v,uint32_t y,
                   uint32_t heads,uint32_t len,uint32_t padded,struct nx_stream_result *result){
    if(!result)return NX_EINVAL;
    *result=(struct nx_stream_result){0};
    if(heads<1||heads>7||len<1||len>512||padded<len||padded>512||(padded&(padded-1)))return NX_EINVAL;
    uint64_t vend=(uint64_t)v+(len-1)*512+256;
    uint32_t bytes=heads*256,pbytes=heads*(len>64?padded:64)*4;
    if(!t||!t->context||!call)return NX_EINVAL;
    if(len>64){
        nx_status ready=call_ready(t,call);if(ready)return ready;
        if(!t->context->base.io.read32)return NX_ESTATE;
        if((v&255u)||(p&511u))return NX_EBOUNDS;
        if(t->context->base.io.read32(t->context->base.io.cookie,CE64_MMIO_BASE+CE64_LONG_PV_CAPABILITY)!=CE64_LONG_PV_MAGIC)return NX_EUNSUPPORTED;
    }
    if(!region(p,pbytes)||!region(y,bytes)||(v&15)||v<0xa8000000u||vend>0xa8f00000u||
       ((uint64_t)p<(uint64_t)y+bytes&&(uint64_t)y<(uint64_t)p+pbytes))return NX_EBOUNDS;
    nx_status status=begin(t,call);if(status)return status;
    struct nx_stream_request request={.abi=NX_LINEAR_ABI,.size=96,
      .session_lo=(uint32_t)call->session,.session_hi=(uint32_t)(call->session>>32),
      .sequence_lo=(uint32_t)call->sequence,.sequence_hi=(uint32_t)(call->sequence>>32),
      .opcode=5,.m=1,.n=1,.k=len,.source=p,.scales=v,.destination=y,
      .output_stride=heads,.row_bytes=padded,.source_stride=512};
    return finish(t,call,&request,result);
}

static nx_status pv_window_fault(nx_ce64_context *c,struct nx_stream_result *result,nx_status status){
    c->base.io.write32(c->base.io.cookie,NX_BRIDGE_CONTROL,3);
    c->base.io.write32(c->base.io.cookie,CE64_MMIO_BASE+CE64_CONTROL,CE64_CTL_ISOLATE);
    c->base.io.fence(c->base.io.cookie);
    c->base.kv_valid=0;c->base.state=NX_ACCEL_FAULTED;
    *result=(struct nx_stream_result){.status=status};return status;
}

nx_status nx_pv_window_run(nx_ce64_transport *t,const nx_call *call,const float *p,uint32_t v,uint32_t y,
                          uint32_t heads,uint32_t len,uint32_t padded,struct nx_stream_result *result){
    if(!result)return NX_EINVAL;
    *result=(struct nx_stream_result){0};
    if(!t||!t->context||!call||!p||heads<1||heads>7||len<1||len>64||
       padded<len||padded>64||(padded&(padded-1)))return NX_EINVAL;
    nx_ce64_context *c=t->context;
    if(!c->base.initialized)return NX_ESTATE;
    uint64_t vend=(uint64_t)v+(len-1)*512+256;
    uint32_t words=heads*64,bytes=words*4;
    if(!region(y,bytes)||(v&15)||v<0xa8000000u||vend>0xa8f00000u)return NX_EBOUNDS;
    /* Reject numeric input before any device write or state transition. */
    for(uint32_t i=0;i<heads*len;i++)if(!vec_finite(p[i]))return NX_ENUMERIC;
    if(c->base.io.read32(c->base.io.cookie,CE64_MMIO_BASE+CE64_P_WINDOW_CAPABILITY)!=CE64_P_WINDOW_MAGIC)
        return NX_EUNSUPPORTED;
    nx_status status=begin(t,call);if(status)return status;
    uint64_t started=c->base.io.ticks(c->base.io.cookie);
    /* Session reset leaves the CE isolated. Enable its ordinary private
     * register path before BEGIN; no DDR ownership is acquired until finish. */
    c->base.io.write32(c->base.io.cookie,CE64_MMIO_BASE+CE64_CONTROL,CE64_CTL_RUN_ENABLE);
    c->base.io.fence(c->base.io.cookie);
    if(c->base.io.read32(c->base.io.cookie,CE64_MMIO_BASE+CE64_EPOCH)!=c->epoch)
        return pv_window_fault(c,result,NX_EFAULT);
    c->base.io.write32(c->base.io.cookie,CE64_MMIO_BASE+CE64_P_WINDOW_BEGIN,1);
    c->base.io.write32(c->base.io.cookie,CE64_MMIO_BASE+CE64_P_WINDOW_WORDS,words);
    c->base.io.write32(c->base.io.cookie,CE64_MMIO_BASE+CE64_P_WINDOW_SESSION_LO,(uint32_t)call->session);
    c->base.io.write32(c->base.io.cookie,CE64_MMIO_BASE+CE64_P_WINDOW_SESSION_HI,(uint32_t)(call->session>>32));
    c->base.io.write32(c->base.io.cookie,CE64_MMIO_BASE+CE64_P_WINDOW_SEQUENCE_LO,(uint32_t)call->sequence);
    c->base.io.write32(c->base.io.cookie,CE64_MMIO_BASE+CE64_P_WINDOW_SEQUENCE_HI,(uint32_t)(call->sequence>>32));
    c->base.io.write32(c->base.io.cookie,CE64_MMIO_BASE+CE64_P_WINDOW_LENGTH,len);
    c->base.io.write32(c->base.io.cookie,CE64_MMIO_BASE+CE64_P_WINDOW_PADDED,padded);
    for(uint32_t h=0;h<heads;h++)for(uint32_t i=0;i<64;i++){
        union{float f;uint32_t u;}value={.f=i<len?p[h*len+i]:0.0f};
        c->base.io.write32(c->base.io.cookie,CE64_MMIO_BASE+CE64_P_WINDOW_DATA+(h*64+i)*4,value.u);
    }
    c->base.io.fence(c->base.io.cookie);
    c->base.io.write32(c->base.io.cookie,CE64_MMIO_BASE+CE64_P_WINDOW_PUBLISH,1);
    c->base.io.fence(c->base.io.cookie);
    if(c->base.io.read32(c->base.io.cookie,CE64_MMIO_BASE+CE64_P_WINDOW_STATUS)!=
       ((words<<16)|CE64_P_WINDOW_READY))return pv_window_fault(c,result,NX_EFAULT);
    uint64_t spent=c->base.io.ticks(c->base.io.cookie)-started;
    if(spent>=call->timeout_ticks)return pv_window_fault(c,result,NX_ETIMEOUT);
    nx_call submit=*call;submit.timeout_ticks-=spent;
    struct nx_stream_request request={.abi=NX_LINEAR_ABI,.size=96,
      .session_lo=(uint32_t)call->session,.session_hi=(uint32_t)(call->session>>32),
      .sequence_lo=(uint32_t)call->sequence,.sequence_hi=(uint32_t)(call->sequence>>32),
      .opcode=5,.m=1,.n=1,.k=len,.source=0,.scales=v,.destination=y,
      .output_stride=heads,.row_bytes=padded,.source_stride=512,.destination_stride=CE64_P_WINDOW_LOCAL};
    status=finish(t,&submit,&request,result);
    if(!status&&c->base.io.ticks(c->base.io.cookie)-started>=call->timeout_ticks)
        return pv_window_fault(c,result,NX_ETIMEOUT);
    return status;
}
