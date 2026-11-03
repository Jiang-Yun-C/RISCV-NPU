"""Independent operator samples and original-reference comparisons for OPT07."""
import argparse
import ctypes as C
import json
from pathlib import Path
import sys
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from evidence import sha256,write_json
from software.reference.runtime import library,ptr
from model_tools import numeric_v1 as num
from tests.vectors.check_v1 import metric

def independent(g,u):
    e=np.exp(-np.abs(g).astype('f8')).astype('f4')
    sig=np.where(g>=0,np.float32(1)/(np.float32(1)+e),e/(np.float32(1)+e))
    return (g*sig)*u

def samples():
    rng=np.random.default_rng(20261019)
    tiny=np.nextafter(np.float32(0),np.float32(1))
    edge=np.array([0.,-0.,tiny,-tiny,np.finfo('f4').tiny,-np.finfo('f4').tiny,
                   0.0625,16.,16.000002,-16.,-16.000002,80.,-80.,88.,-88.,
                   100.,-100.,103.,-103.,104.,-104.,1e30,-1e30,
                   np.finfo('f4').max,-np.finfo('f4').max],np.float32)
    yield 'edge',edge,np.ones_like(edge)
    for i in range(8):
        g=rng.uniform(-120,120,4864).astype('f4') if i%2 else rng.normal(0,5,4864).astype('f4')
        u=rng.normal(0,3,4864).astype('f4')
        yield 'random'+str(i),g,u
    # A known group peak of 127, with values one FP32 ULP about half integers.
    values=np.arange(-126.5,127.,1,dtype='f4')
    values=np.concatenate([np.nextafter(values,-np.inf),values,np.nextafter(values,np.inf)])
    u=np.resize(values,4864).copy();u[::64]=127
    yield 'half-integers',np.full(4864,32.,np.float32),u/32
    root=ROOT/'models/reference-v1/acceptance-20261005-v3/primary'
    manifest=json.loads((root/'manifest.json').read_text())
    for case in manifest['cases']:
        if case['context']==1 and case['past']==0:
            p=root/case['path']
            if sha256(p)!=case['sha256']:raise ValueError('independent T11 fixture hash')
            with np.load(p) as data:
                for layer in (0,11,23):
                    yield 'T11-layer'+str(layer),data[f'layer{layer}.gate'][0].copy(),data[f'layer{layer}.up'][0].copy()

def evaluate(path,output):
    lib=library(path);lib.nx_opt07_configure.argtypes=[C.c_int,C.c_int]
    report={};limits=json.loads((ROOT/'configs/t05-thresholds.json').read_text())
    for mode in range(4):
        rows=[];passed=True
        for name,g,u in samples():
            y=np.empty_like(g);lib.nx_opt07_configure(mode,0)
            rc=lib.nx_swiglu(ptr(g),ptr(u),len(g),ptr(y))
            e=independent(g,u)
            try:
                if rc:raise ValueError('numeric status '+str(rc))
                m=metric(y,e,limits['operators']['swiglu'])
                # Quantizer is compared on identical actual activation input:
                # arithmetic is bit exact; approximation drift is separate.
                q=np.empty((1,len(y)),np.int8);s=np.empty((1,(len(y)+63)//64),np.float32)
                if lib.nx_quantize(ptr(y),1,len(y),ptr(q),ptr(s)):raise ValueError('quantize')
                eq,es=num.quantize(y[None,:])
                if not np.array_equal(q,eq) or not np.array_equal(s.view('u4'),es.view('u4')):raise ValueError('integer/scale contract')
                bq,bs=num.quantize(e[None,:])
                m.update(quantized_vs_baseline_mismatches=int(np.count_nonzero(q!=bq)),
                         scale_vs_baseline_bit_differences=int(np.count_nonzero(s.view('u4')!=bs.view('u4'))),
                         exact_integer_checks=q.size+s.size)
                rows.append(dict(case=name,status='PASS',**m))
            except (ValueError,AssertionError) as exc:
                passed=False;rows.append(dict(case=name,status='FAIL',reason=str(exc)))
        # Validation-before-write for nonfinite inputs and invalid arguments.
        boundary=[]
        for field in ('gate','up'):
            for v in (np.nan,np.inf,-np.inf):
                g=np.ones(65,np.float32);u=g.copy();y=np.full(65,123,np.float32)
                (g if field=='gate' else u)[64]=v
                ok=lib.nx_swiglu(ptr(g),ptr(u),65,ptr(y))==-2 and np.all(y==123)
                passed &= bool(ok);boundary.append(bool(ok))
        # Forced reference is bit-identical even when the candidate is selected.
        for _,g,u in samples():
            a=np.empty_like(g);b=a.copy()
            lib.nx_opt07_configure(0,0);lib.nx_swiglu(ptr(g),ptr(u),len(g),ptr(a))
            lib.nx_opt07_configure(mode,1);lib.nx_swiglu(ptr(g),ptr(u),len(g),ptr(b))
            if not np.array_equal(a.view('u4'),b.view('u4')):passed=False
        report[str(mode)]=dict(status='PASS' if passed else 'FAIL',cases=rows,nonfinite_rejection=boundary)
    write_json(output,report);return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--lib',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    print(json.dumps(evaluate(a.lib,a.output),indent=2))
