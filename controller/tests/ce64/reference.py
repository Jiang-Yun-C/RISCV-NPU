"""Independent integer binary32 RNE oracle; no candidate RTL imports.

Finite values are exact signed integers times powers of two. Every operation
rounds separately, including gradual underflow. Also cross-checked with numpy.
"""
import struct

def bits(x):
    return struct.unpack('<I', struct.pack('<f', x))[0]

def number(x):
    return struct.unpack('<f', struct.pack('<I', x))[0]

def finite(x):
    return (x >> 23) & 255 != 255

def scale_ok(x):
    return x == 0 or (x >> 31 == 0 and 0 < ((x >> 23) & 255) < 255)

def unpack(x):
    exponent = (x >> 23) & 255
    mantissa = x & 0x7fffff
    return ((-1 if x >> 31 else 1) * (mantissa | (0x800000 if exponent else 0)),
            exponent - 150 if exponent else -149)

def round32(n, exponent, zero_sign=0):
    sign = int(n < 0)
    n = abs(n)
    if not n:
        return zero_sign << 31, 0
    top = n.bit_length() - 1 + exponent
    shift = max(n.bit_length() - 24, -149 - exponent)
    if shift > 0:
        q, rem = divmod(n, 1 << shift)
        half = 1 << (shift - 1)
        q += rem > half or (rem == half and q & 1)
        inexact = bool(rem)
    else:
        q, inexact = n << (-shift), False
    quantum = exponent + shift
    if not q:
        return sign << 31, 3 if inexact else 0
    top = q.bit_length() - 1 + quantum
    if top > 127:
        return (sign << 31) | 0x7f800000, 5
    if top < -126:
        word = q << (quantum + 149)
        return (sign << 31) | word, (3 if inexact else 0)
    normalized = q << max(0, 24 - q.bit_length())
    if q.bit_length() > 24:
        normalized = q >> (q.bit_length() - 24)
    word = ((top + 127) << 23) | (normalized & 0x7fffff)
    return (sign << 31) | word, int(inexact)

def mul(a, b):
    ea, eb = (a >> 23) & 255, (b >> 23) & 255
    nan_a, nan_b = ea == 255 and a & 0x7fffff, eb == 255 and b & 0x7fffff
    sign = (a ^ b) >> 31
    if nan_a or nan_b:
        signaling = bool(nan_a and not a & 0x400000) or bool(nan_b and not b & 0x400000)
        return 0x7fc00000, 16 if signaling else 0
    if ea == 255 or eb == 255:
        if (a & 0x7fffffff) == 0 or (b & 0x7fffffff) == 0:
            return 0x7fc00000, 16
        return (sign << 31) | 0x7f800000, 0
    na, xa = unpack(a)
    nb, xb = unpack(b)
    return round32(na * nb, xa + xb, sign)

def add(a, b):
    ea, eb = (a >> 23) & 255, (b >> 23) & 255
    if ea == 255 or eb == 255:
        if (ea == 255 and a & 0x7fffff) or (eb == 255 and b & 0x7fffff):
            snan = (ea == 255 and a & 0x7fffff and not a & 0x400000) or (eb == 255 and b & 0x7fffff and not b & 0x400000)
            return 0x7fc00000, 16 if snan else 0
        if ea == 255 and eb == 255 and (a ^ b) >> 31:
            return 0x7fc00000, 16
        return a if ea == 255 else b, 0
    na, xa = unpack(a)
    nb, xb = unpack(b)
    exponent = min(xa, xb)
    n = (na << (xa - exponent)) + (nb << (xb - exponent))
    return round32(n, exponent, int(not na and not nb and a >> 31 and b >> 31))

def restore(dot, sa, sw, acc, initial=0):
    # Illegal dot values still traverse the RTL's bounded cast; only legal
    # dots have a numerical output contract. Such tests check status alone.
    cast = bits(float(dot))
    p, f1 = mul(cast, sa)
    v, f2 = mul(p, sw)
    y, f3 = add(acc, v)
    status = initial
    if not status:
        status = 1 if not scale_ok(sa) or not scale_ok(sw) else 2 if abs(dot) > 1032256 else 5 if not finite(acc) else 0
    if not status:
        status = 3 if not finite(p) else 4 if not finite(v) else 5 if not finite(y) else 0
    return p, v, y, status, f1 | f2 | f3
