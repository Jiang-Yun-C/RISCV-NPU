/* Route 2 must survive the reference graph's dispatch trace. */
#define NX_PORTABLE
#define NX_SMALL
#include "nx_reference.c"
#include <assert.h>
#include <stdio.h>
static uint64_t tick;
uint64_t nx_port_ticks(void){return ++tick;}
static int response,observed_route,observed_reason,observed_status;
static int backend(void *cookie,const float *x,int rows,const nx_matrix *w,float *y){
    (void)cookie;(void)x;(void)rows;(void)w;if(!response)*y=123;return response;
}
static void trace(void *cookie,int kind,int route,int reason,int rc,uint64_t ticks){
    (void)cookie;assert(kind==NX_LINEAR&&ticks>0);
    observed_route=route;observed_reason=reason;observed_status=rc;
}
int main(void){
    nx_session s={0};float x[64]={0},scale=1,y=-999;int8_t q[64]={0};
    nx_matrix w={.q=q,.s=&scale,.n=1,.k=64};
    nx_bind_backend(&s,0,backend,trace,2);
    assert(dispatched_linear(&s,x,1,&w,&y)==0&&y==123&&observed_route==2&&observed_reason==0);
    nx_bind_backend(&s,0,backend,trace,1);
    assert(dispatched_linear(&s,x,1,&w,&y)==0&&observed_route==1);
    nx_bind_backend(&s,0,backend,trace,2);response=NX_UNSUPPORTED;
    assert(dispatched_linear(&s,x,1,&w,&y)==0&&y==0&&observed_route==0&&observed_reason==2);
    response=NX_STATE;y=-999;
    assert(dispatched_linear(&s,x,1,&w,&y)==NX_STATE&&y==-999&&observed_route==2&&observed_status==NX_STATE&&observed_reason==0);
    nx_bind_backend(&s,0,0,trace,0);
    assert(dispatched_linear(&s,x,1,&w,&y)==0&&observed_route==0&&observed_reason==3);
    puts("T25_DISPATCH_PASS CE64=2 Coral=1 CPU=0 fallback_and_fault=PASS");return 0;
}
