#include <stdint.h>
#include <stddef.h>
#define MMIO(off) (*(volatile uint32_t *)(uintptr_t)(0x10000000u + (off)))
#define CSR_READ(name) ({ uint32_t v; __asm__ volatile("csrr %0, " #name : "=r"(v)); v; })
#define REQUIRE(test, code) do { if (!(test)) { MMIO(0x20) = 0xdead0000u | (code); for (;;) {} } } while (0)
#define OUT(n,v) (MMIO(0x100 + 4*(n)) = (v))
#define PHASE(n) (MMIO(0x40) = (n))
static volatile uint32_t memory_words[32], interrupt_count;
static volatile float float_a=1.5f, float_b=2.25f, float_c=-0.5f;
extern uint32_t hazards(volatile uint32_t *), branch_test(void), fence_patch_test(void);
extern uint32_t cache_a(void), cache_b(void), cache_c(void);
extern void illegal(void), badcsr(void), readonly_csr(void), ecall_test(void), ebreak_test(void);
extern void misload(void), misstore(void), misjump(void), badload(void), errload(void), badfetch(void), fetch_resume(void);
uint32_t trap_handler(uint32_t cause, uint32_t pc, uint32_t value) {
    MMIO(0x200)=cause; MMIO(0x204)=pc; MMIO(0x208)=value; MMIO(0x20c)=CSR_READ(mstatus);
    if (cause & 0x80000000u) {
        MMIO(0x48)=cause & 31u;
        interrupt_count++;
        return pc;
    }
    return cause == 1 ? (uint32_t)(uintptr_t)fetch_resume : pc+4;
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

#ifdef HARD_FLOAT
// Separate translation unit checks ILP32F argument/return convention and libm.
extern float abi_compute(float, float);
static uint32_t fp_test(void) {
    union { float f; uint32_t u; } x;
    x.f=abi_compute(float_a,float_b); OUT(20,x.u);
    __asm__ volatile("csrw fcsr, zero");
    float zero=0.0f, one=1.0f, out;
    __asm__ volatile("fdiv.s %0,%1,%2" : "=f"(out) : "f"(one),"f"(zero));
    x.f=out; OUT(21,x.u); OUT(22,CSR_READ(fflags));
    __asm__ volatile("csrw fcsr, zero");
    float neg=-1.0f;
    __asm__ volatile("fsqrt.s %0,%1" : "=f"(out) : "f"(neg));
    x.f=out; OUT(23,x.u); OUT(24,CSR_READ(fflags));
    __asm__ volatile("csrwi frm, 1");
    int rounded; float f=2.75f;
    __asm__ volatile("fcvt.w.s %0,%1,dyn" : "=r"(rounded) : "f"(f));
    OUT(25,rounded); OUT(26,CSR_READ(fcsr));
    __asm__ volatile("csrw fcsr, zero");
    return CSR_READ(mstatus) & 0x6000;
}
#endif

int main(void) {
    uint32_t seed=MMIO(0x18);
    OUT(0, seed); OUT(1, hazards(memory_words));
    OUT(2, arithmetic(seed)); OUT(3, memory_test(seed));
    union { float f; uint32_t u; } fp;
    fp.f=float_a*float_b+float_c; OUT(4,fp.u);
    PHASE(10);
    volatile uint32_t *a=(void *)0xb4100000u, *b=(void *)0xb4102000u, *c=(void *)0xb4104000u;
    uint32_t sum=*a; sum+=*b; sum+=*a; sum+=*b;
    OUT(6,sum);
    PHASE(11); sum=*c; sum+=*a; sum+=*b; OUT(7,sum);
    PHASE(12);
    __asm__ volatile(".word 0x0000500f" ::: "memory");
    OUT(8,*a);
    *a=0xdecafbad; __asm__ volatile("fence rw,rw" ::: "memory");
    OUT(9,*a);
    PHASE(20); sum=cache_a(); sum+=cache_b(); sum+=cache_a(); sum+=cache_b(); OUT(10,sum);
    PHASE(21); sum=cache_c(); sum+=cache_a(); sum+=cache_b(); OUT(11,sum);
    PHASE(22); OUT(5,fence_patch_test());
    PHASE(30); OUT(12,branch_test()+branch_test());
    PHASE(40);
    illegal(); badcsr(); readonly_csr(); ecall_test(); ebreak_test();
    misload(); misstore(); misjump(); badload(); errload(); badfetch();
    PHASE(50);
    const uint32_t irqs[]={7,11,3};
    for (unsigned i=0;i<3;i++) {
        uint32_t bit=1u<<irqs[i];
        __asm__ volatile("csrw mie, %0; csrs mstatus, %1" :: "r"(bit),"r"(8u) : "memory");
        MMIO(0x44)=irqs[i];
        while(interrupt_count==i) __asm__ volatile("nop");
        __asm__ volatile("csrc mstatus, %0; csrw mie, zero" :: "r"(8u) : "memory");
    }
    OUT(13,interrupt_count);
    __asm__ volatile("csrw mscratch, %0" :: "r"(0x76543210u));
    OUT(14,CSR_READ(mscratch)); OUT(15,CSR_READ(misa));
#ifdef HARD_FLOAT
    OUT(16,fp_test());
#else
    OUT(16,0);
#endif
    OUT(17,CSR_READ(mcycle)); OUT(18,CSR_READ(minstret));
    const char *s="T09 CPU OK\n";
    while(*s) MMIO(0)=(unsigned char)*s++;
    MMIO(0x20)=0x600d0009u;
    for (;;) __asm__ volatile("nop");
}
