"""All 512 positions: real candidate graph against independent NumPy oracle."""
import argparse,ctypes as C,json,hashlib
from pathlib import Path
import numpy as np
from software.reference.runtime import library,Weights,Matrix,ptr,TRACE
from tests.opt09.fixture import Oracle
from tests.opt09.numeric import Identity,bind

def main():
    p=argparse.ArgumentParser();p.add_argument('--lib',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=False);o=Oracle();lib=library(a.lib);bind(lib);w=Weights()
    def mat(q,s,n,k,b=None):return Matrix(ptr(q),ptr(s),ptr(b),n,k)
    w.embedding=mat(o.qe,o.se,32,8);w.norm=ptr(o.norm);w.inv_freq=ptr(o.inv)
    for l in range(2):
        w.layer[l].norm1=ptr(o.n1[l]);w.layer[l].norm2=ptr(o.n2[l])
        for j,(name,n,k) in enumerate(zip(('q','k','v','o','gate','up','down'),(8,4,4,8,16,16,8),(8,8,8,8,8,8,16))):
            setattr(w.layer[l],name,mat(o.q[l,j],o.s[l,j],n,k,o.bias[l,j] if j<3 else None))
    session=lib.nx_create(C.byref(w),1);assert session
    key=Identity();C.memset(C.byref(key),1,C.sizeof(key));key.abi=1;key.start_position=0;key.context_limit=512;key.flags=0
    ids=np.array([i%32 for i in range(512)],'i4');y=np.empty((1,32),'f4');positions=[];count=0;max_abs=0
    def kv():
        n=lib.nx_length(session)
        return np.stack([np.stack([np.ctypeslib.as_array(C.cast(lib.nx_cache(session,l,v),C.POINTER(C.c_float)),shape=(640,4))[:n].copy() for v in range(2)]) for l in range(2)])
    for pos,token in enumerate(ids):
        ey=o.forward(int(token));id=np.array([token],'i4');assert lib.nx_forward(session,ptr(id),1,pos,ptr(y),TRACE())==0
        actual=kv();expected=np.stack((o.k,o.v),axis=1)
        np.testing.assert_allclose(y[0],ey,atol=2e-5,rtol=2e-4);np.testing.assert_allclose(actual,expected,atol=2e-5,rtol=2e-4)
        max_abs=max(max_abs,float(np.max(np.abs(y[0]-ey))),float(np.max(np.abs(actual-expected))))
        count+=y.size+actual.size
        positions.append(dict(past=pos,valid=pos+1,greedy_id=int(np.argmax(y)),kv_sha256=hashlib.sha256(actual.tobytes()).hexdigest()))
    cold_y=y.copy();cold_kv=kv();np.savez(a.output/'cold-512.npz',ids=ids,logits=cold_y,kv=cold_kv)
    assert lib.nx_prefix_prepare(session,C.byref(key),ptr(ids),511)==0
    assert lib.nx_prefix_restore(session,C.byref(key),ptr(ids),511)==1
    assert lib.nx_forward(session,ptr(ids[511:]),1,511,ptr(y),TRACE())==0
    np.testing.assert_array_equal(y.view('u4'),cold_y.view('u4'));np.testing.assert_array_equal(kv().view('u4'),cold_kv.view('u4'))
    assert lib.nx_prefix_prepare(session,C.byref(key),ptr(ids),512)==0 and lib.nx_length(session)==512
    assert lib.nx_prefix_restore(session,C.byref(key),ptr(ids),512)==1
    assert lib.nx_prefix_prepare(session,C.byref(key),ptr(ids),513)==-1 and lib.nx_length(session)==0
    assert lib.nx_prefix_prepare(session,C.byref(key),ptr(ids),0)==-1
    lib.nx_destroy(session)
    (a.output/'positions.json').write_text(json.dumps(positions,indent=2)+'\n')
    (a.output/'result.json').write_text(json.dumps(dict(status='PASS',positions=512,independent_elements=count,max_abs=max_abs,hot_511_plus_1_bitwise=True,prefix_512_valid=True,prefix_513_rejected=True),indent=2)+'\n')
    print('PASS 512-position independent graph; 511+1 cold/hot bit exact',flush=True)

if __name__=='__main__':main()
