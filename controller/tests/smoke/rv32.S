.file "rv32.S"
.section .text.start,"ax",@progbits
.globl _start
.type _start,@function
_start:
    la sp, _stack_top
    call smoke_main
1:  j 1b
.size _start, .-_start
