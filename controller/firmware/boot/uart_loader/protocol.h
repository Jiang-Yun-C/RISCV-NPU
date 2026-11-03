#ifndef NX_UART_PROTOCOL_H
#define NX_UART_PROTOCOL_H
#include <stdint.h>
#define NX_APP_BASE 0xb4000000u
#define NX_APP_LIMIT 0xb7ff0000u
#define NX_IMAGE_MAX 65536u
#define NX_CHUNK_MAX 256u
#define NX_BYTE_TIMEOUT 100000u
enum { NX_BEGIN=1, NX_DATA=2, NX_RUN=3 };
enum { NX_OK=0, NX_DUP=1, NX_CRC=2, NX_RANGE=3, NX_SEQUENCE=4,
       NX_TIMEOUT=5, NX_INCOMPLETE=6, NX_FORMAT=7, NX_IMAGE_CRC=8 };
static inline int nx_image_range(uint32_t address,uint32_t size,uint32_t entry) {
    return address>=NX_APP_BASE && address<NX_APP_LIMIT && size>0 && size<=NX_IMAGE_MAX
        && size<=NX_APP_LIMIT-address && !(address&3u) && !(entry&3u)
        && entry>=address && entry-address<size && size-(entry-address)>=4;
}
static inline uint32_t nx_crc_byte(uint32_t crc,uint8_t value) {
    crc^=value;
    for(unsigned i=0;i<8;i++) crc=(crc>>1)^(0xedb88320u & (0u-(crc&1u)));
    return crc;
}
#endif
