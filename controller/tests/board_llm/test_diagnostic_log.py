import copy
import pytest
from software.boot.t25_diagnostics import telemetry, pressure, memory


def sample(ticks=0):
    words=[0]*64
    words[:3]=[0x34364543,2,0x307]
    words[6]=0x48;words[8]=1;words[12]=1
    return dict(begin_ticks=ticks,end_ticks=ticks+100,status_after=0x307,profile=2,words=words)


def encode(s):
    return ['T25 TELEMETRY BEGIN '+' '.join(f'{k}={s[k]:016x}' for k in
            ('begin_ticks','end_ticks','status_after','profile'))]+[
        f'T25 TELEMETRY WORD {i:08x} {v:08x}' for i,v in enumerate(s['words'])]+['T25 TELEMETRY END']


def test_rejects_missing_reordered_faulted_or_unsealed_telemetry():
    lines=encode(sample())
    assert telemetry(lines)[0]['words'][8]==1
    for damaged in (lines[:-2]+lines[-1:],lines[:5]+[lines[4]]+lines[5:]):
        with pytest.raises(ValueError):telemetry(damaged)
    for word in (0x107,0x317,0x303):
        s=sample();s['words'][2]=word
        with pytest.raises(ValueError):telemetry(encode(s))


def test_rejects_short_pressure_or_missing_actual_ce_traffic():
    a=sample();a['words'][12]=0;b=sample(3601*125000000)
    for i in (32,34,40,42,48,50,56,58):b['words'][i]=100
    assert pressure(a,b)['bus_deltas']['ce']['read_bytes']==100
    for bad in ('time','ce','profile','pass'):
        c=copy.deepcopy(b)
        if bad=='time':c['begin_ticks']=1
        if bad=='ce':c['words'][50]=0
        if bad=='profile':c['profile']=0
        if bad=='pass':c['words'][12]=0
        with pytest.raises(ValueError):pressure(a,c)
    stale=copy.deepcopy(a);stale['words'][12]=b['words'][12]
    with pytest.raises(ValueError):pressure(stale,b)


def test_rejects_static_budget_or_duplicate_memory_records():
    regions=[(0x80000000+i*0x1000,64) for i in range(13)]
    lines=[f'T25 MEMORY REGION {i:08x} {base:08x} {n:08x}' for i,(base,n) in enumerate(regions)]
    report='T25 MEMORY committed_bytes=0000000000000340 peak_committed_bytes=0000000000000340 regions=000000000000000d runtime_write_readback_bytes=0000000000000200'
    assert memory(lines+[report],regions)['peak_application_committed_ddr_bytes']==832
    with pytest.raises(ValueError):memory(lines+[report.replace('0000000000000340','00000000215f2ca0')],regions)
    with pytest.raises(ValueError):memory(lines+[lines[0],report],regions)
