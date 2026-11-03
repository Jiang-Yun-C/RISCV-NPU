/* Board-only parser/SPI port; shared T18 is unchanged. */
#include "sd_loader_core.c"
static uint64_t board_ticks(void){
    uint32_t hi,lo,again;
    do{__asm__ volatile("csrr %0,mcycleh":"=r"(hi));__asm__ volatile("csrr %0,mcycle":"=r"(lo));__asm__ volatile("csrr %0,mcycleh":"=r"(again));}while(hi!=again);
    return (uint64_t)hi<<32|lo;
}
static void put_char(char c){while(UART(4)&1){}UART(0)=(uint8_t)c;}
static void put_text(const char *p){while(*p)put_char(*p++);}
static void put_hex(uint32_t v){for(int i=7;i>=0;i--)put_char("0123456789abcdef"[(v>>(4*i))&15]);}
int main(void){
    for(;;){
        put_text("T25 SD WAIT DDR\n");uint64_t begin=board_ticks();uint32_t rc=0;
        while(!SPI(0x34))if(board_ticks()-begin>=UINT64_C(15000000000)){rc=E_TIMEOUT;break;}
        if(!rc){
            uint64_t started=board_ticks();
            *(volatile uint32_t *)0xba080000=(uint32_t)started;
            *(volatile uint32_t *)0xba080004=(uint32_t)(started>>32);
            put_text("T25 SD EXPECT APP ");
            for(unsigned i=0;i<32;i++){put_char("0123456789abcdef"[nx_trusted_apps[0][i]>>4]);put_char("0123456789abcdef"[nx_trusted_apps[0][i]&15]);}
            put_text(" MODEL ");
            for(unsigned i=0;i<32;i++){put_char("0123456789abcdef"[nx_trusted_models[0][i]>>4]);put_char("0123456789abcdef"[nx_trusted_models[0][i]&15]);}
            put_char('\n');
            rc=nx_sd_boot();
        }
        // A successful application serves UART requests and does not return.
        select(0);SPI(0x18)=0;SPI(0x1c)=rc;SPI(0x20)=SPI(0x24);
        put_text("T25 SD ERROR ");put_hex(rc);put_text("; send r for platform reset/reload\n");
        for(;;){while(!(UART(4)&2)){}if((uint8_t)UART(0xc0)=='r')break;}
        while(UART(4)&1){}UART(0xec)=0x52535432u;for(;;){}
    }
}
