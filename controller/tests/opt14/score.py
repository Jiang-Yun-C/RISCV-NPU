"""Independent complete logits inventory and production software observations."""
import struct
from pathlib import Path

N = 151936


def words():
    return [0x3fc00000 if i == N-1 else 0x3f000000+((i*13)&0x7fffff) for i in range(N)]


def golden():
    vector = words()
    cases = []
    for name, edits, zeros in (
        ('last_row', {}, False),
        ('cross_block_tie', {255:0x40000000,256:0x40000000,151808:0x40000000}, False),
        ('eos', {151645:0x40000000}, False),
        ('nan_last', {N-1:0x7fc00001}, False),
        ('positive_infinity_first', {0:0x7f800000}, False),
        ('negative_infinity_last', {N-1:0xff800000}, False),
        ('signed_zero_tie', {}, True)):
        data = [0x80000000 if not i%2 else 0 for i in range(N)] if zeros else vector.copy()
        for i, value in edits.items():data[i] = value
        # Check IEEE exponent bits before comparing values. No DUT result used.
        bad = any((v&0x7f800000)==0x7f800000 for v in data)
        values = struct.unpack('<%df'%N, struct.pack('<%dI'%N, *data))
        best = max(range(N), key=values.__getitem__) if not bad else 123456
        cases.append(dict(name=name,status=-2 if bad else 0,token=best))
    return dict(vocabulary=N,bytes=N*4,cases=cases)


def score(path, expected, checks):
    checks.equal(expected, golden(), 'golden', 'independent complete-vocabulary oracle')
    records = {}
    for line in Path(path).read_text().splitlines():
        g,i,v = map(int,line.split())
        checks.require((g,i) not in records,'output_set','unique CPU record')
        records[g,i] = v
    keys = {(0,i) for i in range(2)}|{(100+(i>>16),i&65535) for i in range(N)}
    keys |= {(j,i) for j in range(1,8) for i in range(4)}
    checks.equal(set(records),keys,'output_set','all logits and all phase reports, no extras')
    for i,w in enumerate(words()):
        checks.equal(records[100+(i>>16),i&65535],w,'data','CPU readback remaining staging copy')
    results = []
    for j,c in enumerate(expected['cases'],1):
        checks.equal(records[j,0],c['status']&0xffffffff,'semantics',c['name']+' status')
        checks.equal(records[j,1],c['token'],'semantics',c['name']+' token/atomic error')
        elapsed=records[j,2]+(records[j,3]<<32)
        checks.require(0<elapsed<100000000,'timing',c['name']+' mcycle interval')
        results.append(dict(c,cycles=elapsed))
    elapsed=records[0,0]+(records[0,1]<<32)
    checks.require(0<elapsed<100000000,'timing','remaining BA -> AC copy mcycle')
    return dict(copy_cycles=elapsed,scans=results,bytes=N*4,elements=N,
                scope='UNCHANGED_PRODUCTION_CPU_GREEDY_AND_COPY_T04_BEHAVIORAL_AXI_NOT_ARGMAX_RTL_OR_BOARD')
