#include <stdint.h>
#define REG(o) (*(volatile uint32_t *)(uintptr_t)(0x10000000u+(o)))
static volatile uint32_t traps,irqs,failed;
extern char fetch_resume;
uint32_t trap_handler(uint32_t cause,uint32_t pc,uint32_t val){
    REG(0x80)=cause;REG(0x84)=pc;REG(0x88)=val;
    if(cause>>31){irqs++;uint32_t bit=1u<<(cause&31u);__asm__ volatile("csrc mie,%0"::"r"(bit):"memory");return pc;}
    traps++;return cause==1?(uint32_t)(uintptr_t)&fetch_resume:pc+4;
}
#define OP(n) extern void f_##n(void)
OP(store_fp);OP(load_fp_misaligned);OP(store_slv);OP(store_dec);OP(store_cached);OP(load_slv);OP(load_dec);OP(load_cached);
OP(load_misaligned);OP(store_misaligned);OP(illegal);OP(csr);OP(readonly);OP(ecall);OP(ebreak);OP(fetch);OP(i_misaligned);
static void hex(uint32_t v){for(int i=7;i>=0;i--)REG(0)="0123456789abcdef"[(v>>(4*i))&15];}
int main(void){
    __asm__ volatile("csrs mstatus,%0;csrw mie,%1"::"r"(8),"r"(0x888):"memory");
    f_store_slv();f_store_dec();f_store_cached();f_store_fp();f_load_fp_misaligned();
    if(*(volatile uint32_t *)0xb4102000u!=0xa5a5a5a5u)failed|=1;
    f_load_slv();f_load_dec();f_load_cached();
    // A later cache line and normal uncached transaction must remain usable.
    *(volatile uint32_t *)0xb4104020u=0x11223344;
    if(*(volatile uint32_t *)0xb4104020u!=0x11223344)failed|=2;
    f_load_misaligned();f_store_misaligned();f_illegal();f_csr();f_readonly();f_ecall();f_ebreak();f_fetch();f_i_misaligned();
    uint32_t m,s;__asm__ volatile("csrr %0,mstatus;csrr %1,misa":"=r"(m),"=r"(s));
    if((m&0x1800)!=0x1800||s!=0x40001120u)failed|=4;
    // Masking of mepc, mtvec MODE, MPP and reserved MIE/MIP bits.
    uint32_t before,after;__asm__ volatile("csrr %0,mepc;li t0,-1;csrw mepc,t0;csrr %1,mepc;csrw mepc,%0":"=r"(before),"=r"(after)::"t0","memory");
    if(after!=0xfffffffcu)failed|=8;
    __asm__ volatile("csrr %0,mtvec;li t0,-1;csrw mtvec,t0;csrr %1,mtvec;csrw mtvec,%0":"=r"(before),"=r"(after)::"t0","memory");if(after!=0xfffffffcu)failed|=16;
    __asm__ volatile("csrw mie,zero;csrw mstatus,zero;csrr %0,mstatus":"=r"(after));if((after&0x1800)!=0x1800)failed|=32;
    __asm__ volatile("li t0,5;csrw 0x320,t0;csrw mcycle,zero;csrw mcycleh,zero;csrw minstret,zero;csrw minstreth,zero;nop;nop;csrr %0,mcycle;csrr %1,minstret":"=r"(before),"=r"(after)::"t0","memory");if(before||after)failed|=64;
    __asm__ volatile("csrw 0x320,zero":::"memory");
    __asm__ volatile("csrc mstatus,%0;csrs mie,%1"::"r"(8),"r"(0x80):"memory");
    REG(0x90)=1;__asm__ volatile("wfi":::"memory");REG(0x90)=2;
    __asm__ volatile("csrc mie,%0"::"r"(0x80):"memory");
    hex(traps);REG(0)=' ';hex(irqs);REG(0)=' ';hex(failed);REG(0)='\n';
    REG(0x20)=(!failed&&traps==17&&irqs==3)?0xc021:0xdead;
    for(;;){}
}
