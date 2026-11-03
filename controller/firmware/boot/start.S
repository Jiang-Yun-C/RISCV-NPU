.file "start.S"
.section .text.start,"ax",@progbits
.globl _start
.type _start,@function
_start:
    .option push
    .option norelax
    la gp, __global_pointer$
    .option pop
    la sp, __stack_top
    csrw mie, zero
    csrw mstatus, zero
    la t0, trap_entry
    csrw mtvec, t0
    la t0, __data_load
    la t1, __data_start
    la t2, __data_end
1:  bgeu t1, t2, 2f
    lw t3, 0(t0)
    sw t3, 0(t1)
    addi t0, t0, 4
    addi t1, t1, 4
    j 1b
2:  la t1, __bss_start
    la t2, __bss_end
3:  bgeu t1, t2, 4f
    sw zero, 0(t1)
    addi t1, t1, 4
    j 3b
4:  call main
    li t0, 0x10000020
    li t1, 0xdead0001
    sw t1, 0(t0)
5:  j 5b
.size _start, .-_start

.section .text.trap,"ax",@progbits
.balign 4
.globl trap_entry
.type trap_entry,@function
trap_entry:
    // Keep the interrupted stack 16-byte aligned; preserve all caller-saved GPRs.
    addi sp, sp, -64
    sw ra, 0(sp)
    sw t0, 4(sp)
    sw t1, 8(sp)
    sw t2, 12(sp)
    sw a0, 16(sp)
    sw a1, 20(sp)
    sw a2, 24(sp)
    sw a3, 28(sp)
    sw a4, 32(sp)
    sw a5, 36(sp)
    sw a6, 40(sp)
    sw a7, 44(sp)
    sw t3, 48(sp)
    sw t4, 52(sp)
    sw t5, 56(sp)
    sw t6, 60(sp)
    csrr a0, mcause
    csrr a1, mepc
    csrr a2, mtval
    call trap_handler
    csrw mepc, a0
    lw ra, 0(sp)
    lw t0, 4(sp)
    lw t1, 8(sp)
    lw t2, 12(sp)
    lw a0, 16(sp)
    lw a1, 20(sp)
    lw a2, 24(sp)
    lw a3, 28(sp)
    lw a4, 32(sp)
    lw a5, 36(sp)
    lw a6, 40(sp)
    lw a7, 44(sp)
    lw t3, 48(sp)
    lw t4, 52(sp)
    lw t5, 56(sp)
    lw t6, 60(sp)
    addi sp, sp, 64
    mret
.size trap_entry, .-trap_entry

.globl illegal_test
.type illegal_test,@function
illegal_test:
.globl illegal_site
illegal_site:
    .word 0xffffffff
    ret
.size illegal_test, .-illegal_test

// The target can already be prefetched when the store completes. No branch
// separates the store/FENCE.I from the overwritten instruction.
.globl fence_patch_test
.type fence_patch_test,@function
fence_patch_test:
    la t0, fence_target
    li t1, 0x02a00513
    sw t1, 0(t0)
    fence.i
.globl fence_target
fence_target:
    addi a0, zero, 1
    ret
.size fence_patch_test, .-fence_patch_test
