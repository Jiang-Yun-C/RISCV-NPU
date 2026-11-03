OUTPUT_ARCH(riscv)
ENTRY(_start)
MEMORY {
    ITCM (rx)  : ORIGIN = 0x00000000, LENGTH = 8K
    DTCM (rw)  : ORIGIN = 0x00010000, LENGTH = 32K
}
SECTIONS {
    .text : { KEEP(*(.text.start)) *(.text*) *(.rodata*) } > ITCM
    .data : { *(.data*) *(.sdata*) } > DTCM
    .bss (NOLOAD) : { *(.bss*) *(.sbss*) *(COMMON) } > DTCM
    __stack_top = ORIGIN(DTCM) + LENGTH(DTCM);
    ASSERT(. <= __stack_top - 4096, "DTCM data overlaps stack")
}
