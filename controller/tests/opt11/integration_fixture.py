"""Independent complete-input SFU/quant/down fixtures for the native SoC."""
import json
from pathlib import Path
import numpy as np
from scripts.evidence import sha256,write_json
from tests.opt11.fixture import independent
from model_tools.numeric_v1 import quantize,linear_quantized
ROOT=Path(__file__).resolve().parents[2]

def generate(folder,long=False):
    folder=Path(folder);folder.mkdir(parents=True);rng=np.random.default_rng(20261019)
    regions=[];jobs=[]
    def blob(name,a,x):
        p=folder/(name+'.bin');p.write_bytes(x.tobytes());regions.append(dict(name=name,address=a,bytes=p.stat().st_size,path=str(p),sha256=sha256(p),kind='input'))
    model=np.load(ROOT/'evidence/OPT07_BATCH/opt07-batch24-20261019-v2/original-inputs.npz')
    gkey=next(k for k in model.files if 'gate' in k);g=model[gkey].reshape(-1).astype('f4');u=model[gkey.replace('gate','up')].reshape(-1).astype('f4')
    # The producer archive contains all layers. Select its first real width.
    if len(g)>4864:g=g[:4864];u=u[:4864]
    cases=[('zero',np.zeros(64,'f4'),np.ones(64,'f4'),0,0,True),
      ('tail65',rng.normal(size=65).astype('f4'),rng.normal(size=65).astype('f4'),0,0,True),
      ('half',np.asarray([127,-127,.5,1.5,2.5,-.5,-1.5,-2.5]+[0]*56,'f4'),np.ones(64,'f4'),1,0,True),
      ('tiny',np.arange(1,65,dtype='u4').view('f4'),np.ones(64,'f4'),1,0,True),
      ('down896',g[:896],u[:896],0,0,False)]
    if long:cases += [('reference4864',g,u,2,0,True),('diagnostic4864',g,u,0,0,True),('fused4864',g,u,0,0,False)]
    for mode in (3,4,5,9,10):cases.append(('fault'+str(mode),g[:64],u[:64],0,mode,False))
    for value,label in [(np.nan,'nan'),(np.inf,'inf'),(-np.inf,'neginf')]:
        bg=g[:64].copy();bg[63]=value;cases.append((label,bg,u[:64],0,0,True))
    bad_up=u[:64].copy();bad_up[63]=np.nan;cases.append(('nan-up',g[:64],bad_up,0,0,True))
    cases.append(('recovered',g[:896],u[:896],0,0,False))
    rows=[]
    for i,(name,gate,up,mode,fault,diag) in enumerate(cases):
        k=len(gate);base=0xac100000+i*0x40000
        addresses=dict(gate=base+0xff0,up=base+0x10ff0,aq=base+0x20000,sa=base+0x22000,fp32=base+0x24000 if diag else 0)
        blob(name+'-gate',addresses['gate'],gate);blob(name+'-up',addresses['up'],up)
        with np.errstate(all='ignore'):y=gate if mode==1 else independent(gate,up)
        status=-9 if not np.isfinite(y).all() else (-7 if fault in (5,10) else -8 if fault==9 else -11 if fault else 0)
        aq=np.zeros(((k+63)//64)*64,dtype='i1');sa=np.zeros((k+63)//64,dtype='f4')
        if status==0:
            tq,ts=quantize(y[None,:]);aq[:k]=tq[0];sa[:]=ts[0]
        expected=folder/(name+'.npz');np.savez(expected,fp=y,aq=aq,sa=sa)
        down=k in (896,4864) and not diag and not status
        wa,sw_a,bias_a=0x88000000+i*0x10000,0x89000000+i*0x10000,0x8a000000+i*0x1000
        ya=base+0x28000
        if down:
            w=rng.integers(-127,128,(4,k),dtype='i1');sw=rng.uniform(.0001,.01,(4,k//64)).astype('f4');bias=rng.normal(size=4).astype('f4')
            blob(name+'-w',wa,w);blob(name+'-sw',sw_a,sw);blob(name+'-bias',bias_a,bias)
            dy,dots=linear_quantized(aq[:k][None,:],sa[None,:],w,sw,bias);np.savez(expected,fp=y,aq=aq,sa=sa,down=dy,dots=dots)
        job=dict(name=name,k=k,mode=mode,fault=fault,status=status,down=down,**addresses,y=ya,w=wa,sw=sw_a,bias=bias_a,expected=str(expected),expected_sha256=sha256(expected))
        jobs.append(job)
        fields=','.join(f'0x{addresses[n]:08x}u' for n in ('gate','up','aq','sa','fp32'))+f',{k}u,{1 if mode==1 else 0}u'
        rows.append('{{'+fields+'},'+','.join(str(v)+'u' for v in (mode,fault,int(down),wa,sw_a,bias_a,ya))+'}')
    (folder/'jobs.h').write_text('#include "opt11.h"\n#define JOB_COUNT '+str(len(jobs))+'\nstruct test_job{nx_opt11_job job;uint32_t mode,fault,down,w,sw,bias,y;};\nstatic const struct test_job jobs[]={\n'+',\n'.join(rows)+'\n};\n')
    fixture=dict(schema_version=1,group_size=64,seed=20261019,regions=regions,jobs=jobs,long=long)
    write_json(folder/'fixture.json',fixture);return fixture
