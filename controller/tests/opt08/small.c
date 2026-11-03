#include "nx_reference.h"
#include <string.h>
#include <math.h>
static int8_t q[64*64];static float scales[64],norm[64],bias[64],inv[32];
int replay(int unused,float *out,uint64_t *meta){
    (void)unused;nx_weights w={0};
    for(int i=0;i<64*64;i++)q[i]=(i*17%31)-15;
    for(int i=0;i<64;i++){scales[i]=0.01f;norm[i]=1;bias[i]=0.001f;}
    for(int i=0;i<32;i++)inv[i]=1.0f/(i+1);
    nx_matrix a={q,scales,0,64,64},b=a;b.bias=bias;
    w.embedding=a;w.norm=norm;w.inv_freq=inv;
    w.layer[0]=(nx_layer){norm,norm,b,b,b,a,a,a,a};
    nx_session *s=nx_create(&w,1);if(!s)return 1;
    int32_t id=1,next=-1;int rc=nx_forward(s,&id,1,0,out,0);
    if(!rc)rc=nx_forward_token_v2(s,2,1,&next);
    if(!rc)memcpy(out+64,nx_logits_v2(s),256);
    meta[2]=(uint32_t)next;nx_reset(s);meta[4]=nx_length(s);meta[5]=nx_logits_v2(s)!=0;
    if(!rc)rc=nx_forward_token_v2(s,3,0,&next);
    if(!rc)memcpy(out+128,nx_logits_v2(s),256);
    meta[3]=(uint32_t)next;meta[6]=nx_length(s)-1;
    float save=norm[63];norm[63]=NAN;next=123;
    int bad=nx_forward_token_v2(s,4,1,&next);norm[63]=save;
    meta[7]=bad==NX_NUMERIC&&next==123&&nx_length(s)==-1&&nx_logits_v2(s)==0;
    nx_opt08_counters(s,meta,meta+1);nx_destroy(s);return rc;
}
