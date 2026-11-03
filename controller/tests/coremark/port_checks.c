/* Controlled host CSR sequences: correctness tests, never performance data. */
#include "coremark.h"
#include "core_portme_timer.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

static uint32_t highs[16], lows[16];
static unsigned hi_count, lo_count;
static char output[8192];
static unsigned output_length;
static uint32_t completion;
extern volatile ee_s32 seed1_volatile, seed2_volatile, seed3_volatile;

uint32_t cm_test_cycle_high(void) { assert(hi_count < 16); return highs[hi_count++]; }
uint32_t cm_test_cycle_low(void) { assert(lo_count < 16); return lows[lo_count++]; }
void cm_test_putchar(char c) {
    assert(output_length + 1 < sizeof(output));
    output[output_length++] = c; output[output_length] = 0;
}
void cm_test_complete(uint32_t code) { completion = code; }

static void reset_reads(void) {
    memset(highs, 0, sizeof(highs)); memset(lows, 0, sizeof(lows));
    hi_count = lo_count = 0;
}
static void reset_output(void) { output[0] = 0; output_length = 0; }

int main(void) {
    assert(sizeof(CORE_TICKS) == 8);
    reset_reads();
    highs[0] = 7; highs[1] = 8; highs[2] = 8; highs[3] = 8;
    lows[0] = 0xffffffffu; lows[1] = 3;
    assert(cm_read_cycle64() == UINT64_C(0x800000003));
    assert(hi_count == 4 && lo_count == 2);

    reset_reads();
    highs[0] = highs[1] = 1; highs[2] = highs[3] = 3;
    lows[0] = 0xffffff00u; lows[1] = 0x100;
    start_time(); stop_time();
    assert(get_time() == UINT64_C(0x100000200));
    reset_reads();
    highs[0] = highs[1] = 0xffffffffu;
    lows[0] = 0xffffff00u; lows[1] = 0x100;
    start_time(); stop_time();
    assert(get_time() == 512);

#if HAS_FLOAT
    double one = time_in_secs(1);
    assert(one > 0 && one == 1.0 / (double)CM_CPU_HZ);
    assert(time_in_secs((uint64_t)CM_CPU_HZ * 12 + CM_CPU_HZ / 2) == 12.5);
    assert(time_in_secs(UINT64_C(5000000000)) == 5000000000.0 / (double)CM_CPU_HZ);
#else
    assert(time_in_secs((uint64_t)CM_CPU_HZ * 12 + CM_CPU_HZ / 2) == 12);
#endif
#if defined(VALIDATION_RUN) && VALIDATION_RUN
    assert(seed1_volatile == 0x3415 && seed2_volatile == 0x3415 && seed3_volatile == 0x66);
#elif defined(PROFILE_RUN) && PROFILE_RUN
    assert(seed1_volatile == 8 && seed2_volatile == 8 && seed3_volatile == 8);
#else
    assert(seed1_volatile == 0 && seed2_volatile == 0 && seed3_volatile == 0x66);
#endif
    reset_output();
    assert(ee_printf("%08x %u %d %llu %lld %% %s", 0xc021u, 4294967295u,
                     -2147483647 - 1, 18446744073709551615ull,
                     -9223372036854775807ll - 1, "ok") == 78);
    assert(strcmp(output, "0000c021 4294967295 -2147483648 18446744073709551615 -9223372036854775808 % ok") == 0);
#if HAS_FLOAT
    reset_output();
    ee_printf("%f %f %.3f %.0f %f", 12.5, 0.000000008, 1.9999, 9.75, -0.0);
    assert(strcmp(output, "12.500000 0.000000 2.000 10 -0.000000") == 0);
#endif
    reset_output();
    core_portable portable; int argc = 0; char *argv[] = {0};
    portable_init(&portable, &argc, argv);
    assert(portable.portable_id == 1);
#if COREMARK_FORMAL
    assert(strstr(output, "T21_SHORT_DEBUG_ONLY") == 0);
#else
    assert(strstr(output, "T21_SHORT_DEBUG_ONLY") != 0);
#endif
    portable_fini(&portable);
    assert(portable.portable_id == 0 && completion == 0xc021);
#if COREMARK_REPORT_METADATA
    assert(strstr(output, "CM_TICKS high=00000000 low=00000200\nCM_DONE\n") != 0);
#endif
    puts("PASS: rollover, elapsed cycles, clock precision, seeds, reporting");
    return 0;
}
