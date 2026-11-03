"""512-position independent graph, tails, prefix poison and mutation oracle."""
import argparse,ctypes as C,json,hashlib
from pathlib import Path
import numpy as np
from software.reference.runtime import library,Weights,Matrix,TRACE,ptr
from tests.opt13.fixture import Oracle,H,F,V,L,D,KV
from tests.opt09.numeric import bind,Identity
from tests.opt13.numeric import bind_block

def main():
    p=argparse.ArgumentParser();p.add_argument('--lib',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True)
    o=Oracle();lib=library(a.lib);bind_block(lib);w=Weights()
    def mat(q,s,n,k,b=None):return Matrix(ptr(q),ptr(s),ptr(b),n,k)
    w.embedding=mat(o.qe,o.se,V,H);w.norm=ptr(o.norm);w.inv_freq=ptr(o.inv)
    for l in range(L):
        w.layer[l].norm1=ptr(o.n1[l]);w.layer[l].norm2=ptr(o.n2[l])
        for j,(name,n,k) in enumerate(zip(('q','k','v','o','gate','up','down'),(H,KV,KV,H,F,F,H),(H,H,H,H,H,H,F))):setattr(w.layer[l],name,mat(o.q[l,j],o.sc[l,j],n,k,o.bias[l,j] if j<3 else None))
    session=lib.nx_create(C.byref(w),1);assert session;ids=np.array([(i+1)%V for i in range(512)],'i4');gold_y=[];gold_k=[]
    for id in ids:gold_y.append(o.forward(int(id)));gold_k.append(o.cache().copy())
    np.savez(a.output/'serial-golden.npz',ids=ids,logits=np.stack(gold_y),kv=gold_k[-1]);checks=0
    def cache():
        n=lib.nx_length(session);assert n>=0
        return np.stack([np.stack([np.ctypeslib.as_array(C.cast(lib.nx_cache(session,l,v),C.POINTER(C.c_float)),shape=(640,KV))[:n].copy() for v in range(2)]) for l in range(L)])
    def close(y,kv,pos):
        nonlocal checks
        np.testing.assert_allclose(y,gold_y[pos-1],atol=2e-5,rtol=2e-4);np.testing.assert_allclose(kv,gold_k[pos-1],atol=2e-5,rtol=2e-4);checks+=y.size+kv.size
    for width in (1,4):
        lib.nx_reset(session);assert lib.nx_set_prefill_rows(session,width)==0
        for lo in range(0,512,width):
            rows=min(width,512-lo);next=C.c_int32(-1);assert lib.nx_forward_block_v3(session,ptr(ids[lo:]),rows,lo,C.byref(next))==0
            y=np.ctypeslib.as_array(C.cast(lib.nx_logits_v2(session),C.POINTER(C.c_float)),shape=(V,)).copy();close(y,cache(),lo+rows);assert next.value==int(np.argmax(gold_y[lo+rows-1]))
    # Independent cold prompt boundaries and all-row diagnostic logits.
    for n in (1,3,4,5,7,8,9,32,128,256,511,512):
        lib.nx_reset(session)
        for lo in range(0,n,4):
            rows=min(4,n-lo);y=np.empty((rows,V),'f4');assert lib.nx_forward(session,ptr(ids[lo:]),rows,lo,ptr(y),TRACE())==0
            np.testing.assert_allclose(y,np.stack(gold_y[lo:lo+rows]),atol=2e-5,rtol=2e-4);checks+=y.size
        close(y[-1],cache(),n)
    key=Identity();C.memset(C.byref(key),1,C.sizeof(key));key.abi=1;key.start_position=0;key.context_limit=512;key.flags=0
    for prefix in (3,5,7,31,127,255,511):
        assert lib.nx_prefix_prepare(session,C.byref(key),ptr(ids),prefix)==0
        for l in range(L):
            for v in range(2):
                raw=np.ctypeslib.as_array(C.cast(lib.nx_cache(session,l,v),C.POINTER(C.c_float)),shape=(640,KV));raw[prefix:]=np.nan
        assert lib.nx_prefix_restore(session,C.byref(key),ptr(ids),prefix)==1
        end=min(prefix+5,512)
        for lo in range(prefix,end,4):
            rows=min(4,end-lo);next=C.c_int32();assert lib.nx_forward_block_v3(session,ptr(ids[lo:]),rows,lo,C.byref(next))==0
        y=np.ctypeslib.as_array(C.cast(lib.nx_logits_v2(session),C.POINTER(C.c_float)),shape=(V,)).copy();close(y,cache(),end)
    # Future tokens cannot affect earlier rows, including next-layer K/V.
    lib.nx_reset(session);full=np.empty((4,V),'f4');assert lib.nx_forward(session,ptr(ids),4,0,ptr(full),TRACE())==0;before=cache()
    changed=ids[:4].copy();changed[3]=17;lib.nx_reset(session);other=np.empty_like(full);assert lib.nx_forward(session,ptr(changed),4,0,ptr(other),TRACE())==0
    np.testing.assert_array_equal(before[:,:,:3].view('u4'),cache()[:,:,:3].view('u4'));np.testing.assert_array_equal(full[:3].view('u4'),other[:3].view('u4'));checks+=before[:,:,:3].size+full[:3].size
    # Complete greedy/controller context cap also applies to this public API.
    for n in (511,512):
        output=np.full(128,-99,'i4');count=C.c_int(-1);stop=C.c_int(-1);assert lib.nx_generate(session,ptr(ids),n,ptr(output),C.byref(count),C.byref(stop))==0
        assert count.value==512-n and stop.value==3
        if n==511:assert output[0]==int(np.argmax(gold_y[510])) and np.all(output[1:]==-99)
        else:assert np.all(output==-99)
    assert lib.nx_prefix_prepare(session,C.byref(key),ptr(ids),3)==0
    assert lib.nx_forward_block_v3(session,ptr(ids),4,4,None)==-4
    assert lib.nx_logits_v2(session) is None and lib.nx_prefix_restore(session,C.byref(key),ptr(ids),3)==0
    lib.nx_destroy(session);(a.output/'result.json').write_text(json.dumps(dict(status='PASS',independent_elements=checks,positions=512,gqa='14:2',future_pollution_rejected=True,prefixes=[3,5,7,31,127,255,511],boundaries=[511,512],max_context=512),indent=2)+'\n');print('PASS',checks,flush=True)
if __name__=='__main__':main()
