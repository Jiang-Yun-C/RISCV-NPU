/* Exercise the graph adapter against the actual public descriptor validator.
 * The transport stub checks dispatch/commit semantics, not FPGA arithmetic. */
#define _GNU_SOURCE
#include <assert.h>
#include <stdio.h>
#include <sys/mman.h>
#include <string.h>
#include "ce64_backend.c"
static int transport_status,valid=1,submissions;
static uint32_t expected_n=128;
nx_status nx_linear_run_v2(nx_ce64_context *c,const nx_call *call,const nx_accel_linear *j,nx_stats *s){
    assert(call->api_version==2&&call->route==2&&call->session==7&&call->sequence==c->base.sequence+1);
    assert(call->timeout_ticks==900000000);
    assert(j->a.shape[0]==1&&j->a.shape[1]==896&&j->wq.shape[0]==expected_n);
    assert(j->sw.shape[1]==14&&j->group_size==64);
    const float *a=(const float *)(uintptr_t)j->a.address;
    for(unsigned i=0;i<896;i++)assert(a[i]==(float)i/8);
    assert(j->bias.address==0||j->bias.address==0x90000000);
    submissions++;c->base.sequence++;
    float *y=(float *)(uintptr_t)j->y.address;
    for(unsigned i=0;i<j->y.shape[1];i++)y[i]=(float)i+0.5f;
    *s=(nx_stats){.output_valid=valid,.backend_cycles=42};return transport_status;
}
int main(void){
    void *memory=mmap((void *)0xba100000,0x200000,PROT_READ|PROT_WRITE,
        MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED_NOREPLACE,-1,0);assert(memory==(void *)0xba100000);
    nx_ce64_context c={.base={.session=7}};
    nxr_ce64_backend b={.accelerator=&c,.input=memory,.output=(float *)0xba110000,
        .input_bytes=19456,.output_bytes=607744,.timeout_ticks=900000000};
    nx_matrix w={.q=(const int8_t *)0x80000000,.s=(const float *)0x89000000,.n=128,.k=896};
    float x[896],y[151936];for(unsigned i=0;i<896;i++)x[i]=(float)i/8;
    for(unsigned i=0;i<151936;i++)y[i]=-999;
    assert(nxr_ce64_linear(&b,x,1,&w,y)==0);
    for(unsigned i=0;i<128;i++)assert(y[i]==(float)i+0.5f);
    assert(y[128]==-999&&b.calls==1&&b.completed==1&&b.backend_cycles==42);
    w.bias=(const float *)0x90000000;assert(nxr_ce64_linear(&b,x,1,&w,y)==0);w.bias=0;
    expected_n=w.n=151936;assert(nxr_ce64_linear(&b,x,1,&w,y)==0);
    assert(y[151935]==151935.5f&&b.completed==3);expected_n=w.n=128;
    for(unsigned i=0;i<151936;i++)y[i]=-999;
    transport_status=NX_EIO;
    assert(nxr_ce64_linear(&b,x,1,&w,y)==NX_STATE&&y[0]==-999&&b.completed==3);
    transport_status=0;valid=0;
    assert(nxr_ce64_linear(&b,x,1,&w,y)==NX_STATE&&y[0]==-999&&b.completed==3);valid=1;
    transport_status=NX_EUNSUPPORTED;
    assert(nxr_ce64_linear(&b,x,1,&w,y)==NX_STATE&&y[0]==-999);transport_status=0;
    int count=submissions;
    w.k=64;assert(nxr_ce64_linear(&b,x,1,&w,y)==NX_UNSUPPORTED);w.k=896;
    assert(nxr_ce64_linear(NULL,x,1,&w,y)==NX_ARGUMENT);
    assert(nxr_ce64_linear(&b,x,0,&w,y)==NX_ARGUMENT);
    assert(nxr_ce64_linear(&b,x,513,&w,y)==NX_ARGUMENT);
    assert(nxr_ce64_linear(&b,NULL,1,&w,y)==NX_ARGUMENT);
    w.n=-1;assert(nxr_ce64_linear(&b,x,1,&w,y)==NX_ARGUMENT);w.n=128;
    b.input_bytes=4;assert(nxr_ce64_linear(&b,x,1,&w,y)==NX_MEMORY);b.input_bytes=19456;
    b.output_bytes=4;assert(nxr_ce64_linear(&b,x,1,&w,y)==NX_MEMORY);b.output_bytes=607744;
    w.s=(const float *)0x89000004;assert(nxr_ce64_linear(&b,x,1,&w,y)==NX_MEMORY);w.s=(const float *)0x89000000;
    w.q=(const int8_t *)0xb4000000;assert(nxr_ce64_linear(&b,x,1,&w,y)==NX_MEMORY);w.q=(const int8_t *)0x80000000;
    b.output=b.input;assert(nxr_ce64_linear(&b,x,1,&w,y)==NX_MEMORY);b.output=(float *)0xba110000;
    b.input=(float *)0x80000000;assert(nxr_ce64_linear(&b,x,1,&w,y)==NX_MEMORY);b.input=memory;
    c.base.sequence=UINT64_MAX;assert(nxr_ce64_linear(&b,x,1,&w,y)==NX_STATE);c.base.sequence=0;
    b.timeout_ticks=0;assert(nxr_ce64_linear(&b,x,1,&w,y)==NX_ARGUMENT);
    assert(submissions==count&&y[0]==-999);
    puts("T25_BRIDGE_PASS full_head=151936 faults_do_not_publish=3");
    assert(munmap(memory,0x200000)==0);return 0;
}
