#include <assert.h>
#include <stdint.h>
#include <string.h>
#include "../../firmware/runtime/board/request_pmu.h"
typedef struct {uint32_t capability,flags,tag,next_tag,seq;uint64_t count[24];unsigned writes,fences,reads;int torn;} model;
static uint32_t read32(void *p,uint32_t a){model*m=p;m->reads++;
 if(a==NX_REQUEST_PMU_CAPABILITY||a==NX_REQUEST_PMU_SNAPSHOT)return m->capability;
 if(a==NX_REQUEST_PMU_STATUS||a==NX_REQUEST_PMU_SNAPSHOT+4)return m->flags;
 if(a==NX_REQUEST_PMU_SNAPSHOT+8)return m->tag;
 if(a==NX_REQUEST_PMU_SNAPSHOT+12)return m->seq;
 if(a>=NX_REQUEST_PMU_SNAPSHOT+16&&a<NX_REQUEST_PMU_SNAPSHOT+16+24*8){
  unsigned i=(a-NX_REQUEST_PMU_SNAPSHOT-16)/8;
  if(m->torn&&i==12)m->seq++;
  return (a&4)?(uint32_t)(m->count[i]>>32):(uint32_t)m->count[i];
 }return 0;}
static void write32(void*p,uint32_t a,uint32_t v){model*m=p;m->writes++;
 if(a==NX_REQUEST_PMU_TAG)m->next_tag=v;
 if(a==NX_REQUEST_PMU_COMMAND){
  if(v==NX_REQUEST_PMU_START){m->tag=m->next_tag;m->flags=(1u<<16)|NX_REQUEST_PMU_ACTIVE;}
  else if(v==NX_REQUEST_PMU_CAPTURE||v==NX_REQUEST_PMU_STOP){m->seq++;m->flags|=NX_REQUEST_PMU_VALID;if(v==NX_REQUEST_PMU_STOP)m->flags&=~NX_REQUEST_PMU_ACTIVE;}
 }}
static void fence(void*p){((model*)p)->fences++;}
int main(void){
 model m={.capability=NX_REQUEST_PMU_MAGIC,.flags=1u<<16};nx_request_pmu_io io={&m,read32,write32,fence};nx_request_pmu_snapshot s;
 assert(!nx_request_pmu_available(0));assert(nx_request_pmu_available(&io));
 assert(nx_request_pmu_begin(&io,42)==1);unsigned writes=m.writes;assert(nx_request_pmu_begin(&io,43)==-1&&m.writes==writes);
 for(unsigned i=0;i<24;i++)m.count[i]=UINT64_C(0x1234567800000000)+i;
 assert(nx_request_pmu_capture(&io,0,42,&s)==1&&s.tag==42&&s.sequence==1);
 for(unsigned i=0;i<24;i++)assert(s.count[i]==m.count[i]);
 assert(nx_request_pmu_capture(&io,1,42,&s)==1&&!(s.flags&NX_REQUEST_PMU_ACTIVE));
 assert(nx_request_pmu_begin(&io,44)==1);assert(nx_request_pmu_capture(&io,0,45,&s)==-1);
 m.torn=1;assert(nx_request_pmu_capture(&io,1,44,&s)==-1);m.torn=0;
 m.capability=0;writes=m.writes;assert(!nx_request_pmu_begin(&io,44)&&m.writes==writes);assert(!nx_request_pmu_capture(&io,1,44,&s));
 m.capability=NX_REQUEST_PMU_MAGIC;m.flags=2u<<16;assert(!nx_request_pmu_available(&io));
 return 0;
}
