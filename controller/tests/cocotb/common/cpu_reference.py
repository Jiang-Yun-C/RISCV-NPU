"""Frozen-input golden; no DUT data enters expected arithmetic or trap values."""
import math
import struct
from check_cpu import reference


def expected(seed, hard, symbols, instruction_at):
    old = reference(seed)
    values = {0: seed, 1: 685, 2: old['ARITH'], 3: old['MEM'], 4: 0x40380000,
              5: 42, 6: 2*(0x11223344+0x22334455), 7: 0x11223344+0x22334455+0x33445566,
              8: 0x55667788, 9: 0xdecafbad, 10: 68, 11: 71, 12: 384,
              13: 3, 14: 0x76543210, 15: 0x40001120 if hard else 0x40001100,
              16: 0x6000 if hard else 0}
    if hard:
        values.update({20: struct.unpack('<I', struct.pack('<f', math.sqrt(8.25)))[0],
                       21: 0x7f800000, 22: 8, 23: 0x7fc00000, 24: 16, 25: 2, 26: 0x31})
    traps = []
    for name, cause, value in [('illegal',2,None),('badcsr',2,None),('readonly_csr',2,None),
                               ('ecall_test',11,None),('ebreak_test',3,None),
                               ('misload',4,0xb4100001),('misstore',6,0xb4100001),
                               ('misjump',0,0xb4010002),('badload',5,0xbc000000),
                               ('errload',5,0xb4300000)]:
        pc=symbols[name+'_site']
        traps.append([cause, pc, instruction_at(pc) if value is None else value])
    traps.append([1, 0xbc000000, 0xbc000000])
    return {"results": values, "traps": traps, "irq_causes": [0x80000007,0x8000000b,0x80000003],
            "uart": "T09 CPU OK\n", "exit": 0x600d0009}
