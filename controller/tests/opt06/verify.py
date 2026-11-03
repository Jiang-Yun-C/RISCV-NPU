"""Independent archived-byte and waveform checks, separate from DUT encoder."""
import json,re
from pathlib import Path

def check_waveform(directory):
    from tests.boot.uart.waveform import check_waveform as original
    return original(directory)

def verify_bytes(directory,golden):
    d=Path(directory);raw=json.loads((d/'uart-trace.json').read_text());checks=0
    wire=bytes(b for _,b in raw['tx']);requests=raw['requests']
    if len(requests)!=len(golden):raise ValueError('missing requests')
    for rec,g in zip(requests,golden):
        if rec['name']!=g['name']:raise ValueError('case order')
        lines=rec['lines'];pieces=[];ids=[];end=False;abort=False
        for line in lines:
            m=re.fullmatch(r'T25 STREAM 1 (\w+) (.*)',line)
            if not m:continue
            kind=m[1];f=dict(x.split('=',1) for x in m[2].split())
            if kind=='TEXT':pieces.append(bytes.fromhex(f['data']));pieces[-1].decode('utf8');checks+=1
            if kind=='TOKEN':ids.append(int(f['token'],16))
            end|=kind=='END';abort|=kind=='ABORT'
        if g['error']:
            if not abort or end:raise ValueError('failure committed')
        elif g['enabled']:
            if not end or abort or b''.join(pieces)!=g['expected_text'].encode() or ids!=g['expected_ids']:raise ValueError('independent byte/ID mismatch')
        checks+=3
    writes=bytes(int(x.split(',')[1]) for x in (d/'uart-writes.csv').read_text().splitlines())
    if writes!=wire:raise ValueError('physical wire/MMIO mismatch')
    checks+=len(wire)
    return dict(status='PASS',independent_checks=checks,wire_bytes=len(wire),requests=len(requests))
