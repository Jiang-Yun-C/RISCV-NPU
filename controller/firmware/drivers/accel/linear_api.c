#include "ce64_linear.h"
/* Reuse the OPT08 board quantizer verbatim, including SRAM group staging. */
#define NX_CE_BOARD_BOOT 1
#include "linear_api.h"
#include "ce64_abi_v1.h"
#include <stddef.h>
#include <limits.h>
static uint32_t bits(float f){union {float f;uint32_t u;} v={.f=f};return v.u;}
static int finite(float f){return (bits(f)&0x7f800000u)!=0x7f800000u;}
static int region(uint32_t a,uint64_t bytes,int write){uint64_t end=(uint64_t)a+bytes;
    return bytes&&end<=UINT64_C(0x100000000)&&((!write&&a>=0x80000000u&&end<=0xa8000000u)||
        (a>=0xa8000000u&&end<=0xac000000u)||(a>=0xac000000u&&end<=0xb4000000u)||(a>=0xba000000u&&end<=0xbc000000u));}
static nx_status tensor(const nx_tensor *t,uint32_t dtype,uint32_t rank,int output){
    if(t->dtype!=dtype||t->rank!=rank)return NX_EINVAL;
    uint64_t span=dtype==NX_I8?1:4,expected=span;
    for(unsigned i=0;i<4;i++) {
        if(i<rank){
            if(!t->shape[i]||!t->stride_bytes[i])return NX_EINVAL;
            uint64_t term=(uint64_t)(t->shape[i]-1)*t->stride_bytes[i];
            if(term>UINT64_MAX-span)return NX_EBOUNDS;
            span+=term;
        }
        else if(t->shape[i]||t->stride_bytes[i])return NX_EINVAL;
    }
    if(span>t->allocation_bytes||!region(t->address,t->allocation_bytes,output))return NX_EBOUNDS;
    if(t->address&15)return NX_EALIGN;
    if(t->layout_id!=1)return NX_EUNSUPPORTED;
    for(unsigned i=rank;i>0;i--){if(t->stride_bytes[i-1]!=expected)return NX_EUNSUPPORTED;expected*=t->shape[i-1];}
    return NX_OK;
}
static int absent(const nx_tensor *t){
    if(t->address||t->allocation_bytes||t->dtype||t->rank||t->layout_id)return 0;
    for(unsigned i=0;i<4;i++)if(t->shape[i]||t->stride_bytes[i])return 0;
    return 1;
}
static int overlap(const nx_tensor *a,const nx_tensor *b){return (uint64_t)a->address<(uint64_t)b->address+b->allocation_bytes&&(uint64_t)b->address<(uint64_t)a->address+a->allocation_bytes;}
nx_status nx_linear_validate(const nx_linear *j){
    if(!j)return NX_EINVAL;
    const nx_tensor *ts[5]={&j->a,&j->wq,&j->sw,&j->bias,&j->y};
    for(unsigned i=0;i<5;i++) {
        if(i==3&&absent(ts[i]))continue;
        nx_status status=tensor(ts[i],i==1?NX_I8:NX_F32,i==3?1:2,i==4);if(status)return status;
    }
    uint32_t m=j->a.shape[0],k=j->a.shape[1],n=j->wq.shape[0];
    if(j->wq.shape[1]!=k||j->sw.shape[0]!=n||j->sw.shape[1]!=(k+63)/64||j->y.shape[0]!=m||j->y.shape[1]!=n||(!absent(&j->bias)&&j->bias.shape[0]!=n))return NX_EINVAL;
    for(unsigned i=0;i<4;i++)if(!absent(ts[i])&&overlap(ts[i],&j->y))return NX_EBOUNDS;
    if(j->group_size!=64||m>512||n>151936)return NX_EUNSUPPORTED;
#ifdef NX_T19_MINI
    if(k!=128)return NX_EUNSUPPORTED;
#else
    if(k!=896&&k!=4864)return NX_EUNSUPPORTED;
#endif
    return NX_OK;
}
static int quantize(const float *x,uint32_t m,uint32_t k,int8_t *q,float *sa){
    uint32_t g=k/64;
    for(uint32_t row=0;row<m;row++)for(uint32_t group=0;group<g;group++) {
        float max=0;
        for(uint32_t j=0;j<64;j++){float v=x[row*k+group*64+j];if(!finite(v))return NX_ENUMERIC;if(v<0)v=-v;if(v>max)max=v;}
        float s=max/127.0f;if(max&&s<0x1p-126f)s=0x1p-126f;sa[row*g+group]=s;
        for(uint32_t j=0;j<64;j++) {
            float v=s?x[row*k+group*64+j]/s:0;int negative=v<0;if(negative)v=-v;
            int32_t r=(int32_t)v;float fraction=v-(float)r;
            if(fraction>0.5f||(fraction==0.5f&&(r&1)))r++;
            if(r>127)r=127;
            q[row*k+group*64+j]=(int8_t)(negative?-r:r);
        }
    }
    return NX_OK;
}
/* Separate, non-inlined loop avoids spilling provider state on each q. The
 * T09 D cache writes through; every spilled stack store costs a native drain.
 * Legacy routes retain their original byte-store loop above. */
__attribute__((noinline)) int nx_opt11_software_quantize(const float *x,uint32_t m,uint32_t k,int8_t *q,float *sa){
    uint32_t g=k/64;
    for(uint32_t row=0;row<m;row++)for(uint32_t group=0;group<g;group++){
        const float *values=x+row*k+group*64;
#ifdef NX_CE_BOARD_BOOT
        /* The board linker puts this 256-byte group on the existing local
         * SRAM stack. Read each external activation once under contention;
         * retain the same max, scale, division and RNE operations below. */
        float local_values[64];
        /* DDR-stack component/recovery linkers must not stage 64 floats
         * through write-through DDR. Retain staging only in physical SRAM. */
        int local_stage=(uintptr_t)local_values>=0x20000u &&
            (uintptr_t)(local_values+64)<=0x30000u;
#endif
        uint32_t *words=(uint32_t *)(void *)(q+row*k+group*64);
        float max=0;
        for(uint32_t j=0;j<64;j++){
            float v=values[j];if(!finite(v))return NX_ENUMERIC;
#ifdef NX_CE_BOARD_BOOT
            if(local_stage)local_values[j]=v;
#endif
            if(v<0)v=-v;
            if(v>max)max=v;
        }
        float scale=max/127.0f;if(max&&scale<0x1p-126f)scale=0x1p-126f;
        sa[row*g+group]=scale;
        for(uint32_t w=0;w<16;w++){
            uint32_t packed=0;
            for(uint32_t lane=0;lane<4;lane++){
#ifdef NX_CE_BOARD_BOOT
                float v=scale?(local_stage?local_values[w*4+lane]:values[w*4+lane])/scale:0;
#else
                float v=scale?values[w*4+lane]/scale:0;
#endif
                int negative=v<0;if(negative)v=-v;
                int32_t rounded=(int32_t)v;float fraction=v-(float)rounded;
                if(fraction>0.5f||(fraction==0.5f&&(rounded&1)))rounded++;
                if(rounded>127)rounded=127;
                packed|=(uint32_t)(uint8_t)(int8_t)(negative?-rounded:rounded)<<(lane*8);
            }
            words[w]=packed;
        }
    }
    return NX_OK;
}
void nx_linear_input_invalidate(nx_linear_binding *b) {
    if(b){b->input_cache.valid=0;b->input_cache.resident_valid=0;b->input_cache.requested_version=0;}
}
void nx_linear_input_v2(nx_linear_binding *b,uintptr_t source,uint64_t version,uint32_t m,uint32_t k) {
    if(!b)return;
    nx_input_cache_v2 *c=&b->input_cache;
    if(!version||!source||!m||!k){nx_linear_input_invalidate(b);return;}
    if(c->requested_version!=version||c->requested_source!=source||c->requested_m!=m||c->requested_k!=k){c->valid=0;c->resident_valid=0;}
    c->requested_version=version;c->requested_source=source;c->requested_m=m;c->requested_k=k;
}
static uint64_t now(nx_linear_binding *b){nx_context *c=b->context;return c->io.ticks(c->io.cookie);}
static nx_status provider(void *cookie,const nx_call *call,const nx_linear *j,nx_stats *s){
    nx_linear_binding *b=cookie;uint64_t start=now(b),validated=start,quantized=start,end;nx_status status=nx_linear_validate(j);
    uint32_t m=j->a.shape[0],k=j->a.shape[1],n=j->wq.shape[0],g=k/64;int accepted=0;
    int resident_pending=b->input_cache.resident_valid!=0,resident_use=0;
    *s=(nx_stats){.session=call->session,.sequence=call->sequence,.tick_hz=b->context->io.tick_hz,.route=call->route,.valid_counters=NX_REFERENCE_TICKS};
    if(status)goto finish;
    uint64_t qb=(uint64_t)m*k,sb=(uint64_t)m*g*4;
    if(qb>b->aq_bytes||sb>b->sa_bytes||!region(b->aq_address,b->aq_bytes,1)||!region(b->sa_address,b->sa_bytes,1)){status=NX_EBOUNDS;goto finish;}
    nx_tensor scratch[2]={{.address=b->aq_address,.allocation_bytes=b->aq_bytes},{.address=b->sa_address,.allocation_bytes=b->sa_bytes}};
    const nx_tensor *ts[5]={&j->a,&j->wq,&j->sw,&j->bias,&j->y};
    if((b->aq_address|b->sa_address)&15){status=NX_EALIGN;goto finish;}
    for(unsigned i=0;i<2;i++) {
        for(unsigned z=0;z<5;z++)if(!absent(ts[z])&&overlap(&scratch[i],ts[z])){status=NX_EBOUNDS;goto finish;}
    }
    if(overlap(&scratch[0],&scratch[1])){status=NX_EBOUNDS;goto finish;}
    const float *x=b->resolve(b->cookie,j->a.address,j->a.allocation_bytes,0);
    const int8_t *w=b->resolve(b->cookie,j->wq.address,j->wq.allocation_bytes,0);
    const float *sw=b->resolve(b->cookie,j->sw.address,j->sw.allocation_bytes,0);
    const float *bias=absent(&j->bias)?NULL:b->resolve(b->cookie,j->bias.address,j->bias.allocation_bytes,0);
    float *y=b->resolve(b->cookie,j->y.address,j->y.allocation_bytes,1);
    int8_t *aq=b->resolve(b->cookie,b->aq_address,b->aq_bytes,1);float *sa=b->resolve(b->cookie,b->sa_address,b->sa_bytes,1);
    if(!x||!w||!sw||!y||!aq||!sa||(!absent(&j->bias)&&!bias)){status=NX_EBOUNDS;goto finish;}
    if((call->route==NX_CORAL_RVV || call->route==2u)&&!b->execute){status=NX_EUNSUPPORTED;goto finish;}
    /* Immutable model numeric validation is T10/T18 loader seal. Recheck in
     * this standalone provider so an unsealed host arena cannot bypass it. */
    int sealed=b->model_sealed && b->model_sealed(b->cookie,j);
    for(uint32_t row=0;row<n && !sealed;row++) {
        if(bias&&!finite(bias[row])){status=NX_ENUMERIC;goto finish;}
        for(uint32_t group=0;group<g;group++) {
            uint32_t u=bits(sw[row*g+group]);if((u>>31)||(u&&u<0x00800000u)||u>=0x7f800000u){status=NX_ENUMERIC;goto finish;}
            for(uint32_t z=0;z<64;z++){int q=w[row*k+group*64+z];if(q==-128||(!u&&q)){status=NX_ENUMERIC;goto finish;}}
        }
    }
    validated=now(b);
    nx_input_cache_v2 *cache=&b->input_cache;
    int hit=call->route==2u&&cache->requested_version&&(cache->valid||cache->resident_valid)&&cache->session==call->session&&
        cache->version==cache->requested_version&&cache->source==cache->requested_source&&
        cache->m==m&&cache->k==k&&cache->requested_m==m&&cache->requested_k==k&&cache->aq==b->aq_address&&cache->sa==b->sa_address&&cache->input_address==j->a.address&&cache->aq_bytes==b->aq_bytes&&cache->sa_bytes==b->sa_bytes;
    /* A pending scratch lease never authorizes reading the DDR alias. A
     * wrong request fails before quantization/submission instead of silently
     * treating stale DDR as the producer output. */
    if(resident_pending){
        if(!hit||call->route!=2u||k!=4864||m<1||m>4||!cache->resident_first_sequence||
           cache->resident_first_sequence>UINT64_MAX-m||
           call->sequence!=cache->resident_first_sequence+m){status=NX_ESTATE;goto finish;}
        resident_use=1;
    }
    if(hit){cache->hits++;status=NX_OK;}
    else {cache->valid=0;cache->quantizations++;status=(call->route==2u ? nx_opt11_software_quantize(x,m,k,aq,sa) : quantize(x,m,k,aq,sa));}
    quantized=now(b);cache->ticks+=quantized-validated;if(status)goto finish;
    if(!resident_use&&call->route==2u&&cache->requested_version&&cache->requested_m==m&&cache->requested_k==k){
        cache->session=call->session;cache->version=cache->requested_version;cache->source=cache->requested_source;
        cache->m=m;cache->k=k;cache->aq=b->aq_address;cache->sa=b->sa_address;cache->input_address=j->a.address;cache->aq_bytes=b->aq_bytes;cache->sa_bytes=b->sa_bytes;cache->valid=1;
    }
    if(quantized-start>=call->timeout_ticks){status=NX_ETIMEOUT;goto finish;}
    accepted=1;s->session=call->session;s->sequence=call->sequence;s->macs=(uint64_t)m*n*k;
    if((call->route==NX_CORAL_RVV || call->route==2u)) {
        struct nx_stream_request r={.abi=NX_LINEAR_ABI,.size=96,.session_lo=(uint32_t)call->session,.session_hi=(uint32_t)(call->session>>32),.sequence_lo=(uint32_t)call->sequence,.sequence_hi=(uint32_t)(call->sequence>>32),.opcode=NX_STREAM_LINEAR,.m=m,.n=n,.k=k,.source=j->wq.address,.destination=j->y.address,.scales=j->sw.address,.bias=absent(&j->bias)?0:j->bias.address,.aq=b->aq_address,.sa=b->sa_address,.output_stride=n*4};
        if(resident_use){
            r.destination_stride=CE64_AQSA_CONSUMER|((m-1u)<<2);
            r.reserved[1]=(uint32_t)cache->resident_first_sequence;
            r.reserved[2]=(uint32_t)(cache->resident_first_sequence>>32);
            r.reserved[3]=cache->input_address;
            /* Consume before entering transport, even if transport fails. */
            cache->resident_valid=0;cache->valid=0;
        }
        nx_call execution_call=*call;execution_call.timeout_ticks-=quantized-start;
        struct nx_stream_result result={0};status=b->execute(b->cookie,&execution_call,&r,&result);
        if(!status) {
            if(result.abi!=NX_LINEAR_ABI||result.size!=104||result.session_lo!=r.session_lo||result.session_hi!=r.session_hi||result.sequence_lo!=r.sequence_lo||result.sequence_hi!=r.sequence_hi)status=NX_EFAULT;
            else if(result.status)status=result.valid==0&&result.status==NX_ENUMERIC?NX_ENUMERIC:NX_EFAULT;
            else if(result.valid!=1||!result.cycles||result.rows!=n*((m+3)/4)||result.tiles!=((n+127)/128)*((m+3)/4))status=NX_EFAULT;
            else{s->backend_cycles=result.cycles;s->valid_counters|=NX_BACKEND_CYCLES;}
        }
    } else {
        for(uint32_t row=0;row<m;row++)for(uint32_t col=0;col<n;col++) {
            float sum=0;
            for(uint32_t group=0;group<g;group++) {
                int32_t dot=0;for(uint32_t z=0;z<64;z++)dot+=(int32_t)aq[row*k+group*64+z]*(int32_t)w[col*k+group*64+z];
                float p=(float)dot*sa[row*g+group];float v=p*sw[col*g+group];sum=sum+v;
                if(!finite(p)||!finite(v)||!finite(sum)){status=NX_ENUMERIC;goto finish;}
            }
            if(bias)sum=sum+bias[col];
            if(!finite(sum)){status=NX_ENUMERIC;goto finish;}
            y[row*n+col]=sum;
            if(now(b)-start>=call->timeout_ticks){status=NX_ETIMEOUT;goto finish;}
        }
        s->fallback_reason=NX_FALLBACK_CPU_REQUEST;
    }
finish:
    if(resident_pending){b->input_cache.resident_valid=0;b->input_cache.valid=0;}
    end=now(b);if(!status&&end-start>=call->timeout_ticks)status=NX_ETIMEOUT;
    /* The provider also owns failures detected after transport returns (for
     * example a stale record or the total-call deadline). Preserve the same
     * explicit isolate/drain/reset rule as failures detected by transport. */
    if(status&&call->route==2u)nx_diag_capture(((3u<<16)|__LINE__),status,((nx_ce64_transport *)b->cookie)->context,call,0);
    if(accepted&&(call->route==NX_CORAL_RVV || call->route==2u)&&(status==NX_EFAULT||status==NX_EIO||status==NX_ETIMEOUT||status==NX_ENUMERIC)){
        nx_context *c=b->context;
        c->io.write32(c->io.cookie,NX_BRIDGE_CONTROL,3);c->io.fence(c->io.cookie);
        c->fault_address=c->io.read32(c->io.cookie,NX_BRIDGE_ADDRESS);c->kv_valid=0;end=now(b);
    }
    if(validated==start)validated=end;
    if(quantized<validated)quantized=validated;
    s->elapsed_ticks=end-start;s->validate_ticks=validated-start;s->quantize_ticks=quantized-validated;
    if(call->route==NX_CPU_C)s->fallback_ticks=end-quantized;else s->execute_ticks=end-quantized;
    if(status)nx_linear_input_invalidate(b);
    s->status=status;s->output_valid=accepted&&status==0;return status;
}
nx_status nx_linear_bind(nx_context *c,nx_linear_binding *b,uint32_t routes){
    if(!c||!b||!b->resolve)return NX_EINVAL;
    if((routes&(1u<<NX_CORAL_RVV))&&!b->execute)return NX_EUNSUPPORTED;
    nx_linear_input_invalidate(b);b->context=c;return nx_linear_install(c,provider,b,routes);
}

/* API-v2 owns its own lifecycle; API1 still rejects route >1. */
nx_status nx_linear_execute_binding(nx_linear_binding *b,const nx_call *c,const nx_linear *j,nx_stats *s){return provider(b,c,j,s);}
