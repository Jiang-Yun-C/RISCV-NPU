/* Same production core/controller on host and real RV32; no injected logits. */
#include "prefix.h"
#include "stream.h"
#include "inputs.h"
#include <string.h>
#include <math.h>
#ifndef __riscv
#include <stdio.h>
#include <time.h>
#endif
static _Alignas(16) unsigned char state[16384];
static nx_session *session;
static nx_weights weights;
static nxr_request request;
static nxp_cache cache;
static int backend_fail;
static uint32_t prompt[513];
static nx_prefix_identity key;
static const int32_t prefix[3]={1,2,3};
static void emit(unsigned group,unsigned index,uint32_t value){
#ifdef __riscv
    *(volatile uint32_t *)0x10000080=(group<<16)|index;
    *(volatile uint32_t *)0x10000084=value;
#else
    printf("%u %u %u\n",group,index,value);
#endif
}
static uint32_t bits(float x){uint32_t u;memcpy(&u,&x,4);return u;}
static void check(unsigned i,int value){emit(200,i,(uint32_t)!!value);}
uint64_t nx_port_ticks(void){
#ifdef __riscv
    uint32_t a,b,c;do{__asm__ volatile("csrr %0,mcycleh":"=r"(a));__asm__ volatile("csrr %0,mcycle":"=r"(b));__asm__ volatile("csrr %0,mcycleh":"=r"(c));}while(a!=c);
    return (uint64_t)a<<32|b;
#else
    struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return (uint64_t)t.tv_sec*1000000000u+t.tv_nsec;
#endif
}
static uint64_t clock_fn(void *p){(void)p;return nx_port_ticks();}
static void tick(unsigned i,uint64_t n){emit(400,2*i,(uint32_t)n);emit(400,2*i+1,(uint32_t)(n>>32));}
static int reset_fn(void *p){nx_reset(p);return 0;}
static int forward_fn(void *p,uint32_t id,uint32_t past,uint32_t *next){
    int32_t out=-1;int rc=nx_forward_token_v2(p,(int32_t)id,(int)past,&out);if(!rc)*next=(uint32_t)out;return rc;
}
static int prefill_fn(void *p,uint32_t id,uint32_t past){int32_t token=(int32_t)id;return nx_forward(p,&token,1,(int)past,NULL,NULL);}
static int backend(void *p,const float *x,int rows,const nx_matrix *w,float *y){
    (void)p;(void)x;(void)rows;(void)w;(void)y;return backend_fail?NX_STATE:NX_UNSUPPORTED;
}
static void setup(void){
    weights.embedding=(nx_matrix){&q_embedding[0][0],s_embedding,NULL,32,8};
    weights.norm=norm;weights.inv_freq=inv;
    for(unsigned l=0;l<2;l++){
        nx_layer *w=weights.layer+l;w->norm1=norm1[l];w->norm2=norm2[l];
        nx_matrix *m[7]={&w->q,&w->k,&w->v,&w->o,&w->gate,&w->up,&w->down};
        const int ns[7]={8,4,4,8,16,16,8},ks[7]={8,8,8,8,8,8,16};
        for(int j=0;j<7;j++)*m[j]=(nx_matrix){&q_layers[l][j][0][0],s_layers[l][j],j<3?bias[l][j]:NULL,ns[j],ks[j]};
    }
    session=nx_init_static(&weights,state,sizeof(state),(void *)0xa8000000,nx_kv_bytes(),(void *)0xac000000,nx_work_bytes());
}
#ifndef __riscv
static _Alignas(16) unsigned char host_kv[40960],host_work[1024];
#endif
static void snapshot(unsigned label,int logits){
    unsigned group=10+label*10;
    const float *y=nx_logits_v2(session);if(logits&&y)for(unsigned i=0;i<32;i++)emit(group,i,bits(y[i]));
    for(int l=0;l<2;l++)for(int v=0;v<2;v++){
        size_t n=0;const float *p=nx_cache_view(session,l,v,&n);
        emit(group+5,(unsigned)(l*2+v),(uint32_t)n);
        if(p)for(size_t i=0;i<n*4;i++)emit(group+1+(unsigned)(l*2+v),(unsigned)i,bits(p[i]));
    }
}
static int advance(int32_t id,int head){
    if(head){int32_t next=-1;return nx_forward_token_v2(session,id,nx_length(session),&next);}
    return nx_forward(session,&id,1,nx_length(session),NULL,NULL);
}
static int finish_request(unsigned label){
    int rc=0;while(!rc&&(request.state==NXR_PREFILL||request.state==NXR_DECODE))rc=nxr_step(&request);
    emit(300,label*4,(uint32_t)rc);emit(300,label*4+1,request.generated);
    for(unsigned i=0;i<request.generated;i++)emit(301+label,i,request.output[i]);
    if(!rc)snapshot(4+label,1);
    return rc;
}
static uint32_t boundary_past;
static int boundary_reset(void *p){(void)p;boundary_past=0;return 0;}
static int boundary_forward(void *p,uint32_t id,uint32_t past,uint32_t *next){
    (void)p;(void)id;if(past!=boundary_past||past>=512)return NXR_STATE;boundary_past++;*next=1;return 0;
}
uint32_t trap_handler(uint32_t a,uint32_t b,uint32_t c){(void)b;(void)c;emit(999,0,a);
#ifdef __riscv
    *(volatile uint32_t *)0x10000020=0xdead;for(;;){}
#endif
    return 0;
}
int main(void){
    setup();
#ifndef __riscv
    session=nx_init_static(&weights,state,sizeof(state),host_kv,sizeof(host_kv),host_work,sizeof(host_work));
#endif
    if(!session)return 1;
    memset(&key,1,sizeof(key));key.abi=NX_PREFIX_ABI;key.start_position=0;key.context_limit=512;key.flags=0;
    for(int i=1;i<=5;i++)check((unsigned)i,advance(i,i==5)==0);
    snapshot(0,1);
    check(6,nx_prefix_prepare(session,&key,prefix,3)==0);
    check(7,nx_logits_v2(session)==NULL);
    check(8,advance(6,0)==0&&advance(7,1)==0);
    emit(900,0,1);
    uint64_t start=nx_port_ticks();int hit=nx_prefix_restore(session,&key,prefix,3);uint64_t restore_ticks=nx_port_ticks()-start;
    emit(900,1,0);tick(0,restore_ticks);
    emit(100,0,(uint32_t)hit);emit(100,1,(uint32_t)nx_length(session));check(9,nx_logits_v2(session)==NULL);
    snapshot(2,0);
    /* Poison EVERY old suffix position. An attention read beyond logical past
     * causes numeric failure; restoring itself must leave these bytes intact. */
    for(int l=0;l<2;l++)for(int v=0;v<2;v++){
        float *p=(float *)nx_cache(session,l,v);for(int i=3*4;i<640*4;i++)p[i]=NAN;
    }
    check(10,advance(4,0)==0&&advance(5,1)==0);snapshot(1,1);
    check(11,nx_prefix_restore(session,&key,prefix,3)==1);
    check(12,advance(7,0)==0&&advance(8,1)==0);snapshot(3,1);
    /* Every identity component, one token, and prefix length changes miss. */
    for(unsigned j=0;j<9;j++){
        check(20+j*2,nx_prefix_prepare(session,&key,prefix,3)==0);
        nx_prefix_identity different=key;
        if(j<5)((uint8_t *)&different)[j*32]^=1;
        if(j==5)different.abi++;
        if(j==6)different.start_position=1;
        if(j==7)different.context_limit=511;
        if(j==8)different.flags=1;
        emit(110,j,(uint32_t)nx_prefix_restore(session,&different,prefix,3));
        check(21+j*2,nx_length(session)==0&&nx_logits_v2(session)==NULL);
    }
    int32_t changed[3]={1,9,3};
    check(40,nx_prefix_prepare(session,&key,prefix,3)==0);emit(110,9,(uint32_t)nx_prefix_restore(session,&key,changed,3));
    check(41,nx_length(session)==0);
    check(42,nx_prefix_prepare(session,&key,prefix,3)==0);emit(110,10,(uint32_t)nx_prefix_restore(session,&key,prefix,2));
    check(43,nx_length(session)==0);
    check(44,nx_prefix_prepare(session,&key,prefix,0)==NX_ARGUMENT&&nx_length(session)==0);
    check(45,nx_prefix_prepare(session,&key,prefix,513)==NX_ARGUMENT&&nx_length(session)==0);
    check(46,nx_prefix_prepare(session,&key,prefix,3)==0);nx_reset(session);
    check(47,nx_prefix_restore(session,&key,prefix,3)==0);
    check(48,nx_prefix_prepare(session,&key,prefix,3)==0);nx_bind_backend(session,NULL,backend,NULL,0);
    check(49,nx_prefix_restore(session,&key,prefix,3)==0);
    check(50,nx_prefix_prepare(session,&key,prefix,3)==0);nx_prefix_identity other=key;other.numeric[0]^=1;
    check(51,nx_prefix_configure(session,&other)==0&&nx_prefix_restore(session,&key,prefix,3)==0);
    check(52,nx_prefix_prepare(session,&key,prefix,3)==0);int32_t invalid=-1;
    check(53,nx_forward(session,&invalid,1,3,NULL,NULL)==NX_ARGUMENT&&nx_prefix_restore(session,&key,prefix,3)==0);
    nx_bind_backend(session,NULL,backend,NULL,2);
    check(54,nx_prefix_prepare(session,&key,prefix,3)==0);backend_fail=1;
    check(55,advance(4,1)==NX_STATE&&nx_logits_v2(session)==NULL);backend_fail=0;
    check(56,nx_prefix_restore(session,&key,prefix,3)==0);
    check(57,nxr_init(&request,session,forward_fn,reset_fn,clock_fn,NULL,32)==0);
    check(58,nxr_set_prefill(&request,prefill_fn)==0&&nxp_init(&cache,&request,session)==0);
    for(unsigned i=0;i<5;i++)prompt[i]=i+1;
    start=nx_port_ticks();check(59,nxp_begin(&cache,&key,prompt,5,3,2,UINT64_C(1000000000))==0);
    check(60,cache.last_hit==0&&request.kv_length==0);check(61,finish_request(0)==0);tick(1,nx_port_ticks()-start);
    tick(2,request.token_at[0]-request.start_ticks);
    tick(7,request.total_ticks);
    check(62,nxp_prepare(&cache,&key,prefix,3)==0);tick(3,cache.prepare_ticks);
    start=nx_port_ticks();check(63,nxp_begin(&cache,&key,prompt,5,3,2,UINT64_C(1000000000))==0);
    check(64,cache.last_hit==1&&request.kv_length==3&&request.prefilled==3&&request.generated==0&&request.last==0);
    check(65,finish_request(1)==0);tick(4,nx_port_ticks()-start);tick(5,request.token_at[0]-request.start_ticks);tick(6,cache.restore_ticks);
    tick(8,request.total_ticks);
    check(66,nxp_begin(&cache,&key,prompt,5,3,2,1)==0);check(67,nxr_step(&request)==NXR_TIMEOUT);
    check(68,nx_prefix_restore(session,&key,prefix,3)==0&&request.generated==0&&nx_logits_v2(session)==NULL);
    check(69,nxp_prepare(&cache,&key,prefix,3)==0);
    check(70,nxp_begin(&cache,&key,prompt,5,3,2,UINT64_C(1000000000))==0);
    nxs_stream stream;char output[16];nxt_tokenizer tokenizer={0};
    check(71,nxs_open(&stream,&request,&tokenizer,output,sizeof(output),nx_port_ticks(),0,NULL,NULL)==0);
    check(72,nxs_abort(&stream,NXR_FAULT)==NXR_FAULT&&stream.active==0&&stream.bytes==0&&request.state==NXR_FAILED);
    check(73,nx_prefix_restore(session,&key,prefix,3)==0);
    check(74,nxp_prepare(&cache,&key,prefix,3)==0);
    check(75,nxp_begin(&cache,&key,prompt,3,3,2,UINT64_C(1000000000))==0&&cache.last_hit==0);
    check(76,nxp_prepare(&cache,&key,prefix,3)==NXR_BUSY);check(77,nxr_cancel(&request,NXR_FAULT)==NXR_FAULT);
    check(78,nxp_prepare(&cache,&key,prefix,3)==0);
    check(79,nxp_begin(&cache,&key,prompt,513,3,1,10000)==NXR_BOUNDS);
    check(80,nxp_begin(&cache,&key,prompt,5,3,2,UINT64_C(1000000000))==0&&cache.last_hit==1);
    check(81,nxr_cancel(&request,NXR_FAULT)==NXR_FAULT);
    /* Real CPU request-control boundary, independent counting model callback.
     * Full 512-position numerical graph is exercised separately on the host. */
    check(82,nxr_init(&request,NULL,boundary_forward,boundary_reset,clock_fn,NULL,32)==0);
    check(83,nxr_begin_ids(&request,prompt,512,1,UINT64_C(1000000000))==0);
    while(request.state==NXR_PREFILL||request.state==NXR_DECODE)if(nxr_step(&request))break;
    emit(120,0,request.state);emit(120,1,request.stop);emit(120,2,request.generated);emit(120,3,boundary_past);
    check(84,nxr_reset(&request)==0&&nxr_begin_ids(&request,prompt,511,128,UINT64_C(1000000000))==0);
    while(request.state==NXR_PREFILL||request.state==NXR_DECODE)if(nxr_step(&request))break;
    emit(120,4,request.state);emit(120,5,request.stop);emit(120,6,request.generated);emit(120,7,boundary_past);
    emit(130,0,(uint32_t)nx_state_bytes());emit(130,1,(uint32_t)nx_kv_bytes());emit(130,2,(uint32_t)nx_work_bytes());
#ifdef __riscv
    *(volatile uint32_t *)0x10000020=0x0900;for(;;){}
#endif
    return 0;
}
