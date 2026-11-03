#include <stdint.h>
#include <stddef.h>

#define MMIO(off) (*(volatile uint32_t *)(uintptr_t)(0x10000000u + (off)))
#define CSR_READ(name) ({ uint32_t v; __asm__ volatile("csrr %0, " #name : "=r"(v)); v; })
#define REQUIRE(test, code) do { if (!(test)) fail(code); } while (0)

extern uint32_t __bss_start[], __bss_end[], __stack_bottom[], __stack_top[];
extern void illegal_test(void), illegal_site(void);
extern uint32_t fence_patch_test(void);
static volatile uint32_t initialized = 0x13579bdf;
static volatile float float_a = 1.5f, float_b = 2.25f, float_c = -0.5f;
static volatile uint32_t memory_words[32];
static volatile uint32_t timer_count, illegal_count, illegal_pc, illegal_value;

static void putc_uart(char c) {
    while (MMIO(4) & 1u) {}
    MMIO(0) = (unsigned char)c;
}
static void puts_uart(const char *s) { while (*s) putc_uart(*s++); }
static void hex_uart(uint32_t x) {
    for (int shift = 28; shift >= 0; shift -= 4)
        putc_uart("0123456789abcdef"[(x >> shift) & 15u]);
}
static void field(const char *s, uint32_t x) { puts_uart(s); hex_uart(x); putc_uart('\n'); }
static void stop(uint32_t code) __attribute__((noreturn));
static void stop(uint32_t code) {
    while (MMIO(4) & 1u) {}
    __asm__ volatile("fence iorw, iorw" ::: "memory");
    MMIO(0x20) = code;
    for (;;) __asm__ volatile("nop");
}
static void fail(uint32_t code) __attribute__((noreturn));
static void fail(uint32_t code) { field("FAIL=", code); stop(0xdead0000u | code); }

uint32_t trap_handler(uint32_t cause, uint32_t pc, uint32_t value) {
    if (cause == 0x80000007u) {
        MMIO(0x14) = 0xffffffffu;
        timer_count++;
        return pc;
    }
    if (cause == 2u && pc == (uint32_t)(uintptr_t)illegal_site) {
        illegal_count++;
        illegal_pc = pc;
        illegal_value = value;
        return pc + 4u;
    }
    field("TRAP_CAUSE=", cause);
    field("TRAP_PC=", pc);
    field("TRAP_VALUE=", value);
    fail(0x100u | cause);
}

static uint32_t mix(uint32_t h, uint32_t x) {
    return ((h << 5) | (h >> 27)) ^ x;
}
static uint32_t random_word(uint32_t *state) {
    uint32_t x = *state;
    x ^= x << 13; x ^= x >> 17; x ^= x << 5;
    return *state = x;
}
#define M_OP(op, a, b) ({ uint32_t v; __asm__ volatile(#op " %0, %1, %2" : "=r"(v) : "r"(a), "r"(b)); v; })
static uint32_t arithmetic(uint32_t seed) {
    uint32_t h = 0x12345678u, state = seed | 1u;
    for (unsigned i = 0; i != 32; ++i) {
        uint32_t a = random_word(&state), b = random_word(&state) | 1u;
        h = mix(h, a + b); h = mix(h, a - b);
        h = mix(h, M_OP(mul, a, b)); h = mix(h, M_OP(mulh, a, b));
        h = mix(h, M_OP(mulhu, a, b)); h = mix(h, M_OP(mulhsu, a, b));
        h = mix(h, M_OP(div, a, b)); h = mix(h, M_OP(divu, a, b));
        h = mix(h, M_OP(rem, a, b)); h = mix(h, M_OP(remu, a, b));
    }
    REQUIRE(M_OP(div, 123u, 0u) == 0xffffffffu, 0x21);
    REQUIRE(M_OP(divu, 123u, 0u) == 0xffffffffu, 0x22);
    REQUIRE(M_OP(rem, 123u, 0u) == 123u, 0x23);
    REQUIRE(M_OP(remu, 123u, 0u) == 123u, 0x24);
    REQUIRE(M_OP(div, 0x80000000u, 0xffffffffu) == 0x80000000u, 0x25);
    REQUIRE(M_OP(rem, 0x80000000u, 0xffffffffu) == 0, 0x26);
    return h;
}
static uint32_t memory_test(uint32_t seed) {
    uint32_t h = 0;
    volatile uint32_t stack_words[16];
    for (unsigned i = 0; i != 32; ++i) memory_words[i] = seed ^ (0x1020304u * (i + 1u));
    volatile uint8_t *bytes = (volatile uint8_t *)memory_words;
    bytes[0] = 0x80; bytes[1] = 0x7f; bytes[2] = 0xa5; bytes[3] = 0x5a;
    REQUIRE(memory_words[0] == 0x5aa57f80u, 0x31);
    REQUIRE(*(volatile int8_t *)bytes == -128, 0x32);
    // Halfword accesses in inline assembly avoid C aliasing assumptions.
    uint32_t signed_half, unsigned_half;
    __asm__ volatile("sh %2, 4(%3)\n\tlh %0, 4(%3)\n\tlhu %1, 4(%3)"
        : "=&r"(signed_half), "=&r"(unsigned_half) : "r"(0x8001u), "r"(bytes) : "memory");
    REQUIRE(signed_half == 0xffff8001u && unsigned_half == 0x8001u, 0x33);
    for (unsigned i = 0; i != 16; ++i) stack_words[i] = memory_words[i] ^ memory_words[31-i];
    for (unsigned i = 0; i != 32; ++i) h = mix(h, memory_words[i]);
    for (unsigned i = 0; i != 16; ++i) h = mix(h, stack_words[i]);
    return h;
}
int main(void) {
    // RAM starts poisoned; these checks precede any mutation of BSS variables.
    for (volatile uint32_t *p = __bss_start; p != __bss_end; ++p) REQUIRE(*p == 0, 1);
    REQUIRE(initialized == 0x13579bdfu, 2);
    uintptr_t sp; __asm__ volatile("mv %0, sp" : "=r"(sp));
    REQUIRE((sp & 15u) == 0 && sp >= (uintptr_t)__stack_bottom && sp < (uintptr_t)__stack_top, 3);
    REQUIRE(CSR_READ(misa) == 0x40001100u, 4);
    puts_uart("Hello T03\nBOOT OK\n");
    uint32_t seed = MMIO(0x18);
    field("SEED=", seed);
    uint32_t a = arithmetic(seed), m = memory_test(seed);
    field("ARITH=", a); field("MEM=", m);
    union { float f; uint32_t u; } fp;
    fp.f = float_a * float_b + float_c;
    REQUIRE(fp.u == 0x40380000u, 0x41);
    field("SOFTFP=", fp.u);
    REQUIRE(fence_patch_test() == 42u, 0x51);
    puts_uart("FENCE.I OK\n");
    illegal_test();
    REQUIRE(illegal_count == 1 && illegal_pc == (uint32_t)(uintptr_t)illegal_site && illegal_value == 0xffffffffu, 0x61);
    field("ILLEGAL=", illegal_count);
    uint32_t start = MMIO(8);
    MMIO(0x14) = 0xffffffffu;
    MMIO(0x10) = start + 256u;
    MMIO(0x14) = MMIO(12);
    __asm__ volatile("csrs mie, %0\n\tcsrs mstatus, %1" :: "r"(0x80u), "r"(8u) : "memory");
    while (timer_count == 0) REQUIRE((uint32_t)(MMIO(8) - start) < 8192u, 0x71);
    __asm__ volatile("csrc mstatus, %0\n\tcsrw mie, zero" :: "r"(8u) : "memory");
    REQUIRE(timer_count == 1u && (uint32_t)(MMIO(8)-start) >= 256u, 0x72);
    REQUIRE(CSR_READ(mcause) == 0x80000007u, 0x73);
    field("TIMER=", timer_count);
    uint32_t cycles = CSR_READ(mcycle), retired = CSR_READ(minstret);
    REQUIRE(retired > 100 && cycles > retired, 0x74);
    field("CYCLES=", cycles); field("RETIRED=", retired);
    uint32_t signature = mix(mix(mix(a, m), fp.u), seed) ^ 0x54303301u;
    MMIO(0x1c) = signature;
    field("SIGNATURE=", signature);
    puts_uart("T03 PASS\n");
    stop(0x600d0003u);
}
