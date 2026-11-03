/* Native Coral transport probe, not a W8 implementation. No BSS/data required. */
#include <stdint.h>
void main(void){
    volatile uint32_t *p=(volatile uint32_t *)0x10000,*r=(volatile uint32_t *)0x10100;
    volatile uint32_t *in=(volatile uint32_t *)(uintptr_t)p[7],*out=(volatile uint32_t *)(uintptr_t)p[8];
    for(uint32_t i=0;i<p[9];i++)out[i]=in[i]^p[10];
    __asm__ volatile("fence rw,rw":::"memory");
    r[0]=1;r[1]=32;for(unsigned i=2;i<6;i++)r[i]=p[i];r[6]=0;r[7]=1;
}
