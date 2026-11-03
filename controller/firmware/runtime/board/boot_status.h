#ifndef NX_T25_BOOT_STATUS_H
#define NX_T25_BOOT_STATUS_H
#include <stdint.h>
static inline int nxr_boot_ready(void){
#ifdef NX_T25_UART
    return (*(volatile uint32_t *)0x100000e0&2)!=0;
#else
    /* SD publication and the actual CE guard feedback (telemetry bit 9).
     * The separate diagnostic UART SEAL register cannot satisfy this. */
    return *(volatile uint32_t *)0x10002018==1&&
        (*(volatile uint32_t *)0x10000208&(1u<<9))!=0;
#endif
}
#endif
