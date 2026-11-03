#ifndef NX_SD_SHA256_H
#define NX_SD_SHA256_H
#include <stdint.h>
typedef struct { uint32_t h[8]; uint64_t bytes; unsigned used; uint8_t block[64]; } nx_sha;
void nx_sha_init(nx_sha *);
void nx_sha_add(nx_sha *,const uint8_t *,unsigned);
void nx_sha_end(nx_sha *,uint8_t out[32]);
#endif
