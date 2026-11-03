.file "directed.S"
.text
.balign 4
.globl hazards
hazards:
    li t0, 17
    addi t1, t0, 5
    add t2, t1, t0
    sub t3, t2, t1
    mul t4, t3, t2
    sw t4, 0(a0)
    lw t5, 0(a0)
    add a0, t5, t1
    ret
.globl branch_test
branch_test:
    li t0, 64
    li a0, 0
1:  addi a0, a0, 3
    addi t0, t0, -1
.globl branch_site
branch_site:
    bnez t0, 1b
    j 2f
    sw zero, 0(zero) // Must be flushed, never reach bus.
2:  ret

.macro trap_test name, instruction
.globl \name
\name:
.globl \name\()_site
\name\()_site:
    \instruction
    ret
.endm
trap_test illegal, ".word 0xffffffff"
trap_test ecall_test, ecall
trap_test ebreak_test, ebreak
.globl badcsr
badcsr:
.globl badcsr_site
badcsr_site:
    csrr a0, 0x7ff
    ret
.globl readonly_csr
readonly_csr:
.globl readonly_csr_site
readonly_csr_site:
    csrw mcycle, zero
    ret
.globl misload
misload:
    li t0, 0xb4100001
.globl misload_site
misload_site:
    lw a0, 0(t0)
    ret
.globl misstore
misstore:
    li t0, 0xb4100001
.globl misstore_site
misstore_site:
    sw zero, 0(t0)
    ret
.globl misjump
misjump:
    li t0, 0xb4010002
.globl misjump_site
misjump_site:
    jalr zero, t0, 0
    ret
.globl badload
badload:
    li t0, 0xbc000000
.globl badload_site
badload_site:
    lw a0, 0(t0)
    ret
.globl errload
errload:
    li t0, 0xb4300000
.globl errload_site
errload_site:
    lw a0, 0(t0)
    ret
.globl badfetch
badfetch:
    li t0, 0xbc000000
    jr t0
.globl fetch_resume
fetch_resume:
    ret
.globl fence_patch_test
fence_patch_test:
    la t0, fence_target
    li t1, 0x02a00513
    sw t1, 0(t0)
    fence.i
.globl fence_target
fence_target:
    addi a0, zero, 1
    ret

.section .cache_a,"ax",@progbits
.globl cache_a
cache_a: li a0, 11
    ret
.section .cache_b,"ax",@progbits
.globl cache_b
cache_b: li a0, 23
    ret
.section .cache_c,"ax",@progbits
.globl cache_c
cache_c: li a0, 37
    ret
