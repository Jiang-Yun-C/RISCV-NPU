"""Independent T11 regression plus bitwise A/B comparison of every C trace."""
import argparse,ctypes as C,json,sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT),str(ROOT/'tests/reference')]
import validate as reference
from software.reference.runtime import Runtime,ptr
class Mirrored(Runtime):
    baseline_lib=None
    exact_arrays=0
    exact_elements=0
    def __init__(self,*args,**kw):
        super().__init__(*args,**kw);self.baseline=Runtime(self.baseline_lib,4)
    def reset(self):super().reset();self.baseline.reset()
    def forward(self,ids,logits=True,trace=None):
        expected={};actual={}
        def capture(target):return lambda l,n,a:target.update({(l,n):a.copy()})
        ey=self.baseline.forward(ids,logits=logits,trace=capture(expected))
        ay=super().forward(ids,logits=logits,trace=capture(actual))
        assert set(expected)==set(actual)
        for (l,n),a in actual.items():
            np.testing.assert_array_equal(a.view('u4'),expected[l,n].view('u4'),err_msg=f'{l}/{n}')
            Mirrored.exact_arrays+=1;Mirrored.exact_elements+=a.size
            if trace:trace(l,n,a)
        np.testing.assert_array_equal(self.cache().view('u4'),self.baseline.cache().view('u4'))
        if logits:np.testing.assert_array_equal(ay.view('u4'),ey.view('u4'))
        return ay
    def close(self):
        self.lib.nx_opt08_counters.argtypes=[C.c_void_p,C.c_void_p,C.c_void_p]
        calls=C.c_uint64();hits=C.c_uint64();self.lib.nx_opt08_counters(self.session,C.byref(calls),C.byref(hits))
        self.counters=dict(quantizations=calls.value,hits=hits.value,baseline_quantizations=calls.value+hits.value)
        # Exercise production v2 token/diagnostic entry with the real 24-layer model.
        super().reset();self.baseline.reset();expected=self.baseline.forward([0])
        self.lib.nx_forward_token_v2.argtypes=[C.c_void_p,C.c_int32,C.c_int,C.c_void_p]
        self.lib.nx_logits_v2.argtypes=[C.c_void_p];self.lib.nx_logits_v2.restype=C.POINTER(C.c_float)
        token=C.c_int32(-1);assert self.lib.nx_forward_token_v2(self.session,0,0,C.byref(token))==0
        y=np.ctypeslib.as_array(self.lib.nx_logits_v2(self.session),shape=(151936,))
        np.testing.assert_array_equal(y.view('u4'),expected[0].view('u4'));assert token.value==int(np.argmax(expected[0]))
        Path(OUTPUT/'exact.json').write_text(json.dumps(dict(status='PASS',arrays=self.exact_arrays,elements=self.exact_elements,counters=self.counters,production_v2_full_vocab=True,greedy_id=token.value),indent=2)+'\n')
        self.baseline.close();super().close()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--lib',required=True);p.add_argument('--baseline',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    OUTPUT=a.output;Mirrored.baseline_lib=a.baseline;reference.Runtime=Mirrored
    reference.validate(a.lib,a.output,4)
