OUTPUT_ARCH(riscv)
ENTRY(_start)
MEMORY {
 ROM (rx) : ORIGIN = 0x10000, LENGTH = 64K
 PROGRAM (rwx) : ORIGIN = 0xb4000000, LENGTH = 8M
 HEAP (rw) : ORIGIN = 0xb4800000, LENGTH = 8M
 STACK (rw) : ORIGIN = 0xb7ff0000, LENGTH = 64K
}
PHDRS { rom PT_LOAD FLAGS(5); text PT_LOAD FLAGS(5); data PT_LOAD FLAGS(6); }
SECTIONS {
 .boot : { KEEP(*(.text.start)) } > ROM :rom
 .text : { *(.text.trap) *(.text .text.*) . = ALIGN(16); } > PROGRAM :text
 .rodata : { *(.rodata .rodata.*) . = ALIGN(16); } > PROGRAM :text
 .data : { __data_start = .; __global_pointer$ = . + 0x800;
  *(.sdata .sdata.* .data .data.*) . = ALIGN(16); __data_end = .;
 } > PROGRAM :data
 __data_load = __data_start;
 .bss (NOLOAD) : { __bss_start = .; *(.sbss .sbss.* .bss .bss.* COMMON) . = ALIGN(16); __bss_end = .; } > PROGRAM :data
 __heap_start = ORIGIN(HEAP); __heap_end = ORIGIN(HEAP)+LENGTH(HEAP);
 end = __heap_start;
 __stack_bottom = ORIGIN(STACK); __stack_top = ORIGIN(STACK)+LENGTH(STACK);
 ASSERT(__bss_end <= ORIGIN(PROGRAM)+LENGTH(PROGRAM), "T10 program/BSS ceiling exceeded")
 ASSERT(__heap_end <= __stack_bottom, "heap and stack overlap")
 /DISCARD/ : { *(.comment) *(.note*) *(.eh_frame*) }
}
