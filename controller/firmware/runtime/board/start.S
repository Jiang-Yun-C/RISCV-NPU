/* Reuse the qualified CPU startup and FPU initialization. Seed the otherwise
 * unused local SRAM stack before the first call, for a measured high water. */
#define main t25_entry
#include "../../cpu/start.S"
#undef main
.section .text.start,"ax",@progbits
.globl t25_entry
t25_entry:
    la t0, __stack_bottom
    la t1, __stack_top
    li t2, 0xa5a5a5a5
1:  sw t2, 0(t0)
    addi t0, t0, 4
    bltu t0, t1, 1b
    j main
