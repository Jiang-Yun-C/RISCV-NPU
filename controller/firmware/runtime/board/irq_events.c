/* Integer-only ISR path: disassembly is audited. No parser, UART TX, DMA,
 * libcall, float operation, completion ACK or owner change is allowed here. */
#include "irq_events.h"
#define R(a) (*(volatile uint32_t *)(uintptr_t)(a))
#define UART_STATUS 0x10000004u
#define UART_RX 0x100000c0u
#define UART_MASK 0x100000c4u
#define UART_CLEAR 0x100000c8u
#define BR_PENDING 0x1000010cu
#define BR_MASK 0x10000114u
#define EVENT 0x10000420u
#define RX_SIZE 8192u
static volatile unsigned char rx_data[RX_SIZE];
static volatile uint32_t rx_head,rx_tail,rx_poison,rx_drop;
static volatile uint32_t event_pending,started;
static uint64_t next_tick;
static volatile uint32_t tick_ms;
static volatile uint32_t led_mask,led_period,led_due,led_left,led_value;
volatile nx_irq_metrics nx_irq_stats;
static inline uint32_t lock(void){uint32_t v;__asm__ volatile("csrrc %0,mstatus,%1":"=r"(v):"r"(8):"memory");return v&8;}
static inline void unlock(uint32_t v){__asm__ volatile("csrs mstatus,%0"::"r"(v):"memory");}
static inline uint32_t cycles_lo(void){uint32_t v;__asm__ volatile("csrr %0,mcycle":"=r"(v));return v;}
static uint64_t time_read(void){uint32_t h,l,h2;do{h=R(0x1000000cu);l=R(0x10000008u);h2=R(0x1000000cu);}while(h!=h2);return (uint64_t)h<<32|l;}
static void compare_write(uint64_t v){R(0x10000010u)=UINT32_MAX;R(0x10000014u)=(uint32_t)(v>>32);R(0x10000010u)=(uint32_t)v;}
static void record(uint32_t ev){event_pending|=ev;nx_irq_stats.software_events++;R(EVENT)=0x100u|ev;}
int nx_irq_enabled(void){return started!=0;}
void nx_irq_start(void){
    uint32_t old=lock();(void)old;
    rx_head=rx_tail=rx_poison=rx_drop=0;event_pending=0;tick_ms=0;
    next_tick=time_read()+NX_IRQ_PERIOD;compare_write(next_tick);
    R(UART_CLEAR)=12;R(UART_MASK)=1;R(BR_MASK)=0;started=1;
    __asm__ volatile("csrs mie,%0"::"r"(0x880):"memory");unlock(8);
}
void nx_irq_stop(void){uint32_t old=lock();started=0;R(UART_MASK)=0;R(BR_MASK)=0;compare_write(UINT64_MAX);__asm__ volatile("csrc mie,%0"::"r"(0x880):"memory");unlock(old);}
uint32_t nx_irq_handler(uint32_t cause,uint32_t pc){
    const uint32_t began=cycles_lo();
    if(cause==0x8000000bu){
        nx_irq_stats.external_isrs++;
        if((R(BR_PENDING)&1)&&(R(BR_MASK)&1)){
            // Mask the notification, leave completion, generation and owner intact.
            R(BR_MASK)=0;record(NX_EV_NPU);nx_irq_stats.npu_events++;
        }
        for(unsigned i=0;i<64;i++){
            uint32_t st=R(UART_STATUS);
            if(st&12){rx_poison=1;rx_drop=1;nx_irq_stats.rx_errors++;R(UART_CLEAR)=st&12;record(NX_EV_RX_ERROR);}
            if(!(st&2))break;
            unsigned c=R(UART_RX)&255u;nx_irq_stats.rx_bytes++;
            if(rx_drop){if(c=='\n')rx_drop=0;continue;}
            if(rx_poison)continue;
            uint32_t h=rx_head;
            if(h-rx_tail>=RX_SIZE){rx_poison=1;rx_drop=1;nx_irq_stats.rx_overflow++;record(NX_EV_RX_ERROR);continue;}
            rx_data[h&(RX_SIZE-1)]=(unsigned char)c;
            __asm__ volatile("":::"memory");rx_head=h+1;
        }
        record(NX_EV_UART);
    }else if(cause==0x80000007u){
        nx_irq_stats.timer_isrs++;
        uint64_t now=time_read();uint32_t late=(uint32_t)(now-next_tick);
        if(late>nx_irq_stats.max_tick_late)nx_irq_stats.max_tick_late=late;
        // Bounded catch-up: one division, never an unbounded missed-tick loop.
        uint32_t elapsed=1;
        if(now-next_tick>=NX_IRQ_PERIOD){elapsed+=(uint32_t)((now-next_tick)/NX_IRQ_PERIOD);nx_irq_stats.late_ticks+=elapsed-1;}
        tick_ms+=elapsed;next_tick+=(uint64_t)elapsed*NX_IRQ_PERIOD;compare_write(next_tick);
        if(led_mask&&(int32_t)(tick_ms-led_due)>=0){
            uint32_t steps=1+(tick_ms-led_due)/led_period;
            if(led_left&&steps>=led_left){uint32_t mask=led_mask;led_mask=0;R(0x10000418u)=mask<<8;led_left=0;}
            else{
                if(led_left)led_left-=steps;
                if(steps&1)led_value^=led_mask;
                R(0x10000418u)=(led_mask<<8)|(led_value&led_mask);
                led_due+=steps*led_period;
            }
            nx_irq_stats.led_writes++;
        }
        record(NX_EV_TIMER);
    }
    uint32_t elapsed=cycles_lo()-began;if(elapsed>nx_irq_stats.max_isr_cycles)nx_irq_stats.max_isr_cycles=elapsed;
    return pc;
}
int nx_irq_rx_pop(void){
    if(!started)return (R(UART_STATUS)&2)?(int)(R(UART_RX)&255u):-1;
    uint32_t m=lock();
    if(rx_poison){rx_tail=rx_head;rx_poison=0;unlock(m);return -2;}
    uint32_t t=rx_tail;if(t==rx_head){unlock(m);return -1;}
    int c=rx_data[t&(RX_SIZE-1)];rx_tail=t+1;unlock(m);return c;
}
void nx_irq_npu_arm(void){
    if(!started)return;
    uint32_t m=lock();event_pending&=~NX_EV_NPU;R(BR_MASK)=1;unlock(m);
}
int nx_irq_npu_notified(void){return !started||(event_pending&NX_EV_NPU)!=0;}
void nx_irq_npu_wait(void *unused){
    (void)unused;if(!started)return;nx_irq_stats.waits++;
    uint32_t m=lock();
    // WFI observes enabled individual pending bits even with global MIE clear.
    // A pending level, an ISR-registered event, or the 1ms timer closes every race.
    if(!(event_pending&NX_EV_NPU))__asm__ volatile("wfi":::"memory");
    unlock(m);
}
void nx_irq_consume(uint32_t ev){uint32_t m=lock();event_pending&=~ev;nx_irq_stats.main_consumed++;R(EVENT)=0x200u|ev;unlock(m);}
void nx_irq_led_override(void){uint32_t m=lock();led_mask=0;led_left=0;unlock(m);}
void nx_irq_led_stop(void){
    uint32_t m=lock();uint32_t mask=led_mask;led_mask=0;led_left=0;
    if(mask){R(0x10000418u)=mask<<8;nx_irq_stats.led_writes++;}unlock(m);
}
int nx_irq_blink(uint32_t mask,uint32_t period_ms,uint32_t edges){
    if(!started||!mask||(mask&~0x2du)||period_ms<10||period_ms>60000||edges>1000000)return -1;
    uint32_t m=lock();led_mask=0;led_left=edges;led_period=period_ms;led_due=tick_ms+period_ms;
    led_value=mask;R(0x10000418u)=(mask<<8)|mask;led_mask=mask;nx_irq_stats.led_writes++;unlock(m);return 0;
}
