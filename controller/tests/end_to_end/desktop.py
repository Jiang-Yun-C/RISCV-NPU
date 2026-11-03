#!/usr/bin/env python3
"""Replay all 99 immutable T11 traces with the current complete 0.5B C graph."""
import json,sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/'scripts'),str(ROOT/'tests/reference')]
from software.reference.runtime import build,Runtime
from evidence import sha256,write_json
from validate import compare,limit

def main(out):
    out=Path(out);out.mkdir(parents=True,exist_ok=False);build(out/'reference.so');runtime=Runtime(out/'reference.so',8)
    parent=ROOT/'models/reference-v1/acceptance-20261005-v3/primary';manifest=json.loads((parent/'manifest.json').read_text());metrics=[];elements=0;cases=0;max_abs=0
    evidence=json.loads((ROOT/'evidence/T11/acceptance-20261005-v3/manifest.json').read_text())
    managed=evidence['managed_artifacts'];assert sha256(parent/'manifest.json')==managed[str((parent/'manifest.json').relative_to(ROOT))]['sha256']
    # Published small manifest plus accepted full manifest bind pack and numeric identity.
    assert manifest['pack_sha256']==runtime.manifest['sha256'];assert manifest['thresholds_sha256']==sha256(ROOT/'configs/t05-thresholds.json')
    for record in manifest['cases']:
        if record['past']==0:runtime.reset()
        assert runtime.length==record['past'];p=parent/record['path'];assert sha256(p)==record['sha256']
        expected=np.load(p,allow_pickle=False);actual={}
        runtime.forward(record['input_ids'],logits=any(k.endswith('.logits') for k in expected.files),trace=lambda l,n,a:actual.update({f'layer{l}.{n}':a}))
        if 'cache' in expected:actual['cache']=runtime.cache()
        for key in expected.files:
            if key in ('past','input_ids'):continue
            tol=json.loads((ROOT/'configs/t05-thresholds.json').read_text())['cumulative']['kv'] if key=='cache' else limit(key.split('.')[1])
            m=compare(actual[key],expected[key],tol,record['path']+'/'+key);metrics.append(dict(case=record['path'],stage=key,**m));max_abs=max(max_abs,m['max_abs']);elements+=expected[key].size
        cases+=1
    # Exercise the actual 640-slot complete graph, then reject the next append.
    while runtime.length<640:runtime.forward([17]*min(8,640-runtime.length),logits=False)
    import ctypes as C
    from software.reference.runtime import ptr,TRACE
    ids=np.array([17],'<i4');y=np.full((1,151936),123,'f4')
    assert runtime.lib.nx_forward(runtime.session,ptr(ids),1,640,ptr(y),TRACE())==-1 and (y==123).all() and runtime.length==640
    runtime.reset();assert runtime.length==0 and runtime.cache().shape==(24,2,0,128)
    result=dict(status='PASS',scope='DESKTOP_CPU_C_FULL_24_LAYER_0.5B',cases=cases,contexts=manifest['context_lengths'],fixed_decode_steps=8,checked_elements=elements,max_abs=max_abs,
        pack_sha256=manifest['pack_sha256'],t11_manifest_sha256=sha256(parent/'manifest.json'),current_library_sha256=sha256(out/'reference.so'),actual_context_640_overflow_and_reset='PASS',metrics=metrics,profile=runtime.profile())
    runtime.close();write_json(out/'result.json',result);print(json.dumps({k:v for k,v in result.items() if k not in ('metrics','profile')},indent=2));return result
if __name__=='__main__':main(sys.argv[1])
