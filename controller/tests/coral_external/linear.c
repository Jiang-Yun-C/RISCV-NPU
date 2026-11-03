/* T07 probe: W8A8 group-64 RVV dot, scalar FP32 restoration, direct external
 * weights/scales/results. Aq and Sa arrive prequantized under the T05 contract.
 * This is a bounded evaluation kernel, not the T15 runtime/API implementation. */
#include <stdint.h>
#include <stddef.h>
#include <riscv_vector.h>

struct Config { uint32_t n,k,m,w,sw,b,y,dots,audit,restore; } config;
int8_t activations[4*4864] __attribute__((aligned(16)));
float activation_scales[4*76] __attribute__((aligned(16)));
volatile uint32_t done, begin_cycle, end_cycle;
static inline uint32_t cycles(void) {
    uint32_t v; __asm__ volatile("csrr %0, 0xb00" : "=r"(v) :: "memory"); return v;
}
int main(void) {
    const uint32_t n=config.n, k=config.k, m=config.m, groups=(k+63)/64;
    const int8_t *weights=(const int8_t *)config.w;
    const float *scales=(const float *)config.sw, *bias=(const float *)config.b;
    volatile float *output=(volatile float *)config.y;
    volatile int32_t *dots=(volatile int32_t *)config.dots;
    if (!n || !k || k>4864 || !m || m>4) { done=0xbad; return 1; }
    begin_cycle=cycles();
    for (uint32_t row=0; row<n; ++row) {
        float sum[4]={0,0,0,0};
        for (uint32_t g=0; g<groups; ++g) {
            size_t count=k-g*64; if (count>64) count=64;
            size_t vl=__riscv_vsetvl_e8m4(count);
            vint8m4_t w=__riscv_vle8_v_i8m4(weights+row*k+g*64,vl);
            float sw=0; if (config.restore) sw=scales[row*groups+g];
            for (uint32_t token=0; token<m; ++token) {
                vint8m4_t a=__riscv_vle8_v_i8m4(activations+token*k+g*64,vl);
                vint16m8_t products=__riscv_vwmul_vv_i16m8(a,w,vl);
                vint32m1_t zero=__riscv_vmv_v_x_i32m1(0,1);
                vint32m1_t reduced=__riscv_vwredsum_vs_i16m8_i32m1(products,zero,vl);
                int32_t dot=__riscv_vmv_x_s_i32m1_i32(reduced);
                if (config.audit) dots[(row*groups+g)*m+token]=dot;
                if (config.restore) {
                    float value=(float)dot;
                    value=value*activation_scales[token*groups+g];
                    value=value*sw;
                    sum[token]=sum[token]+value;
                }
            }
        }
        if (config.restore) for (uint32_t token=0; token<m; ++token) {
            float value=sum[token]; if (bias) value=value+bias[row];
            output[token*n+row]=value;
        }
    }
    __asm__ volatile("fence rw,rw" ::: "memory");
    end_cycle=cycles(); done=0x743037aa;
    return 0;
}
