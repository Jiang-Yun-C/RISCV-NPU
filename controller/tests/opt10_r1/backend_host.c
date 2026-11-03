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
    *r=(struct nx_stream_result){.valid=1,.cycles=100};return 0;
}
nx_status nx_opt12_acquire(nx_ce64_context *c,const nx_opt12_view *v){return !v->valid||v->epoch!=c->epoch||v->session!=c->base.session||v->sequence!=c->base.sequence?NX_ESTATE:0;}
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
    c->base.sequence=call->sequence;linear_calls++;*s=(nx_stats){.output_valid=1,.backend_cycles=100};return 0;
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
        CHECK(!nxr_ce64_linear(&b,x,rows,&w,y));CHECK(submits==before+rows);
        CHECK(b.lease_valid&&b.lease_sequence==c.base.sequence);
        CHECK(!nxr_ce64_linear(&b,x,rows,&w,y));CHECK(submits==before+rows);
        c.epoch++;CHECK(!nxr_ce64_linear(&b,x,rows,&w,y));CHECK(submits==before+2*rows);
        c.base.sequence++;CHECK(!nxr_ce64_linear(&b,x,rows,&w,y));CHECK(submits==before+3*rows);
    }
    w.k=4864;nxr_ce64_input_v2(&b,x,4,w.k,9);unsigned before=submits;
    CHECK(!nxr_ce64_linear(&b,x,4,&w,y));CHECK(submits==before+4);
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
    printf("{\"checks\":%u,\"mock_sfu_calls\":%u,\"mock_linear_calls\":%u}\n",checks,submits,linear_calls);
    return 0;
}
