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
2:  li t0,0x28000
    li t1,0x30000
    li t2,0x5a5a5a5a
4:  sw t2,0(t0)
    addi t0,t0,4
    bltu t0,t1,4b
    call main
fatal_trap:
    li t0,0x10000020
    li t1,0xdead0018
    sw t1,0(t0)
3:  j 3b
