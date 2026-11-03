"""Finite FMA boundary vectors from exact rational arithmetic, for all five formats."""
from fractions import Fraction
import random

FORMATS = [(8, 23), (11, 52), (5, 10), (5, 2), (8, 7)]


def pow2(n):
    return Fraction(1 << n) if n >= 0 else Fraction(1, 1 << -n)


def exponent(x):
    e = x.numerator.bit_length() - x.denominator.bit_length()
    return e - (x < pow2(e))


def decode(bits, eb, mb):
    e = (bits >> mb) & ((1 << eb) - 1)
    m = bits & ((1 << mb) - 1)
    assert e != (1 << eb) - 1
    bias = (1 << (eb - 1)) - 1
    x = (m if e == 0 else (1 << mb) + m) * pow2((1 if e == 0 else e) - bias - mb)
    return -x if bits >> (eb + mb) else x


def rounded(x, step, mode, neg):
    x /= step
    q, r = divmod(x.numerator, x.denominator)
    up = [2*r > x.denominator or (2*r == x.denominator and q % 2),
          False, neg and r != 0, not neg and r != 0, 2*r >= x.denominator][mode]
    return (q + bool(up)) * step


def reference(a, b, c, op, mod, mode, fmt):
    eb, mb = FORMATS[fmt]
    av, bv, cv = [decode(v, eb, mb) for v in (a, b, c)]
    if mod:
        cv = -cv
    x = bv + cv if op == 2 else av*bv if op == 3 else (-av*bv if op == 1 else av*bv) + cv
    sign = 1 << (eb + mb)
    if not x:
        return (sign if mode == 2 else 0), 0
    neg = x < 0
    x = abs(x)
    bias = (1 << (eb - 1)) - 1
    emin = 1 - bias
    e = exponent(x)
    unlimited = rounded(x, pow2(e - mb), mode, neg)
    out = rounded(x, pow2(max(e, emin) - mb), mode, neg)
    nx = out != x
    uf = unlimited < pow2(emin) and nx
    if out < pow2(emin):
        bits = int(out / pow2(emin - mb))
    else:
        oe = exponent(out)
        assert oe <= bias, 'vectors intentionally exclude overflow/special values'
        bits = ((oe + bias) << mb) | (int(out / pow2(oe - mb)) - (1 << mb))
    return bits | (sign if neg else 0), (int(uf) << 1) | int(nx)


def vectors(fmt):
    eb, mb = FORMATS[fmt]
    one = ((1 << (eb - 1)) - 1) << mb
    half, normal, sub, sign = one - (1 << mb), 1 << mb, (1 << mb)-1, 1 << (eb+mb)
    cases = [(one, one, one, 2, 0), (one, one, one, 2, 1),
             (one, one+1, one, 2, 1), (one, normal, sub, 2, 1),
             (one, sub, 1, 2, 0), (normal, half, 0, 3, 0),
             (1, half, 0, 3, 0), (normal+1, half, 0, 3, 0),
             (one+1, one-1, one|sign, 0, 0),
             (one+1, one+1, one+2, 0, 1),
             (one+1, one+1, one+2, 1, 0)]
    rng = random.Random(19 + fmt)
    for _ in range(64):
        a, b = one+rng.randrange(1 << mb), one+rng.randrange(1 << mb)
        c = one+rng.randrange(1 << mb)
        cases.append((a, b, c, 0, 1))
        cases.append((one, a, b, 2, 1))
    for a, b, c, op, mod in cases:
        for mode in range(5):
            result, flags = reference(a, b, c, op, mod, mode, fmt)
            yield a, b, c, op, mod, mode, result, flags
