.section .text.start,"ax",@progbits
.globl _start
_start:
    .option norelax
    la sp, __stack_top
    la t0, trap
    csrw mtvec, t0
    li t0, 0x6600
    csrs mstatus, t0
    call main
    fence rw,rw
    .word 0x08000073 /* Coral mpause: retire outstanding work and halt. */
1:  j 1b
trap:
    ebreak
    j trap
