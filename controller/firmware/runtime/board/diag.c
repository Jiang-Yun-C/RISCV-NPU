#include "diag.h"
#ifndef NX_DIAG_HOST
#include "diag_identity.h"
#else
#define NX_DIAG_CID "HOST_FAULT_INJECTION"
#endif
#include "ce64_backend.h"
#define NX_OK NX_ACCEL_OK
#define NX_LINEAR NX_ACCEL_LINEAR
#define NX_ROPE NX_ACCEL_ROPE
#define NX_SWIGLU NX_ACCEL_SWIGLU
#define nx_linear nx_accel_linear
#include "ce64_linear.h"
#include "opt12.h"
#undef nx_linear
#undef NX_SWIGLU
#undef NX_ROPE
#undef NX_LINEAR
#undef NX_OK
#include "runtime.h"
#include <string.h>
/* Separate SRAM below the retained 4KiB stack guard. No tensor/FP/port added.
 * This observer changes timing; it is never a performance qualification. */
typedef struct {uint32_t tag,line,rc,rows,past,layer,phase,epoch,generation,state;
 uint64_t ticks,session,sequence;} record;
typedef struct {uint32_t magic,count,fault,line,rc,rows,past,layer,phase;
 uint64_t budget[4],fault_budget[4];uint32_t entry_backend[256],entry_cache[64];
 record ring[32];uint32_t request[24],call[8],regs[24],bank[2][40],stable[6];
 uint32_t context_words[192],cache_words[64];
 uint32_t vector_view[64],vector_result[32];
 uint32_t backend_words[256],backend_size;uint32_t runtime_words[32];uint32_t dma_words[64];} trace;
#ifdef NX_DIAG_HOST
static trace data;
#else
static trace data __attribute__((section(".diag"),aligned(16)));
#endif
_Static_assert(sizeof(trace)<=8192,"diagnostic SRAM reservation");
static nx_ce64_context *active;
static const uint32_t offsets[24]={CE64_STATUS,CE64_CONTROL,CE64_EPOCH,CE64_RESET_STATUS,
 CE64_ACCEPT_GENERATION,CE64_ACK,CE64_IRQ_STATUS,CE64_FIRST_FAULT_ADDRESS,
 CE64_RUN_LIMIT_LO,CE64_RUN_LIMIT_HI,CE64_TRANSPORT_DIAGNOSTIC,CE64_OUTSTANDING,
 CE64_DESC_WRITTEN_BITMAP,CE64_P_WINDOW_STATUS,CE64_STARTUP_STATUS,CE64_EXECUTION_PROFILE,
 CE64_IRQ_GENERATION,CE64_CAPS,CE64_P_WINDOW_SESSION_LO,CE64_P_WINDOW_SEQUENCE_LO,
 CE64_P_WINDOW_SEQUENCE_HI,CE64_P_WINDOW_PUBLISH,CE64_P_WINDOW_WORDS,CE64_P_WINDOW_LENGTH};
void nx_diag_init(void){memset(&data,0,sizeof(data));data.magic=0x44323731;active=0;}
static void note(uint32_t tag,uint32_t line,int rc,nx_ce64_context *c){
 record *r=&data.ring[data.count++%32];
 *r=(record){.tag=tag,.line=line,.rc=(uint32_t)rc,.rows=data.rows,.past=data.past,.layer=data.layer,.phase=data.phase,.ticks=nx_port_ticks()};
 if(c){r->epoch=c->epoch;r->generation=c->generation;r->state=c->base.state;r->session=c->base.session;r->sequence=c->base.sequence;}
}
void nx_diag_phase(uint32_t rows,uint32_t past,int32_t layer,uint32_t phase){
 data.rows=rows;data.past=past;data.layer=(uint32_t)layer;data.phase=phase;
 note(1,0,0,active);
}
void nx_diag_context(uint32_t tag,const void *p){active=(nx_ce64_context *)p;note(tag,0,0,active);}
void nx_diag_capture(uint32_t line,int rc,const void *p,const void *call,const void *request){
 nx_ce64_context *c=(nx_ce64_context *)p;note(2,line,rc,c);
 if(data.fault)return;
 data.fault=1;data.line=line;data.rc=(uint32_t)rc;memcpy(data.fault_budget,data.budget,sizeof(data.budget));
 if(request)memcpy(data.request,request,sizeof(data.request));
 if(call){_Static_assert(sizeof(nx_call)<=sizeof(data.call),"call snapshot");memcpy(data.call,call,sizeof(nx_call));}
 if(c){_Static_assert(sizeof(*c)<=sizeof(data.context_words),"context snapshot");memcpy(data.context_words,c,sizeof(*c));
  if(c->binding){_Static_assert(sizeof(c->binding->input_cache)<=sizeof(data.cache_words),"cache snapshot");memcpy(data.cache_words,&c->binding->input_cache,sizeof(c->binding->input_cache));}}
 if(!c||!c->base.io.read32)return;
 nx_accel_io *io=&c->base.io;
 data.stable[0]=io->read32(io->cookie,CE64_MMIO_BASE+CE64_EPOCH);
 for(unsigned i=0;i<24;i++)data.regs[i]=io->read32(io->cookie,CE64_MMIO_BASE+offsets[i]);
 for(unsigned b=0;b<2;b++)for(unsigned i=0;i<40;i++)
  data.bank[b][i]=io->read32(io->cookie,CE64_MMIO_BASE+CE64_COMPLETION_BANK0+b*256+4*i);
 data.stable[1]=io->read32(io->cookie,CE64_MMIO_BASE+CE64_EPOCH);
 data.stable[2]=io->read32(io->cookie,CE64_MMIO_BASE+CE64_COMPLETION_BANK0+156);
 data.stable[3]=io->read32(io->cookie,CE64_MMIO_BASE+CE64_COMPLETION_BANK1+156);
 data.stable[4]=io->read32(io->cookie,NX_BRIDGE_STATUS);
 data.stable[5]=io->read32(io->cookie,NX_BRIDGE_ADDRESS);
 for(unsigned i=0;i<64;i++)data.dma_words[i]=io->read32(io->cookie,CE64_MMIO_BASE+0x600+4*i);
}
int nx_diag_state(uint32_t line,void *p){
 nxr_ce64_backend *b=p;nx_diag_capture(line,NX_STATE,b?b->accelerator:0,0,0);
 if(b&&!data.backend_size){_Static_assert(sizeof(*b)<=sizeof(data.backend_words),"backend snapshot");
  memcpy(data.backend_words,b,sizeof(*b));data.backend_size=sizeof(*b);}
 return NX_STATE;
}
int nx_diag_runtime(uint32_t line,int rc,const void *p){
 const nxr_request *r=p;note(3,line,rc,active);
 if(rc&&!data.fault)nx_diag_capture(line,rc,active,0,0);
 if(r){uint32_t words[16]={r->state,r->busy,r->prefilled,r->prompt_length,r->generated,r->kv_length,
  (uint32_t)r->session,(uint32_t)(r->session>>32),(uint32_t)r->sequence,(uint32_t)(r->sequence>>32),
  (uint32_t)r->start_ticks,(uint32_t)(r->start_ticks>>32),(uint32_t)r->timeout_ticks,(uint32_t)(r->timeout_ticks>>32),(uint32_t)rc,0};
  memcpy(data.runtime_words,words,sizeof(words));}
 return rc;
}
static void word(void (*put)(char),uint32_t v){for(int i=7;i>=0;i--)put("0123456789abcdef"[(v>>(4*i))&15]);}
void nx_diag_dump(void (*put)(char)){
 const uint32_t *p=(const uint32_t *)&data;
 const char *header="D27 SNAPSHOT 1 CID=" NX_DIAG_CID "\n";while(*header)put(*header++);
 for(unsigned i=0;i<sizeof(data)/4;i++){if(i%8==0){put('D');put('2');put('7');put(' ');word(put,i);put(' ');}word(put,p[i]);put(i%8==7?'\n':' ');}
 if((sizeof(data)/4)%8)put('\n');header="D27 SNAPSHOT END\n";while(*header)put(*header++);
}
void nx_diag_recovery(int rc){note(4,0,rc,active);}
void nx_diag_vector(const void *view,const void *result){
 _Static_assert(sizeof(nx_opt12_view)<=sizeof(data.vector_view),"view snapshot");
 _Static_assert(sizeof(struct nx_stream_result)<=sizeof(data.vector_result),"result snapshot");
 memcpy(data.vector_view,view,sizeof(nx_opt12_view));memcpy(data.vector_result,result,sizeof(struct nx_stream_result));
}

void nx_diag_budget(uint64_t start,uint64_t spent,uint64_t remaining,uint64_t total){
 data.budget[0]=start;data.budget[1]=spent;data.budget[2]=remaining;data.budget[3]=total;
}
void nx_diag_backend_enter(void *p){
 nxr_ce64_backend *b=p;if(!b)return;memcpy(data.entry_backend,b,sizeof(*b));
 nx_ce64_context *c=b->accelerator;if(c&&c->binding)memcpy(data.entry_cache,&c->binding->input_cache,sizeof(c->binding->input_cache));
}
void nx_diag_reference(uint32_t line,int length,int valid,int in_flight,uint64_t version,uint64_t tail){
 nx_diag_capture(line,-4,active,0,0);data.runtime_words[16]=length;data.runtime_words[17]=valid;data.runtime_words[18]=in_flight;
 data.runtime_words[19]=(uint32_t)version;data.runtime_words[20]=(uint32_t)(version>>32);
 data.runtime_words[21]=(uint32_t)tail;data.runtime_words[22]=(uint32_t)(tail>>32);
}
