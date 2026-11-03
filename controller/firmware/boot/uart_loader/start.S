.section .text.start,"ax",@progbits
.globl _start
_start:
    .option push
    .option norelax
    la gp, __global_pointer$
    .option pop
    la sp, __stack_top
    csrw mie, zero
    csrw mstatus, zero
    la t0, fatal_trap
    csrw mtvec, t0
    la t0, __bss_start
    la t1, __bss_end
1:  bgeu t0,t1,2f
    sw zero,0(t0)
    addi t0,t0,4
    j 1b
2:  call main
fatal_trap:
    li t0,0x10000020
    li t1,0xdead0017
    sw t1,0(t0)
3:  j 3b
