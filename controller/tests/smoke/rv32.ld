/* T01 link-only fixture. This address is not the future system address map. */
OUTPUT_ARCH(riscv)
ENTRY(_start)
MEMORY { RAM (rwx) : ORIGIN = 0x00010000, LENGTH = 16K }
PHDRS { text PT_LOAD FLAGS(5); data PT_LOAD FLAGS(6); }
SECTIONS {
    .text : { KEEP(*(.text.start)) *(.text*) } > RAM :text
    .rodata : { *(.rodata*) } > RAM :text
    . = ALIGN(16);
    .data : { *(.sdata*) *(.data*) } > RAM :data
    .bss (NOLOAD) : { *(.sbss*) *(.bss*) *(COMMON) } > RAM :data
    _stack_top = ORIGIN(RAM) + LENGTH(RAM);
}
