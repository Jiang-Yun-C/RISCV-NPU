/* Small streaming reporter for the format strings in unmodified CoreMark.
 * No libc, libm, heap, 1 KiB buffer, or hidden ecvtbuf/fcvtbuf dependency.
 * Formatting is outside the timed benchmark. Legacy ee_printf.c is retained
 * for old T21 scripts; standalone builds select this file instead. */
#include "coremark.h"
#include <stdarg.h>
#include <stdint.h>

static int emit(char c) { cm_port_putchar(c); return 1; }
static int emit_string(const char *s) {
    int n = 0;
    if (!s) s = "(null)";
    while (*s) n += emit(*s++);
    return n;
}
static int emit_unsigned(uint64_t v, unsigned base, unsigned width, char pad,
                         int upper) {
    char buffer[24];
    const char *digits = upper ? "0123456789ABCDEF" : "0123456789abcdef";
    unsigned count = 0; int n = 0;
    do { buffer[count++] = digits[v % base]; v /= base; } while (v);
    while (width > count) { n += emit(pad); --width; }
    while (count) n += emit(buffer[--count]);
    return n;
}
#if HAS_FLOAT
static int emit_fixed(double v, unsigned precision) {
    union { double number; uint64_t bits; } bits = {v};
    int n = 0;
    unsigned exponent = (unsigned)((bits.bits >> 52) & 0x7ffu);
    if (bits.bits >> 63) { n += emit('-'); v = -v; }
    if (exponent == 0x7ffu)
        return n + emit_string((bits.bits & UINT64_C(0xfffffffffffff)) ? "nan" : "inf");
    if (v >= 18446744073709551616.0) return n + emit_string("overflow");
    if (precision > 9) precision = 9;
    uint64_t scale = 1;
    for (unsigned i = 0; i < precision; ++i) scale *= 10;
    uint64_t whole = (uint64_t)v;
    uint64_t fraction = (uint64_t)((v - (double)whole) * (double)scale + 0.5);
    if (fraction == scale) { ++whole; fraction = 0; }
    n += emit_unsigned(whole, 10, 0, ' ', 0);
    if (precision) { n += emit('.'); n += emit_unsigned(fraction, 10, precision, '0', 0); }
    return n;
}
#endif

int ee_printf(const char *fmt, ...) {
    va_list args; int n = 0;
    va_start(args, fmt);
    while (*fmt) {
        if (*fmt != '%') { n += emit(*fmt++); continue; }
        ++fmt;
        char pad = ' '; unsigned width = 0, precision = 6, length = 0;
        if (*fmt == '0') { pad = '0'; ++fmt; }
        while (*fmt >= '0' && *fmt <= '9') { width = width * 10u + (unsigned)(*fmt++ - '0'); }
        if (*fmt == '.') {
            ++fmt; precision = 0;
            while (*fmt >= '0' && *fmt <= '9') precision = precision * 10u + (unsigned)(*fmt++ - '0');
        }
        if (*fmt == 'l') { ++length; ++fmt; if (*fmt == 'l') { ++length; ++fmt; } }
        char kind = *fmt;
        if (!kind) break;
        ++fmt;
        if (kind == '%') { n += emit('%'); continue; }
        if (kind == 's') { n += emit_string(va_arg(args, const char *)); continue; }
        if (kind == 'c') { n += emit((char)va_arg(args, int)); continue; }
#if HAS_FLOAT
        if (kind == 'f') { n += emit_fixed(va_arg(args, double), precision); continue; }
#endif
        if (kind == 'u' || kind == 'x' || kind == 'X' || kind == 'd' || kind == 'i') {
            uint64_t value;
            if (kind == 'd' || kind == 'i') {
                int64_t sv = length == 2 ? va_arg(args, long long) :
                             length == 1 ? va_arg(args, long) : va_arg(args, int);
                value = (uint64_t)sv;
                if (sv < 0) { n += emit('-'); value = 0u - value; if (width) --width; }
            } else {
                value = length == 2 ? va_arg(args, unsigned long long) :
                        length == 1 ? va_arg(args, unsigned long) : va_arg(args, unsigned int);
            }
            n += emit_unsigned(value, (kind == 'x' || kind == 'X') ? 16 : 10,
                               width, pad, kind == 'X');
            continue;
        }
        n += emit('%'); n += emit(kind);
    }
    va_end(args);
    return n;
}
