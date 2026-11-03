/* Host-only driver edge tests. The real submission path is tested in VCS. */
#include "accel.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
typedef struct {uint32_t ram[0x31000/4],control,errors;uint64_t time;nx_context *context;int reenter,checked;} fake;
static uint32_t read32(void *p,uint32_t a){
    fake *f=p;
    if(f->reenter&&f->context->state==NX_ACCEL_RUNNING){
        f->reenter=0;nx_stats s;nx_call c={1,1,f->context->session,f->context->sequence+1,1000};
        nx_accel_job j={1,NX_ACCEL_PROBE,0xac000000,0xba000000,16,0};
        assert(nx_accel_run(f->context,&c,&j,&s)==NX_EBUSY);
        assert(nx_wait(f->context,c.session,c.sequence,&s)==NX_EBUSY);
        uint64_t session;assert(nx_reset_session(f->context,1000,&session)==NX_EBUSY);f->checked++;
    }
    if(a==NX_BRIDGE_CONTROL)return f->control;
    if(a==NX_BRIDGE_STATUS)return 1|f->errors;
    if(a==NX_BRIDGE_IRQ||a==NX_BRIDGE_ADDRESS)return 0;
    assert(a>=0x20000000&&a<0x20031000);return f->ram[(a-0x20000000)/4];
}
static void write32(void *p,uint32_t a,uint32_t v){
    fake *f=p;
    if(a==NX_BRIDGE_CONTROL){f->control=v;return;}
    if(a==NX_BRIDGE_CLEAR){f->errors=0;return;}
    if(a==NX_BRIDGE_IRQ)return;
    assert(a>=0x20000000&&a<0x20031000);f->ram[(a-0x20000000)/4]=v;
    if(a==NX_ACCEL_CONTROL&&v==0){
        uint32_t *param=f->ram+0x10000/4,*r=f->ram+0x10100/4;
        r[0]=1;r[1]=32;for(unsigned i=2;i<6;i++)r[i]=param[i];r[6]=0;r[7]=1;
        f->ram[0x30008/4]=1;
    }
}
static uint64_t ticks(void *p){return ++((fake *)p)->time;}
static void fence(void *p){(void)p;}
int main(void){
    static fake f;nx_context c;f.context=&c;nx_accel_io io={&f,read32,write32,ticks,fence,100};
    const uint32_t image[]={0x08000073};nx_accel_program p={image,4,0,nx_accel_crc32(image,4)};
    assert(nx_accel_init(&c,&io,&p,1000)==0&&c.session==1);
    nx_accel_job j={1,NX_ACCEL_PROBE,0xac000000,0xba000000,16,0};nx_call call={1,1,1,1,1000};nx_stats s;
    f.reenter=1;assert(nx_accel_run(&c,&call,&j,&s)==0&&f.checked==1);
    assert(nx_wait(&c,1,1,&s)==0&&s.output_valid);
    assert(nx_accel_run(&c,&call,&j,&s)==NX_ESTATE&&s.status==NX_ESTATE&&!s.output_valid);
    c.sequence=UINT64_MAX;call.sequence=0;assert(nx_accel_run(&c,&call,&j,&s)==NX_ESTATE&&s.status==NX_ESTATE&&!s.output_valid);
    c.session=UINT64_MAX;uint64_t session=123;assert(nx_reset_session(&c,1000,&session)==NX_ESTATE&&session==123);
    c.session=1;c.sequence=1;
    f.errors=2;call.sequence=2;assert(nx_accel_run(&c,&call,&j,&s)==NX_EIO&&c.state==NX_ACCEL_FAULTED&&!s.output_valid);
    nx_context other;assert(nx_accel_init(&other,&io,&p,1000)==NX_EBUSY);
    assert(nx_reset_session(&c,1000,&session)==0&&session==2);
    assert(nx_wait(&c,1,2,&s)==NX_ESTATE);
    call.session=2;call.sequence=1;call.timeout_ticks=1;assert(nx_accel_run(&c,&call,&j,&s)==NX_ETIMEOUT&&c.sequence==0);
    call.timeout_ticks=1000;assert(nx_accel_run(&c,&call,&j,&s)==0);
    puts("PASS host state: reentry/global owner/sequence64/session64/recovery/deadline");
}
