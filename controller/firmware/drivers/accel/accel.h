#ifndef NX_ACCEL_H
#define NX_ACCEL_H
#include "backend_v1.h"
/* T13 native Coral transport. This is not a numerical operator capability. */
#define NX_ACCEL_ABI 1u
#define NX_ACCEL_PROBE 0x54503133u
#define NX_ACCEL_PARAMS 0x20010000u
#define NX_ACCEL_RESULT 0x20010100u
#define NX_ACCEL_CONTROL 0x20030000u
#define NX_ACCEL_ENTRY 0x20030004u
#define NX_ACCEL_STATUS 0x20030008u
#define NX_BRIDGE_CONTROL 0x10000100u /* bit 0 owner, bit 1 isolate */
#define NX_BRIDGE_STATUS 0x10000104u  /* bit 0 drained, bit 1 CPU IO error, bit 2 backend IO error */
#define NX_BRIDGE_CLEAR 0x10000108u
#define NX_BRIDGE_IRQ 0x1000010cu     /* pending W1C; notification only */
#define NX_BRIDGE_ADDRESS 0x10000110u
#define NX_BRIDGE_IRQ_ENABLE 0x10000114u

typedef struct {
    void *cookie;
    uint32_t (*read32)(void *, uint32_t);
    void (*write32)(void *, uint32_t, uint32_t);
    uint64_t (*ticks)(void *);
    void (*fence)(void *);
    uint64_t tick_hz;
} nx_accel_io;
typedef struct {
    const uint32_t *words;
    uint32_t bytes, entry, crc32;
} nx_accel_program;
typedef struct {
    uint32_t abi, opcode, input, output, words, xor_mask;
} nx_accel_job;
typedef nx_status (*nx_linear_provider)(void *, const nx_call *, const nx_linear *, nx_stats *);
enum { NX_ACCEL_IDLE, NX_ACCEL_RUNNING, NX_ACCEL_FAULTED };
struct nx_context {
    nx_accel_io io;
    nx_accel_program program;
    uint64_t session, sequence;
    uint32_t state, initialized, kv_valid, fault_address;
    nx_stats last;
    nx_linear_provider linear_provider;
    void *linear_cookie;
    uint32_t linear_routes;
};
/* The checked ITCM image must outlive the context. nx_accel_run retains the
 * T13 probe ABI; the installed linear provider uses the T15 numerical ABI. */
nx_status nx_accel_init(nx_context *, const nx_accel_io *, const nx_accel_program *, uint64_t timeout);
nx_status nx_accel_run(nx_context *, const nx_call *, const nx_accel_job *, nx_stats *);
nx_status nx_accel_validate_job(const nx_accel_job *);
uint32_t nx_accel_crc32(const uint32_t *, uint32_t);
void nx_accel_target_io(nx_accel_io *);
void nx_accel_irq(nx_context *);
/* T15 numerical provider; platform transport qualification remains T16. */
nx_status nx_linear_install(nx_context *, nx_linear_provider, void *, uint32_t routes);
#endif
