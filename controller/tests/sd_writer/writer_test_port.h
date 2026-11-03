#include <stdint.h>
static volatile uint32_t mock_spi[64],mock_uart[64];
#define SPI(o) mock_spi[(o)/4]
#define UART(o) mock_uart[(o)/4]
static uint32_t ticks(void){static uint32_t n;return ++n;}
static int nx_test_read(uint32_t,uint8_t *);
static int nx_test_write(uint32_t,const uint8_t *);
