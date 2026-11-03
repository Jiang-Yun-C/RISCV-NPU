/* G5 CPU/FPU/cache/native-DDR baseline, before enabling any CE hardware. */
#include <stdint.h>
#include "ce64_board_boot.h"
#define MM(a) (*(volatile uint32_t *)(uintptr_t)(a))
#ifndef NX_BASELINE_TICKS
#define NX_BASELINE_TICKS UINT64_C(450625000000)
#endif
static void report(uint32_t group,uint32_t item,uint32_t value){MM(0x10000080)=group<<16|item;MM(0x10000084)=value;}
static uint64_t ticks(void){uint32_t hi,lo,again;do{hi=MM(0x1000000c);lo=MM(0x10000008);again=MM(0x1000000c);}while(hi!=again);return (uint64_t)hi<<32|lo;}
static void telemetry(void){nx_ce64_board_telemetry();}
uint32_t trap_handler(uint32_t cause,uint32_t pc,uint32_t value){report(255,0,cause);report(255,1,pc);report(255,2,value);MM(0x10000020)=1;for(;;){}}
int main(void){
    if(nx_ce64_board_load()){MM(0x10000020)=4;for(;;){}}
    volatile float a=1.5f,b=2.0f,c=0.25f;
    union {float f;uint32_t u;} result;result.f=a*b+c;
    report(5,0,result.u);
    if(result.u!=0x40500000u){MM(0x10000020)=2;for(;;){}}
    uint64_t begin=ticks();uint32_t rounds=0,seed=0xa5a55a5a;
    telemetry();
    do{
        /* Exercise both uncached workspace and the original cached window. */
        for(unsigned k=0;k<2;k++){
            uint32_t base=k ? 0xb4000000u : 0xa8000000u;
            for(uint32_t i=0;i<16384;i++)MM(base+4*i)=(base+4*i)^seed;
            __asm__ volatile("fence iorw,iorw":::"memory");
            for(uint32_t i=0;i<16384;i++)if(MM(base+4*i)!=((base+4*i)^seed)){
                report(5,1,base+4*i);report(5,2,MM(base+4*i));MM(0x10000020)=3;for(;;){}
            }
        }
        seed=~seed;rounds++;report(5,3,rounds);
        if((rounds&15)==0)telemetry();
    }while(ticks()-begin<NX_BASELINE_TICKS);
    telemetry();report(5,4,rounds);MM(0x10000020)=0;
    for(;;)nx_ce64_board_load();
}
