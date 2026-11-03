"""Frozen independent NumPy/T05 fixtures; never consumes a DUT output."""
from pathlib import Path
import numpy as np
def independent(g,u):
    e=np.exp(-np.abs(g).astype('f8')).astype('f4')
    sig=np.where(g>=0,np.float32(1)/(np.float32(1)+e),e/(np.float32(1)+e))
    return (g*sig)*u

def samples():
    rng=np.random.default_rng(20261019)
    edge=np.asarray([0.,-0.,np.nextafter(np.float32(0),np.float32(1)),np.finfo('f4').tiny,
        .0625,16.,-16.,80.,-80.,88.,-88.,100.,-100.,103.,-103.,104.,-104.,1e30,-1e30,
        np.finfo('f4').max,-np.finfo('f4').max],dtype='f4')
    yield 'edge',edge,np.ones_like(edge)
    for i in range(8):
        g=(rng.normal(0,5,4864) if i%2==0 else rng.uniform(-120,120,4864)).astype('f4')
        yield 'random'+str(i),g,rng.normal(0,3,4864).astype('f4')

from model_tools.numeric_v1 import quantize

def generate(path,quick=False):
    rng=np.random.default_rng(20261019);rows=[]
    for label,g,u in samples():
        if quick:g,u=g[:65],u[:65]
        for offset in range(0,len(g),64):rows.append((g[offset:offset+64],u[offset:offset+64],0))
    if not quick:
        data=np.load(Path(__file__).resolve().parents[2]/'evidence/OPT07_BATCH/opt07-batch24-20261019-v2/original-inputs.npz')
        for key in data.files:
            if 'gate' in key:
                g=data[key].reshape(-1);u=data[key.replace('gate','up')].reshape(-1)
                for offset in range(0,len(g),64):rows.append((g[offset:offset+64],u[offset:offset+64],0))
    # Exact half-integer quantization, min-normal clamp, signed zeros and max.
    for g in [np.zeros(64,dtype='f4'),np.arange(-31.5,32.5,dtype='f4'),
              np.asarray([127,-127,.5,1.5,2.5,-.5,-1.5,-2.5]+[0]*56,dtype='f4'),
              np.arange(1,65,dtype='u4').view('f4'),np.asarray([np.finfo('f4').max]*64,dtype='f4')]:
        rows.append((g,np.ones(len(g),dtype='f4'),1))
    for bad in [np.nan,np.inf,-np.inf]:
        g=np.ones(64,dtype='f4');g[63]=bad;rows.append((g,np.ones(64,dtype='f4'),0))
    bad_up=np.ones(64,dtype='f4');bad_up[63]=np.nan;rows.append((np.ones(64,dtype='f4'),bad_up,0))
    g=np.full(64,np.finfo('f4').max,dtype='f4');rows.append((g,np.full(64,2,dtype='f4'),0))
    out={k:[] for k in ('gate','up','fp','q','scale','length','mode','bad')}
    for g,u,mode in rows:
        n=len(g);gp=np.zeros(64,dtype='f4');up=gp.copy();gp[:n]=g;up[:n]=u
        with np.errstate(all='ignore'):y=gp.copy() if mode else independent(gp,up)
        bad=not np.isfinite(gp).all() or not np.isfinite(up).all() or not np.isfinite(y).all()
        if bad:q=np.zeros((1,64),dtype='i1');s=np.zeros((1,1),dtype='f4')
        else:q,s=quantize(y.reshape(1,64))
        for key,val in dict(gate=gp.view('u4'),up=up.view('u4'),fp=y.view('u4'),q=q[0],scale=s.view('u4')[0,0],length=n,mode=mode,bad=int(bad)).items():out[key].append(val)
    # Uniform bit patterns exercise all exponents without division overflow.
    count=128 if quick else 12000
    a=rng.integers(0,0x7f800000,count,dtype='u4');b=rng.integers(0x3f000000,0x40000000,count,dtype='u4')
    a=np.concatenate((a,np.asarray([0,0x80000000,1,0x80000001,0x007fffff,0x00800000,0x42cff1b4,0x42d00000,0x7f7fffff],dtype='u4')))
    b=np.resize(b,len(a))
    with np.errstate(all='ignore'):
        exp=np.exp(-np.abs(a.view('f4').astype('f8'))).astype('f4').view('u4')
        div=(a.view('f4')/b.view('f4')).view('u4')
    out.update(unit_a=a,unit_b=b,unit_exp=exp,unit_div=div)
    np.savez(path,**{k:np.asarray(v) for k,v in out.items()})
