/* T25 SD qualification controls. No arbitrary address/write/execute command.
 * Counters are sampled before UART output; each live u64 uses high/low/high.
 * A snapshot is an interval, not an atomic capture of every hardware counter. */
#ifndef T25_DIAGNOSTICS_H
#define T25_DIAGNOSTICS_H
#include "ddr_accounting.h"
extern uint8_t __bss_start[],__bss_end[];
static uint64_t committed_ddr,peak_committed_ddr,commit_verified_bytes;
static uint32_t memory_regions;
static void diagnostic_fence(void){
#ifdef __riscv
    __asm__ volatile("fence iorw,iorw\n.word 0x0000500f" ::: "memory");
#else
    __asm__ volatile("" ::: "memory");
#endif
}
static void memory_add(uint32_t base,uint32_t bytes,unsigned kind){
    committed_ddr+=bytes;if(committed_ddr>peak_committed_ddr)peak_committed_ddr=committed_ddr;
    memory_regions++;
    text("T25 MEMORY REGION ");hex(kind);put(' ');hex(base);put(' ');hex(bytes);put('\n');
}
static int memory_initialize(void){
    /* Startup has zeroed BSS. Verify it before changing any application state. */
    for(volatile const uint8_t *p=__bss_start;p<__bss_end;p++)if(*p)return NXR_FAULT;
    volatile const uint32_t *m=(volatile const uint32_t *)(uintptr_t)T25_MEMORY_HANDOFF;
    if(m[0]!=T25_MEMORY_MAGIC)return NXR_STATE;
    const uint32_t bases[]={0x80000000u,0xb8000000u,0xb4000000u,0xba000000u};
    const uint32_t limits[]={0xa8000000u,0xba000000u,0xb4800000u,0xba080000u};
    for(unsigned i=0;i<4;i++){
        uint32_t n=m[i+1],end=m[i+5];
        if(!n||end<bases[i]||end>limits[i]||n>end-bases[i])return NXR_FAULT;
        memory_add(bases[i],n,i);
    }
    uint32_t n=(uint32_t)(__bss_end-__bss_start);
    commit_verified_bytes+=n;memory_add((uint32_t)(uintptr_t)__bss_start,n,4);
    /* Actual loader timestamp (8B) and accounting handoff (36B). */
    memory_add(0xba080000u,44,5);return 0;
}
static int memory_commit(uint32_t base,uint32_t bytes,unsigned kind){
    if((base|bytes)&3u)return NXR_BOUNDS;
#ifdef NX_T25_CE64
    /* Internal controller writes every byte, retires native B and explicitly
     * reads every byte back before comparing it with physical zero. */
    if(kind<6||kind>12)return NXR_BOUNDS;
    int rc=nxr_ce64_startup_zero(base,bytes,kind-6);if(rc)return rc;
    diagnostic_fence();
#else
    volatile uint32_t *p=(volatile uint32_t *)(uintptr_t)base;
    for(uint32_t i=0;i<bytes/4;i++)p[i]=0;
    diagnostic_fence();
    for(uint32_t i=0;i<bytes/4;i++)if(p[i])return NXR_FAULT;
#endif
    commit_verified_bytes+=bytes;memory_add(base,bytes,kind);return 0;
}
static void memory_report(void){
    text("T25 MEMORY ");value("committed_bytes=",committed_ddr);
    value("peak_committed_bytes=",peak_committed_ddr);value("regions=",memory_regions);
    value("runtime_write_readback_bytes=",commit_verified_bytes);put('\n');
}
static uint64_t telemetry64(unsigned index){
    uint32_t a,b,c;
    do{a=REG(0x200+4*(index+1));b=REG(0x200+4*index);c=REG(0x200+4*(index+1));}while(a!=c);
    return (uint64_t)a<<32|b;
}
static void telemetry_report(void){
    uint32_t words[64];uint64_t begin=nx_port_ticks();
    for(unsigned i=0;i<64;i++)words[i]=REG(0x200+i*4);
    /* reference ticks; DDR cycle/payload; four bus payload counter pairs. */
    const unsigned wide[]={4,16,18,20,22,24,32,34,40,42,48,50,56,58};
    for(unsigned j=0;j<sizeof(wide)/sizeof(wide[0]);j++){
        unsigned i=wide[j];uint64_t v=telemetry64(i);words[i]=(uint32_t)v;words[i+1]=(uint32_t)(v>>32);
    }
    uint32_t status=REG(0x208),profile=REG(0xe8);uint64_t end=nx_port_ticks();
    text("T25 TELEMETRY BEGIN ");value("begin_ticks=",begin);value("end_ticks=",end);
    value("status_after=",status);value("profile=",profile);put('\n');
    for(unsigned i=0;i<64;i++){text("T25 TELEMETRY WORD ");hex(i);put(' ');hex(words[i]);put('\n');}
    text("T25 TELEMETRY END\n");memory_report();
}
static int pressure_set(unsigned on){
    uint32_t status=REG(0x208);
    /* Flags: sealed, backend idle, calibration, full range and masks;
     * no owner/quarantine/platform or BIST failure. */
    if(on){
        if((status&0x3ffu)!=0x307u||!nxr_boot_ready()||REG(0xe8)!=0)return NXR_STATE;
        REG(0xe8)=2;
    }
    else{
        REG(0xe8)=0;uint64_t start=nx_port_ticks();
        /* WAIT(0) means never started; HOLD(8) is reached only after a complete
         * B response or all read beats and data checks. Never infer drain from
         * an arbitrary fixed delay or an unchanged cumulative byte counter. */
        for(;;){
            uint32_t phase=REG(0x228)&15u;
            if(REG(0x208)&0x38u)return NXR_FAULT;
            if(phase==0||phase==8)break;
            if(nx_port_ticks()-start>UINT64_C(250000000))return NXR_TIMEOUT;
        }
    }
    diagnostic_fence();
    if(REG(0xe8)!=(on?2u:0u))return NXR_FAULT;
    text(on?"T25 PRESSURE ON\n":"T25 PRESSURE OFF DRAINED\n");return 0;
}
#endif
