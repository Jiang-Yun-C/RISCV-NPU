/* Exact production nx_greedy microbenchmark on the T09 CPU, not a host timer.
 * All input stores precede the observation marker. The benchmark owns the
 * uncached workspace window; no accelerator or board peripheral is active. */
#include <stdint.h>
#include "nx_reference.h"

#define VOCABULARY 151936u
#define LOGITS_ADDRESS 0xac000000u
#define RESULT_SENTINEL 0x12345678
#ifndef MEMBENCH_CASE
#define MEMBENCH_CASE 0
#endif
#if MEMBENCH_CASE < 0 || MEMBENCH_CASE > 3
#error MEMBENCH_CASE must be valid=0, tie=1, signed_zero=2 or late_nan=3
#endif

static volatile uint32_t *const uart = (volatile uint32_t *)0x10000000u;
static volatile uint32_t *const status = (volatile uint32_t *)0x10000004u;
static volatile uint32_t *const completion = (volatile uint32_t *)0x10000020u;
static volatile uint32_t *const marker = (volatile uint32_t *)0x100000f0u;

static uint64_t ticks(void) {
    uint32_t hi, lo, again;
    do {
        __asm__ volatile("csrr %0,mcycleh" : "=r"(hi) :: "memory");
        __asm__ volatile("csrr %0,mcycle" : "=r"(lo) :: "memory");
        __asm__ volatile("csrr %0,mcycleh" : "=r"(again) :: "memory");
    } while (hi != again);
    return ((uint64_t)hi << 32) | lo;
}

static void put(char c) {
    while (*status & 1u) __asm__ volatile("nop");
    *uart = (uint8_t)c;
}
static void text(const char *s) { while (*s) put(*s++); }
static void hex32(uint32_t value) {
    static const char digits[] = "0123456789abcdef";
    for (int shift = 28; shift >= 0; shift -= 4) put(digits[(value >> shift) & 15u]);
}
static void finish(uint32_t code) {
    while (*status & 1u) __asm__ volatile("nop");
    __asm__ volatile("fence iorw,iorw" ::: "memory");
    *completion = code;
    for (;;) __asm__ volatile("nop");
}

uint32_t trap_handler(uint32_t cause, uint32_t epc, uint32_t value) {
    text("MEMBENCH_TRAP cause="); hex32(cause);
    text(" epc="); hex32(epc); text(" value="); hex32(value); put('\n');
    finish(0xbadu);
    return epc;
}

int main(void) {
    volatile uint32_t *bits = (volatile uint32_t *)LOGITS_ADDRESS;
    const float *logits = (const float *)LOGITS_ADDRESS;
    /* Negative finite values, then one or two maxima; integer bit construction
     * keeps setup deterministic without pulling conversion/libm into timing. */
    for (uint32_t i = 0; i < VOCABULARY; ++i) bits[i] = 0xbf000000u | (i & 0x007fffffu);
    bits[VOCABULARY - 2] = 0x3f800000u;
    int expected_status = NX_OK, expected_token = (int)VOCABULARY - 2;
#if MEMBENCH_CASE == 1
    bits[19] = 0x3f800000u;
    expected_token = 19;
#elif MEMBENCH_CASE == 2
    bits[23] = 0x80000000u;
    bits[VOCABULARY - 2] = 0x00000000u;
    expected_token = 23;
#elif MEMBENCH_CASE == 3
    bits[VOCABULARY - 1] = 0x7fc12345u;
    expected_status = NX_NUMERIC;
    expected_token = RESULT_SENTINEL;
#endif
    int32_t token = RESULT_SENTINEL;
    __asm__ volatile("fence iorw,iorw" ::: "memory");
    *marker = 1u;
    __asm__ volatile("fence iorw,iorw" ::: "memory");
    uint64_t start = ticks();
    int result = nx_greedy(logits, &token);
    uint64_t elapsed = ticks() - start;
    __asm__ volatile("fence iorw,iorw" ::: "memory");
    *marker = 2u;
    __asm__ volatile("fence iorw,iorw" ::: "memory");
    int passed = result == expected_status && token == expected_token;
    text("MEMBENCH case="); hex32(MEMBENCH_CASE);
    text(" count="); hex32(VOCABULARY);
    text(" ticks="); hex32((uint32_t)(elapsed >> 32)); hex32((uint32_t)elapsed);
    text(" status="); hex32((uint32_t)result);
    text(" token="); hex32((uint32_t)token);
    text(" pass="); hex32((uint32_t)passed); put('\n');
    finish(passed ? 0xc021u : 0xbadu);
    return 0;
}
