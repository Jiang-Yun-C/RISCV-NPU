#include "ce64_backend.h"
/* Qualify the historical driver identifiers without changing either ABI. */
#define NX_OK NX_ACCEL_OK
#define NX_LINEAR NX_ACCEL_LINEAR
#define NX_ROPE NX_ACCEL_ROPE
#define NX_SWIGLU NX_ACCEL_SWIGLU
#define nx_linear nx_accel_linear
#include "ce64_linear.h"
#include "opt12.h"
#undef nx_linear
#undef NX_SWIGLU
#undef NX_ROPE
#undef NX_LINEAR
#undef NX_OK
#include <string.h>
#include "opt10_norm_catalog.h"
#ifndef NX_OPT10_SEALED_NORM_DIRECT
#define NX_OPT10_SEALED_NORM_DIRECT 1
#endif

static nx_tensor view(uint32_t a,uint32_t bytes,uint32_t dtype,uint32_t n,uint32_t k){
    uint32_t item=dtype==NX_I8?1u:4u;
    return (nx_tensor){.address=a,.allocation_bytes=bytes,.dtype=dtype,.rank=2,
        .shape={n,k},.stride_bytes={k*item,item},.layout_id=1};
}
static int physical(const void *p,uint64_t bytes){
    uintptr_t a=(uintptr_t)p;
    return p&&!(a&15u)&&a<=UINT32_MAX&&bytes&&bytes<=UINT32_MAX&&
        bytes<=UINT64_C(0x100000000)-a;
}
void nxr_ce64_input_v2(void *cookie,const float *x,int rows,int k,uint64_t version){
    nxr_ce64_backend *b=cookie;if(!b)return;
    nx_ce64_context *c=b->accelerator;
    if(b->input_serial!=UINT64_MAX)b->input_serial++;
    if(!version||b->source!=x||b->version!=version||b->source_rows!=(uint32_t)rows||b->source_k!=(uint32_t)k){b->staged_version=0;b->lease_valid=0;}
    b->source=x;b->version=version;b->source_rows=rows;b->source_k=k;
    if(c&&c->binding)nx_linear_input_v2(c->binding,(uintptr_t)x,version,rows,k);
}
static int intersects(uintptr_t a,uint64_t n,uintptr_t b,uint64_t m){return a<(uint64_t)b+m&&b<(uint64_t)a+n;}
static uint64_t remaining_ticks(nxr_ce64_backend *b,uint64_t start){
    uint64_t spent=nx_port_ticks()-start;
    return spent<b->timeout_ticks?b->timeout_ticks-spent:0;
}
static int vector_submit(nxr_ce64_backend *b,const nx_opt12_job *j,uint64_t start,int sealed_norm,nx_opt12_view *completed){
    nx_ce64_context *c=b->accelerator;
    uint64_t remaining=remaining_ticks(b,start);
    if(!remaining||c->base.sequence==UINT64_MAX)return NX_STATE;
    nx_call call={.api_version=2,.route=NX_CE64,.session=c->base.session,
        .sequence=c->base.sequence+1,.timeout_ticks=remaining};
    nx_ce64_transport t={.context=c};nx_opt12_view v={0};struct nx_stream_result result={0};
    int rc=sealed_norm?nx_opt12_run_sealed_norm(&t,&call,j,&v,&result):nx_opt12_run(&t,&call,j,&v,&result);b->sfu_calls++;
    if(rc||!result.valid||nx_opt12_acquire(c,&v))return NX_STATE;
    if(completed)*completed=v;
    b->sfu_cycles+=result.cycles;return NX_OK;
}
static int vector_region(uintptr_t,uint64_t);
/* Every row retires before its version can be leased. Aq writes directly to
 * the provider row; Sa uses the original temporary only for an unaligned row.
 * All future destinations are validated before the first DMA submission. */
static int produce_quantized(nxr_ce64_backend *b,const nx_accel_linear *job,const float *x,uint64_t start){
    nx_ce64_context *c=b->accelerator;nx_linear_binding *binding=c->binding;
    uint32_t m=job->a.shape[0],k=job->a.shape[1],g=k/64;
    uint64_t aq_bytes=(uint64_t)m*k,sa_bytes=(uint64_t)m*g*4,in=(uint64_t)m*k*4;
    b->lease_valid=0;binding->input_cache.valid=0;
    if(!b->version||m>4||!physical((void *)(uintptr_t)b->producer_aq,k)||
       !physical((void *)(uintptr_t)b->producer_sa,g*4)||aq_bytes>binding->aq_bytes||sa_bytes>binding->sa_bytes)return NX_STATE;
    uintptr_t aq=binding->aq_address,sa=binding->sa_address;
    int temporary_sa=m>1&&((g*4)&15u);
    if(!vector_region(aq,aq_bytes)||!vector_region(sa,sa_bytes)||aq<0xba000000u||sa<0xba000000u||
       intersects(aq,aq_bytes,sa,sa_bytes)||intersects(aq,aq_bytes,(uintptr_t)x,in)||intersects(sa,sa_bytes,(uintptr_t)x,in))return NX_STATE;
    const uint32_t address[4]={job->wq.address,job->sw.address,job->bias.address,job->y.address};
    const uint64_t span[4]={job->wq.allocation_bytes,job->sw.allocation_bytes,job->bias.allocation_bytes,job->y.allocation_bytes};
    for(unsigned i=0;i<4;i++)if(span[i]&&
        (intersects(aq,aq_bytes,address[i],span[i])||intersects(sa,sa_bytes,address[i],span[i])))return NX_STATE;
    if(temporary_sa){
        if(!vector_region(b->producer_sa,g*4)||b->producer_sa<0xba000000u||
           intersects(b->producer_sa,g*4,aq,aq_bytes)||intersects(b->producer_sa,g*4,sa,sa_bytes)||
           intersects(b->producer_sa,g*4,(uintptr_t)x,in))return NX_STATE;
        for(unsigned i=0;i<4;i++)if(span[i]&&intersects(b->producer_sa,g*4,address[i],span[i]))return NX_STATE;
    }
    if(c->base.sequence>UINT64_MAX-m)return NX_STATE;
    uint32_t epoch=c->epoch;uint64_t session=c->base.session;
    for(uint32_t row=0;row<m;row++){
        uint32_t row_aq=binding->aq_address+row*k,row_sa=binding->sa_address+row*g*4;
        uint32_t dma_sa=(row_sa&15u)?b->producer_sa:row_sa;
        uint64_t sequence=c->base.sequence;
        nx_opt12_job q={.gate=(uintptr_t)(x+(size_t)row*k),.aq=row_aq,.sa=dma_sa,.k=k,.mode=1};
        if(vector_submit(b,&q,start,0,NULL)||c->epoch!=epoch||c->base.session!=session||
           c->base.sequence!=sequence+1||c->base.state!=NX_ACCEL_IDLE)return NX_STATE;
        b->producer_direct_aq_bytes+=k;
        if(dma_sa!=row_sa){
            memcpy((void *)(uintptr_t)row_sa,(void *)(uintptr_t)dma_sa,g*4);
            b->producer_sa_copy_bytes+=g*4;
        }else b->producer_direct_sa_bytes+=g*4;
    }
    if(!remaining_ticks(b,start))return NX_STATE;
    c->base.io.fence(c->base.io.cookie);
    nx_input_cache_v2 *cache=&binding->input_cache;
    cache->session=session;cache->version=b->version;cache->source=cache->requested_source;
    cache->m=m;cache->k=k;cache->aq=binding->aq_address;cache->sa=binding->sa_address;
    cache->input_address=job->a.address;cache->aq_bytes=binding->aq_bytes;cache->sa_bytes=binding->sa_bytes;
    b->lease_epoch=epoch;b->lease_session=session;b->lease_sequence=c->base.sequence;
    cache->valid=1;b->lease_valid=1;return NX_OK;
}
/* Private destinations are explicitly leased AC workspace. Every row is
 * checked before coefficient staging or the first device submission. */
static int vector_region(uintptr_t a,uint64_t n){
    return !(a&15u)&&n&&n<=UINT32_MAX&&a<=UINT32_MAX&&
        (((uint64_t)a>=0xac000000u&&(uint64_t)a+n<=0xb4000000u)||
         ((uint64_t)a>=0xba000000u&&(uint64_t)a+n<=0xbc000000u));
}
/* The M1 producer can write the existing provider allocation directly. This
 * is a private output reservation, not a certificate. Validate whole arenas
 * before the first submission; every other geometry retains the old path. */
static int swiglu_handoff_buffers(nxr_ce64_backend *b,nx_linear_binding *p,
                                  const float *x,const float *u,float *y){
    const uint32_t k=4864,bytes=k*4,scales=(k/64)*4;
    if(!p||p->context!=&((nx_ce64_context *)b->accelerator)->base||
       p->aq_bytes<k||p->sa_bytes<scales||p->aq_address<0xba000000u||p->sa_address<0xba000000u||
       !vector_region(p->aq_address,p->aq_bytes)||!vector_region(p->sa_address,p->sa_bytes)||
       intersects(p->aq_address,p->aq_bytes,p->sa_address,p->sa_bytes))return 0;
    const uintptr_t address[]={(uintptr_t)x,(uintptr_t)u,(uintptr_t)y,
        (uintptr_t)b->input,(uintptr_t)b->output,b->producer_aq,b->producer_sa};
    const uint64_t span[]={bytes,bytes,bytes,b->input_bytes,b->output_bytes,k,scales};
    for(unsigned i=0;i<sizeof(address)/sizeof(address[0]);i++)
        if(intersects(p->aq_address,p->aq_bytes,address[i],span[i])||
           intersects(p->sa_address,p->sa_bytes,address[i],span[i]))return 0;
    return 1;
}
static int vector_v2(void *cookie,unsigned mode,const float *x,const float *u,int rows,int k,float *y,int private_output){
    nxr_ce64_backend *b=cookie;unsigned bit=mode==7?2:mode==0?4:mode==2?8:0;
    if(!b||!bit||!(b->vector_mask&bit))return NX_UNSUPPORTED;
    if(rows<1||rows>4||k<1||k>4864||!b->accelerator||!x||!u||!y)return NX_ARGUMENT;
    nx_ce64_context *c=b->accelerator;
    uint64_t bytes=(uint64_t)rows*k*4,up_bytes=mode==7?(uint32_t)k*4:bytes;
    if(bytes>b->output_bytes||(uint32_t)k*4>b->input_bytes||
       !physical(x,bytes)||!physical(u,up_bytes)||!physical(y,bytes)||
       intersects((uintptr_t)x,bytes,(uintptr_t)b->output,bytes)||
       intersects((uintptr_t)u,up_bytes,(uintptr_t)b->output,bytes)||
       intersects((uintptr_t)y,bytes,(uintptr_t)b->output,bytes))return NX_MEMORY;
    if(c->base.state!=NX_ACCEL_IDLE)return NX_STATE;
    if(private_output){
        uint64_t begin=b->private_output_address,end=begin+b->private_output_bytes;
        uint32_t padded=((uint32_t)k+63u)&~63u,scales=(padded/64)*4;
        if(!b->private_output_bytes||begin<0xac000000u||end>0xb4000000u||
           (uintptr_t)y<begin||(uint64_t)(uintptr_t)y+bytes>end||
           !vector_region((uintptr_t)b->input,(uint32_t)k*4)||
           (uintptr_t)b->input<0xba000000u||
           !vector_region((uintptr_t)b->output,bytes)||(uintptr_t)b->output<0xba000000u||
           intersects((uintptr_t)x,bytes,(uintptr_t)u,up_bytes)||
           intersects((uintptr_t)y,bytes,(uintptr_t)b->input,(uint32_t)k*4)||
           intersects((uintptr_t)y,bytes,b->producer_aq,padded)||
           intersects((uintptr_t)y,bytes,b->producer_sa,scales)||
           (intersects((uintptr_t)y,bytes,(uintptr_t)x,bytes)&&!(mode==2&&y==x))||
           (intersects((uintptr_t)y,bytes,(uintptr_t)u,up_bytes)&&!(mode==2&&y==u)))return NX_MEMORY;
        if(mode==7&&intersects((uintptr_t)x,bytes,(uintptr_t)b->input,(uint32_t)k*4))return NX_MEMORY;
        for(int row=0;row<rows;row++){
            if(!vector_region((uintptr_t)(x+(size_t)row*k),(uint32_t)k*4)||
               !vector_region((uintptr_t)(mode==7?b->input:u+(size_t)row*k),(uint32_t)k*4)||
               !vector_region((uintptr_t)(y+(size_t)row*k),(uint32_t)k*4))return NX_MEMORY;
        }
        if(mode==0&&(!vector_region(b->producer_aq,padded)||!vector_region(b->producer_sa,scales)||
           intersects(b->producer_aq,padded,b->producer_sa,scales)||
           intersects((uintptr_t)x,bytes,b->producer_aq,padded)||intersects((uintptr_t)x,bytes,b->producer_sa,scales)||
           intersects((uintptr_t)u,bytes,b->producer_aq,padded)||intersects((uintptr_t)u,bytes,b->producer_sa,scales)))return NX_MEMORY;
        if(!b->timeout_ticks||c->base.sequence>UINT64_MAX-(uint64_t)rows)return NX_STATE;
    }
    nx_linear_binding *handoff_binding=c->binding;
    uint64_t output_version=b->version;
    int handoff=private_output&&mode==0&&rows==1&&k==4864&&(b->vector_mask&1)&&
        output_version&&b->source==y&&b->source_rows==1&&b->source_k==4864&&
        b->input_serial!=UINT64_MAX&&swiglu_handoff_buffers(b,handoff_binding,x,u,y);
    uint32_t aq=handoff?handoff_binding->aq_address:0,sa=handoff?handoff_binding->sa_address:0;
    uint32_t aq_bytes=handoff?handoff_binding->aq_bytes:0,sa_bytes=handoff?handoff_binding->sa_bytes:0;
    /* Revoke the previous input in all cases. No valid or pending producer
     * proof survives this call. Only the completed view below can create one. */
    nxr_ce64_input_v2(b,0,0,0,0);
    uint64_t input_serial=b->input_serial;
    if(input_serial==UINT64_MAX)handoff=0;
    uint64_t start=nx_port_ticks();uint32_t epoch=c->epoch;uint64_t session=c->base.session;
    nx_opt12_view produced={0};
    int direct_coefficient=NX_OPT10_SEALED_NORM_DIRECT&&private_output&&mode==7&&k==896&&
        nx_opt10_norm_member((uint32_t)(uintptr_t)u,(uint32_t)up_bytes,(uint32_t)k)&&
        c->binding&&c->binding->context==&c->base&&c->binding->sealed_norm_read&&
        c->binding->sealed_norm_read(c->binding->cookie,(uint32_t)(uintptr_t)u,(uint32_t)up_bytes,(uint32_t)k,epoch,session);
    if(mode==7&&!direct_coefficient){memcpy(b->input,u,(size_t)k*4);b->vector_coefficient_copy_bytes+=(uint32_t)k*4;}
    for(int row=0;row<rows;row++){
        uint64_t sequence=c->base.sequence;
        nx_opt12_job j={.gate=(uintptr_t)(x+(size_t)row*k),
            .up=(uintptr_t)(mode==7?(direct_coefficient?u:b->input):u+(size_t)row*k),
            .fp32=(uintptr_t)((private_output?y:b->output)+(size_t)row*k),.k=k,.mode=mode,
            .aq=mode==0?(handoff?aq:b->producer_aq):0,.sa=mode==0?(handoff?sa:b->producer_sa):0};
        if(vector_submit(b,&j,start,direct_coefficient,handoff?&produced:NULL)||c->epoch!=epoch||c->base.session!=session||
           (private_output&&(c->base.sequence!=sequence+1||c->base.state!=NX_ACCEL_IDLE))){nxr_ce64_input_v2(b,0,0,0,0);return NX_STATE;}
    }
    if(!remaining_ticks(b,start))return NX_STATE;
    if(handoff){
        const nx_opt11_view *q=&produced.quantized;
        if(!produced.valid||produced.fp32!=(uint32_t)(uintptr_t)y||produced.k!=4864||
           produced.epoch!=epoch||produced.session!=session||produced.sequence!=c->base.sequence||
           q->version!=1||!q->valid||q->epoch!=epoch||q->session!=session||
           q->sequence!=c->base.sequence||q->k!=4864||q->aq!=aq||q->sa!=sa)return NX_STATE;
        c->base.io.fence(c->base.io.cookie);
        /* The context is single-caller, as in the original backend. This
         * serial also detects revocation from callbacks during submission or
         * the fence; saturation disables reuse instead of wrapping a lease. */
        if(b->accelerator!=c||c->binding!=handoff_binding||handoff_binding->context!=&c->base||
           handoff_binding->aq_address!=aq||handoff_binding->sa_address!=sa||
           handoff_binding->aq_bytes!=aq_bytes||handoff_binding->sa_bytes!=sa_bytes||
           b->input_serial!=input_serial||c->epoch!=epoch||c->base.session!=session||
           c->base.sequence!=produced.sequence||c->base.state!=NX_ACCEL_IDLE||!remaining_ticks(b,start))return NX_STATE;
        nxr_ce64_input_v2(b,y,1,4864,output_version);
        nx_input_cache_v2 *cache=&handoff_binding->input_cache;
        cache->session=session;cache->version=output_version;cache->source=(uintptr_t)y;
        cache->m=1;cache->k=4864;cache->aq=aq;cache->sa=sa;
        cache->input_address=(uintptr_t)y;cache->aq_bytes=aq_bytes;cache->sa_bytes=sa_bytes;
        b->staged_version=output_version;
        b->lease_epoch=epoch;b->lease_session=session;b->lease_sequence=produced.sequence;
        cache->valid=1;b->lease_valid=1;b->swiglu_quantized_handoffs++;
    }
    if(direct_coefficient){b->vector_coefficient_direct_bytes+=(uint64_t)rows*up_bytes;b->vector_coefficient_saved_bytes+=up_bytes;}
    if(private_output)b->vector_output_saved_bytes+=bytes;
    else{memcpy(y,b->output,(size_t)bytes);b->vector_output_copy_bytes+=bytes;}
    return NX_OK;
}
int nxr_ce64_vector(void *cookie,unsigned mode,const float *x,const float *u,int rows,int k,float *y){
    return vector_v2(cookie,mode,x,u,rows,k,y,0);
}
int nxr_ce64_vector_private(void *cookie,unsigned mode,const float *x,const float *u,int rows,int k,float *y){
    int rc=vector_v2(cookie,mode,x,u,rows,k,y,1);
    if(rc&&cookie)nxr_ce64_input_v2(cookie,0,0,0,0);
    return rc;
}
static int linear_v2(void *cookie,const float *x,int rows,const nx_matrix *w,float *y,int private_output){
    nxr_ce64_backend *b=cookie;
    if(!b||!b->accelerator||!x||!w||!y||rows<1||w->n<1||w->n>151936||
       rows>512||w->k<1||!b->timeout_ticks)return NX_ARGUMENT;
    if(w->k!=896&&w->k!=4864)return NX_UNSUPPORTED;
    uint64_t in=(uint64_t)rows*w->k*4,out=(uint64_t)rows*w->n*4;
    uint64_t weights=(uint64_t)w->n*w->k,scales=(uint64_t)w->n*(w->k/64)*4;
    if(private_output){
        uint64_t start=b->private_output_address,end=start+b->private_output_bytes;
        /* Only the explicitly registered, uncached AC workspace is eligible.
         * In particular, a valid public tensor is not a private-output lease. */
        if(!physical(y,out)||!b->private_output_bytes||start<0xac000000u||
           end>0xb4000000u||(uintptr_t)y<start||(uint64_t)(uintptr_t)y+out>end)
            return NX_MEMORY;
        if((b->vector_mask&1)&&
           (intersects((uintptr_t)y,out,b->producer_aq,w->k)||
            intersects((uintptr_t)y,out,b->producer_sa,(w->k/64)*4)))return NX_MEMORY;
    }
    if(in>b->input_bytes||out>b->output_bytes||
       !physical(b->input,in)||!physical(b->output,out)||
       !physical(w->q,weights)||!physical(w->s,scales)||
       (w->bias&&!physical(w->bias,(uint64_t)w->n*4)))return NX_MEMORY;
    /* Staging is written by the CPU before submission. Read permission on a
     * public input tensor alone does not authorize writing the model region. */
    if((uintptr_t)b->input<0xba000000u||(uint64_t)(uintptr_t)b->input+in>0xbc000000u||
       (uintptr_t)b->output<0xba000000u||(uint64_t)(uintptr_t)b->output+out>0xbc000000u)return NX_MEMORY;
    nx_ce64_context *c=b->accelerator;
#ifndef NX_OPT08_DIRECT_INPUT
#define NX_OPT08_DIRECT_INPUT 1
#endif
    if(c->base.state!=NX_ACCEL_IDLE||!c->binding)return NX_STATE;
    if((uintptr_t)x>UINT32_MAX||(uintptr_t)y>UINT32_MAX||in>UINT64_C(0x100000000)-(uintptr_t)x||out>UINT64_C(0x100000000)-(uintptr_t)y)return NX_MEMORY;
    if(intersects((uintptr_t)y,out,(uintptr_t)x,in)||intersects((uintptr_t)y,out,(uintptr_t)b->output,out)||intersects((uintptr_t)y,out,(uintptr_t)w->q,weights)||intersects((uintptr_t)y,out,(uintptr_t)w->s,scales))return NX_MEMORY;
    if(intersects((uintptr_t)b->input,in,c->binding->aq_address,c->binding->aq_bytes)||intersects((uintptr_t)b->input,in,c->binding->sa_address,c->binding->sa_bytes)||intersects((uintptr_t)y,out,c->binding->aq_address,c->binding->aq_bytes)||intersects((uintptr_t)y,out,c->binding->sa_address,c->binding->sa_bytes))return NX_MEMORY;
    /* Both dynamic-input windows are already read-authorized by the provider.
     * Read the immutable version in place; all overlap and bounds checks above
     * still precede submission. This avoids a full DDR-to-DDR staging copy. */
    int direct=NX_OPT08_DIRECT_INPUT&&physical(x,in)&&
        (((uintptr_t)x>=0xac000000u&&(uint64_t)(uintptr_t)x+in<=0xb4000000u)||
         ((uintptr_t)x>=0xba000000u&&(uint64_t)(uintptr_t)x+in<=0xbc000000u));
    if(intersects((uintptr_t)x,in,(uintptr_t)b->output,out)||intersects((uintptr_t)y,out,(uintptr_t)b->input,in))return NX_MEMORY;
    if(intersects((uintptr_t)x,in,(uintptr_t)b->input,in)&&x!=b->input)return NX_MEMORY;
    if(intersects((uintptr_t)b->input,in,(uintptr_t)w->q,weights)||intersects((uintptr_t)b->input,in,(uintptr_t)w->s,scales)||intersects((uintptr_t)x,in,(uintptr_t)w->q,weights)||intersects((uintptr_t)x,in,(uintptr_t)w->s,scales))return NX_MEMORY;
    if(w->bias&&(intersects((uintptr_t)y,out,(uintptr_t)w->bias,(uint64_t)w->n*4)||intersects((uintptr_t)x,in,(uintptr_t)w->bias,(uint64_t)w->n*4)||intersects((uintptr_t)b->input,in,(uintptr_t)w->bias,(uint64_t)w->n*4)))return NX_MEMORY;
    /* Validate every public view before staging can overwrite an arena. */
    nx_accel_linear job={.a=view(direct?(uintptr_t)x:(uintptr_t)b->input,(uint32_t)in,NX_F32,rows,w->k),
        .wq=view((uintptr_t)w->q,(uint32_t)weights,NX_I8,w->n,w->k),
        .sw=view((uintptr_t)w->s,(uint32_t)scales,NX_F32,w->n,w->k/64),
        .y=view((uintptr_t)(private_output?y:b->output),(uint32_t)out,NX_F32,rows,w->n),.group_size=64};
    if(w->bias)job.bias=(nx_tensor){.address=(uintptr_t)w->bias,
        .allocation_bytes=w->n*4u,.dtype=NX_F32,.rank=1,
        .shape={w->n},.stride_bytes={4},.layout_id=1};
    if(nx_linear_validate(&job))return NX_MEMORY;
    uint64_t ia=(uintptr_t)b->input,oa=(uintptr_t)b->output;
    if(ia<oa+out&&oa<ia+in)return NX_MEMORY;
    if(c->base.sequence==UINT64_MAX)return NX_STATE;
    uint64_t api_start=nx_port_ticks();
    int hit=b->version&&b->source==x&&b->source_rows==(uint32_t)rows&&b->source_k==(uint32_t)w->k&&
        b->staged_version==b->version&&c->binding&&c->binding->input_cache.valid&&c->binding->input_cache.session==c->base.session;
    if(b->vector_mask&1){
        if(!b->lease_valid||b->lease_epoch!=c->epoch||b->lease_session!=c->base.session||b->lease_sequence!=c->base.sequence){hit=0;c->binding->input_cache.valid=0;}
    }
    uint64_t tick=nx_port_ticks();
    if(!direct&&!hit){memcpy(b->input,x,(size_t)in);b->staging_bytes+=in;}
    else b->staging_saved_bytes+=in;
    b->staging_ticks+=nx_port_ticks()-tick;
    if((b->vector_mask&1)&&!hit&&produce_quantized(b,&job,direct?x:b->input,api_start))return NX_STATE;
    uint64_t remaining=remaining_ticks(b,api_start);
    if(!remaining||c->base.sequence==UINT64_MAX)return NX_STATE;
    nx_call call={.api_version=2,.route=NX_CE64,.session=c->base.session,
        .sequence=c->base.sequence+1,.timeout_ticks=remaining};
    uint32_t submitted_epoch=c->epoch;
    nx_stats stats={0};b->calls++;
    int rc=nx_linear_run_v2(c,&call,&job,&stats);b->last_status=rc;
    /* Unsupported after dispatch, faults and uncommitted output invalidate the
     * model request; they never silently fall back to a different executor. */
    if(rc||!stats.output_valid||c->epoch!=submitted_epoch||c->base.session!=call.session||
       c->base.sequence!=call.sequence||c->base.state!=NX_ACCEL_IDLE||
       (private_output&&!remaining_ticks(b,api_start))){b->staged_version=0;nxr_ce64_input_v2(b,0,0,0,0);return NX_STATE;}
    b->staged_version=b->version;
    if(b->lease_valid)b->lease_sequence=c->base.sequence;
    if(private_output){
        /* run_v2 already acquired, checked the total deadline, ACKed and
         * fenced the drained result. No CPU cache holds AC workspace lines. */
        b->private_output_saved_bytes+=out;
    }else{
        tick=nx_port_ticks();memcpy(y,b->output,(size_t)out);b->output_copy_bytes+=out;b->output_copy_ticks+=nx_port_ticks()-tick;
    }
    b->completed++;b->backend_cycles+=stats.backend_cycles;
    return NX_OK;
}

int nxr_ce64_linear(void *cookie,const float *x,int rows,const nx_matrix *w,float *y){
    int rc=linear_v2(cookie,x,rows,w,y,0);
    if(rc&&cookie)nxr_ce64_input_v2(cookie,0,0,0,0);
    return rc;
}
int nxr_ce64_linear_private(void *cookie,const float *x,int rows,const nx_matrix *w,float *y){
    int rc=linear_v2(cookie,x,rows,w,y,1);
    if(rc&&cookie)nxr_ce64_input_v2(cookie,0,0,0,0);
    return rc;
}
