#include "accel.h"
static uint32_t read32(void *cookie,uint32_t address){(void)cookie;return *(volatile uint32_t *)(uintptr_t)address;}
static void write32(void *cookie,uint32_t address,uint32_t value){(void)cookie;*(volatile uint32_t *)(uintptr_t)address=value;}
static void fence(void *cookie){(void)cookie;__asm__ volatile("fence iorw,iorw":::"memory");}
static uint64_t ticks(void *cookie){
    (void)cookie;uint32_t hi,lo,again;
    do{__asm__ volatile("csrr %0,mcycleh":"=r"(hi));__asm__ volatile("csrr %0,mcycle":"=r"(lo));__asm__ volatile("csrr %0,mcycleh":"=r"(again));}while(hi!=again);
    return ((uint64_t)hi<<32)|lo;
}
void nx_accel_target_io(nx_accel_io *io){*io=(nx_accel_io){.read32=read32,.write32=write32,.ticks=ticks,.fence=fence,.tick_hz=100000000};}
