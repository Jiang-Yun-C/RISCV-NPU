OUTPUT_ARCH(riscv)
ENTRY(_start)
MEMORY {
 PROGRAM (rwx) : ORIGIN = 0xb4000000, LENGTH = 8M
 STACK (rw) : ORIGIN = 0x20000, LENGTH = 64K
}
PHDRS { app PT_LOAD FLAGS(7); }
SECTIONS {
 .diag (NOLOAD) : { KEEP(*(.diag)) } > STACK :NONE
 .text : { KEEP(*(.text.start)) *(.text.trap) *(.text .text.*) . = ALIGN(16); } > PROGRAM :app
 .rodata : { *(.rodata .rodata.*) . = ALIGN(16); } > PROGRAM :app
 .data : { __data_start = .; __global_pointer$ = . + 0x800;
  *(.sdata .sdata.* .data .data.*) . = ALIGN(16); __data_end = .;
 } > PROGRAM :app
 __data_load = __data_start;
 .bss (NOLOAD) : { __bss_start = .; *(.sbss .sbss.* .bss .bss.* COMMON) . = ALIGN(16); __bss_end = .; } > PROGRAM :app
 __stack_bottom = ORIGIN(STACK)+8192;
 ASSERT(SIZEOF(.diag)<=8192,"diagnostic reservation overflow") __stack_top = ORIGIN(STACK)+LENGTH(STACK);
 end = __bss_end;
 ASSERT(__bss_end <= ORIGIN(PROGRAM)+LENGTH(PROGRAM), "T25 program/tokenizer/BSS exceeds 8MiB")
 /DISCARD/ : { *(.comment) *(.note*) *(.eh_frame*) }
}
