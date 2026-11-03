.section .text,"ax",@progbits
.globl app_entry
app_entry:
    li t0,0x10000000
    li t1,APP_SIGNATURE
    sw t1,0x24(t0)
    la t2,message
1:  lbu t3,0(t2)
    beqz t3,4f
2:  lw t4,4(t0)
    andi t4,t4,1
    bnez t4,2b
    sw t3,0(t0)
    addi t2,t2,1
    j 1b
4:  li t1,APP_SIGNATURE
    la t2,data_signature
    lw t3,0(t2)
    bne t1,t3,5f
    sw t3,0x28(t0)
    ret
5:  sw zero,0x28(t0)
    ret
.balign 4
data_signature: .word APP_SIGNATURE
message: .asciz APP_MESSAGE
/* A genuine few-KiB download, including non-code bytes verified by image CRC. */
.fill 2048,1,0x5a
