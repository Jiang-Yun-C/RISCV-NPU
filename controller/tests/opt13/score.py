"""Compare actual CPU reports to frozen per-token NumPy golden."""
import struct
from pathlib import Path
import numpy as np

def score(path,g,c):
    r={}
    for line in Path(path).read_text().splitlines():
        a,b,v=map(int,line.split());c.require((a,b) not in r,'output_set','unique report');r[a,b]=v
    controls={i:v for (group,i),v in r.items() if group==200}
    c.equal(set(controls),set(range(r[300,0])),'output_set','complete contract checks')
    for i,v in controls.items():c.equal(v,1,'contract',f'production contract {i}')
    c.require(len(controls)>150,'contract','nonzero required matrix')
    metrics=[];expected={(200,i) for i in controls}|{(300,i) for i in range(4)}
    for case in g['cases']:
        idx=case['index'];group=1000+10*idx;n=case['n']+1
        for offset,values in [(0,case['logits'])]+[(1+l*2+v,np.array(case['kv'],'f4').reshape(2,2,n,4)[l,v].reshape(-1)) for l in range(2) for v in range(2)]:
            actual_values=[]
            for j,x in enumerate(values):
                expected.add((group+offset,j));a=struct.unpack('<f',struct.pack('<I',r[group+offset,j]))[0]
                actual_values.append(a)
                c.require(np.isfinite(a) and abs(a-float(x))<=g['atol']+g['rtol']*abs(float(x)),'numeric',dict(case=idx,field=offset,index=j,actual=a,expected=float(x)))
            av=np.array(actual_values,'f8');ev=np.array(values,'f8');nrmse=float(np.sqrt(np.mean((av-ev)**2))/max(np.sqrt(np.mean(ev**2)),1e-12));c.require(nrmse<=1e-4,'numeric','frozen cumulative NRMSE')
        for j,id in enumerate(case['output']):expected.add((group+5,j));c.equal(r[group+5,j],id,'token','greedy same IDs')
        def ticks(i):return r[group+6,i]+(r[group+6,i+1]<<32)
        for j in range(8):expected.add((group+6,j))
        c.require(ticks(0)>0 and ticks(2)>0 and ticks(4)>0 and ticks(6)>=ticks(0)+ticks(2),'timing','inclusive phases/TTFT')
        metrics.append(dict(index=idx,rows=case['rows'],prompt=case['n'],prefix=case['prefix'],prefill_cycles=ticks(0),decode_cycles=ticks(2),ttft_cycles=ticks(4),total_cycles=ticks(6)))
    c.equal(set(r),expected,'output_set','exact all reports; no traps')
    return dict(cases=metrics,memory=dict(state=r[300,1],kv=r[300,2],work=r[300,3]),contract_checks=len(controls))
