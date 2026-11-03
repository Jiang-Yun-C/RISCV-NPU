#ifndef NX_UART_STREAM_H
#define NX_UART_STREAM_H
#include <stdint.h>
#define NX_UART_MAGIC 0x31353255u /* U251 */
#define NX_UART_ACK 0x41353255u   /* U25A */
#define NX_UART_DATA 1u
#define NX_UART_START 2u
#define NX_UART_RESET 3u
enum { NX_UART_CRC=256,NX_UART_SEQUENCE,NX_UART_FORMAT,NX_UART_TIMEOUT,NX_UART_STATE };
typedef struct {
    void *cookie;
    /* RX: 1 byte, 0 deadline expired, -1 transport closed (host tests only).
     * deadline=0 waits for the first byte without a partial-frame deadline. */
    int (*get)(void *,uint64_t deadline,uint8_t *);
    void (*put)(void *,const uint8_t *,unsigned);
    uint64_t (*ticks)(void *);
    int (*seal)(void *);
    void (*reset)(void *);
    uint64_t frame_ticks;
} nx_uart_io;
void nx_uart_init(const nx_uart_io *);
int nx_uart_sector(uint32_t lba,uint8_t out[512]);
int nx_uart_finish(void);
void nx_uart_reject(uint32_t error);
uint32_t nx_uart_boot(void);
void nx_uart_observe_model(int32_t dot,uint32_t entries);
void nx_uart_enter(uint32_t address);
#endif
