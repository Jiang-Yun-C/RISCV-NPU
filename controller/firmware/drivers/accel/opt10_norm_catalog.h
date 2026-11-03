/* Exact original immutable norm views; generated from the frozen verified pack.
 * Membership grants no seal by itself. Callers must use the typed live authority. */
#ifndef NX_OPT10_NORM_CATALOG_H
#define NX_OPT10_NORM_CATALOG_H
#include <stdint.h>
#define NX_OPT10_NORM_COUNT 49u
#define NX_OPT10_NORM_K 896u
#define NX_OPT10_NORM_BYTES 3584u
#define NX_OPT10_NORM_PACK_SHA256 "f55c1a1efd0188a3b792e695fb9f404080f0ffd10cae44d1831b595af6b37f71"
static const uint32_t nx_opt10_norm_addresses[49]={
    0x889f1400u,
    0x88bcf400u,
    0x8990fa00u,
    0x89aeda00u,
    0x8a82e000u,
    0x8aa0c000u,
    0x8b74c600u,
    0x8b92a600u,
    0x8c66ac00u,
    0x8c848c00u,
    0x8d589200u,
    0x8d767200u,
    0x8e4a7800u,
    0x8e685800u,
    0x8f3c5e00u,
    0x8f5a3e00u,
    0x902e4400u,
    0x904c2400u,
    0x91202a00u,
    0x913e0a00u,
    0x92121000u,
    0x922ff000u,
    0x9303f600u,
    0x9321d600u,
    0x93f5dc00u,
    0x9413bc00u,
    0x94e7c200u,
    0x9505a200u,
    0x95d9a800u,
    0x95f78800u,
    0x96cb8e00u,
    0x96e96e00u,
    0x97bd7400u,
    0x97db5400u,
    0x98af5a00u,
    0x98cd3a00u,
    0x99a14000u,
    0x99bf2000u,
    0x9a932600u,
    0x9ab10600u,
    0x9b850c00u,
    0x9ba2ec00u,
    0x9c76f200u,
    0x9c94d200u,
    0x9d68d800u,
    0x9d86b800u,
    0x9e5abe00u,
    0x9e789e00u,
    0x9f4ca400u,
};
static inline int nx_opt10_norm_member(uint32_t address,uint32_t bytes,uint32_t k){
    if(bytes!=NX_OPT10_NORM_BYTES||k!=NX_OPT10_NORM_K)return 0;
    for(unsigned i=0;i<NX_OPT10_NORM_COUNT;i++)if(address==nx_opt10_norm_addresses[i])return 1;
    return 0;
}
#endif
