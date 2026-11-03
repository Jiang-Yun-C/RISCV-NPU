/* Synthetic timer only for native algorithm/port regression. Never a score. */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
static uint32_t cycle;
uint32_t cm_test_cycle_high(void) { return 0; }
uint32_t cm_test_cycle_low(void) { cycle += 1000000; return cycle; }
void cm_test_putchar(char c) { putchar((unsigned char)c); }
void cm_test_complete(uint32_t code) { if (code != 0xc021u) abort(); }
