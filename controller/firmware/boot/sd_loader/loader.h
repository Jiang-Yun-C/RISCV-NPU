#ifndef NX_SD_LOADER_H
#define NX_SD_LOADER_H
#include <stdint.h>
/* Stable error numbers; model errors match the names in T10's manifest. */
enum { SD_OK=0,E_TIMEOUT=1,E_CARD=2,E_CRC=3,E_MEDIA=4,E_MAGIC=5,E_VERSION=6,E_ENDIAN=7,
 E_LAYOUT=8,E_CHECKSUM=9,E_BOUNDS=10,E_OVERFLOW=11,E_ALIGNMENT=12,E_RESERVED=13,
 E_SHAPE=14,E_ALIAS=15,E_DUPLICATE=16,E_OVERLAP=17,E_NUMERIC=18,E_METADATA=19,E_SELFTEST=20 };
#define NX_DIRECTORY 0xba000000u
#define NX_DIRECTORY_LIMIT 4096u
uint32_t nx_sd_boot(void);
#endif
