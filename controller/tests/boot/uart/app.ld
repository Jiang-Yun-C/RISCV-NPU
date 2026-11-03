OUTPUT_ARCH(riscv)
ENTRY(app_entry)
SECTIONS { . = 0xb4000000; .text : { *(.text) } /DISCARD/ : { *(.comment) *(.note*) } }
