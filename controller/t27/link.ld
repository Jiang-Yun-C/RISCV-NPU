OUTPUT_ARCH(riscv)
ENTRY(_start)
MEMORY {
 ROM (rx) : ORIGIN = 0x10000, LENGTH = 64K
 RAM (rwx) : ORIGIN = 0xb4000000, LENGTH = 64M
}
PHDRS { rom PT_LOAD FLAGS(5); text PT_LOAD FLAGS(5); data PT_LOAD FLAGS(6); }
SECTIONS {
 .observer 0x20000 (NOLOAD) : { __observer_begin = .; . += 0x800; __observer_end = .; } :NONE
 .boot : { KEEP(*(.text.start)) } > ROM :rom
 .text : { *(.text.trap) *(.text .text.*) . = ALIGN(4); } > RAM :text
 .rodata : { *(.rodata .rodata.*) . = ALIGN(4); } > RAM :text
 .data 0xb4040000 : {
  __data_start = .; __global_pointer$ = . + 0x800;
  *(.sdata .sdata.* .data .data.*) . = ALIGN(4); __data_end = .;
 } > RAM :data
 __data_load = __data_start;
 .bss (NOLOAD) : { __bss_start = .; *(.sbss .sbss.* .bss .bss.* COMMON) . = ALIGN(4); __bss_end = .; end = .; } > RAM :data
 /* Existing board-local SRAM stack; all tensors remain on native DDR. */
 __stack_top = 0x30000; __stack_bottom = 0x22000;
 ASSERT(__bss_end < 0xb4100000, "test data overlaps fixtures")
 ASSERT(__observer_end <= 0x21000, "observer overlaps guard")
 ASSERT(__stack_bottom >= 0x22000, "guard overlaps stack")
 /DISCARD/ : { *(.comment) *(.note*) *(.eh_frame*) }
}
