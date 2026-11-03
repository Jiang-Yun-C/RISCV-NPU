"""Independent exact-rational FP32 multiply oracle; no host float or DUT output."""
from fractions import Fraction
import random


def power2(n):
    return Fraction(2**n) if n >= 0 else Fraction(1, 2**-n)


def decode(bits):
    exponent, mantissa = (bits >> 23) & 255, bits & 0x7fffff
    assert exponent != 255
    value = mantissa * power2(-149) if not exponent else ((1 << 23) + mantissa) * power2(exponent - 150)
    return -value if bits >> 31 else value


def exponent_of(value):
    exponent = value.numerator.bit_length() - value.denominator.bit_length()
    return exponent - (value < power2(exponent))


def rounded_units(value, step, mode, negative):
    scaled = value / step
    q, r = divmod(scaled.numerator, scaled.denominator)
    twice = 2*r
    up = {0: twice > scaled.denominator or (twice == scaled.denominator and q % 2),
          1: False, 2: negative and r != 0, 3: not negative and r != 0,
          4: twice >= scaled.denominator}[mode]
    return q + bool(up)


def multiply(a, b, mode):
    value = decode(a)*decode(b)
    negative = bool((a ^ b) >> 31)
    value = abs(value)
    if not value:
        return int(negative) << 31, 0
    exponent = exponent_of(value)
    unlimited_step = power2(exponent - 23)
    unlimited = rounded_units(value, unlimited_step, mode, negative)*unlimited_step
    step = power2(max(exponent - 23, -149))
    rounded = rounded_units(value, step, mode, negative)*step
    inexact = rounded != value
    # Tininess after rounding to 24 significant bits, before exponent limiting.
    underflow = unlimited < power2(-126) and inexact
    if rounded < power2(-126):
        bits = int(rounded / power2(-149))
    else:
        e = exponent_of(rounded)
        assert e < 128
        bits = ((e + 127) << 23) | (int(rounded / power2(e - 23)) - (1 << 23))
    return bits | (int(negative) << 31), (int(underflow) << 1) | int(inexact)


def vectors():
    pairs = [(0x3fc00000, 0x40000000), (0x00800000, 0x3f000000),
             (0x00000001, 0x3f000000), (0x00800000, 0x3f7fffff),
             (0x007fffff, 0x3f800001), (0x00800001, 0x3f7ffffe)]
    # Products immediately below the smallest normal number; include both
    # sides of the unbounded-exponent rounding threshold and fixed-seed cases.
    rng = random.Random(19)
    for k in [1, 1000, 1448, 1449, 1600, 2047, 2048, 2049, 4096] + [rng.randrange(1, 4097) for _ in range(48)]:
        pairs.append((0x00800000+k, 0x3f800000-2*k))
    for a, b in pairs:
        for negative in (0, 0x80000000):
            for mode in range(5):
                result, flags = multiply(a | negative, b, mode)
                yield a | negative, b, mode, result, flags
