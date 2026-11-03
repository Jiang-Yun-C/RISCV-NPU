#ifndef T27_COREMARK_TIMER_H
#define T27_COREMARK_TIMER_H
#include <stdint.h>

#ifdef COREMARK_HOST_TEST
/* Host tests supply CSR read sequences; they do not measure RV32 performance. */
uint32_t cm_test_cycle_high(void);
uint32_t cm_test_cycle_low(void);
#define CM_CYCLE_HIGH() cm_test_cycle_high()
#define CM_CYCLE_LOW() cm_test_cycle_low()
#else
static inline uint32_t cm_cycle_high(void) {
    uint32_t value;
    __asm__ volatile("csrr %0,mcycleh" : "=r"(value) : : "memory");
    return value;
}
static inline uint32_t cm_cycle_low(void) {
    uint32_t value;
    __asm__ volatile("csrr %0,mcycle" : "=r"(value) : : "memory");
    return value;
}
#define CM_CYCLE_HIGH() cm_cycle_high()
#define CM_CYCLE_LOW() cm_cycle_low()
#endif

static inline uint64_t cm_read_cycle64(void) {
    uint32_t first_high, low, second_high;
    do {
        first_high = CM_CYCLE_HIGH();
        low = CM_CYCLE_LOW();
        second_high = CM_CYCLE_HIGH();
    } while (first_high != second_high);
    return ((uint64_t)second_high << 32) | low;
}
#endif
