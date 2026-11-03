#include <stdint.h>
extern uint32_t nx_sd_test_regs[64];
#define SPI(o) nx_sd_test_regs[(o)/4]
uint32_t nx_sd_test_ticks(void);
int nx_sd_test_initialize(void);
int nx_sd_test_sector(uint32_t,uint8_t *);
void nx_sd_test_after_store(uint32_t,unsigned);
int nx_sd_test_finish(uint32_t,uint32_t);
