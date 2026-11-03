"""Frozen full-K, reduced-N fixtures; independent T05 integer/FP32 golden."""
from pathlib import Path
import numpy as np
from scripts.evidence import sha256, write_json
from model_tools.numeric_v1 import quantize, linear_quantized
from tests.soc_accel.prepare import tensor, c_tensor
ROOT=Path(__file__).resolve().parents[2]

def generate(folder, smoke=False):
    folder=Path(folder);folder.mkdir(parents=True)
    rng=np.random.default_rng(20261019);regions=[];jobs=[];matrices={}
    def blob(name,address,array,kind):
        p=folder/(name+'.bin');p.write_bytes(array.tobytes())
        regions.append(dict(name=name,address=address,bytes=p.stat().st_size,path=str(p),sha256=sha256(p),kind=kind))
    for k in (896,4864):
        base=0x88000000 if k==896 else 0x88200000
        w=rng.integers(-127,128,(129,k),dtype='i1')
        sw=rng.uniform(.001,.02,(129,k//64)).astype('<f4');bias=rng.normal(size=129).astype('<f4')
        wa,sca,ba=base+0xfc0,base+0xc0ff0,base+0xe0000
        matrices[k]=w,sw,bias,wa,sca,ba
        blob('w'+str(k),wa,w,'immutable_model');blob('sw'+str(k),sca,sw,'immutable_model');blob('bias'+str(k),ba,bias,'immutable_model')
    specs=[(op,1,4,4864 if op=='down' else 896,0,0) for op in ('q','k','v','o','gate','up','down','head')]
    specs += [('tail1',1,5,896,0,0),('tail2',1,6,896,0,0),('tail3',1,7,896,0,0),
              ('n129',1,129,896,0,0),('m4',4,7,896,0,0),('m4-down',4,5,4864,0,0),
              ('shared-ddr-m1',1,7,896,0,1),('shared-ddr-m4',4,7,896,0,1)]
    for mode in (3,4,5,9):
        specs += [('fault'+str(mode),1,5 if mode==5 else 129 if mode==9 else 4,896,mode,0),
                  ('recovery'+str(mode),1,4,896,0,0)]
    if smoke:specs=[specs[0],specs[12],specs[16],specs[17]]
    for i,(name,m,n,k,mode,pressure) in enumerate(specs):
        w,sw,bias,wa,sca,ba=matrices[k]
        x=rng.normal(size=(m,k)).astype('<f4');x[0,:64]=np.arange(64,dtype='<f4')-31.5
        if m==4:x[1,:64]=0
        aq,sa=quantize(x);y,trace=linear_quantized(aq,sa,w[:n],sw[:n],bias[:n])
        source=0xb4300000+i*0x20000;blob(name+'-x',source,x,'cpu_private_input')
        job=dict(a=tensor(0xac010000,x.nbytes,2,[m,k]),wq=tensor(wa,n*k,1,[n,k]),
                 sw=tensor(sca,n*(k//64)*4,2,[n,k//64]),bias=tensor(ba,n*4,2,[n]),
                 y=tensor(0xac100000,m*n*4,2,[m,n]),group_size=64)
        p=folder/(name+'.npz');np.savez(p,aq=aq,sa=sa,y=y)
        jobs.append(dict(name=name,job=job,input_source=source,mode=mode,pressure=pressure,
                         status=-11 if mode in (3,4) else -7 if mode==5 else -8 if mode==9 else 0,
                         timeout=1400000 if mode==5 else 20000000,
                         expected_path=str(p),expected_sha256=sha256(p),
                         scope='complete K, reduced N representative; no full-model latency claim'))
    guards=[0xac0ffff0,0xac100810]
    for i,a in enumerate(guards):blob('guard'+str(i),a,np.full(16,165,dtype='u1'),'guard')
    header='#include "linear_api.h"\nstruct fixture_job { nx_linear job; uint32_t input_source,mode,pressure; uint64_t timeout; };\n#define FIXTURE_JOBS %d\nstatic const struct fixture_job fixture_jobs[]={\n'%len(jobs)
    for f in jobs:
        header+='{.job={'+','.join('.%s=%s'%(k,c_tensor(f['job'][k])) for k in ('a','wq','sw','bias','y'))+',.group_size=64},.input_source=%du,.mode=%du,.pressure=%du,.timeout=%du},\n'%(f['input_source'],f['mode'],f['pressure'],f['timeout'])
    (folder/'fixture_jobs.h').write_text(header+'};\n')
    fixture=dict(profile='control',regions=regions,guards=guards,group_size=64,layout_id=1,endianness='little',numeric_version='w8a8-g64-fp32-v1',seed=20261019)
    golden=dict(jobs=jobs,thresholds_sha256=sha256(ROOT/'configs/t05-thresholds.json'),generator_sha256=sha256(__file__),producer='independent numeric_v1, pre-execution inputs')
    write_json(folder/'fixture.json',fixture);write_json(folder/'golden.json',golden)
    return fixture,golden
