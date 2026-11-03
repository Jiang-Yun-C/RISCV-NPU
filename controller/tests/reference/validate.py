#!/usr/bin/env python3
"""Generate independent golden first, then check C; fail on the first divergence."""
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
from software.reference.runtime import Runtime,ptr
from oracle import Oracle

LIMITS=json.loads((ROOT/'configs/t05-thresholds.json').read_text())
IDS=[0,255,256,1023,151642,151643,151645,151935]
def limit(name):
    if name=='logits':return LIMITS['cumulative']['logits_24_layers']
    if name=='embedding':return LIMITS['operators']['embedding']
    return LIMITS['cumulative']['block']

def compare(actual,expected,tolerance,label):
    try:return metric(actual,expected,tolerance)
    except (ValueError,AssertionError) as e:
        delta=np.abs(np.asarray(actual,dtype=np.float64)-expected)
        bad=(~np.isfinite(delta))|(delta>tolerance['atol']+tolerance['rtol']*np.abs(expected))
        first=np.argwhere(bad)
        index=tuple(first[0]) if len(first) else np.unravel_index(np.argmax(delta),delta.shape)
        raise AssertionError(f'{label}: first index={index}, actual={actual[index]}, expected={expected[index]}; {e}') from e

def file_spec(path,base):
    return {'path':str(path.relative_to(base)),'sha256':sha256(path),'bytes':path.stat().st_size}

def validate(lib,out,threads=4):
    out=Path(out);out.mkdir(parents=True,exist_ok=False)
    golden=out/'golden';golden.mkdir();small=out/'fixtures';small.mkdir()
    oracle=Oracle();runtime=Runtime(lib,threads);metrics=[];records=[];small_records=[]
    integer_count=0
    # Real model operator: independent grouped dot, scales and output.
    x=np.random.default_rng(20261005).normal(size=(4,896)).astype(np.float32)
    name='model.layers.0.self_attn.q_proj.weight'
    y,aq,sa,dots=oracle.linear(x,name,details=True)
    op=small/'linear-q.npz';np.savez(op,x=x,aq=aq,sa=sa,dots=dots,y=y)
    cq=np.empty_like(aq);cs=np.empty_like(sa);cy=np.empty_like(y);cd=np.empty_like(dots)
    assert runtime.lib.nx_quantize(ptr(x),4,896,ptr(cq),ptr(cs))==0
    assert np.array_equal(cq,aq) and np.array_equal(cs.view('u4'),sa.view('u4'))
    w=runtime.matrix(name)
    assert runtime.lib.nx_linear(ptr(x),4,C.byref(w),ptr(cy),ptr(cd))==0
    assert np.array_equal(cd,dots);integer_count+=cd.size+cq.size+cs.size
    metrics.append({'label':'isolated-q-linear',**compare(cy,y,LIMITS['operators']['linear'],'isolated-q-linear')})
    small_records.append({**file_spec(op,out),'kind':'linear','weight':name,
                          'weight_pack_sha256':runtime.manifest['sha256'],
                          'fields':{'x':'input-f32','aq':'expected-i8','sa':'expected-f32-bitwise','dots':'expected-i32','y':'expected-f32'},
                          'tolerance':['operators','linear'],'dot_layout':'[group,M,N]','shape_MNK':[4,896,896]})
    for context in LIMITS['cumulative']['teacher_forcing']['context_lengths']:
        oracle.reset();runtime.reset();tokens=(IDS*((context+15)//8))[:context+8]
        chunks=[tokens[lo:min(context,lo+8)] for lo in range(0,context,8)]+[[t] for t in tokens[context:context+8]]
        pos=0;argmax=[]
        for step,ids in enumerate(chunks):
            last=pos+len(ids)>=context
            expected={};actual={}
            def trace(target):return lambda l,n,a:target.update({f'layer{l}.{n}':a})
            ey=oracle.forward(ids,logits=last,trace=trace(expected))
            ek=oracle.cache() if last else None
            selected={k:a for k,a in expected.items() if k.split('.')[0] in ('layer-1','layer0','layer11','layer23','layer24') or k.endswith('.output')}
            if last:selected['cache']=ek
            selected['input_ids']=np.array(ids,np.int32);selected['past']=np.array(pos,np.int32)
            # Written before candidate invocation. No candidate output enters golden.
            path=golden/f'context{context}-chunk{step:03d}.npz';np.savez(path,**selected)
            entry={**file_spec(path,out),'context':context,'past':pos,'input_ids':ids,'prefix_ids':tokens[:pos],
                   'fields':{k:{'shape':list(v.shape),'dtype':v.dtype.str,'endianness':'little',
                                'strides_bytes':list(v.strides)} for k,v in selected.items()}}
            records.append(entry)
            ay=runtime.forward(ids,logits=last,trace=trace(actual))
            assert set(actual)==set(expected),'missing trace stage'
            for key in expected:
                m=compare(actual[key],expected[key],limit(key.split('.')[1]),f'context{context}/pos{pos}/{key}')
                metrics.append({'label':f'context{context}/pos{pos}/{key}',**m})
            if last:
                metrics.append({'label':f'context{context}/pos{pos}/KV',**compare(runtime.cache(),ek,LIMITS['cumulative']['kv'],'KV')})
                for i in range(len(ids)):
                    order=np.argsort(ey[i])[-2:];margin=float(ey[i,order[-1]]-ey[i,order[-2]])
                    error=float(np.max(np.abs(ay[i]-ey[i])));same=int(np.argmax(ay[i]))==int(np.argmax(ey[i]))
                    if margin>2*error:assert same,'stable argmax changed'
                    argmax.append({'position':pos+i,'same':same,'margin':margin,'max_abs':error})
            if context==1 and step in (0,1,8):
                import shutil
                dest=small/path.name;shutil.copyfile(path,dest)
                small_records.append({**entry,**file_spec(dest,out),'kind':'block-kv-logits',
                                      'blocks':[0,11,23],'tolerances':{'block':['cumulative','block'],'cache':['cumulative','kv'],
                                                                   'logits':['cumulative','logits_24_layers']}})
            pos+=len(ids)
        write_json(out/f'argmax-context{context}.json',argmax)
        print(f'context={context}: full prefill and 8 fixed-token decode steps PASS',flush=True)
    # Actual full cache boundary, then reject overflow without publishing output.
    while runtime.length<640:runtime.forward([17]*min(8,640-runtime.length),logits=False)
    ids=np.array([17],np.int32);untouched=np.full((1,151936),123,np.float32)
    assert runtime.lib.nx_forward(runtime.session,ptr(ids),1,640,ptr(untouched),__import__('software.reference.runtime',fromlist=['TRACE']).TRACE())==-1
    assert (untouched==123).all() and runtime.length==640
    runtime.reset();assert runtime.length==0 and runtime.cache().shape==(24,2,0,128)
    manifest={'schema_version':1,'producer':'T11','consumers':['T15','T19'],'qualification':'DESKTOP_C_PYTHON_ONLY',
              'numeric_version':'w8a8-g64-fp32-v1','layout_id':4097,'group_size':64,'thresholds_path':'configs/t05-thresholds.json',
              'thresholds_sha256':sha256(ROOT/'configs/t05-thresholds.json'),
              'pack_manifest':'docs/spec/model-pack-v1-manifest.json','pack_sha256':runtime.manifest['sha256'],
              'generator':{'path':'tests/reference/oracle.py','sha256':sha256(Path(__file__).with_name('oracle.py'))},
              'checker':{'path':'tests/reference/validate.py','sha256':sha256(Path(__file__))},
              'seed':20261005,'context_lengths':[1,4,8,512],'decode_steps':8,
              'replay_command':'make t11','comparison_command':'npu-python tests/reference/fixture_io.py <manifest> --candidate <trace.npz> --case <path>',
              'golden_provenance':'Independent Python arithmetic from frozen inputs; written before C execution',
              'cases':records,'small_cases':small_records}
    write_json(out/'manifest.json',manifest)
    sm=dict(manifest);sm['cases']=small_records;sm.pop('small_cases')
    write_json(out/'fixture-manifest.json',sm)
    report={'status':'PASS','contexts':[1,4,8,512],'decode_steps':8,'integer_elements_exact':integer_count,
            'comparisons':len(metrics),'max_abs':max(m['max_abs'] for m in metrics),'cache_640_overflow_and_reset':'PASS',
            'metrics':metrics,'profile':runtime.profile(),'fixture_manifest_sha256':sha256(out/'fixture-manifest.json')}
    write_json(out/'result.json',report);runtime.close();return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--lib',required=True);p.add_argument('--output',required=True);p.add_argument('--threads',type=int,default=4)
    a=p.parse_args();validate(a.lib,a.output,a.threads)
