/* Real CPU UART bootstrap into DDR, before the hardware read-only model seal.
 * Host binds payloads to frozen SHA256 identities; every frame has a CRC and
 * each CPU store obtains the same native 1024-cycle drain/readback completion.
 * No Flash access. No weights or numerical answers are synthesized here. */
#include "ce64_board_boot.h"
#include <stdint.h>
#define REG(o) (*(volatile uint32_t *)(uintptr_t)(0x10000000u+(o)))
static uint8_t packet[24+512+4];
uint64_t nx_ce64_board_ticks(void){
    uint32_t hi,lo,again;
    do{hi=REG(0x0c);lo=REG(8);again=REG(0x0c);}while(hi!=again);
    return (uint64_t)hi<<32|lo;
}
void nx_ce64_board_telemetry(void){
    for(unsigned i=0;i<64;i++){
        uint32_t value=REG(0x200+4*i),high=0;
        int pair=i==4||(i>=16&&i<=24&&!(i&1))||(i>=32&&((i&7)==0||(i&7)==2));
        if(pair){uint32_t again;do{high=REG(0x204+4*i);value=REG(0x200+4*i);again=REG(0x204+4*i);}while(high!=again);}
        REG(0x80)=128u<<16|i;REG(0x84)=value;
        if(pair){i++;REG(0x80)=128u<<16|i;REG(0x84)=high;}
    }
}
static uint32_t crc(const uint8_t *p,uint32_t n){
    uint32_t c=~0u;
    for(uint32_t i=0;i<n;i++){c^=p[i];for(unsigned j=0;j<8;j++)c=(c>>1)^(0xedb88320u&(0u-(c&1)));}
    return ~c;
}
static uint32_t word(const uint8_t *p){return (uint32_t)p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;}
static void put(uint8_t value){while(REG(4)&1){}REG(0)=value;}
static uint8_t get(void){while(!(REG(4)&2)){}return (uint8_t)REG(0xc0);}
static void response_value(uint32_t sequence,uint32_t status,uint32_t value){
    uint32_t words[5]={0x324b4341u,sequence,status,value,0};words[4]=crc((const uint8_t *)words,16);
    for(unsigned i=0;i<20;i++)put(((const uint8_t *)words)[i]);
    while(REG(4)&1){} /* do not switch TX to binary reports mid-byte */
}
static void response(uint32_t sequence,uint32_t status){response_value(sequence,status,0);}
static int range(uint32_t address,uint32_t bytes){
    uint64_t end=(uint64_t)address+bytes;
    return bytes&&end<=UINT64_C(0xc0000000)&&!(address&3)&&!(bytes&3)&&
        ((address>=0x80000000u&&end<=UINT64_C(0xa8000000))||
         (address>=0xa8000000u&&end<=UINT64_C(0xb4000000))||
         (address>=0xb4000000u&&end<=UINT64_C(0xb8000000))||
         (address>=0xba000000u&&end<=UINT64_C(0xbc000000)));
}
int nx_ce64_board_load(void){
    if(REG(0xe4)==1)return 0; /* Explicit digital PRELOAD, never used on board. */
    uint64_t next_status=0;
    while(!(REG(0xe0)&1)){
        uint64_t now=nx_ce64_board_ticks();
        if(now>=next_status){nx_ce64_board_telemetry();next_status=now+125000000u;}
    }
    nx_ce64_board_telemetry();
    const char ready[]="CE64 BOOT v2\n";
    for(unsigned i=0;i<sizeof(ready)-1;i++)put((uint8_t)ready[i]);
    uint32_t expected=1,last=0,last_crc=0,last_value=0;
    for(;;){
        uint32_t magic=0;
        do{magic=(magic>>8)|((uint32_t)get()<<24);}while(magic!=0x324c4543u);
        packet[0]='C';packet[1]='E';packet[2]='L';packet[3]='2';
        for(unsigned i=4;i<24;i++)packet[i]=get();
        uint32_t command=word(packet+4),address=word(packet+8),bytes=word(packet+12),sequence=word(packet+16);
        if(bytes>512){response(sequence,3);continue;}
        unsigned total=24+(command==1?bytes:0)+4;
        for(unsigned i=24;i<total;i++)packet[i]=get();
        uint32_t received_crc=word(packet+total-4);
        if(crc(packet,total-4)!=received_crc){response(sequence,2);continue;}
        if(sequence==last&&received_crc==last_crc){response_value(sequence,0,last_value);continue;}
        if(sequence!=expected||sequence==UINT32_MAX){response(sequence,4);continue;}
        if(command==1){
            if(!range(address,bytes)){response(sequence,3);continue;}
            volatile uint32_t *dst=(volatile uint32_t *)(uintptr_t)address;
            for(unsigned i=0;i<bytes/4;i++)dst[i]=word(packet+24+4*i);
            __asm__ volatile("fence iorw,iorw":::"memory");
            last=sequence;last_crc=received_crc;last_value=0;expected++;response(sequence,0);
        }else if(command==2&&bytes==0&&address==0&&word(packet+20)<=3){
            REG(0xe8)=word(packet+20);
            REG(0xe0)=0x5345414cu;__asm__ volatile("fence iorw,iorw":::"memory");
            if(!(REG(0xe0)&2)){response(sequence,5);continue;}
            response(sequence,0);return 0;
        }else if(command==3&&range(address,bytes)){
            const volatile uint32_t *src=(const volatile uint32_t *)(uintptr_t)address;
            for(unsigned i=0;i<bytes/4;i++){
                uint32_t value=src[i];
                for(unsigned j=0;j<4;j++)packet[24+4*i+j]=(uint8_t)(value>>(8*j));
            }
            last=sequence;last_crc=received_crc;expected++;last_value=crc(packet+24,bytes);
            response_value(sequence,0,last_value);
        }else if(command==4&&bytes==0&&address==0){
            response(sequence,0);REG(0xec)=0x52535432u;for(;;){}
        }else response(sequence,3);
    }
}
