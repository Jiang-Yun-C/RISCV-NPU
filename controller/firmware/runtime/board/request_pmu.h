#ifndef NX_REQUEST_PMU_H
#define NX_REQUEST_PMU_H
#include <stdint.h>
#define NX_REQUEST_PMU_MAGIC UINT32_C(0x3152504e)
#define NX_REQUEST_PMU_TAG UINT32_C(0x100000b0)
#define NX_REQUEST_PMU_COMMAND UINT32_C(0x100000b4)
#define NX_REQUEST_PMU_CAPABILITY UINT32_C(0x100000b8)
#define NX_REQUEST_PMU_STATUS UINT32_C(0x100000bc)
#define NX_REQUEST_PMU_SNAPSHOT UINT32_C(0x10000300)
#define NX_REQUEST_PMU_COUNTERS 24
/* Status: active, valid, protocol error, live overflow, frozen overflow. */
#define NX_REQUEST_PMU_ACTIVE 1u
#define NX_REQUEST_PMU_VALID 2u
#define NX_REQUEST_PMU_ERROR 4u
#define NX_REQUEST_PMU_OVERFLOW 16u
#define NX_REQUEST_PMU_START 1u
#define NX_REQUEST_PMU_CAPTURE 2u
#define NX_REQUEST_PMU_STOP 3u
#define NX_REQUEST_PMU_CLEAR 4u
enum nx_request_pmu_event {
  NX_PMU_CYCLES,NX_PMU_RETIRED,NX_PMU_EXECUTE_STALL,NX_PMU_BRANCHES,NX_PMU_MISPREDICTS,
  NX_PMU_I_AR,NX_PMU_I_R_BEATS,NX_PMU_I_R_BYTES,NX_PMU_I_ADDRESS_BLOCKED,
  NX_PMU_D_AR,NX_PMU_D_R_BEATS,NX_PMU_D_R_BYTES,NX_PMU_D_AW,NX_PMU_D_W_BEATS,NX_PMU_D_W_BYTES,NX_PMU_D_ADDRESS_BLOCKED,
  NX_PMU_CE_AR,NX_PMU_CE_R_BEATS,NX_PMU_CE_R_BYTES,NX_PMU_CE_AW,NX_PMU_CE_W_BEATS,NX_PMU_CE_W_BYTES,NX_PMU_CE_ADDRESS_BLOCKED,NX_PMU_RESPONSE_ERRORS
};
typedef struct { uint32_t flags,tag,sequence; uint64_t count[NX_REQUEST_PMU_COUNTERS]; } nx_request_pmu_snapshot;
typedef struct {
  void *cookie;
  uint32_t (*read32)(void *,uint32_t);
  void (*write32)(void *,uint32_t,uint32_t);
  void (*fence)(void *);
} nx_request_pmu_io;
/* Return 0 if the old/disabled bitstream does not advertise the PMU. */
static inline int nx_request_pmu_available(const nx_request_pmu_io *io) {
  return io&&io->read32&&io->write32&&io->fence&&io->read32(io->cookie,NX_REQUEST_PMU_CAPABILITY)==NX_REQUEST_PMU_MAGIC
      &&io->read32(io->cookie,NX_REQUEST_PMU_SNAPSHOT)==NX_REQUEST_PMU_MAGIC
      &&(io->read32(io->cookie,NX_REQUEST_PMU_STATUS)>>16)==1u;
}
/* Do not silently restart an active interval. Tag is latched by START. */
static inline int nx_request_pmu_begin(const nx_request_pmu_io *io,uint32_t tag) {
  if(!nx_request_pmu_available(io))return 0;
  if(io->read32(io->cookie,NX_REQUEST_PMU_STATUS)&NX_REQUEST_PMU_ACTIVE)return -1;
  io->write32(io->cookie,NX_REQUEST_PMU_TAG,tag);
  io->write32(io->cookie,NX_REQUEST_PMU_COMMAND,NX_REQUEST_PMU_START);io->fence(io->cookie);
  return (io->read32(io->cookie,NX_REQUEST_PMU_STATUS)&(NX_REQUEST_PMU_ACTIVE|NX_REQUEST_PMU_ERROR))==NX_REQUEST_PMU_ACTIVE?1:-1;
}
/* CAPTURE keeps counting; STOP freezes and stops. Frozen data are coherent,
 * checked with sequence reads around the block. A status change alone cannot
 * authenticate a physical board or make these counters mutually exclusive. */
static inline int nx_request_pmu_capture(const nx_request_pmu_io *io,int stop,uint32_t tag,nx_request_pmu_snapshot *out) {
  if(!out||!nx_request_pmu_available(io))return 0;
  uint32_t before=io->read32(io->cookie,NX_REQUEST_PMU_SNAPSHOT+12);
  io->write32(io->cookie,NX_REQUEST_PMU_COMMAND,stop?NX_REQUEST_PMU_STOP:NX_REQUEST_PMU_CAPTURE);io->fence(io->cookie);
  uint32_t seq=io->read32(io->cookie,NX_REQUEST_PMU_SNAPSHOT+12);
  out->flags=io->read32(io->cookie,NX_REQUEST_PMU_SNAPSHOT+4);
  out->tag=io->read32(io->cookie,NX_REQUEST_PMU_SNAPSHOT+8);out->sequence=seq;
  if(seq==before||out->tag!=tag||(out->flags&(NX_REQUEST_PMU_VALID|NX_REQUEST_PMU_ERROR|NX_REQUEST_PMU_OVERFLOW))!=NX_REQUEST_PMU_VALID)return -1;
  if(stop&&(out->flags&NX_REQUEST_PMU_ACTIVE))return -1;
  for(unsigned i=0;i<NX_REQUEST_PMU_COUNTERS;i++){
    uint32_t lo=io->read32(io->cookie,NX_REQUEST_PMU_SNAPSHOT+16+8*i);
    uint32_t hi=io->read32(io->cookie,NX_REQUEST_PMU_SNAPSHOT+20+8*i);
    out->count[i]=((uint64_t)hi<<32)|lo;
  }
  return seq==io->read32(io->cookie,NX_REQUEST_PMU_SNAPSHOT+12)?1:-1;
}
#endif
