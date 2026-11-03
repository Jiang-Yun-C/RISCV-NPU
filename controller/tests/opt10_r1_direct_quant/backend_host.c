/* Scheduler plumbing only: real adapter/provider validation, mock SFU/CE
 * completions. This cannot qualify RTL arithmetic, stop/reset or ownership. */
#include "ce64_backend.h"
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
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>

extern int nx_opt11_software_quantize(const float *,uint32_t,uint32_t,int8_t *,float *);
static unsigned checks,submits,fail_at,linear_calls;
static uint64_t ticks;
static unsigned linear_failure,vector_failure;
#define CHECK(x) do { checks++;if(!(x)){fprintf(stderr,"line %d: %s\n",__LINE__,#x);exit(1);} } while(0)
uint64_t nx_port_ticks(void){return ticks+=10;}
static void fence(void *unused){(void)unused;}
static void map(uintptr_t address,size_t n){CHECK(mmap((void *)address,n,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED_NOREPLACE,-1,0)==(void *)address);}
nx_status nx_opt12_run(nx_ce64_transport *t,const nx_call *call,const nx_opt12_job *j,nx_opt12_view *v,struct nx_stream_result *r){
    nx_ce64_context *c=t->context;submits++;
    CHECK(call->session==c->base.session&&call->sequence==c->base.sequence+1);
    CHECK(call->timeout_ticks>0&&call->timeout_ticks<=20000000);
    CHECK(!(j->gate&15)&&!(j->up&15)&&!(j->fp32&15)&&!(j->aq&15)&&!(j->sa&15));
    if(fail_at==submits){c->base.state=NX_ACCEL_FAULTED;return NX_EIO;}
    const float *x=(void *)(uintptr_t)j->gate,*u=(void *)(uintptr_t)j->up;
    float *y=(void *)(uintptr_t)j->fp32;
    if(j->mode==1){
        CHECK(j->aq&&j->sa&&!j->fp32);
        CHECK(!nx_opt11_software_quantize(x,1,j->k,(void *)(uintptr_t)j->aq,(void *)(uintptr_t)j->sa));
    }else{
        CHECK(y&&u);
        if(j->mode==0)CHECK(j->aq&&j->sa);
        for(unsigned i=0;i<j->k;i++)y[i]=x[i]+u[i];
    }
    c->base.sequence=call->sequence;
    *v=(nx_opt12_view){.valid=1,.epoch=c->epoch,.session=call->session,.sequence=call->sequence};
    *r=(struct nx_stream_result){.valid=1,.cycles=100};
    if(j->mode!=1)switch(vector_failure){
        case 1:return NX_EIO;
        case 2:r->valid=0;break;
        case 3:v->valid=0;break;
        case 4:c->epoch++;break;
        case 5:c->base.session++;break;
        case 6:c->base.sequence++;break;
        case 7:c->base.state=NX_ACCEL_FAULTED;break;
        case 8:ticks+=20000000;break;
        default:break;
    }
    return 0;
}
nx_status nx_opt12_acquire(nx_ce64_context *c,const nx_opt12_view *v){return c->base.state!=NX_ACCEL_IDLE||!v->valid||v->epoch!=c->epoch||v->session!=c->base.session||v->sequence!=c->base.sequence?NX_ESTATE:0;}
nx_status nx_linear_run_v2(nx_ce64_context *c,const nx_call *call,const nx_accel_linear *j,nx_stats *s){
    CHECK(call->sequence==c->base.sequence+1);CHECK(c->binding->input_cache.valid);
    CHECK(c->binding->input_cache.input_address==j->a.address);
    for(unsigned row=0;row<j->a.shape[0];row++){
        unsigned k=j->a.shape[1];int8_t q[4864];float scale[76];
        const float *x=(void *)(uintptr_t)(j->a.address+row*k*4);
        CHECK(!nx_opt11_software_quantize(x,1,k,q,scale));
        CHECK(!memcmp(q,(void *)(uintptr_t)(c->binding->aq_address+row*k),k));
        CHECK(!memcmp(scale,(void *)(uintptr_t)(c->binding->sa_address+row*(k/64)*4),(k/64)*4));
    }
    float *y=(void *)(uintptr_t)j->y.address;
    for(unsigned i=0;i<j->y.shape[0]*j->y.shape[1];i++)y[i]=(float)i;
    c->base.sequence=call->sequence;linear_calls++;*s=(nx_stats){.output_valid=1,.backend_cycles=100};
    if(linear_failure==1)return NX_EIO;
    if(linear_failure==2)s->output_valid=0;
    if(linear_failure==3)c->epoch++;
    if(linear_failure==4)c->base.session++;
    if(linear_failure==5)c->base.sequence++;
    if(linear_failure==6)ticks+=20000001;
    if(linear_failure==7)c->base.state=NX_ACCEL_FAULTED;
    return 0;
}
int main(void){
    map(0xac000000,0x200000);map(0xba100000,0x100000);map(0x88000000,0x100000);
    nx_linear_binding binding={.aq_address=0xba1c0000,.aq_bytes=4*4864,.sa_address=0xba1c5000,.sa_bytes=4*304};
    nx_ce64_context c={.base={.state=NX_ACCEL_IDLE,.session=1,.initialized=1,.io={.fence=fence}},.epoch=1,.binding=&binding};
    nxr_ce64_backend b={.accelerator=&c,.input=(void *)0xba100000,.output=(void *)0xba120000,
        .input_bytes=4*4864*4,.output_bytes=151936*4,.timeout_ticks=20000000,.vector_mask=15,.producer_aq=0xba1d0000,.producer_sa=0xba1d1400};
    float *x=(void *)0xac000000,*u=(void *)0xac080000,*y=(void *)0xac100000;
    for(unsigned i=0;i<4*4864;i++){x[i]=(float)((int)(i%255)-127)*0.125f;u[i]=(float)(i%31);y[i]=-999;}
    nx_matrix w={.n=4,.k=896,.q=(void *)0x88000000,.s=(void *)0x88010000};
    for(unsigned rows=1;rows<=4;rows++){
        nxr_ce64_input_v2(&b,x,rows,896,rows);unsigned before=submits;
        uint64_t direct_aq=b.producer_direct_aq_bytes,direct_sa=b.producer_direct_sa_bytes,copied_sa=b.producer_sa_copy_bytes;
        CHECK(!nxr_ce64_linear(&b,x,rows,&w,y));CHECK(submits==before+rows);
        CHECK(b.producer_direct_aq_bytes-direct_aq==rows*896);
        CHECK(b.producer_direct_sa_bytes-direct_sa==((rows+1)/2)*56);
        CHECK(b.producer_sa_copy_bytes-copied_sa==(rows/2)*56);
        CHECK(b.lease_valid&&b.lease_sequence==c.base.sequence);
        CHECK(!nxr_ce64_linear(&b,x,rows,&w,y));CHECK(submits==before+rows);
        c.epoch++;CHECK(!nxr_ce64_linear(&b,x,rows,&w,y));CHECK(submits==before+2*rows);
        c.base.sequence++;CHECK(!nxr_ce64_linear(&b,x,rows,&w,y));CHECK(submits==before+3*rows);
    }
    w.k=4864;nxr_ce64_input_v2(&b,x,4,w.k,9);unsigned before=submits;
    uint64_t direct_sa_before=b.producer_direct_sa_bytes,sa_copy_before=b.producer_sa_copy_bytes;
    CHECK(!nxr_ce64_linear(&b,x,4,&w,y));CHECK(submits==before+4);
    CHECK(b.producer_direct_sa_bytes-direct_sa_before==4*304&&b.producer_sa_copy_bytes==sa_copy_before);
    nxr_ce64_input_v2(&b,x,4,w.k,10);fail_at=submits+2;
    for(unsigned i=0;i<16;i++)y[i]=-999;
    CHECK(nxr_ce64_linear(&b,x,4,&w,y)==NX_STATE);CHECK(!b.lease_valid&&!binding.input_cache.valid);
    for(unsigned i=0;i<16;i++)CHECK(y[i]==-999);
    fail_at=0;c.base.state=NX_ACCEL_IDLE;
    for(unsigned mode=0;mode<=7;mode++)if(mode==0||mode==2||mode==7){
        CHECK(!nxr_ce64_vector(&b,mode,x,u,4,896,y));CHECK(!b.lease_valid);
        for(unsigned i=0;i<4*896;i++)CHECK(y[i]==x[i]+u[mode==7?i%896:i]);
        b.vector_mask=0;before=submits;CHECK(nxr_ce64_vector(&b,mode,x,u,1,896,y)==NX_UNSUPPORTED);CHECK(submits==before);b.vector_mask=15;
    }
    fail_at=submits+2;for(unsigned i=0;i<4*896;i++)y[i]=-999;
    CHECK(nxr_ce64_vector(&b,2,x,u,4,896,y)==NX_STATE);
    for(unsigned i=0;i<4*896;i++)CHECK(y[i]==-999);
    /* New private path: authorization, bounds/aliases, identity, late faults.
     * A dirty private destination is allowed only behind session revocation. */
    fail_at=0;c.base.state=NX_ACCEL_IDLE;
    b.private_output_address=(uintptr_t)y;b.private_output_bytes=4*4864*4;
    w.k=896;w.n=4;
    for(unsigned rows=1;rows<=4;rows++){
        nxr_ce64_input_v2(&b,x,rows,w.k,100+rows);
        uint64_t copied=b.output_copy_bytes,saved=b.private_output_saved_bytes;
        CHECK(!nxr_ce64_linear_private(&b,x,rows,&w,y));
        CHECK(b.output_copy_bytes==copied&&b.private_output_saved_bytes==saved+rows*w.n*4);
        for(unsigned i=0;i<rows*w.n;i++)CHECK(y[i]==(float)i);
    }
    float *bad[]={y+1,(void *)0xac0ffff0,(void *)0xac200000,x,b.input,b.output,
                  (void *)(uintptr_t)binding.aq_address,(void *)(uintptr_t)binding.sa_address};
    for(unsigned i=0;i<sizeof(bad)/sizeof(bad[0]);i++){
        unsigned before_linear=linear_calls,before_sfu=submits;
        CHECK(nxr_ce64_linear_private(&b,x,1,&w,bad[i])==NX_MEMORY);
        CHECK(linear_calls==before_linear&&submits==before_sfu);
    }
    uint32_t cap=b.private_output_bytes;b.private_output_bytes=4;
    CHECK(nxr_ce64_linear_private(&b,x,1,&w,y)==NX_MEMORY);b.private_output_bytes=cap;
    for(linear_failure=1;linear_failure<=7;linear_failure++){
        c.base.state=NX_ACCEL_IDLE;nxr_ce64_input_v2(&b,x,1,w.k,200+linear_failure);
        uint64_t copied=b.output_copy_bytes,saved=b.private_output_saved_bytes,completed=b.completed;
        CHECK(nxr_ce64_linear_private(&b,x,1,&w,y)==NX_STATE);
        CHECK(!b.lease_valid&&!binding.input_cache.valid);
        CHECK(b.output_copy_bytes==copied&&b.private_output_saved_bytes==saved&&b.completed==completed);
        /* Recovered legacy calls continue to protect the public output. */
        c.base.state=NX_ACCEL_IDLE;nxr_ce64_input_v2(&b,x,1,w.k,300+linear_failure);
        for(unsigned i=0;i<4;i++)y[i]=-999;
        /* The extra adapter-level private deadline is deliberately new.
         * Real legacy transport checks its deadline before returning. */
        if(linear_failure!=6){
            CHECK(nxr_ce64_linear(&b,x,1,&w,y)==NX_STATE);
            for(unsigned i=0;i<4;i++)CHECK(y[i]==-999);
        }
    }
    linear_failure=0;c.base.state=NX_ACCEL_IDLE;
    nxr_ce64_input_v2(&b,x,1,w.k,400);
    CHECK(!nxr_ce64_linear_private(&b,x,1,&w,y));
    /* Invalid future producer spans must fail before any row is issued. */
    uint32_t original_aq=binding.aq_address,original_sa=binding.sa_address,original_aq_bytes=binding.aq_bytes;
    unsigned producer_preflight_failures=0;
    for(unsigned bad=0;bad<6;bad++){
        nx_matrix altered=w;altered.k=896;altered.n=4;
        binding.aq_address=original_aq;binding.sa_address=original_sa;binding.aq_bytes=original_aq_bytes;
        if(bad==0)binding.aq_address+=4;
        if(bad==1)binding.sa_address+=4;
        if(bad==2)binding.aq_bytes=895;
        if(bad==3)binding.sa_address=b.producer_sa;
        if(bad==4)binding.aq_address=(uintptr_t)x;
        if(bad==5)altered.q=(void *)(uintptr_t)binding.aq_address;
        c.base.state=NX_ACCEL_IDLE;nxr_ce64_input_v2(&b,x,4,896,800+bad);unsigned old_submits=submits;
        CHECK(nxr_ce64_linear(&b,x,4,&altered,y)!=NX_OK);CHECK(submits==old_submits&&!b.lease_valid&&!binding.input_cache.valid);producer_preflight_failures++;
    }
    CHECK(producer_preflight_failures==6);
    binding.aq_address=original_aq;binding.sa_address=original_sa;binding.aq_bytes=original_aq_bytes;
    /* Private vectors: original public staging, explicit authorization and
     * all identity/deadline failures. Arithmetic here is a plumbing mock. */
    unsigned vector_checks_start=checks,vector_faults=0;
    b.private_output_address=(uintptr_t)y;b.private_output_bytes=4*4864*4;
    for(unsigned mode=0;mode<=7;mode++)if(mode==0||mode==2||mode==7){
        for(unsigned rows=1;rows<=4;rows++)for(unsigned ki=0;ki<2;ki++){
            unsigned k=ki?4864:896;uint64_t saved=b.vector_output_saved_bytes,copied=b.vector_output_copy_bytes;
            CHECK(!nxr_ce64_vector_private(&b,mode,x,u,rows,k,y));
            CHECK(b.vector_output_saved_bytes==saved+rows*k*4&&b.vector_output_copy_bytes==copied);
            for(unsigned i=0;i<rows*k;i++)CHECK(y[i]==x[i]+u[mode==7?i%k:i]);
        }
        for(vector_failure=1;vector_failure<=8;vector_failure++){
            c.base.state=NX_ACCEL_IDLE;uint64_t saved=b.vector_output_saved_bytes;
            CHECK(nxr_ce64_vector_private(&b,mode,x,u,4,896,y)==NX_STATE);
            CHECK(!b.lease_valid&&!binding.input_cache.valid&&b.vector_output_saved_bytes==saved);vector_faults++;
            c.base.state=NX_ACCEL_IDLE;for(unsigned i=0;i<4*896;i++)y[i]=-999;
            CHECK(nxr_ce64_vector(&b,mode,x,u,4,896,y)==NX_STATE);
            for(unsigned i=0;i<4*896;i++)CHECK(y[i]==-999);
        }
        vector_failure=0;c.base.state=NX_ACCEL_IDLE;
        for(unsigned row=1;row<=4;row++){
            fail_at=submits+row;uint64_t saved=b.vector_output_saved_bytes;
            CHECK(nxr_ce64_vector_private(&b,mode,x,u,4,896,y)==NX_STATE);
            CHECK(b.vector_output_saved_bytes==saved&&!b.lease_valid);vector_faults++;fail_at=0;c.base.state=NX_ACCEL_IDLE;
            CHECK(!nxr_ce64_vector_private(&b,mode,x,u,4,896,y));
        }
        unsigned before=submits;
        float *bad_y[]={y+1,(void *)0xac0ffff0,(void *)0xac200000,x+4,b.input,b.output};
        for(unsigned i=0;i<sizeof(bad_y)/sizeof(bad_y[0]);i++)CHECK(nxr_ce64_vector_private(&b,mode,x,u,1,896,bad_y[i])==NX_MEMORY);
        CHECK(submits==before);
        CHECK(nxr_ce64_vector_private(&b,mode,x,x+4,1,896,y)==NX_MEMORY);
        CHECK(nxr_ce64_vector_private(&b,mode,x,u,4,131,y)==NX_MEMORY);
        uint64_t oldseq=c.base.sequence;c.base.sequence=UINT64_MAX-2;
        CHECK(nxr_ce64_vector_private(&b,mode,x,u,4,896,y)==NX_STATE);c.base.sequence=oldseq;
        uint32_t cap=b.private_output_bytes;b.private_output_bytes=4;
        CHECK(nxr_ce64_vector_private(&b,mode,x,u,1,896,y)==NX_MEMORY);b.private_output_bytes=cap;
        CHECK(submits==before);
        CHECK(!nxr_ce64_vector_private(&b,mode,x,u,1,131,y));
    }
    b.private_output_address=(uintptr_t)x;b.private_output_bytes=0x200000;
    CHECK(nxr_ce64_vector_private(&b,0,x,u,1,896,x)==NX_MEMORY);
    CHECK(!nxr_ce64_vector_private(&b,2,x,u,4,896,x));
    CHECK(nxr_ce64_vector_private(&b,2,x,u,1,896,x+4)==NX_MEMORY);
    b.private_output_address=(uintptr_t)y;b.private_output_bytes=4*4864*4;
    uint32_t aq=b.producer_aq;b.producer_aq=(uintptr_t)y;
    CHECK(nxr_ce64_vector_private(&b,0,x,u,1,896,y)==NX_MEMORY);b.producer_aq=aq;
    printf("{\"checks\":%u,\"private_faults\":7,\"producer_preflight_failures\":6,\"vector_checks\":%u,\"vector_faults\":%u}\n",checks,checks-vector_checks_start,vector_faults);
    return 0;
}
