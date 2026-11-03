/* Native differential probe. Includes the selected unmodified/changed source
 * so private attention is tested directly; never claims CE64 or board timing. */
#include NX_REFERENCE_SOURCE

static unsigned probe_pv_calls;
static int probe_pv_mode;
static uint64_t probe_pv_hash;

uint64_t nx_port_ticks(void) { static uint64_t tick; return ++tick; }

static int probe_pv(void *cookie,const float *p,const float *v,int stride,
                    int heads,int len,int padded,float *y) {
    (void)cookie;probe_pv_calls++;
    const unsigned char *bytes=(const unsigned char *)p;
    for(size_t i=0;i<(size_t)heads*len*sizeof(float);i++)
        probe_pv_hash=(probe_pv_hash^bytes[i])*UINT64_C(1099511628211);
    if(probe_pv_mode==2)return NX_UNSUPPORTED;
    if(probe_pv_mode==3)return NX_STATE;
    if(probe_pv_mode==4)return NX_NUMERIC;
    /* A host callback checking the exact handoff probabilities and unchanged
     * adjacent-pair PV semantics; it is not a hardware-backend simulation. */
    for(int h=0;h<heads;h++)for(int i=0;i<64;i++) {
        float product[64];
        for(int t=0;t<len;t++)product[t]=p[h*len+t]*v[t*stride+i];
        for(int t=len;t<padded;t++)product[t]=0.0f;
        for(int width=padded;width>1;width/=2)
            for(int t=0;t<width/2;t++)product[t]=product[2*t]+product[2*t+1];
        y[h*64+i]=product[0];
    }
    return NX_OK;
}

int memory_attention_probe(float *q,float *k,float *v,float *out,int rows,int past,
                           int pv_mode,uint64_t metadata[3]) {
    if(!q||!k||!v||!out||!metadata||rows<1||rows>4||past<0||past+rows>S)
        return NX_ARGUMENT;
    nx_session s={0};
    s.q=q;s.k=(void *)k;s.v=(void *)v;s.a=out;
    s.requested_route=pv_mode!=0;s.pv_backend=pv_mode?probe_pv:NULL;
    probe_pv_calls=0;probe_pv_mode=pv_mode;
    probe_pv_hash=UINT64_C(1469598103934665603);
    feclearexcept(FE_ALL_EXCEPT);
    int rc=attention(&s,0,rows,past);
    metadata[0]=probe_pv_calls;metadata[1]=probe_pv_hash;
    metadata[2]=(uint64_t)fetestexcept(FE_ALL_EXCEPT);
    return rc;
}

int memory_greedy_probe(const float *logits,int32_t *token,int *exceptions) {
    feclearexcept(FE_ALL_EXCEPT);
    int rc=nx_greedy(logits,token);
    if(exceptions)*exceptions=fetestexcept(FE_ALL_EXCEPT);
    return rc;
}

/* Optional host benchmark executes the actual function in C. Its wall time
 * describes this native build/cache, not RV32 cycles, DDR bytes or board TTFT. */
uint64_t memory_greedy_repeat(const float *logits,unsigned repeats) {
    uint64_t sum=0;
    for(unsigned i=0;i<repeats;i++) {
        int32_t token=-1;
        int rc=nx_greedy(logits,&token);
        sum+=(uint32_t)token+(uint64_t)(unsigned)(rc!=0);
    }
    return sum;
}
