"""Full frozen workloads: independent oracle + original B cold + prefix hot.

Golden is written before each hot computation. Full traces/KV/logits are
compared, including every suffix position and two greedy decode positions.
"""
import argparse,ctypes as C,hashlib,json,sys,time
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT),str(ROOT/'tests/reference'),str(ROOT/'scripts')]
from software.reference.runtime import Runtime,ptr
from validate import compare,limit,LIMITS
from oracle import Oracle
from evidence import sha256,write_json

class Identity(C.Structure):
    _fields_=[(n,C.c_uint8*32) for n in ('model','tokenizer','template_version','numeric','backend')]+[(n,C.c_uint32) for n in ('abi','start_position','context_limit','flags')]

def bind(lib):
    for name,args,ret in [('nx_prefix_prepare',[C.c_void_p,C.POINTER(Identity),C.c_void_p,C.c_size_t],C.c_int),
                          ('nx_prefix_restore',[C.c_void_p,C.POINTER(Identity),C.c_void_p,C.c_size_t],C.c_int),
                          ('nx_prefix_configure',[C.c_void_p,C.POINTER(Identity)],C.c_int),
                          ('nx_cache_view',[C.c_void_p,C.c_int,C.c_int,C.c_void_p],C.c_void_p),
                          ('nx_logits_v2',[C.c_void_p],C.c_void_p)]:
        f=getattr(lib,name);f.argtypes=args;f.restype=ret

def identity(workload):
    key=Identity();key.abi=1;key.context_limit=512
    hashes=[bytes.fromhex(workload['model_pack_sha256']),bytes.fromhex(workload['tokenizer_lock_sha256']),
            hashlib.sha256(workload['prefix']['text'].encode()).digest(),
            hashlib.sha256(b'FP32_KV_group64_T05_RNE_no_fast_math_OPT08_v2').digest(),hashlib.sha256(b'CPU_C').digest()]
    for (name,_),value in zip(Identity._fields_,hashes):getattr(key,name)[:]=value
    return key

def main():
    p=argparse.ArgumentParser();p.add_argument('--lib',required=True);p.add_argument('--baseline',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    out=a.output;out.mkdir(parents=True,exist_ok=False);w=json.loads((ROOT/'configs/opt05-workloads.json').read_text());key=identity(w);ids=np.array(w['prefix']['ids'],'i4')
    baseline=Runtime(a.baseline,4);hot=Runtime(a.lib,4);bind(hot.lib);oracle=Oracle();records=[];comparisons=0;elements=0;trace_arrays=0;max_abs=0;timings=[]
    prepare_start=time.monotonic();assert hot.lib.nx_prefix_prepare(hot.session,C.byref(key),ptr(ids),len(ids))==0
    preparation=time.monotonic()-prepare_start
    assert hot.length==len(ids) and not hot.lib.nx_logits_v2(hot.session)
    prefix_cache=hot.cache();np.save(out/'prepared-kv.npy',prefix_cache)
    for case in w['cases'][:5]:
        assert case['ids'][:len(ids)]==ids.tolist();tokens=list(case['ids']);baseline.reset();oracle.reset();expected=[];cold_start=time.monotonic()
        for pos in range(len(tokens)+2):
            token=tokens[pos] if pos<len(tokens) else int(np.argmax(expected[-1]['logits'][0]))
            trace={};y=baseline.forward([token],trace=lambda l,n,x:trace.update({(l,n):x.copy()}))
            ey=oracle.forward([token]);m=compare(y,ey,LIMITS['cumulative']['logits_24_layers'],f'{case["id"]}/{pos}/independent-logits')
            compare(baseline.cache(),oracle.cache(),LIMITS['cumulative']['kv'],f'{case["id"]}/{pos}/independent-KV');comparisons+=2
            expected.append(dict(token=token,logits=y.copy(),kv=baseline.cache(),trace=trace))
            if pos+1==len(ids):np.testing.assert_array_equal(prefix_cache.view('u4'),expected[-1]['kv'].view('u4'))
        cold_seconds=time.monotonic()-cold_start
        # Preserve independently produced cold fixtures before calling hot code.
        golden=out/(case['id']+'-cold.npz');np.savez(golden,ids=np.array([e['token'] for e in expected],'i4'),logits=np.concatenate([e['logits'] for e in expected]),final_kv=expected[-1]['kv'])
        hot_start=time.monotonic();assert hot.lib.nx_prefix_restore(hot.session,C.byref(key),ptr(ids),len(ids))==1
        assert hot.length==len(ids) and not hot.lib.nx_logits_v2(hot.session)
        for l in range(24):
            n=C.c_size_t();assert hot.lib.nx_cache_view(hot.session,l,0,C.byref(n)) and n.value==len(ids)
        for pos in range(len(ids),len(expected)):
            e=expected[pos];trace={};y=hot.forward([e['token']],trace=lambda l,n,x:trace.update({(l,n):x.copy()}))
            assert set(trace)==set(e['trace'])
            for name,x in trace.items():
                np.testing.assert_array_equal(x.view('u4'),e['trace'][name].view('u4'),err_msg=f'{case["id"]}/{pos}/{name}')
                trace_arrays+=1;elements+=x.size
            np.testing.assert_array_equal(y.view('u4'),e['logits'].view('u4'));np.testing.assert_array_equal(hot.cache().view('u4'),e['kv'].view('u4'))
            assert int(np.argmax(y))==int(np.argmax(e['logits']))
            comparisons+=3
            records.append(dict(case=case['id'],past=pos,input_id=e['token'],greedy_id=int(np.argmax(y)),valid_tokens=hot.length,
                                logits_sha256=hashlib.sha256(y.tobytes()).hexdigest(),kv_sha256=hashlib.sha256(hot.cache().tobytes()).hexdigest(),max_abs=0))
        hot_seconds=time.monotonic()-hot_start
        timings.append(dict(case=case['id'],cold_validation_seconds=cold_seconds,hot_validation_seconds=hot_seconds,scope='HOST_VALIDATION_INCLUDES_CHECKING_NOT_CPU_OR_BOARD_SPEED'))
        print(case['id']+': full model cold/hot traces, KV, logits, IDs PASS',flush=True)
    # An identity miss must empty the cache and cannot resurrect the saved prefix.
    changed=Identity.from_buffer_copy(key);changed.tokenizer[0]^=1
    assert hot.lib.nx_prefix_restore(hot.session,C.byref(changed),ptr(ids),len(ids))==0 and hot.length==0
    assert hot.lib.nx_prefix_restore(hot.session,C.byref(key),ptr(ids),len(ids))==0
    write_json(out/'positions.json',records);write_json(out/'timings.json',timings)
    write_json(out/'result.json',dict(status='PASS',cases=5,prefix_tokens=len(ids),suffix_positions=len(records),independent_comparisons=comparisons,
                                   exact_trace_arrays=trace_arrays,exact_trace_elements=elements,max_abs=max_abs,prepare_host_validation_seconds=preparation,
                                   source_model_sha256=w['model_pack_sha256'],source_workload_sha256=sha256(ROOT/'configs/opt05-workloads.json'),identity_bytes=bytes(key).hex(),
                                   cold_hot_bitwise=True,quality_thresholds_changed=False,board_speed_measured=False))
    baseline.close();hot.close()

if __name__=='__main__':main()
