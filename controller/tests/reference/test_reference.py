import ctypes as C
import json
from pathlib import Path
import sys
import tempfile
import unittest
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(Path(__file__).parent))
from model_tools import numeric_v1 as num
from software.reference.runtime import build,library,ptr,Matrix,Runtime

class CReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.path=Path(cls.tmp.name)/'libnx.so'
        build(cls.path);cls.lib=library(cls.path)
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def test_round_even_zero_subnormal_tail(self):
        x=np.zeros((4,65),np.float32);x[0,:9]=[127,-127,0.5,-0.5,1.5,-1.5,2.5,-2.5,0]
        x[1,64]=np.nextafter(np.float32(0),np.float32(1));x[2]=np.finfo(np.float32).max
        q=np.empty(x.shape,np.int8);s=np.empty((4,2),np.float32)
        self.assertEqual(self.lib.nx_quantize(ptr(x),4,65,ptr(q),ptr(s)),0)
        eq,es=num.quantize(x);np.testing.assert_array_equal(q,eq);np.testing.assert_array_equal(s.view('u4'),es.view('u4'))
    def test_nonfinite_quantization_no_partial_output(self):
        for bad in [np.nan,np.inf,-np.inf]:
            x=np.array([[1,bad]],np.float32);q=np.full((1,2),99,np.int8);s=np.full((1,1),42,np.float32)
            self.assertEqual(self.lib.nx_quantize(ptr(x),1,2,ptr(q),ptr(s)),-2)
            self.assertTrue((q==99).all() and (s==42).all())
    def test_group_dots_bias_tail(self):
        rng=np.random.default_rng(7);x=rng.normal(size=(4,65)).astype('f4');w=rng.normal(size=(129,65)).astype('f4')
        aq,sa=num.quantize(x);wq,sw=num.quantize(w);b=rng.normal(size=129).astype('f4')
        expected,dots=num.linear_quantized(aq,sa,wq,sw,b)
        padded=np.pad(wq,((0,0),(0,63)));matrix=Matrix(ptr(padded),ptr(sw),ptr(b),129,65)
        y=np.empty_like(expected);d=np.empty_like(dots)
        self.assertEqual(self.lib.nx_linear(ptr(x),4,C.byref(matrix),ptr(y),ptr(d)),0)
        np.testing.assert_array_equal(d,dots);np.testing.assert_array_equal(y.view('u4'),expected.view('u4'))
    def test_norm_tree_and_overflow(self):
        rng=np.random.default_rng(1);x=rng.normal(size=(4,896)).astype('f4');g=rng.normal(size=896).astype('f4');y=np.empty_like(x)
        self.assertEqual(self.lib.nx_norm(ptr(x),ptr(g),4,896,ptr(y)),0)
        np.testing.assert_array_equal(y,num.rmsnorm(x,g))
        x.fill(np.finfo(np.float32).max)
        self.assertEqual(self.lib.nx_norm(ptr(x),ptr(g),4,896,ptr(y)),-2)
    def test_rope_half_pair_and_limits(self):
        rng=np.random.default_rng(19);x=rng.normal(size=(4,14,64)).astype('f4');original=x.copy()
        inv=(np.float32(1)/np.power(np.float32(1e6),np.arange(0,64,2,dtype='f4')/np.float32(64)))
        self.assertEqual(self.lib.nx_rope(ptr(x),4,14,508,ptr(inv)),0)
        np.testing.assert_allclose(x,num.rope(original,np.arange(508,512)),atol=2e-5,rtol=2e-5)
        self.assertEqual(self.lib.nx_rope(ptr(x),4,14,32767,ptr(inv)),-1)
    def test_swiglu_extreme_finite(self):
        gate=np.array([-1000,-100,-1,0,1,100,1000],np.float32);up=np.ones_like(gate);out=np.empty_like(gate)
        self.assertEqual(self.lib.nx_swiglu(ptr(gate),ptr(up),len(gate),ptr(out)),0)
        np.testing.assert_allclose(out,num.swiglu(gate,up),atol=2e-6,rtol=2e-6)
    def test_shape_and_rounding_mode(self):
        x=np.ones((1,64),np.float32);q=np.zeros((1,64),np.int8);s=np.zeros((1,1),np.float32)
        self.assertEqual(self.lib.nx_quantize(ptr(x),0,64,ptr(q),ptr(s)),-1)
        libc=C.CDLL(None)
        old=libc.fegetround()
        try:
            self.assertEqual(libc.fesetround(0x400),0) # x86 FE_DOWNWARD
            self.assertEqual(self.lib.nx_quantize(ptr(x),1,64,ptr(q),ptr(s)),-1)
        finally:libc.fesetround(old)
    def test_greedy_tie_and_nan(self):
        logits=np.zeros(151936,np.float32);logits[7]=logits[100]=2;token=np.full(1,-1,np.int32)
        self.assertEqual(self.lib.nx_greedy(ptr(logits),ptr(token)),0);self.assertEqual(token[0],7)
        logits[0]=np.nan;token[0]=-1
        self.assertEqual(self.lib.nx_greedy(ptr(logits),ptr(token)),-2);self.assertEqual(token[0],-1)

class SessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.path=Path(cls.tmp.name)/'libnx.so';build(cls.path)
        cls.r=Runtime(cls.path,2)
    @classmethod
    def tearDownClass(cls):cls.r.close();cls.tmp.cleanup()
    def setUp(self):self.r.reset()
    def test_invalid_tokens_and_chunk(self):
        for ids in [[-1],[151936],[1.5],[],[1]*9]:
            with self.assertRaises(ValueError):self.r.forward(ids)
            self.assertEqual(self.r.length,0)
    def test_noncontiguous_append(self):
        with self.assertRaises(ValueError):self.r.forward([1],past=1)
        self.assertEqual(self.r.length,0)
    def test_reset_and_chunk_identity(self):
        a=self.r.forward([0,255,256,1023]);kv=self.r.cache();self.r.reset()
        self.assertEqual(self.r.cache().shape,(24,2,0,128))
        b=np.concatenate([self.r.forward([v]) for v in [0,255,256,1023]])
        np.testing.assert_array_equal(a,b);np.testing.assert_array_equal(kv,self.r.cache())
    def test_prompt_bounds_and_memory(self):
        for ids in [[],[1]*513]:
            with self.assertRaises(ValueError):self.r.generate(ids)
        self.assertLess(self.r.profile()['session_heap_bytes'],32*2**20)
    def test_numeric_failure_invalidates_session_without_logits(self):
        from software.reference.runtime import Weights,TRACE
        bad=Weights.from_buffer_copy(self.r.weights)
        gamma=np.full(896,np.nan,np.float32);bad.norm=ptr(gamma)
        session=self.r.lib.nx_create(C.byref(bad),2)
        self.assertTrue(session)
        try:
            ids=np.array([0],np.int32);out=np.full((1,151936),17,np.float32)
            self.assertEqual(self.r.lib.nx_forward(session,ptr(ids),1,0,ptr(out),TRACE()),-2)
            self.assertTrue((out==17).all());self.assertEqual(self.r.lib.nx_length(session),-1)
            self.assertEqual(self.r.lib.nx_forward(session,ptr(ids),1,0,ptr(out),TRACE()),-4)
        finally:self.r.lib.nx_destroy(session)

class FixtureTests(unittest.TestCase):
    def test_reject_corrupt_missing_nonfinite_and_wrong_threshold(self):
        from fixture_io import load,compare_case
        from evidence import sha256,write_json
        fixture=ROOT/'tests/cocotb/fixtures/golden/manifest.json'
        if not fixture.exists():self.fail('published T11 fixture missing; generate before regression')
        import shutil
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);m=json.loads(fixture.read_text())
            for c in m['cases']:
                p=base/c['path'];p.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(fixture.parent/c['path'],p)
            write_json(base/'manifest.json',m);load(base/'manifest.json');c=m['cases'][0]
            src=base/c['path']
            self.assertGreater(compare_case(base/'manifest.json',c['path'],src),0)
            with np.load(src) as f:arrays={k:f[k] for k in f.files}
            arrays['dots']=arrays['dots'].copy();arrays['dots'].flat[0]+=1
            np.savez(base/'bad.npz',**arrays)
            with self.assertRaisesRegex(AssertionError,'exact'):compare_case(base/'manifest.json',c['path'],base/'bad.npz')
            arrays.pop('dots');np.savez(base/'bad.npz',**arrays)
            with self.assertRaisesRegex(AssertionError,'missing'):compare_case(base/'manifest.json',c['path'],base/'bad.npz')
            with np.load(src) as f:arrays={k:f[k] for k in f.files}
            arrays['y']=arrays['y'].copy();arrays['y'].flat[0]=np.nan;np.savez(base/'bad.npz',**arrays)
            with self.assertRaisesRegex(AssertionError,'nonfinite'):compare_case(base/'manifest.json',c['path'],base/'bad.npz')
            m['thresholds_sha256']='0'*64;write_json(base/'manifest.json',m)
            with self.assertRaisesRegex(AssertionError,'threshold'):load(base/'manifest.json')

if __name__=='__main__':unittest.main()
