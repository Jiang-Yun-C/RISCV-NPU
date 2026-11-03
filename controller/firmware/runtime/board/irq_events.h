#ifndef NX_IRQ_EVENTS_H
#define NX_IRQ_EVENTS_H
#include <stdint.h>
#ifndef NX_APP_IRQ
#define NX_APP_IRQ 0
#endif
#include <stddef.h>
#define NX_IRQ_HZ 125000000u
#define NX_IRQ_PERIOD (NX_IRQ_HZ/1000u)
enum {NX_EV_NPU=1,NX_EV_UART=2,NX_EV_TIMER=4,NX_EV_RX_ERROR=8};
typedef struct {
    uint32_t external_isrs,timer_isrs,npu_events,rx_bytes,rx_errors,rx_overflow;
    uint32_t polls,waits,late_ticks,max_isr_cycles,max_tick_late,led_writes;
    uint32_t software_events,main_consumed;
} nx_irq_metrics;
extern volatile nx_irq_metrics nx_irq_stats;
void nx_irq_start(void);
void nx_irq_stop(void);
int nx_irq_enabled(void);
uint32_t nx_irq_handler(uint32_t cause,uint32_t pc);
int nx_irq_rx_pop(void); /* -1 empty, -2 poisoned line discarded */
void nx_irq_npu_arm(void);
void nx_irq_npu_wait(void *);
int nx_irq_npu_notified(void);
void nx_irq_consume(uint32_t);
void nx_irq_led_override(void);
int nx_irq_blink(uint32_t mask,uint32_t period_ms,uint32_t edges);
void nx_irq_led_stop(void);
#endif
