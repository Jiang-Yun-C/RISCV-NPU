OUTPUT_ARCH(riscv)
ENTRY(_start)
MEMORY { RAM (rwx) : ORIGIN = 0x80000000, LENGTH = 64K }
PHDRS { text PT_LOAD FLAGS(5); data PT_LOAD FLAGS(6); }
SECTIONS {
  .text : { KEEP(*(.text.start)) *(.text.trap) *(.text .text.*) . = ALIGN(4); } > RAM :text
  .rodata : { *(.rodata .rodata.*) . = ALIGN(4); } > RAM :text
  __data_load = LOADADDR(.data);
  .data 0x80008000 : AT(ADDR(.rodata) + SIZEOF(.rodata)) {
    __data_start = .;
    __global_pointer$ = . + 0x800;
    *(.sdata .sdata.* .data .data.*)
    . = ALIGN(4);
    __data_end = .;
  } > RAM :data
  .bss (NOLOAD) : {
    __bss_start = .;
    *(.sbss .sbss.* .bss .bss.* COMMON)
    . = ALIGN(4);
    __bss_end = .;
  } > RAM :data
  __stack_top = ORIGIN(RAM) + LENGTH(RAM);
  __stack_bottom = __stack_top - 4096;
  ASSERT(__bss_end <= __stack_bottom, "data/BSS overlaps stack")
  ASSERT(LOADADDR(.data) + SIZEOF(.data) < 0x80008000, "preload overlaps runtime data")
  /DISCARD/ : { *(.comment) *(.note*) *(.eh_frame*) }
}
