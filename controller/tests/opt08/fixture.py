"""Freeze raw inputs and NumPy T05 golden before compiling or running RTL."""
import json,sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from evidence import sha256,write_json
from model_tools.numeric_v1 import quantize,linear_quantized
def generate(folder):
    folder=Path(folder);folder.mkdir(parents=True)
    rng=np.random.default_rng(20261019);regions=[];cases=[]
    def blob(name,address,array,kind):
        p=folder/(name+'.bin');p.write_bytes(array.tobytes());regions.append(dict(name=name,address=address,bytes=p.stat().st_size,path=str(p),sha256=sha256(p),kind=kind));return address
    matrices={}
    for k in (896,4864):
        q=rng.integers(-127,128,size=(4,k),dtype='i1');sw=rng.uniform(.001,.02,size=(4,k//64)).astype('f4');bias=rng.normal(size=4).astype('f4')
        base=0x88000000 if k==896 else 0x88100000
        matrices[k]=(q,sw,bias)
        blob('w'+str(k),base,q,'immutable_model');blob('sw'+str(k),base+0x10000,sw,'immutable_model');blob('bias'+str(k),base+0x11000,bias,'immutable_model')
    x=rng.normal(size=(4,4864)).astype('f4');x[0,:64]=np.arange(64,dtype='f4')-31.5;x[1,:64]=0
    source=blob('x',0xb4100000,x,'cpu_private_input')
    # id, rows, K, version, direct, source offset, sign, injected error, reset before
    specs=[(1,1,896,0,0,0,1,0,0),(2,1,896,0,0,0,1,0,0),(3,1,896,0,0,0,1,0,0),
           (4,1,896,1,0,0,1,0,0),(5,1,896,1,0,0,1,0,0),(6,1,896,1,0,0,1,0,0),
           (7,1,896,2,0,0,-1,0,0),(8,4,896,3,0,0,1,0,0),(9,4,896,3,0,0,1,0,0),
           (10,1,896,4,1,0,1,0,0),(11,1,896,4,1,0,1,0,0),(12,1,896,5,0,1,1,0,0),
           (13,1,4864,6,0,0,1,0,0),(14,1,4864,6,0,0,1,0,0),(15,1,896,7,0,0,1,3,0),
           (16,1,896,7,0,0,1,0,0),(17,1,896,7,0,0,1,0,1),(18,1,896,7,0,0,1,0,2),
           (19,4,896,7,0,0,1,0,0),(20,1,4864,7,0,0,1,0,0),(21,1,4864,7,1,0,1,0,0)]
    for ident,m,k,version,direct,offset,sign,error,reset in specs:
        # Each CPU fill takes a contiguous view of the same immutable raw input.
        values=(x.ravel()[offset:offset+m*k]*np.float32(sign)).reshape(m,k)
        aq,sa=quantize(values);q,sw,bias=matrices[k];y,_=linear_quantized(aq,sa,q,sw,bias)
        p=folder/f'case{ident}.npz';np.savez(p,x=values,aq=aq,sa=sa,y=y)
        cases.append(dict(id=ident,m=m,k=k,version=version,direct=direct,offset=offset,sign=sign,error=error,reset=reset,expected_path=str(p),expected_sha256=sha256(p),status=-4 if error else 0))
    lines=['struct opt08_case {unsigned id,m,k,version,direct,offset;int sign;unsigned error,reset;};','static const struct opt08_case cases[]={']
    lines += ['{'+','.join(map(str,row))+'},' for row in specs];lines+=['};']
    (folder/'inputs.h').write_text('\n'.join(lines)+'\n')
    fixture=dict(profile='opt08',regions=regions,guards=[],numeric_version='w8a8-g64-fp32-v1',seed=20261019,group_size=64,layout_id=1,endianness='little',max_cycles=100000000,wall_timeout_seconds=7200)
    golden=dict(cases=cases,thresholds_sha256=sha256(ROOT/'configs/t05-thresholds.json'),producer='independent model_tools.numeric_v1 from frozen x/Wq/Sw/bias',generator_sha256=sha256(__file__))
    write_json(folder/'fixture.json',fixture);write_json(folder/'golden.json',golden);return fixture,golden
