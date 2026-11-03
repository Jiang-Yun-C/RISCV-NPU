OUTPUT_ARCH(riscv)
ENTRY(_start)
MEMORY {
 ROM (rx) : ORIGIN = 0x10000, LENGTH = 64K
 SRAM (rw) : ORIGIN = 0x20000, LENGTH = 64K
}
PHDRS { rom PT_LOAD FLAGS(5); ram PT_LOAD FLAGS(6); }
SECTIONS {
 .text : { KEEP(*(.text.start)) *(.text.trap) *(.text .text.*) . = ALIGN(4); } > ROM :rom
 .rodata : { *(.rodata .rodata.*) . = ALIGN(4); } > ROM :rom
 .data : {
  __data_start = .; __global_pointer$ = . + 0x800;
  *(.sdata .sdata.* .data .data.*) . = ALIGN(4); __data_end = .;
 } > SRAM :ram
 __data_load = __data_start;
 .bss (NOLOAD) : { __bss_start = .; *(.sbss .sbss.* .bss .bss.* COMMON) . = ALIGN(4); __bss_end = .; end = .; } > SRAM :ram
 __stack_top = 0x30000; __stack_bottom = 0x28000;
 ASSERT(__bss_end < __stack_bottom, "CE globals overlap local stack")
 ASSERT(SIZEOF(.data) == 0, "Board SRAM initializers require an explicit ROM-copy format")
 /DISCARD/ : { *(.comment) *(.note*) *(.eh_frame*) }
}
