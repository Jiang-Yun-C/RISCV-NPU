#ifndef NX_CE64_BOARD_BOOT_H
#define NX_CE64_BOARD_BOOT_H
#include <stdint.h>
int nx_ce64_board_load(void);
uint64_t nx_ce64_board_ticks(void);
void nx_ce64_board_telemetry(void);
#endif
