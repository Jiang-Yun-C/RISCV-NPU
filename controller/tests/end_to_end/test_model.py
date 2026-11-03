import ctypes as C,json,subprocess,sys,tempfile,unittest
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/'scripts'),str(ROOT/'tests/end_to_end')]
from model_prepare import prepare,MiniOracle,group
from software.reference.runtime import library,Weights,Matrix,TRACE,ptr

class ModelGraph(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.path=Path(cls.tmp.name);cls.fixture=prepare(cls.path/'fixture',{},'continuous');cls.arrays={}
        for r in cls.fixture['regions']:
            if r['kind']=='immutable_model':cls.arrays[r['name']]=np.fromfile(r['path'],dtype=r['dtype']).reshape(r['shape'])
        lib=cls.path/'reference.so';subprocess.run(['gcc','-O2','-shared','-fPIC','-fopenmp','-ffp-contract=off','-fno-fast-math','-DNX_T19_MINI',str(ROOT/'firmware/runtime/reference/nx_reference.c'),'-lm','-o',str(lib)],check=True)
        cls.lib=library(lib);cls.w=Weights()
        def matrix(key):q=cls.arrays[key+'.q'];return Matrix(ptr(q),ptr(cls.arrays[key+'.s']),ptr(cls.arrays.get(key+'.bias')),q.shape[0],128 if key.endswith('down') else 112)
        cls.w.embedding=matrix('embed')
        for l in range(2):
            w=cls.w.layer[l];w.norm1=ptr(cls.arrays[f'l{l}.norm1']);w.norm2=ptr(cls.arrays[f'l{l}.norm2'])
            for n in ('q','k','v','o','gate','up','down'):setattr(w,n,matrix(f'l{l}.{n}'))
        cls.w.norm=ptr(cls.arrays['norm']);cls.w.inv_freq=ptr(cls.arrays['inv'])
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def setUp(self):self.session=self.lib.nx_create(C.byref(self.w),1);self.assertTrue(self.session)
    def tearDown(self):self.lib.nx_destroy(self.session)
    def test_independent_continuous_graph_and_reset(self):
        oracle=MiniOracle(self.arrays);expected=np.load(self.path/'fixture/golden.npz');actual={}
        for step,token in enumerate(self.fixture['tokens']+[7,0]):
            if step==9:self.lib.nx_reset(self.session);oracle.reset()
            past=self.lib.nx_length(self.session);trace,jobs=oracle.forward(token);ids=np.array([token],'<i4');y=np.empty((1,129),'<f4');actual={}
            @TRACE
            def cb(l,n,p,r,c):actual[l,n.decode()]=np.ctypeslib.as_array(C.cast(p,C.POINTER(C.c_float)),shape=(r*c,)).copy()
            self.assertEqual(self.lib.nx_forward(self.session,ptr(ids),1,past,ptr(y),cb),0)
            for l in range(2):
                for value,name in [(0,'cache_k'),(1,'cache_v')]:actual[l,name]=np.ctypeslib.as_array(C.cast(self.lib.nx_cache(self.session,l,value),C.POINTER(C.c_float)),shape=((past+1)*16,)).copy()
            self.assertEqual(set(actual),set(trace))
            for (l,n),a in actual.items():np.testing.assert_array_equal(a,expected[str(group(step,l,n))],err_msg=f'step={step}/layer={l}/{n}')
    def test_overflow_wrong_past_invalid_token_preserve_logits(self):
        ids=np.array([0],'<i4');y=np.empty((1,129),'f4')
        for past in range(9):self.assertEqual(self.lib.nx_forward(self.session,ptr(ids),1,past,ptr(y),TRACE()),0)
        y.fill(123);self.assertEqual(self.lib.nx_forward(self.session,ptr(ids),1,9,ptr(y),TRACE()),-1);self.assertTrue((y==123).all());self.assertEqual(self.lib.nx_length(self.session),9)
        self.lib.nx_reset(self.session);ids[0]=129;self.assertEqual(self.lib.nx_forward(self.session,ptr(ids),1,0,ptr(y),TRACE()),-1)
        ids[0]=0;self.assertEqual(self.lib.nx_forward(self.session,ptr(ids),1,1,ptr(y),TRACE()),-4);self.assertTrue((y==123).all())
    def test_reduced_cache_has_two_heads(self):
        self.assertEqual(self.fixture['kv'],16);self.assertEqual(self.fixture['layers'],2)
        self.assertEqual(self.lib.nx_memory_bytes()>2*2*9*16*4,True)
        # At a multi-token position, mapping to the wrong KV head changes the
        # independent attention output; 14 query heads do not imply 14 caches.
        oracle=MiniOracle(self.arrays)
        for t in [0,127]:trace,_=oracle.forward(t)
        self.assertEqual(np.stack(oracle.k[0]).shape,(2,2,8));self.assertFalse(np.array_equal(trace[0,'attn'][:56],trace[0,'attn'][56:]))

if __name__=='__main__':unittest.main()
