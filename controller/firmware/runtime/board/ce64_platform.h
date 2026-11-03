#ifndef NXR_CE64_PLATFORM_H
#define NXR_CE64_PLATFORM_H
#include "ce64_backend.h"
int nxr_ce64_platform_open(nxr_ce64_backend *,const nx_weights *);
int nxr_ce64_platform_reset(void);
int nxr_ce64_platform_idle(void);
int nxr_ce64_startup_open(void);
int nxr_ce64_startup_zero(uint32_t,uint32_t,unsigned);
int nxr_ce64_startup_close(void);
#endif
