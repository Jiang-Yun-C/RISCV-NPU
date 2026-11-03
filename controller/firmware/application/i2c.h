#ifndef NX_APP_I2C_H
#define NX_APP_I2C_H
#include <stddef.h>
#include <stdint.h>

/* Single-controller, 7-bit I2C transport. No board pins or sensor assumed.
 * A set bit RELEASES an open-drain line; it must never drive logic high.
 * read() returns actual synchronized pad levels, not output latch values.
 * delay_us() must delay AT LEAST the requested time on the target clock.
 * Callers serialize transactions and keep callbacks valid throughout a call. */
#define NX_I2C_SCL 1u
#define NX_I2C_SDA 2u
#define NX_I2C_MAX_BYTES 256u
enum nx_i2c_status {
    NX_I2C_OK, NX_I2C_INVALID, NX_I2C_NACK, NX_I2C_TIMEOUT,
    NX_I2C_BUS_STUCK
};
struct nx_i2c_bus {
    void *context;
    void (*release)(void *, uint32_t);
    uint32_t (*read)(void *);
    void (*delay_us)(void *, uint32_t);
    uint32_t half_period_us; /* >=5: conservative Standard-mode timing */
    uint32_t stretch_timeout_us; /* 1..1000000, independently bounded */
};

/* One write, one read, or write + repeated START + read. Reserved addresses,
 * empty transfers and lengths >256 are rejected before touching the bus.
 * rx is published ONLY after a complete transfer and successful STOP.
 * On failure both lines are released. The device may have consumed tx bytes;
 * only the receive buffer has commit-on-success semantics. No implicit retry. */
int nx_i2c_transfer(const struct nx_i2c_bus *, uint8_t address,
                    const uint8_t *tx, size_t tx_bytes,
                    uint8_t *rx, size_t rx_bytes);

/* Explicit recovery for a single-controller bus: up to nine SCL pulses and
 * STOP, then verify idle. Record the original fault before invoking this.
 * Stuck SCL cannot be cleared in software. No power/reset pins are changed. */
int nx_i2c_recover(const struct nx_i2c_bus *);
#endif
