"""Complete 0.5B model: independent token-serial oracle, frozen before M4.

Host execution is reported as numeric evidence; never as board throughput.
"""
import argparse,ctypes as C,hashlib,json,sys,time
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT),str(ROOT/'tests/reference'),str(ROOT/'scripts')]
from software.reference.runtime import Runtime,TRACE,ptr
from oracle import Oracle
from validate import compare,LIMITS
from evidence import sha256,write_json
from tests.opt09.numeric import bind,identity
CHECKPOINTS=[1,3,4,5,7,8,9,32,128,256,511,512]
def bind_block(lib):
    bind(lib);lib.nx_forward_block_v3.argtypes=[C.c_void_p,C.c_void_p,C.c_int,C.c_int,C.c_void_p];lib.nx_forward_block_v3.restype=C.c_int
    lib.nx_set_prefill_rows.argtypes=[C.c_void_p,C.c_int];lib.nx_set_prefill_rows.restype=C.c_int

def main():
    p=argparse.ArgumentParser();p.add_argument('--lib',required=True);p.add_argument('--baseline',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();out=a.output;out.mkdir(parents=True)
    oracle=Oracle();w=json.loads((ROOT/'configs/opt05-workloads.json').read_text());real=w['cases'][0]['ids'];tokens=(real*((520+len(real)-1)//len(real)))[:520]
    otrace={};golden=out/'golden';golden.mkdir();records=[]
    # Reference never receives candidate values. All complete IDs are saved.
    for pos,id in enumerate(tokens):
        y=oracle.forward([id],logits=pos+1 in CHECKPOINTS or pos>=512)
        if pos+1 in CHECKPOINTS or pos>=512:
            f=golden/f'position-{pos+1}.npz';np.savez(f,logits=y,kv=oracle.cache());records.append(dict(position=pos+1,path=f.name,sha256=sha256(f)))
        if (pos+1)%128==0:print('oracle position '+str(pos+1),flush=True)
    write_json(out/'inputs.json',dict(ids=tokens,checkpoints=CHECKPOINTS,model=w['model_pack_sha256'],workload=sha256(ROOT/'configs/opt05-workloads.json'),thresholds=sha256(ROOT/'configs/t05-thresholds.json'),golden=records))
    baseline=Runtime(a.baseline,4);candidate=Runtime(a.lib,4);bind_block(candidate.lib);metrics=[];timings=[];exact=0
    baseline_y={};baseline_k={}
    for pos,id in enumerate(tokens):
        head=pos+1 in CHECKPOINTS or pos>=512;y=baseline.forward([id],logits=head)
        if head:
            with np.load(golden/f'position-{pos+1}.npz') as f:
                metrics.append(compare(y,f['logits'],LIMITS['cumulative']['logits_24_layers'],f'M1/{pos+1}/logits'))
                kv=baseline.cache();metrics.append(compare(kv,f['kv'],LIMITS['cumulative']['kv'],f'M1/{pos+1}/KV'))
                baseline_y[pos+1]=y.copy();baseline_k[pos+1]=hashlib.sha256(kv.tobytes()).hexdigest()
        if (pos+1)%128==0:print('M1 position '+str(pos+1),flush=True)
    pos=0;next_id=C.c_int32(-1)
    for target in CHECKPOINTS:
        while pos<target:
            rows=min(4,target-pos);ids=np.array(tokens[pos:pos+rows],'i4');end=pos+rows;head=end==target;start=time.monotonic()
            rc=candidate.lib.nx_forward_block_v3(candidate.session,ptr(ids),rows,pos,C.byref(next_id) if head else None);assert rc==0,(pos,rows,rc)
            timings.append(dict(past=pos,rows=rows,head=head,host_seconds=time.monotonic()-start));pos=end
        ay=np.ctypeslib.as_array(C.cast(candidate.lib.nx_logits_v2(candidate.session),C.POINTER(C.c_float)),shape=(151936,)).copy()[None]
        kv=candidate.cache()
        with np.load(golden/f'position-{target}.npz') as f:
            metrics.append(compare(ay,f['logits'],LIMITS['cumulative']['logits_24_layers'],f'M4/{target}/logits'));metrics.append(compare(kv,f['kv'],LIMITS['cumulative']['kv'],f'M4/{target}/KV'))
        np.testing.assert_array_equal(ay.view('u4'),baseline_y[target].view('u4'));assert hashlib.sha256(kv.tobytes()).hexdigest()==baseline_k[target];assert next_id.value==int(np.argmax(baseline_y[target]));exact+=ay.size+kv.size
        print('M4 complete context '+str(target)+' PASS',flush=True)
    # Preserve the original 512+8 teacher-forcing diagnostic graph. Public
    # requests/block-v3 remain capped at 512 and never emit these extra tokens.
    for pos in range(512,520):
        y=candidate.forward([tokens[pos]])
        with np.load(golden/f'position-{pos+1}.npz') as f:
            metrics.append(compare(y,f['logits'],LIMITS['cumulative']['logits_24_layers'],'diagnostic/logits'));metrics.append(compare(candidate.cache(),f['kv'],LIMITS['cumulative']['kv'],'diagnostic/KV'))
        np.testing.assert_array_equal(y.view('u4'),baseline_y[pos+1].view('u4'))
    # Real full prompt and prefix/suffix restore with an unaligned past=3.
    key=identity(w);prefix=np.array(real[:3],'i4');candidate.reset();assert candidate.lib.nx_prefix_prepare(candidate.session,C.byref(key),ptr(prefix),3)==0
    prefix_k=candidate.cache().copy();assert candidate.lib.nx_prefix_restore(candidate.session,C.byref(key),ptr(prefix),3)==1
    for lo in range(3,32,4):
        ids=np.array(tokens[lo:min(32,lo+4)],'i4');assert candidate.lib.nx_forward_block_v3(candidate.session,ptr(ids),len(ids),lo,C.byref(next_id) if lo+len(ids)==32 else None)==0
    assert hashlib.sha256(candidate.cache().tobytes()).hexdigest()==baseline_k[32]
    assert candidate.lib.nx_forward_block_v3(candidate.session,ptr(prefix),4,33,None)!=0
    assert candidate.lib.nx_logits_v2(candidate.session) is None
    # Required 8-step diagnostic teacher forcing at short original contexts.
    for context in (1,4,8):
        oracle.reset();candidate.reset()
        for lo in range(0,context,4):candidate.forward(tokens[lo:min(lo+4,context)],logits=False)
        for id in tokens[:context]:oracle.forward([id],logits=False)
        for step,id in enumerate(tokens[context:context+8]):
            ey=oracle.forward([id]);ay=candidate.forward([id]);metrics.append(compare(ay,ey,LIMITS['cumulative']['logits_24_layers'],f'context{context}/{step}/logits'));metrics.append(compare(candidate.cache(),oracle.cache(),LIMITS['cumulative']['kv'],'teacher/KV'))
    write_json(out/'timings.json',dict(scope='HOST_NUMERIC_RUNTIME_ONLY_NOT_RV32_OR_BOARD_SPEED',samples=timings))
    write_json(out/'result.json',dict(status='PASS',contexts=CHECKPOINTS,teacher_forcing_contexts=[1,4,8,512],teacher_forcing_steps=8,independent_comparisons=len(metrics),exact_m1_m4_elements=exact,max_abs=max(m['max_abs'] for m in metrics),all_ids=tokens,prefix_past=3,prefix_32_bitwise=True,thresholds_changed=False,board_speed_measured=False,full_model_rtl=False))
    baseline.close();candidate.close()
if __name__=='__main__':main()
