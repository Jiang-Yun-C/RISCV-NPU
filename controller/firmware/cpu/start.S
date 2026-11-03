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
4:
#ifdef HARD_FLOAT
    li t0, 0x6000
    csrs mstatus, t0
    csrw fcsr, zero
    fmv.w.x f0, zero
    fmv.w.x f1, zero
    fmv.w.x f2, zero
    fmv.w.x f3, zero
    fmv.w.x f4, zero
    fmv.w.x f5, zero
    fmv.w.x f6, zero
    fmv.w.x f7, zero
    fmv.w.x f8, zero
    fmv.w.x f9, zero
    fmv.w.x f10, zero
    fmv.w.x f11, zero
    fmv.w.x f12, zero
    fmv.w.x f13, zero
    fmv.w.x f14, zero
    fmv.w.x f15, zero
    fmv.w.x f16, zero
    fmv.w.x f17, zero
    fmv.w.x f18, zero
    fmv.w.x f19, zero
    fmv.w.x f20, zero
    fmv.w.x f21, zero
    fmv.w.x f22, zero
    fmv.w.x f23, zero
    fmv.w.x f24, zero
    fmv.w.x f25, zero
    fmv.w.x f26, zero
    fmv.w.x f27, zero
    fmv.w.x f28, zero
    fmv.w.x f29, zero
    fmv.w.x f30, zero
    fmv.w.x f31, zero

#endif
    call main
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
    addi sp, sp, -80
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
#ifdef HARD_FLOAT
    // ISR is integer-only. FS=Off makes accidental FP use trap immediately.
    csrr t0, mstatus
    li t1, 0x6000
    and t0, t0, t1
    sw t0, 64(sp)
    csrc mstatus, t1
#endif
    csrr a0, mcause
    csrr a1, mepc
    csrr a2, mtval
    call trap_handler
    csrw mepc, a0
#ifdef HARD_FLOAT
    lw t0, 64(sp)
    csrs mstatus, t0
#endif
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
    addi sp, sp, 80
    mret
.size trap_entry, .-trap_entry

