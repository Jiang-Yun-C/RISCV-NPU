#!/usr/bin/env python3
"""Checked ELF -> TCM image, deterministic inputs and host integer/FP oracle."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys
from elftools.elf.elffile import ELFFile
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'models'))
from prepare_image import parse_elf


def prepare(elf, output, kind):
    raw = elf.read_bytes()
    entry, segments, flags = parse_elf(raw, base=0, capacity=0x18000)
    if entry % 4 or flags & 1:
        raise ValueError('require 32-bit aligned entry and no compressed ISA')
    mem = bytearray(0x18000)
    for s in segments:
        if not (0 <= s.address < s.address+s.memory_size <= 8192 or
                0x10000 <= s.address < s.address+s.memory_size <= 0x18000):
            raise ValueError('ELF segment outside ITCM/DTCM')
        mem[s.address:s.address+len(s.data)] = s.data
    with elf.open('rb') as f:
        symtab = ELFFile(f).get_section_by_name('.symtab')
        symbols = {s.name: {'address': int(s['st_value']), 'size': int(s['st_size'])}
                   for s in symtab.iter_symbols() if s.name}
    # The upstream linker script reserves four bytes for _ret without an ELF
    # symbol size; coralnpu_start.S writes that ABI word with sw.
    if kind in ('float', 'upstream_rvv') and symbols['_ret']['size'] == 0:
        symbols['_ret']['size'] = 4
        symbols['_ret']['size_source'] = 'coralnpu_tcm.ld.tpl: _ret = .; . += 4'
    expected = {}
    def put(name, data, oracle=False):
        s = symbols[name]; a = s['address']
        if len(data) != s['size'] or not 0x10000 <= a < a+len(data) <= 0x18000:
            raise ValueError('bad symbol bounds: '+name)
        if oracle:
            expected[name] = dict(s, hex=data.hex())
            mem[a:a+len(data)] = b'\xa5'*len(data)
        else:
            mem[a:a+len(data)] = data
    if kind == 'float':
        a = [1., -2., 0.5, 16., -8., 100., -0.25, 0.]
        b = [2., 3., -0.25, -4., -2., -99., 0.5, -1.]
        put('input1', struct.pack('<8f', *a)); put('input2', struct.pack('<8f', *b))
        put('output', struct.pack('<8f', *[x+y for x,y in zip(a,b)]), True)
        put('_ret', struct.pack('<i',0), True)
    elif kind == 'upstream_rvv':
        put('output', struct.pack('<1024h', *([7]*1024)), True)
        put('_ret', struct.pack('<i',0), True)
    elif kind == 'vector':
        a = [((i*37+11)%256)-128 for i in range(67)]
        b = [((i*53+7)%256)-128 for i in range(67)]
        a[:4] = [-128,127,-128,127]; b[:4] = [-128,127,127,-128]
        put('input_a', struct.pack('<67b', *a)); put('input_b', struct.pack('<67b', *b))
        put('sums', struct.pack('<67h', *[x+y for x,y in zip(a,b)]), True)
        put('products', struct.pack('<67h', *[x*y for x,y in zip(a,b)]), True)
        put('dot_result', struct.pack('<i', sum(x*y for x,y in zip(a,b))), True)
        put('done', struct.pack('<I',0x743036aa), True)
        # Guard only actual padding between symbols, never overlap another object.
        for name in ('sums','products'):
            end=symbols[name]['address']+symbols[name]['size']
            stop=(end+15)&~15
            if stop>end and not any(end <= s['address'] < stop for s in symbols.values() if s['size']):
                mem[end:stop]=b'\x69'*(stop-end)
                expected[name+'_guard']={'address':end,'size':stop-end,'hex':mem[end:stop].hex()}
    else:
        raise ValueError('unsupported workload')
    output.mkdir(parents=True, exist_ok=False)
    tcm = mem[:8192]+mem[0x10000:0x18000]
    (output/'load.hex').write_text(''.join(f'{int.from_bytes(tcm[i:i+16],"little"):032x}\n' for i in range(0,len(tcm),16)))
    record = {'schema_version':1,'kind':kind,'entry':entry,'elf_flags':flags,
        'elf_sha256':hashlib.sha256(raw).hexdigest(), 'mode':'AXI_SUBORDINATE_LOAD',
        'image_sha256':hashlib.sha256(tcm).hexdigest(), 'expected':expected,
        'segments':[{'address':s.address,'file_bytes':len(s.data),'memory_bytes':s.memory_size} for s in segments],
        'symbols':symbols}
    (output/'image.json').write_text(json.dumps(record,indent=2)+'\n')
    return record

if __name__ == '__main__':
    p=argparse.ArgumentParser(); p.add_argument('elf',type=Path); p.add_argument('output',type=Path)
    p.add_argument('--kind',required=True,choices=['float','upstream_rvv','vector']); a=p.parse_args()
    result=prepare(a.elf,a.output,a.kind)
    print(json.dumps({'status':'PASS','kind':a.kind,'entry':result['entry'],'mode':result['mode']}))
