/* Actual opt12 driver, with only the completed transport boundary mocked. */
#include "opt12.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static unsigned checks,submits,writes,mode;static uint64_t clock_ticks;
static uint32_t capability=CE64_LONG_PV_MAGIC,bridge;
static struct nx_stream_request captured;
#define CHECK(x) do{checks++;if(!(x)){fprintf(stderr,"PV driver line %d: %s\n",__LINE__,#x);exit(1);}}while(0)
static uint64_t ticks(void*p){(void)p;return ++clock_ticks;}
static void fence(void*p){(void)p;}
static uint32_t read32(void*p,uint32_t a){(void)p;if(a==CE64_MMIO_BASE+CE64_LONG_PV_CAPABILITY)return capability;
 if(a==NX_BRIDGE_CONTROL)return bridge;return 0;}
static void write32(void*p,uint32_t a,uint32_t v){(void)p;writes++;if(a==NX_BRIDGE_CONTROL)bridge=v;}
nx_status nx_ce64_linear_execute(void *cookie,const nx_call *call,const struct nx_stream_request *j,struct nx_stream_result *r){
 nx_ce64_transport*t=cookie;nx_ce64_context*c=t->context;submits++;captured=*j;
 CHECK(c->base.state==NX_ACCEL_RUNNING);c->generation++;c->acquired_generation=c->generation;
 *r=(struct nx_stream_result){.valid=1};if(mode==1)return NX_EIO;
 if(mode==2)clock_ticks+=call->timeout_ticks;return NX_OK;
}
int main(void){
 nx_ce64_context c={.base={.initialized=1,.state=NX_ACCEL_IDLE,.session=9,
  .io={.read32=read32,.write32=write32,.ticks=ticks,.fence=fence}},.epoch=3};
 nx_ce64_transport t={.context=&c};struct nx_stream_result r;
 nx_call call={.api_version=2,.route=NX_CE64,.session=9,.sequence=1,.timeout_ticks=1000};
 const unsigned lengths[]={63,64,65,127,128,129,255,256,257,511,512};
 for(unsigned i=0;i<sizeof(lengths)/sizeof(lengths[0]);i++){
  unsigned n=lengths[i],pad=1;while(pad<n)pad*=2;call.sequence=c.base.sequence+1;
  CHECK(nx_pv_run(&t,&call,0xba000000,0xa8000000,0xac000ff0,7,n,pad,&r)==NX_OK);
  CHECK(r.valid&&c.base.state==NX_ACCEL_IDLE&&captured.k==n&&captured.row_bytes==pad);
  CHECK(captured.opcode==5&&captured.output_stride==7&&captured.source_stride==512&&captured.destination==0xac000ff0);
 }
 call.sequence=c.base.sequence+1;unsigned before=submits,io=writes;capability=0;
 CHECK(nx_pv_run(&t,&call,0xba000000,0xa8000000,0xac000000,7,65,128,&r)==NX_EUNSUPPORTED);
 CHECK(submits==before&&writes==io&&c.base.state==NX_ACCEL_IDLE&&c.base.sequence+1==call.sequence&&!r.valid);
 capability=CE64_LONG_PV_MAGIC;
 c.base.initialized=0;
 CHECK(nx_pv_run(&t,&call,0xba000000,0xa8000000,0xac000000,7,65,128,&r)==NX_ESTATE);
 c.base.initialized=1;c.base.io.read32=NULL;
 CHECK(nx_pv_run(&t,&call,0xba000000,0xa8000000,0xac000000,7,65,128,&r)==NX_ESTATE);
 c.base.io.read32=read32;call.sequence++;
 CHECK(nx_pv_run(&t,&call,0xba000000,0xa8000000,0xac000000,7,65,128,&r)==NX_ESTATE);
 call.sequence--;
 CHECK(nx_pv_run(&t,&call,0xba000010,0xa8000000,0xac000000,7,65,128,&r)==NX_EBOUNDS);
 CHECK(nx_pv_run(&t,&call,0xba000000,0xa8000010,0xac000000,7,65,128,&r)==NX_EBOUNDS);
 CHECK(nx_pv_run(&t,&call,0xbBfffe00,0xa8000000,0xac000000,7,512,512,&r)==NX_EBOUNDS);
 CHECK(nx_pv_run(&t,&call,0xba000000,0xa8efff00,0xac000000,7,512,512,&r)==NX_EBOUNDS);
 CHECK(nx_pv_run(&t,&call,0xba000000,0xa8000000,0xb3ffff00,7,512,512,&r)==NX_EBOUNDS);
 CHECK(nx_pv_run(&t,&call,0xba000000,0xa8000000,0xba000100,7,512,512,&r)==NX_EBOUNDS);
 CHECK(nx_pv_run(&t,&call,0xba000000,0xa8000000,0xac000000,7,513,1024,&r)==NX_EINVAL);
 CHECK(nx_pv_run(&t,&call,0xba000000,0xa8000000,0xac000000,7,512,511,&r)==NX_EINVAL);
 CHECK(nx_pv_run(&t,&call,0xba000000,0xa8000000,0xac000000,8,512,512,&r)==NX_EINVAL);
 CHECK(submits==before&&writes==io&&c.base.state==NX_ACCEL_IDLE);
 for(mode=1;mode<=2;mode++){
  c.base.state=NX_ACCEL_IDLE;call.sequence=c.base.sequence+1;
  CHECK(nx_pv_run(&t,&call,0xba000000,0xa8000000,0xac000000,7,512,512,&r)==(mode==1?NX_EIO:NX_ETIMEOUT));
  CHECK(c.base.state==NX_ACCEL_FAULTED&&bridge==3&&c.base.sequence==call.sequence);
 }
 printf("{\"status\":\"PASS\",\"checks\":%u,\"submissions\":%u,\"scope\":\"actual long PV driver with mocked completed transport\"}\n",checks,submits);
 return 0;
}
