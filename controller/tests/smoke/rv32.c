#include <stdint.h>
volatile uint32_t smoke_result;
void smoke_main(void) {
    uint32_t sum = 0;
    for (uint32_t i = 1; i <= 16; ++i) sum += i;
    smoke_result = sum;
}
