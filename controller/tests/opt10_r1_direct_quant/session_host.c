/* Real complete two-block model control, mock backend executing exact C math.
 * Independent Python oracle checks every final logit and KV element. */
#include "nx_reference.h"
#include "inputs.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static _Alignas(16) unsigned char state[16384],state2[16384];
static _Alignas(16) unsigned char kv[40960],kv2[40960],work[4096],work2[4096];
static nx_session *s,*baseline;
static nx_weights weights;
static unsigned checks,calls,private_calls,legacy_calls,fail_call;
static int fail_status;
static unsigned vector_calls,private_vectors,legacy_vectors,vector_fail_call;
#define CHECK(x) do{checks++;if(!(x)){fprintf(stderr,"line %d: %s\n",__LINE__,#x);exit(1);}}while(0)
uint64_t nx_port_ticks(void){static uint64_t t;return ++t;}
static int execute(const float *x,int rows,const nx_matrix *w,float *y){
    calls++;
    /* No accessor exposes any earlier/partial result during a request. */
    CHECK(!nx_logits_v2(s)&&!nx_cache(s,0,0)&&nx_length(s)==-1);
    size_t n=99;CHECK(!nx_cache_view(s,1,1,&n)&&n==0);
    if(calls==fail_call){
        for(int i=0;i<rows*w->n/2;i++)y[i]=12345.0f;
        return fail_status;
    }
    return nx_linear(x,rows,w,y,NULL);
}
static int legacy(void *p,const float *x,int rows,const nx_matrix *w,float *y){
    (void)p;legacy_calls++;return execute(x,rows,w,y);
}
static int private(void *p,const float *x,int rows,const nx_matrix *w,float *y){
    (void)p;private_calls++;return execute(x,rows,w,y);
}
static int vector_execute(unsigned mode,const float *x,const float *u,int rows,int k,float *y){
    vector_calls++;CHECK(!nx_logits_v2(s)&&!nx_cache(s,0,0)&&nx_length(s)==-1);
    if(vector_calls==vector_fail_call){for(int i=0;i<rows*k/2;i++)y[i]=12345.0f;return fail_status;}
    if(mode==7)return nx_norm(x,u,rows,k,y);
    if(mode==0)return nx_swiglu(x,u,rows*k,y);
    CHECK(mode==2);for(int i=0;i<rows*k;i++)y[i]=x[i]+u[i];return NX_OK;
}
static int vector_legacy(void *p,unsigned mode,const float *x,const float *u,int rows,int k,float *y){
    (void)p;legacy_vectors++;return vector_execute(mode,x,u,rows,k,y);
}
static int vector_private(void *p,unsigned mode,const float *x,const float *u,int rows,int k,float *y){
    (void)p;private_vectors++;if(mode==0)CHECK(y!=x&&y!=u);return vector_execute(mode,x,u,rows,k,y);
}
static void snapshot(FILE *f,int n){
    const float *y=nx_logits_v2(s);CHECK(y&&nx_length(s)==n);
    CHECK(fwrite(y,sizeof(float),32,f)==32);
    for(int l=0;l<2;l++)for(int v=0;v<2;v++){
        size_t count=0;const float *p=nx_cache_view(s,l,v,&count);CHECK(p&&count==(size_t)n);
        CHECK(fwrite(p,sizeof(float),(size_t)n*4,f)==(size_t)n*4);
    }
}
int main(void){
    weights.embedding=(nx_matrix){&qe[0][0],&se[0][0],NULL,32,28};weights.norm=norm;weights.inv_freq=inv;
    for(int l=0;l<2;l++){
        nx_layer *p=&weights.layer[l];p->norm1=n1[l];p->norm2=n2[l];
        nx_matrix *m[]={&p->q,&p->k,&p->v,&p->o,&p->gate,&p->up,&p->down};
        const int ns[]={28,4,4,28,32,32,28},ks[]={28,28,28,28,28,28,32};
        for(int j=0;j<7;j++)*m[j]=(nx_matrix){&wq[l][j][0][0],&sw[l][j][0][0],j<3?bias[l][j]:NULL,ns[j],ks[j]};
    }
    s=nx_init_static(&weights,state,sizeof(state),kv,sizeof(kv),work,sizeof(work));
    baseline=nx_init_static(&weights,state2,sizeof(state2),kv2,sizeof(kv2),work2,sizeof(work2));CHECK(s&&baseline);
    nx_bind_backend(s,NULL,legacy,NULL,2);nx_bind_private_backend(s,private);nx_bind_vector_backend(s,vector_legacy);nx_bind_private_vector_backend(s,vector_private);
    int32_t ids[256];for(unsigned i=0;i<256;i++)ids[i]=(i+1)%32;
    const int lengths[]={1,3,4,5,7,8,9,128,256};
    FILE *f=fopen("snapshots.bin","wb");CHECK(f);
    for(int width=1;width<=4;width+=3)for(unsigned j=0;j<sizeof(lengths)/sizeof(lengths[0]);j++){
        int n=lengths[j];nx_reset(s);CHECK(!nx_set_prefill_rows(s,width));
        for(int past=0;past<n;){int rows=n-past<width?n-past:width;int32_t next=-777;
            CHECK(!nx_forward_block_v3(s,ids+past,rows,past,past+rows==n?&next:NULL));past+=rows;}
        snapshot(f,n);
    }
    CHECK(!fclose(f));
    /* Every projection can fail after a partial write. No fallback, token,
     * KV/logit view or prepared prefix survives. Reset then replay exactly. */
    nx_reset(baseline);int32_t expected=-1;CHECK(!nx_forward_block_v3(baseline,ids,1,0,&expected));
    float reference[32];memcpy(reference,nx_logits_v2(baseline),sizeof(reference));
    for(unsigned target=1;target<=15;target++)for(unsigned kind=0;kind<2;kind++){
        nx_reset(s);calls=0;fail_call=target;fail_status=kind?NX_NUMERIC:NX_STATE;
        int32_t next=-777;CHECK(nx_forward_block_v3(s,ids,1,0,&next)==fail_status);
        CHECK(calls==target&&next==-777&&!nx_logits_v2(s)&&!nx_cache(s,0,0)&&nx_length(s)==-1);
        fail_call=0;nx_reset(s);CHECK(!nx_forward_block_v3(s,ids,1,0,&next));
        CHECK(next==expected&&!memcmp(reference,nx_logits_v2(s),sizeof(reference)));
    }
    for(unsigned target=1;target<=11;target++)for(unsigned kind=0;kind<2;kind++){
        nx_reset(s);calls=vector_calls=0;vector_fail_call=target;fail_status=kind?NX_NUMERIC:NX_STATE;
        int32_t next=-777;CHECK(nx_forward_block_v3(s,ids,1,0,&next)==fail_status);
        CHECK(vector_calls==target&&next==-777&&!nx_logits_v2(s)&&!nx_cache(s,0,0)&&nx_length(s)==-1);
        vector_fail_call=0;nx_reset(s);CHECK(!nx_forward_block_v3(s,ids,1,0,&next));
        CHECK(next==expected&&!memcmp(reference,nx_logits_v2(s),sizeof(reference)));
    }
    vector_calls=private_vectors=legacy_vectors=0;
    /* All public callback/KV routes remain staged; private never takes K/V. */
    calls=private_calls=legacy_calls=0;nx_reset(s);int32_t next=-777;
    CHECK(!nx_forward_block_v3(s,ids,1,0,&next));CHECK(private_calls==11&&legacy_calls==4&&calls==15);CHECK(private_vectors==11&&legacy_vectors==0&&vector_calls==11);
    nx_reset(s);CHECK(!nx_logits_v2(s));
    printf("{\"checks\":%u,\"partial_failure_cases\":30,\"vector_partial_failure_cases\":22,\"vector_private_per_token\":11,\"private_per_token\":%u,\"legacy_KV_per_token\":%u}\n",checks,private_calls,legacy_calls);
    return 0;
}
