"""Independent checks of real CPU MMIO, including quantization of actual values."""
import json
from pathlib import Path
import numpy as np
from tests.runtime.check import records
from model_tools.numeric_v1 import quantize
from tests.vectors.check_v1 import metric
from scripts.evidence import sha256
ROOT=Path(__file__).resolve().parents[2]

def score(path,golden,checks):
    obs=records(path);used=set();metrics={};n=golden['shape'][0]
    def get(g,i):
        checks.require((g,i) in obs,'output_set',f'{g}/{i}');used.add((g,i));return obs[g,i]
    def equal(g,i,x,cat):checks.equal(get(g,i),int(x)&0xffffffff,cat,f'{g}/{i}')
    only=golden['only_mode'];modes=[only] if only is not None else list(range(5))
    expected=np.asarray(golden['expected_bits'],dtype='u4').view('f4')
    lim=json.loads((ROOT/'configs/t05-thresholds.json').read_text())['operators']['swiglu']
    for mode in modes:
        base=100+mode*10
        equal(base+4,0,0,'numeric');equal(base+4,1,0,'quantization')
        y=np.asarray([get(base,i) for i in range(n)],dtype='u4').view('f4')
        checks.require(np.isfinite(y).all(),'numeric','finite outputs')
        m=metric(y,expected,lim);checks.require(m['elementwise_violations']==0,'numeric',m)
        q,s=quantize(y[None,:])
        for i,x in enumerate(q[0]):equal(base+1,i,x,'integer')
        for i,x in enumerate(s[0].view('u4')):equal(base+2,i,x,'scale')
        ticks=get(base+3,0)|(get(base+3,1)<<32)
        checks.require(ticks>0,'timing','actual complete kernel mcycle')
        metrics[str(mode)]=dict(cycles=ticks,**m,output_sha256=__import__('hashlib').sha256(y.tobytes()).hexdigest())
    if only is None:
        for i in range(n):
            checks.equal(get(130,i),get(100,i),'exact_candidate','guarded equals original RV32 bits')
            checks.equal(get(140,i),get(100,i),'fallback','forced original path')
        for mode in range(4):
            calls=[]
            for i in range(24):
                equal(500+mode,48+i,0,'call_overhead');t=get(500+mode,2*i)|(get(500+mode,2*i+1)<<32)
                checks.require(t>0,'timing','24 representative single-element calls');calls.append(t)
            metrics[str(mode)]['call24_single_element_cycles']=calls
            for i in range(6):equal(600+mode,2*i,-2,'reject');equal(600+mode,2*i+1,1,'reject')
        metrics['micro_65']={name:get(400,k*2)|(get(400,k*2+1)<<32) for k,name in enumerate(('double_exp_and_conversions','expf','conversions','division','multiplications','finite_scan','load_store'))}
        for i in range(6):equal(700,i,-1,'reject')
    checks.equal(len(used),len(obs),'output_set','no extra/duplicate observations')
    return metrics
