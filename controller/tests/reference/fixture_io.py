#!/usr/bin/env python3
"""Desktop/cocotb fixture reader and fail-closed, first-difference scoreboard."""
import argparse
import json
from pathlib import Path
import sys
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from evidence import sha256

def load(manifest):
    path=Path(manifest);m=json.loads(path.read_text())
    assert m['schema_version']==1 and m['producer']=='T11' and m['cases']
    assert sha256(ROOT/m['thresholds_path'])==m['thresholds_sha256'],'threshold identity'
    pack=json.loads((ROOT/m['pack_manifest']).read_text());assert pack['sha256']==m['pack_sha256']
    for c in m['cases']:
        p=path.parent/c['path'];assert p.stat().st_size==c['bytes'] and sha256(p)==c['sha256'],c['path']
        with np.load(p,allow_pickle=False) as f:
            for key in f.files:
                assert f[key].dtype.kind in 'ifu' and np.isfinite(f[key]).all(),key
            if 'fields' in c and c['kind']=='block-kv-logits':
                assert set(f.files)==set(c['fields'])
                for key,spec in c['fields'].items():
                    assert list(f[key].shape)==spec['shape'] and f[key].dtype.str==spec['dtype']
    return m

def compare_case(manifest,case,candidate):
    m=load(manifest);matches=[c for c in m['cases'] if c['path']==case];assert len(matches)==1
    c=matches[0];threshold=json.loads((ROOT/m['thresholds_path']).read_text());checked=0
    with np.load(Path(manifest).parent/case,allow_pickle=False) as ref,np.load(candidate,allow_pickle=False) as got:
        assert set(got.files)==set(ref.files),'missing/extra stage'
        for key in ref.files:
            a,b=got[key],ref[key]
            assert a.shape==b.shape and a.dtype==b.dtype,key+': shape/dtype'
            assert np.isfinite(a).all(),key+': nonfinite'
            exact=b.dtype.kind in 'iu' or key in ('sa','input_ids','past','aq','dots')
            if exact:
                if a.tobytes()!=b.tobytes():raise AssertionError(key+': exact integer/scale/input mismatch')
            else:
                category,kind=('operators','linear') if c['kind']=='linear' else ('cumulative','logits_24_layers' if key.endswith('.logits') else 'kv' if key=='cache' else 'block')
                tol=threshold[category][kind];delta=np.abs(a.astype('f8')-b)
                invalid=delta>tol['atol']+tol['rtol']*np.abs(b.astype('f8'))
                nrmse=np.sqrt(np.mean(delta**2))/max(np.sqrt(np.mean(b.astype('f8')**2)),1e-12)
                if invalid.any() or nrmse>tol['nrmse']:
                    ix=tuple(np.argwhere(invalid)[0]) if invalid.any() else np.unravel_index(delta.argmax(),delta.shape)
                    raise AssertionError(f'{key}: first difference {ix}, actual={a[ix]}, expected={b[ix]}, NRMSE={nrmse}')
            checked+=b.size
    assert checked>0
    return checked

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('manifest');p.add_argument('--candidate');p.add_argument('--case')
    a=p.parse_args();m=load(a.manifest)
    if a.candidate:print(compare_case(a.manifest,a.case,a.candidate))
    else:print('PASS',len(m['cases']),'fixtures')
