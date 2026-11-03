#include "coral_backend.h"
/* The reference and public accelerator API both historically name success
 * NX_OK. Keep their independent status types without changing either ABI. */
#include "coral_api_compat.h"
#include <string.h>
static nx_tensor view(uint32_t a,uint32_t bytes,uint32_t dtype,uint32_t n,uint32_t k) {
    uint32_t item=dtype==NX_I8?1:4;
    return (nx_tensor){.address=a,.allocation_bytes=bytes,.dtype=dtype,.rank=2,
        .shape={n,k},.stride_bytes={k*item,item},.layout_id=1};
}
int nxr_coral_linear(void *cookie,const float *x,int rows,const nx_matrix *w,float *y) {
    nxr_coral_backend *b=cookie;
    if(!b||!b->accelerator||!x||!w||!y||rows<1)return NX_ARGUMENT;
    if(w->k!=896&&w->k!=4864) {
#ifdef NX_T19_MINI
        if(w->k!=112&&w->k!=128)return NX_UNSUPPORTED;
#else
        return NX_UNSUPPORTED;
#endif
    }
    uint32_t physical_k=(w->k+63)/64*64;
    uint64_t in=(uint64_t)rows*physical_k*4,out=(uint64_t)rows*w->n*4;
    if(in>b->input_bytes||out>b->output_bytes)return NX_MEMORY;
    nx_context *c=b->accelerator;
    nx_accel_linear j={.a=view((uintptr_t)b->input,in,NX_F32,rows,physical_k),
        .wq=view((uintptr_t)w->q,(uint32_t)w->n*physical_k,NX_I8,w->n,physical_k),
        .sw=view((uintptr_t)w->s,(uint32_t)w->n*((w->k+63)/64)*4,NX_F32,w->n,(w->k+63)/64),
        .y=view((uintptr_t)b->output,out,NX_F32,rows,w->n),.group_size=64};
    if(w->bias)j.bias=(nx_tensor){.address=(uintptr_t)w->bias,.allocation_bytes=w->n*4u,
        .dtype=NX_F32,.rank=1,.shape={w->n},.stride_bytes={4},.layout_id=1};
    nx_call call={.api_version=1,.route=NX_CORAL_RVV,.session=c->session,
        .sequence=c->sequence+1,.timeout_ticks=b->timeout_ticks};
    /* Stage and publish only after actual halt, write response, and drain. */
    for(int r=0;r<rows;r++){memcpy(b->input+r*physical_k,x+r*w->k,w->k*4u);memset(b->input+r*physical_k+w->k,0,(physical_k-w->k)*4u);}
    nx_stats stats;int rc=nx_linear_run(c,&call,&j,&stats);
    if(rc||!stats.output_valid)return NX_STATE;
    memcpy(y,b->output,(size_t)out);return 0;
}
