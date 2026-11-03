/* Read-only native oracle around the existing CPU application C semantics.
 * This neither drives MMIO nor executes any physical action. */
#include "application.h"
#include <stdint.h>

int competition_evaluate(const char *text,size_t bytes,int32_t temperature,
                         uint32_t light,uint32_t out[19]) {
    struct app_program program;
    struct app_state state={temperature,light,1,0};
    struct app_result result={0};
    for(unsigned i=0;i<19;i++)out[i]=0;
    int rc=app_parse(&program,text,bytes);
    if(!rc)rc=app_evaluate(&program,&state,1,0,&result);
    out[0]=(uint32_t)rc;out[1]=result.count;out[2]=result.read_mask;
    for(unsigned i=0;i<result.count;i++) {
        out[3+2*i]=result.actions[i].device;out[4+2*i]=result.actions[i].value;
    }
    return rc;
}
