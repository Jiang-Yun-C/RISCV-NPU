#!/usr/bin/env python3
"""Exercise C against all 24 sealed real-shape T05 linear vectors."""
import argparse
import ctypes as C
import json
from pathlib import Path
import sys
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/'scripts'),str(ROOT/'tests/vectors')]
from evidence import sha256,write_json
from check_v1 import metric
from software.reference.runtime import library,ptr,Matrix

def check(lib,report):
    lib=library(lib)
    # Standalone C calls use the same finite, already validated immutable weights.
    C.CDLL('libgomp.so.1').omp_set_num_threads(4)
    cfg=json.loads((ROOT/'configs/t10-pack.json').read_text());base=ROOT/cfg['t05_vectors']
    idx=json.loads((base/'index.json').read_text());limits=json.loads((ROOT/'configs/t05-thresholds.json').read_text())
    assert idx['thresholds_sha256']==sha256(ROOT/'configs/t05-thresholds.json')
    rows=[];count=0
    for case in idx['cases']:
        path=base/case['path'];weight=idx['weights'][case['weight']]
        def array(p):
            p=Path(p);relative=str(p.relative_to(base));assert sha256(p)==idx['files'][relative]['sha256'],relative
            return np.load(p,mmap_mode='r')
        x=array(path/'x.npy');q=array(base/weight['q']);s=array(base/weight['scale']);b=array(base/weight['bias']) if weight['bias'] else None
        eq=array(path/'aq.npy');es=array(path/'sa.npy');ed=array(path/'dots.npy');ey=array(path/'y.npy')
        aq=np.empty_like(eq);sa=np.empty_like(es);dots=np.empty_like(ed);y=np.empty_like(ey)
        assert lib.nx_quantize(ptr(x),len(x),x.shape[1],ptr(aq),ptr(sa))==0
        assert aq.tobytes()==eq.tobytes() and sa.tobytes()==es.tobytes()
        w=Matrix(ptr(q),ptr(s),ptr(b),*q.shape)
        assert lib.nx_linear(ptr(x),len(x),C.byref(w),ptr(y),ptr(dots))==0
        assert np.array_equal(dots,ed),'group dot mismatch'
        rows.append({'case':case['path'],**metric(y,ey,limits['operators']['linear'])});count+=aq.size+sa.size+dots.size
        print(case['path'],'PASS',flush=True)
    assert len(rows)==24
    result={'status':'PASS','cases':rows,'integer_and_scale_elements_exact':count,'thresholds_sha256':sha256(ROOT/'configs/t05-thresholds.json')}
    write_json(report,result)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--lib',required=True);p.add_argument('--report',required=True);a=p.parse_args();check(a.lib,a.report)
