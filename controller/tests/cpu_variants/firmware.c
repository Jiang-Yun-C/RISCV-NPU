/* Actual RV32 directed cache/branch workload, no host-computed result injection. */
#include <stdint.h>
#ifndef PROBE_CASE
#define PROBE_CASE 0
#endif
#define REG(off) (*(volatile uint32_t *)(uintptr_t)(0x10000000u+(off)))
static void put(char c){while(REG(4)&1u){} REG(0)=(uint8_t)c;}
static void text(const char *s){while(*s)put(*s++);}
static void hex(uint32_t v){const char *h="0123456789abcdef";for(int i=28;i>=0;i-=4)put(h[(v>>i)&15]);}
static void finish(uint32_t code){REG(0x20)=code;for(;;)__asm__ volatile("nop");}
uint32_t trap_handler(uint32_t cause,uint32_t pc,uint32_t val){
 text("VARIANT_TRAP ");hex(cause);put(' ');hex(pc);put(' ');hex(val);put('\n');finish(0xbadu);return pc;
}
static inline void flush_data(void){__asm__ volatile("fence iorw,iorw\n.word 0x0000500f" ::: "memory");}
static inline uint32_t read_word(uintptr_t a){return *(volatile uint32_t *)a;}
typedef uint32_t (*code_fn)(void);
int main(void){
 volatile uint32_t *a=(void *)0xb4100000u,*b=(void *)0xb4102000u,*x=(void *)0xb4100020u,*y=(void *)0xb4102020u,*c=(void *)0xb4104000u;
 *a=11;*b=22;*x=33;*y=44;*c=55;
 /* Generated tiny code spans have same-cache-set PCs and known return values. */
 uintptr_t fnaddr[]={0xb4200000u,0xb4202000u,0xb4200020u,0xb4202020u};
 for(unsigned i=0;i<4;i++){
  volatile uint32_t *p=(void *)fnaddr[i];p[0]=((i+1)<<20)|0x00000513u;p[1]=0x00008067u;
 }
 flush_data();__asm__ volatile("fence.i" ::: "memory");
 uint32_t sum=0,expected=0;
 REG(0xf0)=1;
#if PROBE_CASE == 0
 /* A(set0), X(set1), B(set0), Y(set1): global RR collides across sets. */
 for(unsigned i=0;i<32;i++){sum+=*a;sum+=*x;sum+=*b;sum+=*y;}
 expected=32u*(11u+33u+22u+44u);
#elif PROBE_CASE == 1
 /* Working-set pressure with a hot line, competing cold lines and writes. */
 for(unsigned i=0;i<32;i++){sum+=*a;sum+=*b;sum+=*a;sum+=*c;sum+=*a;}
 expected=32u*(11u+22u+11u+55u+11u);
#elif PROBE_CASE == 2
 for(unsigned i=0;i<32;i++){
  sum+=((code_fn)fnaddr[0])();sum+=((code_fn)fnaddr[2])();
  sum+=((code_fn)fnaddr[1])();sum+=((code_fn)fnaddr[3])();
 }
 expected=320;
#elif PROBE_CASE == 3
 /* Data invalidation, byte writes and FENCE.I/self-modifying code. */
 for(unsigned i=0;i<24;i++){
  volatile uint8_t *p=(void *)a;p[0]=(uint8_t)i;p[1]=0x5a;
  uint32_t got=*a;sum+=got;
  expected+=(0x5a00u|i);
  flush_data();sum+=*a;expected+=(0x5a00u|i);
  volatile uint32_t *f=(void *)fnaddr[0];f[0]=((i+1)<<20)|0x00000513u;
  __asm__ volatile("fence.i" ::: "memory");sum+=((code_fn)fnaddr[0])();expected+=i+1;
 }
#elif PROBE_CASE == 4
 /* Repeated conditional branches plus alternating indirect jump targets. */
 for(unsigned i=0;i<128;i++){
  uint32_t z=read_word((i&1)?(uintptr_t)a:(uintptr_t)b);
  if(z&1u)sum+=3;else sum+=7;
  sum+=((code_fn)fnaddr[(i>>2)&3u])();
 }
 expected=640+320;
#else
#error unknown probe
#endif
 __asm__ volatile("fence iorw,iorw" ::: "memory");REG(0xf0)=2;
 text("CPU_VARIANT case=");hex(PROBE_CASE);text(" sum=");hex(sum);
 text(" expected=");hex(expected);text(" pass=");hex(sum==expected);put('\n');
 finish(sum==expected?0xc021u:0xbadu);return 0;
}
