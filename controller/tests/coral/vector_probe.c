/* T06: signed widening multiply/add, vector reduction and a non-multiple tail.
 * Inputs and expected answers are supplied/checked independently by the host.
 * Explicit intrinsics keep the exercised RVV path visible in disassembly.
 */
#include <stdint.h>
#include <stddef.h>
#include <riscv_vector.h>

enum { N = 67 };
int8_t input_a[N] __attribute__((aligned(16)));
int8_t input_b[N] __attribute__((aligned(16)));
int16_t sums[N] __attribute__((aligned(16)));
int16_t products[N] __attribute__((aligned(16)));
int32_t dot_result;
uint32_t done;

int main(void) {
    int32_t total = 0;
    for (size_t i = 0; i < N;) {
        size_t vl = __riscv_vsetvl_e8m1(N - i);
        vint8m1_t a = __riscv_vle8_v_i8m1(input_a + i, vl);
        vint8m1_t b = __riscv_vle8_v_i8m1(input_b + i, vl);
        vint16m2_t s = __riscv_vwadd_vv_i16m2(a, b, vl);
        vint16m2_t p = __riscv_vwmul_vv_i16m2(a, b, vl);
        __riscv_vse16_v_i16m2(sums + i, s, vl);
        __riscv_vse16_v_i16m2(products + i, p, vl);
        vint32m1_t zero = __riscv_vmv_v_x_i32m1(0, 1);
        vint32m1_t reduction = __riscv_vwredsum_vs_i16m2_i32m1(p, zero, vl);
        total += __riscv_vmv_x_s_i32m1_i32(reduction);
        i += vl;
    }
    dot_result = total;
    done = 0x743036aa;
    return 0;
}
