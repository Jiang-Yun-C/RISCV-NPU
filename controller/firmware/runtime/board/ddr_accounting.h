/* Physical application-owned DDR accounting. BIST traffic and alignment holes
 * are excluded. A loader span is counted only after its actual DDR readback.
 * Monotone per-region addresses prevent duplicate stores inflating occupancy. */
#ifndef T25_DDR_ACCOUNTING_H
#define T25_DDR_ACCOUNTING_H
#include <stdint.h>
#define T25_MEMORY_MAGIC 0x4d323544u
#define T25_MEMORY_HANDOFF 0xba080010u
typedef struct { uint32_t bytes[4], end[4]; } t25_load_memory;
static inline int t25_count_store(t25_load_memory *m,uint32_t address,uint32_t bytes){
    unsigned r;
    uint32_t limit;
    if(address>=0x80000000u&&address<0xa8000000u){r=0;limit=0xa8000000u;}
    else if(address>=0xb8000000u&&address<0xba000000u){r=1;limit=0xba000000u;}
    else if(address>=0xb4000000u&&address<0xb4800000u){r=2;limit=0xb4800000u;}
    else if(address>=0xba000000u&&address<0xba080000u){r=3;limit=0xba080000u;}
    else return -1;
    if(!bytes||bytes>limit-address||address<m->end[r]||bytes>UINT32_MAX-m->bytes[r])return -1;
    m->bytes[r]+=bytes;m->end[r]=address+bytes;return 0;
}
#endif
