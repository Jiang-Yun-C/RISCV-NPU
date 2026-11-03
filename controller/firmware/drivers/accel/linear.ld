OUTPUT_ARCH(riscv)
ENTRY(_start)
MEMORY { ITCM (rx) : ORIGIN = 0, LENGTH = 8K
 DTCM (rw) : ORIGIN = 0x10000, LENGTH = 32K }
SECTIONS {
 .text : { KEEP(*(.text.start)) *(.text*) *(.rodata*) } > ITCM
 .request 0x10000 : { KEEP(*(.request)) } > DTCM
 .result 0x10100 : { KEEP(*(.result)) } > DTCM
 .data 0x10200 : { BYTE(0) *(.data*) *(.sdata*) } > DTCM
 .bss (NOLOAD) : { *(.bss*) *(.sbss*) *(COMMON) } > DTCM
 __data_end = .; __stack_bottom = 0x17000; __stack_top = 0x18000;
 ASSERT(SIZEOF(.request) == 96, "private request size")
 ASSERT(SIZEOF(.result) == 104, "private result size")
 ASSERT(__data_end <= __stack_bottom - 16, "DTCM overlaps stack guard")
 ASSERT(SIZEOF(.text) <= 8192, "ITCM program overflow")
}
