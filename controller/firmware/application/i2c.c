#include "i2c.h"
#include <string.h>

static int valid(const struct nx_i2c_bus *b) {
    return b && b->release && b->read && b->delay_us &&
        b->half_period_us >= 5 && b->half_period_us <= 1000000 &&
        b->stretch_timeout_us && b->stretch_timeout_us <= 1000000;
}
static void pins(const struct nx_i2c_bus *b, uint32_t v) {
    b->release(b->context, v);
}
static void half(const struct nx_i2c_bus *b) {
    b->delay_us(b->context, b->half_period_us);
}
static int high(const struct nx_i2c_bus *b, uint32_t data) {
    pins(b, NX_I2C_SCL | data);
    for (uint32_t elapsed = 0;; elapsed++) {
        if (b->read(b->context) & NX_I2C_SCL) { half(b); return NX_I2C_OK; }
        if (elapsed == b->stretch_timeout_us) return NX_I2C_TIMEOUT;
        b->delay_us(b->context, 1);
    }
}
static int start(const struct nx_i2c_bus *b) {
    int rc = high(b, NX_I2C_SDA);
    if (rc) return rc;
    if (!(b->read(b->context) & NX_I2C_SDA)) return NX_I2C_BUS_STUCK;
    pins(b, NX_I2C_SCL); half(b); /* START: SDA falls while SCL high */
    pins(b, 0); half(b);
    return NX_I2C_OK;
}
static int stop(const struct nx_i2c_bus *b) {
    pins(b, 0); half(b);
    int rc = high(b, 0);
    if (rc) { pins(b, 3); return rc; }
    pins(b, 3); half(b); /* STOP and bus-free interval */
    return (b->read(b->context) & 3u) == 3u ? NX_I2C_OK : NX_I2C_BUS_STUCK;
}
static int write_byte(const struct nx_i2c_bus *b, uint8_t value) {
    for (int bit = 7; bit >= 0; bit--) {
        uint32_t data = ((value >> bit) & 1u) ? NX_I2C_SDA : 0;
        pins(b, data); half(b);
        int rc = high(b, data);
        if (rc) return rc;
        pins(b, data);
    }
    pins(b, NX_I2C_SDA); half(b);
    int rc = high(b, NX_I2C_SDA);
    if (rc) return rc;
    int ack = !(b->read(b->context) & NX_I2C_SDA);
    pins(b, NX_I2C_SDA); half(b);
    return ack ? NX_I2C_OK : NX_I2C_NACK;
}
static int read_byte(const struct nx_i2c_bus *b, uint8_t *value, int last) {
    uint8_t v = 0;
    for (int bit = 7; bit >= 0; bit--) {
        pins(b, NX_I2C_SDA); half(b);
        int rc = high(b, NX_I2C_SDA);
        if (rc) return rc;
        v = (uint8_t)((v << 1) | !!(b->read(b->context) & NX_I2C_SDA));
        pins(b, NX_I2C_SDA);
    }
    uint32_t data = last ? NX_I2C_SDA : 0; /* final byte MUST be NACKed */
    pins(b, data); half(b);
    int rc = high(b, data);
    if (rc) return rc;
    pins(b, data); half(b);
    pins(b, NX_I2C_SDA);
    *value = v;
    return NX_I2C_OK;
}
int nx_i2c_transfer(const struct nx_i2c_bus *b, uint8_t address,
                    const uint8_t *tx, size_t nt, uint8_t *rx, size_t nr) {
    if (!valid(b) || address < 8 || address > 0x77 || (!nt && !nr) ||
        nt > NX_I2C_MAX_BYTES || nr > NX_I2C_MAX_BYTES ||
        (nt && !tx) || (nr && !rx)) return NX_I2C_INVALID;
    uint8_t pending[NX_I2C_MAX_BYTES];
    int rc = start(b);
    if (rc) { pins(b, 3); return rc; }
    rc = write_byte(b, (uint8_t)((address << 1) | !nt));
    for (size_t i = 0; !rc && i < nt; i++) rc = write_byte(b, tx[i]);
    if (!rc && nt && nr) {
        rc = start(b);
        if (!rc) rc = write_byte(b, (uint8_t)((address << 1) | 1u));
    }
    for (size_t i = 0; !rc && i < nr; i++) rc = read_byte(b, pending + i, i + 1 == nr);
    int stopped = stop(b);
    /* A failed STOP is itself a bus fault, even when the target first NACKed. */
    if (stopped) rc = stopped;
    pins(b, 3);
    if (!rc && nr) memcpy(rx, pending, nr);
    return rc;
}
int nx_i2c_recover(const struct nx_i2c_bus *b) {
    if (!valid(b)) return NX_I2C_INVALID;
    int rc = high(b, NX_I2C_SDA);
    for (unsigned i = 0; !rc && i < 9 && !(b->read(b->context) & NX_I2C_SDA); i++) {
        pins(b, NX_I2C_SDA); half(b);
        rc = high(b, NX_I2C_SDA);
    }
    if (!rc) rc = stop(b);
    pins(b, 3);
    return rc;
}
