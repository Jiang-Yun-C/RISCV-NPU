#!/usr/bin/env python3
"""Independent checker of external AXI bytes, integer dots, FP32 and counters."""
import argparse
from collections import Counter, deque
import csv
import hashlib
import json
from pathlib import Path
import struct
import numpy as np
ROOT=Path(__file__).resolve().parents[2]

def require(ok,msg):
    if not ok: raise ValueError(msg)

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def check(case,image,disassembly):
    report=case/'check.json';report.unlink(missing_ok=True)
    meta=json.loads((image/'image.json').read_text()); metrics=json.loads((case/'metrics.json').read_text())
    require(meta['thresholds_sha256']==sha(ROOT/'configs/t05-thresholds.json'),'frozen thresholds changed')
    for name,h in meta['files'].items(): require(sha(image/name)==h,'image identity '+name)
    dis=disassembly.read_text()
    require(all(op in dis for op in ('vle8.v','vwmul.vv','vwredsum.vs','fmul.s','fadd.s')),'missing compute instructions')
    require('fmadd.s' not in dis and 'fmsub.s' not in dis,'forbidden FMA')
    data={name:bytearray((image/r['file']).read_bytes()) for name,r in meta['regions'].items()}
    seen={name:bytearray(r['size']) for name,r in meta['regions'].items() if r['access']=='write'}
    coverage=bytearray(meta['n']*meta['k'])
    def locate(addr,size,access):
        for name,r in meta['regions'].items():
            if r['address']<=addr and addr+size<=r['address']+r['size']:
                require(r['access']==access,'wrong access direction '+name)
                return name,addr-r['address']
        raise ValueError(f'out-of-contract external access {addr:08x}+{size}')
    ar,aw,w=deque(),deque(),deque();count=Counter();sizes=Counter();traffic=Counter();latency=Counter()
    max_out=Counter(); previous=-1; read_bytes=write_bytes=0
    with (case/'external.csv').open() as f:
        for raw in csv.DictReader(f):
            cycle=int(raw['cycle']);ch=raw['ch'];r={k:int(v,16) for k,v in raw.items() if k not in ('cycle','ch')}
            require(previous<=cycle and metrics['start_cycle']<=cycle<=metrics['halt_cycle'],'event timestamp')
            previous=cycle;count[ch]+=1
            if ch in ('AR','AW'):
                require(r['id']==0 and r['len']==0 and r['burst']==1 and r['size']<=4,'unexpected AXI request')
                size=1<<r['size']; require(r['addr']%size==0,'unaligned probe request')
                name,off=locate(r['addr'],size,'read' if ch=='AR' else 'write')
                r.update(size_bytes=size,name=name,off=off,cycle=cycle)
                (ar if ch=='AR' else aw).append(r);sizes[f'{ch}:{size}']+=1
            elif ch=='R':
                require(bool(ar),'response without read');t=ar.popleft()
                require(r['id']==t['id'] and r['resp']==0 and r['last']==1,'R ID/response/last mismatch')
                expected=int.from_bytes(data[t['name']][t['off']:t['off']+t['size_bytes']],'little') << (8*(t['addr']%16))
                require(r['data']==expected,'external read data mismatch')
                read_bytes+=t['size_bytes'];traffic['read:'+t['name']]+=t['size_bytes'];latency[str(cycle-t['cycle'])]+=1
                if t['name']=='weights':
                    end=min(len(coverage),t['off']+t['size_bytes']);coverage[t['off']:end]=b'\1'*(end-t['off'])
            elif ch=='W': w.append(r)
            elif ch=='B':
                require(bool(aw) and bool(w),'B before AW/W');t=aw.popleft();v=w.popleft()
                require(r['id']==t['id'] and r['resp']==0 and v['last']==1,'B ID/response/WLAST mismatch')
                mask=((1<<t['size_bytes'])-1) << (t['addr']%16)
                require(v['strb']==mask,'write strobe mismatch')
                value=(v['data']>>(8*(t['addr']%16))).to_bytes(16,'little')[:t['size_bytes']]
                name,off=t['name'],t['off'];require(not any(seen[name][off:off+len(value)]),'duplicate output write')
                data[name][off:off+len(value)]=value;seen[name][off:off+len(value)]=b'\1'*len(value)
                write_bytes+=len(value);traffic['write:'+name]+=len(value)
            else: raise ValueError('unknown event channel')
            max_out['read']=max(max_out['read'],len(ar));max_out['write']=max(max_out['write'],len(aw))
    require(not ar and not aw and not w,'missing completion / truncated trace')
    require(all(coverage),'weights not streamed in full')
    require(all(metrics[ch.lower()]==count[ch] for ch in ('AR','R','AW','W','B')),'counter / trace mismatch')
    require(metrics['read_bytes']==read_bytes and metrics['write_bytes']==write_bytes,'byte counter mismatch')
    dtcm=b''.join(int(line,16).to_bytes(16,'little') for line in (case/'dtcm.hex').read_text().splitlines())
    require(len(dtcm)==32768,'truncated DTCM')
    def word(name): return struct.unpack_from('<I',dtcm,meta['symbols'][name]['address']-0x10000)[0]
    require(word('done')==0x743037aa,'firmware completion marker')
    kernel_cycles=(word('end_cycle')-word('begin_cycle'))&0xffffffff
    require(0<kernel_cycles<=metrics['cycles'],'firmware cycle counter')
    # Verify inputs stayed intact and independently check slave upload/readback.
    tcm=b''.join(int(line,16).to_bytes(16,'little') for line in (image/'load.hex').read_text().splitlines())
    for name in ('config','activations','activation_scales'):
        s=meta['symbols'][name];a=s['address']-0x10000
        require(dtcm[a:a+s['size']]==tcm[8192+a:8192+a+s['size']],'TCM input changed '+name)
    slave_ar=deque();slave_aw=deque();slave_w=deque();slave_counts=Counter();upload=[];readback=[];result=[]
    for raw in csv.DictReader((case/'bus.csv').open()):
        phase=int(raw['phase']);r={k:(None if any(c in v.lower() for c in 'xz') else int(v,16)) for k,v in raw.items() if k not in ('cycle','phase')}
        require(all(r[ch+s] in (0,1) for ch in ('aw','w','b','ar','r') for s in ('valid','ready')),'unknown slave handshake')
        if r['awvalid'] and r['awready']:slave_aw.append(r['awaddr'])
        if r['wvalid'] and r['wready']:slave_w.append((r['wdata'],r['wstrb']))
        if r['bvalid'] and r['bready']:
            require(slave_aw and slave_w and r['bidresp']==12,'slave B mismatch')
            addr=slave_aw.popleft();val,strb=slave_w.popleft()
            if phase==1 and addr!=0x30004: upload.append((addr,val,strb))
        if r['arvalid'] and r['arready']:slave_ar.append(r['araddr'])
        if r['rvalid'] and r['rready']:
            require(slave_ar and r['ridresp']==20 and r['rlast']==1,'slave R mismatch');addr=slave_ar.popleft()
            if phase==1 and addr!=0x30004:readback.append((addr,r['rdata']))
            if phase==3 and addr!=0x30008:result.append((addr,r['rdata']))
    expected=[(i*16 if i<512 else 0x10000+(i-512)*16,int.from_bytes(tcm[i*16:i*16+16],'little')) for i in range(2560)]
    require(upload==[(a,d,65535) for a,d in expected] and readback==expected,'TCM upload/readback trace')
    require(result==[(0x10000+i*16,int.from_bytes(dtcm[i*16:i*16+16],'little')) for i in range(2048)],'DTCM dump / trace')
    require(not slave_ar and not slave_aw and not slave_w,'slave not drained')
    numerical={}
    for name,enabled in (('dots',meta['audit']),('output',meta['restore'])):
        require(all(seen[name]) if enabled else not any(seen[name]),'missing or unexpected writes '+name)
        if not enabled: continue
        reference=np.load(image/('expected-dots.npy' if name=='dots' else 'expected-y.npy'),allow_pickle=False)
        actual=np.frombuffer(data[name],dtype='<i4' if name=='dots' else '<f4').reshape(reference.shape)
        if name=='dots':require(np.array_equal(actual,reference),'integer dot mismatch');numerical['integer_mismatches']=0
        else:
            tol=json.loads((ROOT/'configs/t05-thresholds.json').read_text())['operators']['linear']
            err=actual.astype(np.float64)-reference;rmse=float(np.sqrt(np.mean(err**2)));nr=rmse/max(float(np.sqrt(np.mean(reference.astype(np.float64)**2))),1e-12)
            require(np.isfinite(actual).all() and np.all(np.abs(err)<=tol['atol']+tol['rtol']*np.abs(reference)) and nr<=tol['nrmse'],'FP32 tolerance failure')
            numerical.update(max_abs=float(np.max(np.abs(err))),nrmse=nr,fp32_bitwise_equal=actual.tobytes()==reference.tobytes())
    out=dict(status='PASS',shape_MKN=[meta['m'],meta['k'],meta['n']],row_offset=meta['row_offset'],family=meta['family'],
        audit=meta['audit'],restore=meta['restore'],numerical=numerical,metrics=metrics,kernel_cycles=kernel_cycles,
        channel_counts=dict(count),transfer_sizes=dict(sizes),traffic_bytes=dict(traffic),read_latency_cycles=dict(latency),
        max_outstanding=dict(max_out),unique_weight_bytes=sum(coverage),macs=meta['m']*meta['k']*meta['n'],
        result_sha256=hashlib.sha256(data['output']+data['dots']).hexdigest(),trace_sha256=sha(case/'external.csv'))
    report.write_text(json.dumps(out,indent=2)+'\n');return out

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('case',type=Path);p.add_argument('image',type=Path);p.add_argument('disassembly',type=Path);a=p.parse_args()
    try:r=check(a.case,a.image,a.disassembly);print(json.dumps({k:r[k] for k in ('status','shape_MKN','kernel_cycles','numerical')}))
    except (ValueError,KeyError,OSError,AssertionError) as e:p.exit(1,f'T07_CHECK_REJECT: {e}\n')
