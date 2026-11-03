OUTPUT_ARCH(riscv)
ENTRY(_start)
MEMORY { ROM (rx) : ORIGIN = 0x10000, LENGTH = 64K
         SRAM (rw) : ORIGIN = 0x20000, LENGTH = 64K }
PHDRS { rom PT_LOAD FLAGS(5); ram PT_LOAD FLAGS(6); }
SECTIONS {
 .text : { KEEP(*(.text.start)) *(.text .text.*) *(.rodata .rodata.*) . = ALIGN(4); } > ROM :rom
 .data : { __global_pointer$ = . + 0x800; *(.data .data.* .sdata .sdata.*) } > SRAM :ram
 .bss (NOLOAD) : { __bss_start = .; *(.bss .bss.* .sbss .sbss.* COMMON) . = ALIGN(4); __bss_end = .; } > SRAM :ram
 __stack_top = 0x30000;
 ASSERT(SIZEOF(.data)==0,"loader must have no initialized SRAM")
 ASSERT(__bss_end<0x28000,"loader stack overlap")
 /DISCARD/ : { *(.comment) *(.note*) *(.eh_frame*) }
}
