/* Execute the production controls with adversarial MMIO, without a board claim. */
#define _GNU_SOURCE
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/mman.h>
#include "runtime.h"
static uint32_t registers[256];
static uint64_t ticks;
static int boot_ready=1,drain_after,drain_reads;
static char transcript[16384];
static size_t used;
static uint32_t *reg(unsigned offset){
    if(offset==0x228&&drain_after&&++drain_reads>=drain_after)registers[offset/4]=8;
    return &registers[offset/4];
}
#define REG(o) (*reg(o))
static uint64_t nx_port_ticks(void){ticks+=100000000;return ticks;}
static int nxr_boot_ready(void){return boot_ready;}
static void put(char c){assert(used+1<sizeof(transcript));transcript[used++]=c;transcript[used]=0;}
static void text(const char *s){while(*s)put(*s++);}
static void hex(uint32_t v){for(int i=7;i>=0;i--)put("0123456789abcdef"[(v>>(4*i))&15]);}
static void value(const char *s,uint64_t v){text(s);hex(v>>32);hex((uint32_t)v);put(' ');}
#define __bss_start t25_test_bss
#define __bss_end t25_test_bss_end
uint8_t t25_test_bss[64] __attribute__((section(".data.mock_bss")))={0};
__asm__(".global t25_test_bss_end\n.set t25_test_bss_end,t25_test_bss+64");
#include "diagnostics.h"
int main(void){
    t25_load_memory loaded={0};
    assert(!t25_count_store(&loaded,0x80000000,64));
    assert(t25_count_store(&loaded,0x80000000,64)); /* duplicates */
    assert(t25_count_store(&loaded,0xa7fffffe,4)); /* crosses region */
    assert(t25_count_store(&loaded,0xb4800000,4)); /* app/BSS boundary */
    assert(t25_count_store(&loaded,0x80000040,0));
    assert(loaded.bytes[0]==64);
    void *page=mmap((void *)0xa8000000,4096,PROT_READ|PROT_WRITE,
        MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED_NOREPLACE,-1,0);
    assert(page==(void *)0xa8000000);memset(page,0xa5,4096);
    assert(memory_commit(0xa8000001,64,6)==NXR_BOUNDS&&committed_ddr==0);
    assert(!memory_commit(0xa8000000,64,6)&&committed_ddr==64&&peak_committed_ddr==64);
    assert(!memory_commit(0xa8000040,32,7)&&commit_verified_bytes==96);
    for(unsigned i=0;i<96;i++)assert(((uint8_t *)page)[i]==0);
    assert(((uint8_t *)page)[96]==0xa5);
    for(unsigned b=0;b<10;b++){
        registers[0x208/4]=0x307u^(1u<<b);registers[0xe8/4]=0;
        assert(pressure_set(1)==NXR_STATE&&registers[0xe8/4]==0);
    }
    registers[0x208/4]=0x307;boot_ready=0;assert(pressure_set(1)==NXR_STATE);boot_ready=1;
    assert(!pressure_set(1)&&registers[0xe8/4]==2);
    assert(pressure_set(1)==NXR_STATE);
    registers[0x228/4]=5;drain_after=3;
    assert(!pressure_set(0)&&registers[0xe8/4]==0&&drain_reads>=3);
    drain_after=0;registers[0x228/4]=3;
    assert(pressure_set(0)==NXR_TIMEOUT&&registers[0xe8/4]==0);
    registers[0x208/4]|=1u<<4;
    assert(pressure_set(0)==NXR_FAULT&&registers[0xe8/4]==0);
    for(unsigned i=0;i<64;i++)registers[0x200/4+i]=0x60000000+i;
    telemetry_report();
    assert(strstr(transcript,"T25 TELEMETRY WORD 00000010 60000010\n"));
    assert(strstr(transcript,"T25 TELEMETRY WORD 0000003f 6000003f\n"));
    assert(strstr(transcript,"peak_committed_bytes=0000000000000060"));
    assert(munmap(page,4096)==0);
    puts("T25_DIAGNOSTICS_PASS guards=10 timeout=1 fault=1 drained=1 physical_qualification=false");
}
