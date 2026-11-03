"""Decode accepted payload counters from physical capture samples.

No simulator or nominal pin rate is used to produce a bandwidth number.
The board receipt gate separately checks capture and implemented identities.
"""

import math

WORKLOADS={1:'sequential_read',2:'sequential_write',3:'mixed',4:'burst_1',5:'burst_16',6:'burst_256'}

def measure(samples, workload):
    if workload not in set(WORKLOADS.values())|{'cpu_npu_competition'}:raise ValueError('unknown workload')
    if len(samples)<2: raise ValueError('missing sustained counter samples')
    required={'sequence','host_elapsed_s','core_cycles','write_payload_bytes','read_payload_bytes','errors','init_done'}
    for sample in samples:
        if not required.issubset(sample) or sample['errors']!=0 or sample['init_done'] is not True:
            raise ValueError('missing counter or calibration/error failure')
        if type(sample['host_elapsed_s']) not in (int,float) or not math.isfinite(sample['host_elapsed_s']):
            raise ValueError('invalid physical timestamp')
        for key in ('sequence','core_cycles','write_payload_bytes','read_payload_bytes'):
            if type(sample[key]) is not int or not 0<=sample[key]<2**64:
                raise ValueError('counter must be unsigned 64-bit')
    for a,b in zip(samples,samples[1:]):
        if b['sequence']!=a['sequence']+1 or b['host_elapsed_s']<=a['host_elapsed_s'] or b['core_cycles']<=a['core_cycles']:
            raise ValueError('dropped sample, reset or nonmonotonic time')
        if b['write_payload_bytes']<a['write_payload_bytes'] or b['read_payload_bytes']<a['read_payload_bytes']:
            raise ValueError('counter reset or unexpanded overflow')
        # More than 32 bytes/cycle cannot come from this 256-bit user port.
        dc=b['core_cycles']-a['core_cycles']
        if any(b[k]-a[k]>dc*32 for k in ('write_payload_bytes','read_payload_bytes')):
            raise ValueError('impossible payload counter delta')
    first,last=samples[0],samples[-1]
    seconds=last['host_elapsed_s']-first['host_elapsed_s']
    if seconds<10: raise ValueError('sustained bandwidth needs at least 10 seconds')
    hz=(last['core_cycles']-first['core_cycles'])/seconds
    if not 121250000<hz<128750000: raise ValueError('physical clock/time window mismatch')
    write=last['write_payload_bytes']-first['write_payload_bytes']
    read=last['read_payload_bytes']-first['read_payload_bytes']
    if workload=='sequential_read' and write or workload=='sequential_write' and read:
        raise ValueError('sequential workload contains opposite-direction payload')
    payload=read if workload=='sequential_read' else write if workload=='sequential_write' else read+write
    if payload<=0 or (workload in ('mixed','cpu_npu_competition') and (read==0 or write==0)):
        raise ValueError('missing required payload traffic')
    return {'status':'PASS','payload_bytes':payload,'write_payload_bytes':write,'read_payload_bytes':read,
            'window_seconds':seconds,'cycles':last['core_cycles']-first['core_cycles'],
            'core_clock_hz_estimated':hz,'bytes_per_second':payload/seconds,'errors':0}

def physical_workloads(capture, raw):
    """Derive counters from CRC-verified original UART bytes and capture times."""
    from ddr_data_protocol import Decoder,is_t23_reset_snapshot
    decoder=Decoder();frames=decoder.feed(raw)
    if capture.get('await_boot'):
        start=next((i for i,f in enumerate(frames) if f['sequence']==0),len(frames));frames=frames[start:]
    recorded=capture['frames']
    if decoder.crc_failures or len(frames)!=len(recorded):raise ValueError('raw physical frame mismatch')
    samples=[]
    for i,(f,r) in enumerate(zip(frames,recorded)):
        if any(r.get(k)!=v for k,v in f.items()):raise ValueError('capture differs from raw UART')
        if i==0 and is_t23_reset_snapshot(f):continue
        if f.get('capacity_counter_schema')!=0x10002:raise ValueError('not a T23 adapter capture')
        f['host_elapsed_s']=r['host_elapsed_s'];samples.append(f)
    windows={};current=[]
    for f in samples+[{'workload':-1}]:
        if current and f['workload']!=current[-1]['workload']:
            mode=current[0]['workload']
            if mode in WORKLOADS and WORKLOADS[mode] not in windows:
                try:
                    result=measure(current,WORKLOADS[mode])
                    windows[WORKLOADS[mode]]={'result':result,'samples':current}
                except ValueError:
                    pass
            current=[]
        current.append(f)
    if set(windows)!=set(WORKLOADS.values()):raise ValueError('missing sustained physical workload windows')
    return windows
