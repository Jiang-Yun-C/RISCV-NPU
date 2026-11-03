"""Actual T05 block operands plus frozen adversarial production block commands."""
import json
from pathlib import Path
import numpy as np
from scripts.evidence import sha256,write_json
from tests.opt12.fixture import result,tree,quantize
from model_tools.numeric_v1 import linear_quantized
ROOT=Path(__file__).resolve().parents[2]

def generate(folder,long=False):
    folder=Path(folder);folder.mkdir(parents=True);rng=np.random.default_rng(20261019)
    block_path=ROOT/'evidence/T05/20261003T123546.536147Z-cfa58369/artifacts/vectors/block-m1.npz'
    block=np.load(block_path);regions=[];jobs=[];cases=[]
    def add(name,g,u,mode,hardware=1,quant=0,alias=0,fault=0,diag=True,down=False):
        cases.append(dict(name=name,g=np.asarray(g,dtype='f4'),u=None if u is None else np.asarray(u,dtype='f4'),mode=mode,hardware=hardware,quant=quant,alias=alias,fault=fault,diag=diag,down=down))
    g=block['input'].reshape(-1);u=block['o'].reshape(-1)
    add('residual896',g,u,2)
    add('quantize65',g[:65],None,1)
    add('swiglu65',g[:65],u[:65],0,diag=True)
    add('t05-input-norm',g,np.load(block_path.parent/'input_layernorm.weight.npy'),7,quant=1)
    add('t05-post-norm',block['res1'].reshape(-1),np.load(block_path.parent/'post_attention_layernorm.weight.npy'),7)
    for mode in (3,4,5,6):add('mode'+str(mode)+'-tail65',g[:65],u[:65] if mode==3 else None,mode)
    for n in (1,3,63,64,65,128,256,896):
        x=rng.normal(size=n).astype('f4');gamma=rng.uniform(.5,1.5,n).astype('f4')
        add('rms'+str(n),x,gamma,7,quant=int(n in (65,896)),down=n==896)
    for mode in (2,4,7):
        add('alias-g-'+str(mode),g[:65],u[:65] if mode==2 else np.ones(65,dtype='f4') if mode==7 else None,mode,alias=1)
    add('alias-u-rms',g[:65],np.ones(65,dtype='f4'),7,alias=2)
    add('zeros-rms',np.zeros(65,dtype='f4'),np.ones(65,dtype='f4'),7,quant=1)
    for mode in (2,5,6,7):
        bad=g[:64].copy();bad[-1]=np.nan;add('nan-'+str(mode),bad,u[:64] if mode in (2,7) else None,mode)
    add('nan-gamma',g[:64],np.full(64,np.inf,dtype='f4'),7)
    add('overflow-rms',np.full(64,np.finfo('f4').max,dtype='f4'),np.ones(64,dtype='f4'),7)
    for fault in (3,4,5,9,10):add('fault'+str(fault),g[:65],u[:65],2,quant=1,fault=fault)
    add('recovered',g[:65],np.ones(65,dtype='f4'),7)
    if long:
        for mode in (2,4,5,6,7):
            for hw in (0,1):add(('cpu' if not hw else 'hw')+str(mode)+'-896',g,u if mode==2 else np.ones(896,dtype='f4') if mode==7 else None,mode,hardware=hw)
        add('cpu-rms-q896',g,np.ones(896,dtype='f4'),7,hardware=0,quant=1)
        add('hw-rms-q896',g,np.ones(896,dtype='f4'),7,quant=1,diag=False,down=True)
        ffn=block['gate'].reshape(-1);up=block['up'].reshape(-1)
        for mode in (2,3,4,5,6,7):add('full4864-'+str(mode),ffn,up if mode in (2,3) else np.ones(4864,dtype='f4') if mode==7 else None,mode,quant=mode==7,diag=mode!=7,down=mode==7)
        add('swiglu4864',ffn,up,0,quant=0,diag=False,down=True)
        # Genuine half-integer boundaries after the independently rounded residual.
        boundary=np.resize(np.asarray([127,-127,.5,1.5,2.5,-.5,-1.5,-2.5],dtype='f4'),896)
        add('half-residual',boundary,np.zeros(896,dtype='f4'),2,quant=1)
    def blob(name,a,x):
        p=folder/(name+'.bin');p.write_bytes(x.tobytes());regions.append(dict(name=name,address=a,bytes=p.stat().st_size,path=str(p),sha256=sha256(p),kind='input'))
    rows=[]
    for i,j in enumerate(cases):
        g=j.pop('g');u=j.pop('u');n=len(g);mode=j['mode'];base=0xac100000+i*0x40000;quant=mode<2 or j['quant']
        addresses=dict(gate=base+0xff0,up=base+0x10ff0 if u is not None else 0,aq=base+0x20000 if quant else 0,sa=base+0x22000 if quant else 0,fp32=base+0x24000 if j['diag'] else 0)
        if j['alias']:addresses['fp32']=addresses['gate' if j['alias']==1 else 'up']
        blob(j['name']+'-gate',addresses['gate'],g)
        if u is not None:blob(j['name']+'-up',addresses['up'],u)
        factor=np.float32(1.25) if mode==4 else np.float32(0)
        with np.errstate(all='ignore'):
            if mode==7:
                s=tree(g*g);inv=np.float32(1)/np.sqrt(np.float32(s/np.float32(n))+np.float32(1e-6));y=(g*inv)*u
                invalid=not np.isfinite(s) or not np.isfinite(inv)
            else:y=result(g,u,mode,factor);invalid=False
        status=-9 if invalid or not np.isfinite(g).all() or u is not None and not np.isfinite(u).all() or not np.isfinite(y).all() else (-7 if j['fault'] in (5,10) else -8 if j['fault']==9 else -11 if j['fault'] else 0)
        aq=np.zeros(((n+63)//64)*64,dtype='i1');sa=np.zeros((n+63)//64,dtype='f4')
        if not status and quant:
            for off in range(0,n,64):aq[off:off+64],sa[off//64]=quantize(y[off:off+64])
        expected=folder/(j['name']+'.npz');values=dict(fp=y,aq=aq if quant else np.empty(0,dtype='i1'),sa=sa if quant else np.empty(0,dtype='f4'))
        wa,swa,ba=0x88000000+i*0x10000,0x89000000+i*0x10000,0x8a000000+i*0x1000;ya=base+0x28000
        if j['down']:
            w=rng.integers(-127,128,(4,n),dtype='i1');sw=rng.uniform(.0001,.01,(4,n//64)).astype('f4');bias=rng.normal(size=4).astype('f4')
            blob(j['name']+'-w',wa,w);blob(j['name']+'-sw',swa,sw);blob(j['name']+'-bias',ba,bias)
            dy,dots=linear_quantized(aq[:n][None,:],sa[None,:],w,sw,bias);values.update(down=dy,dots=dots)
        np.savez(expected,**values)
        j.update(k=n,scalar=int(np.asarray(factor).view('u4')),status=status,**addresses,y=ya,w=wa,sw=swa,bias=ba,expected=str(expected),expected_sha256=sha256(expected))
        jobs.append(j)
        fields=','.join(f'0x{j[key]:08x}u' for key in ('gate','up','aq','sa','fp32','k','mode','quant','scalar'))
        rows.append('{{'+fields+'},'+','.join(str(int(j[key]))+'u' for key in ('hardware','fault','down','w','sw','bias','y'))+'}')
    (folder/'jobs.h').write_text('#define OPT12_LONG '+str(int(long))+'\n#include "opt12.h"\n#define JOB_COUNT '+str(len(jobs))+'\nstruct test_job{nx_opt12_job job;uint32_t hardware,fault,down,w,sw,bias,y;};\nstatic const struct test_job jobs[]={\n'+',\n'.join(rows)+'\n};\n')
    attention=[]
    if long:
        q=rng.normal(0,.1,(14,64)).astype('f4');k=rng.normal(0,.1,(256,2,64)).astype('f4');v=rng.normal(0,.1,(256,2,64)).astype('f4')
        for label,addr,x in [('attn-q',0xaf000000,q),('attn-k',0xaf010000,k),('attn-v',0xaf040000,v)]:blob(label,addr,x)
        for length in (128,256):
            y=np.empty((14,64),dtype='f4')
            for h in range(14):
                scores=np.asarray([tree(q[h]*k[t,h//7])*np.float32(.125) for t in range(length)],dtype='f4')
                probs=np.exp((scores-scores.max()).astype('f8')).astype('f4');probs=probs/tree(probs)
                for col in range(64):y[h,col]=tree(probs*v[:length,h//7,col])
            ep=folder/f'attention-{length}.npy';np.save(ep,y)
            attention.append(dict(length=length,expected=str(ep),sha256=sha256(ep)))
    fixture=dict(schema_version=1,seed=20261019,regions=regions,jobs=jobs,long=long,attention=attention,t05_input=str(block_path),t05_input_sha256=sha256(block_path))
    write_json(folder/'fixture.json',fixture);return fixture
