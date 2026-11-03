"""Independent FP32/T05 oracle. Inputs are frozen before any RTL execution."""
from pathlib import Path
import numpy as np
from tests.opt11.fixture import independent

def tree(x, maximum=False, full=False):
    x=np.asarray(x,dtype='f4').copy()
    size=64 if full else 1 << (len(x)-1).bit_length()
    x=np.pad(x,(0,size-len(x)),constant_values=-np.inf if maximum else 0)
    while len(x)>1:x=np.maximum(x[::2],x[1::2]) if maximum else x[::2]+x[1::2]
    return x[0]

def quantize(x):
    # Independent of the production Python/C quantizer.
    a=np.max(np.abs(x));s=np.float32(0) if a==0 else max(np.float32(a/np.float32(127)),np.finfo('f4').tiny)
    q=np.zeros(64,dtype='i1')
    if s:q[:len(x)]=np.clip(np.rint(x/s),-127,127).astype('i1')
    return q,np.float32(s)

def result(g,u,mode,factor=1,full=False):
    if mode==0:return independent(g,u)
    if mode==1:return g.copy()
    if mode==2:return g+u
    if mode==3:return g*u
    if mode==4:return g*np.float32(factor)
    if mode==5:return np.asarray([tree(g,full=full)],dtype='f4')
    if mode==6:return np.asarray([tree(g,True,full)],dtype='f4')
    if mode==7:return np.asarray([tree(g*g,full=full)],dtype='f4')
    if mode==8:return (g*np.float32(factor))*u
    if mode==9:return np.asarray([np.float32(1)/np.sqrt(np.float32(g[0]/u[0])+np.float32(1e-6))],dtype='f4')
    raise ValueError(mode)

def generate(path,quick=False):
    rng=np.random.default_rng(20261019);rows=[]
    lengths=[1,2,3,17,31,32,33,63,64]
    for mode in range(10):
        for n in (lengths[:3]+[64] if quick else lengths):
            g=rng.normal(0,3,n).astype('f4');u=rng.normal(0,2,n).astype('f4')
            if mode==9:g=np.abs(g);u=np.full(n,896,dtype='f4')
            for q in ([0,1] if mode in (2,3,4,8) else [mode<2]):rows.append((g,u,mode,q,1.25,n%2==0))
    edge=np.asarray([0.,-0.,np.nextafter(np.float32(0),np.float32(1)),np.finfo('f4').tiny,
                     127,-127,.5,1.5,2.5,-.5,-1.5,-2.5],dtype='f4')
    for mode in range(9):
        rows.append((edge,np.ones(len(edge),dtype='f4'),mode,mode<5 or mode==8,1,False))
        rows.append((np.zeros(64,dtype='f4'),np.ones(64,dtype='f4'),mode,mode<5 or mode==8,1,False))
        for bad in (np.nan,np.inf,-np.inf):
            g=np.ones(64,dtype='f4');g[-1]=bad;rows.append((g,g.copy(),mode,mode<2,1,False))
    for mode in (2,3,4,5,7,8):rows.append((np.full(64,np.finfo('f4').max,dtype='f4'),np.full(64,2,dtype='f4'),mode,False,2,False))
    # Actual 24-layer OPT07 gate/up inputs also protect the adopted SwiGLU.
    if not quick:
        data=np.load(Path(__file__).resolve().parents[2]/'evidence/OPT07_BATCH/opt07-batch24-20261019-v2/original-inputs.npz')
        for key in data.files:
            if 'gate' in key:
                g=data[key].reshape(-1);u=data[key.replace('gate','up')].reshape(-1)
                for off in range(0,len(g),64):rows.append((g[off:off+64],u[off:off+64],0,True,1,False))
    out={k:[] for k in ('gate','up','fp','q','scale','length','mode','bad','quant','factor','full')}
    with np.errstate(all='ignore'):
        for g,u,mode,q,factor,full in rows:
            y=result(g,u,mode,factor,full)
            used_up=mode in (0,2,3,8,9)
            bad=not np.isfinite(g).all() or used_up and not np.isfinite(u).all() or not np.isfinite(y).all()
            fp=np.zeros(64,dtype='f4');fp[:len(y)]=y
            qp,sc=quantize(y) if q and not bad else (np.zeros(64,dtype='i1'),np.float32(0))
            gp=np.zeros(64,dtype='f4');up=gp.copy();gp[:len(g)]=g;up[:len(u)]=u
            values=dict(gate=gp.view('u4'),up=up.view('u4'),fp=fp.view('u4'),q=qp,scale=np.asarray(sc).view('u4'),
                        length=len(g),mode=mode,bad=int(bad),quant=int(q),factor=np.asarray(np.float32(factor)).view('u4'),full=int(full))
            for key,val in values.items():out[key].append(val)
        a=rng.integers(0,0x7f800000,256 if quick else 20000,dtype='u4')
        a=np.concatenate((a,np.asarray([0,0x80000000,1,0x007fffff,0x00800000,0x7f7fffff],dtype='u4')))
        out.update(unit_a=a,unit_sqrt=np.sqrt(a.view('f4')).view('u4'))
    np.savez(path,**{k:np.asarray(v) for k,v in out.items()})
