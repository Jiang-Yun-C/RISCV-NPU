/* T21/T27 RV32 port. The five EEMBC algorithms and coremark.h are unchanged. */
#include "coremark.h"
#include "core_portme_timer.h"
#include <stdint.h>

#if defined(VALIDATION_RUN) && VALIDATION_RUN
volatile ee_s32 seed1_volatile = 0x3415;
volatile ee_s32 seed2_volatile = 0x3415;
volatile ee_s32 seed3_volatile = 0x66;
#define CM_RUN_NAME "validation"
#elif defined(PROFILE_RUN) && PROFILE_RUN
volatile ee_s32 seed1_volatile = 8;
volatile ee_s32 seed2_volatile = 8;
volatile ee_s32 seed3_volatile = 8;
#define CM_RUN_NAME "profile"
#else
volatile ee_s32 seed1_volatile = 0;
volatile ee_s32 seed2_volatile = 0;
volatile ee_s32 seed3_volatile = 0x66;
#define CM_RUN_NAME "performance"
#endif
volatile ee_s32 seed4_volatile = ITERATIONS;
volatile ee_s32 seed5_volatile = 0;
ee_u32 default_num_contexts = 1;
static CORE_TICKS begin_tick, end_tick;

#ifdef COREMARK_HOST_TEST
extern void cm_test_putchar(char c);
extern void cm_test_complete(uint32_t code);
#endif

static void uart_drain(void) {
#ifndef COREMARK_HOST_TEST
    while (*(volatile uint32_t *)0x10000004u & 1u) {}
#endif
}

void cm_port_putchar(char c) {
#ifdef COREMARK_HOST_TEST
    cm_test_putchar(c);
#else
    uart_drain();
    *(volatile uint32_t *)0x10000000u = (uint8_t)c;
#endif
}

void start_time(void) {
    /* Never charge the final byte of the preamble to benchmark execution. */
#if COREMARK_REPORT_METADATA
    uart_drain();
#endif
    begin_tick = cm_read_cycle64();
}

void stop_time(void) { end_tick = cm_read_cycle64(); }
CORE_TICKS get_time(void) { return end_tick - begin_tick; }
secs_ret time_in_secs(CORE_TICKS ticks) {
#if HAS_FLOAT
    return (secs_ret)ticks / (secs_ret)CM_CPU_HZ;
#else
    /* Retain the official no-float interface for legacy short-debug callers.
     * Formal builds require HAS_FLOAT so fractional seconds are preserved. */
    return (secs_ret)(ticks / (uint64_t)CM_CPU_HZ);
#endif
}

void portable_init(core_portable *p, int *argc, char *argv[]) {
    (void)argc; (void)argv; p->portable_id = 1;
#if !COREMARK_FORMAL
    ee_printf("T21_SHORT_DEBUG_ONLY iterations=%u data=%u\n", ITERATIONS, TOTAL_DATA_SIZE);
#endif
#if COREMARK_REPORT_METADATA
    ee_printf("CM_PORT version=1 formal=%u hz=%u data=%u mode=%s requested_iterations=%u\n",
              COREMARK_FORMAL, (unsigned)CM_CPU_HZ, TOTAL_DATA_SIZE,
              CM_RUN_NAME, ITERATIONS);
#endif
}

void portable_fini(core_portable *p) {
    p->portable_id = 0;
#if COREMARK_REPORT_METADATA
    /* Unmodified core_main.c prints total_time as unsigned long (32 bits on
     * RV32). This authoritative side record preserves every measured bit. */
    CORE_TICKS ticks = get_time();
    ee_printf("CM_TICKS high=%08x low=%08x\n", (unsigned)(ticks >> 32), (unsigned)ticks);
    ee_printf("CM_DONE\n");
    uart_drain();
#endif
#ifdef COREMARK_HOST_TEST
    cm_test_complete(0xc021u);
#else
    *(volatile uint32_t *)0x10000020u = 0xc021u;
    for (;;) __asm__ volatile("nop");
#endif
}

uint32_t trap_handler(uint32_t cause, uint32_t epc, uint32_t value) {
#if COREMARK_REPORT_METADATA
    ee_printf("CM_TRAP cause=%08x pc=%08x value=%08x\n", cause, epc, value);
    uart_drain();
#else
    (void)cause; (void)value;
#endif
#ifdef COREMARK_HOST_TEST
    cm_test_complete(0xbadu);
#else
    *(volatile uint32_t *)0x10000020u = 0xbadu;
#if COREMARK_REPORT_METADATA
    for (;;) __asm__ volatile("nop");
#endif
#endif
    return epc + 4;
}
