import ctypes as C,json,subprocess,tempfile,unittest
from pathlib import Path
import numpy as np
from software.reference.runtime import library,Weights,Matrix,ptr,TRACE
from tests.opt09.fixture import Oracle
from tests.opt09.numeric import Identity,bind
from scripts.cocotb_case import validate
from scripts.verify_opt09 import receipt
ROOT=Path(__file__).resolve().parents[2]

class Contract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.libs=[];ref=ROOT/'variants/opt09/firmware/runtime/reference'
        for mode in (1,0):
            path=Path(cls.tmp.name)/f'mode{mode}.so'
            subprocess.run(['gcc','-std=c11','-O2','-ffp-contract=off','-fno-fast-math','-fopenmp','-shared','-fPIC','-DNX_OPT09_TEST',f'-DNX_OPT09_PREFIX={mode}','-I',str(ref),str(ref/'nx_reference.c'),'-lm','-o',str(path)],check=True)
            lib=library(path);bind(lib);cls.libs.append(lib)
        cls.o=Oracle();cls.w=Weights();o=cls.o
        cls.w.embedding=Matrix(ptr(o.qe),ptr(o.se),None,32,8);cls.w.norm=ptr(o.norm);cls.w.inv_freq=ptr(o.inv)
        for l in range(2):
            cls.w.layer[l].norm1=ptr(o.n1[l]);cls.w.layer[l].norm2=ptr(o.n2[l])
            for j,(name,n,k) in enumerate(zip(('q','k','v','o','gate','up','down'),(8,4,4,8,16,16,8),(8,8,8,8,8,8,16))):
                setattr(cls.w.layer[l],name,Matrix(ptr(o.q[l,j]),ptr(o.s[l,j]),ptr(o.bias[l,j]) if j<3 else None,n,k))
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def setUp(self):
        self.key=Identity();C.memset(C.byref(self.key),1,C.sizeof(self.key));self.key.abi=1;self.key.start_position=0;self.key.context_limit=512;self.key.flags=0
        self.ids=np.array([1,2,3],'i4');self.sessions=[]
    def make(self,lib=None):
        lib=lib or self.libs[0];s=lib.nx_create(C.byref(self.w),1);self.assertTrue(s);self.sessions.append((lib,s));return lib,s
    def tearDown(self):
        for lib,s in self.sessions:lib.nx_destroy(s)
    def prepare(self,lib,s):self.assertEqual(lib.nx_prefix_prepare(s,C.byref(self.key),ptr(self.ids),3),0)
    def restore(self,lib,s):return lib.nx_prefix_restore(s,C.byref(self.key),ptr(self.ids),3)
    def test_session_local_and_reset_cannot_resurrect(self):
        lib,a=self.make();_,b=self.make();self.prepare(lib,a)
        self.assertEqual(self.restore(lib,b),0);self.assertEqual(self.restore(lib,a),1)
        lib.nx_reset(a);self.assertEqual(self.restore(lib,a),0)
    def test_rollback_uses_full_cold_path_with_same_numbers(self):
        outputs=[]
        for lib in self.libs:
            _,s=self.make(lib);self.prepare(lib,s);hit=self.restore(lib,s)
            self.assertEqual(hit,int(lib is self.libs[0]));y=np.empty(32,'f4')
            for t in ([4] if hit else [1,2,3,4]):
                ids=np.array([t],'i4');self.assertEqual(lib.nx_forward(s,ptr(ids),1,lib.nx_length(s),ptr(y),TRACE()),0)
            outputs.append(y.copy())
        np.testing.assert_array_equal(outputs[0].view('u4'),outputs[1].view('u4'))
    def test_all_digest_bytes_and_scalar_fields_invalidate(self):
        lib,s=self.make()
        for byte in range(160):
            self.prepare(lib,s);key=Identity.from_buffer_copy(self.key);C.cast(C.byref(key),C.POINTER(C.c_uint8))[byte]^=1
            self.assertEqual(lib.nx_prefix_restore(s,C.byref(key),ptr(self.ids),3),0)
            self.assertEqual(lib.nx_length(s),0);self.assertEqual(self.restore(lib,s),0)
        for field in ('abi','start_position','context_limit','flags'):
            self.prepare(lib,s);key=Identity.from_buffer_copy(self.key);setattr(key,field,getattr(key,field)+1)
            self.assertEqual(lib.nx_prefix_restore(s,C.byref(key),ptr(self.ids),3),0)
    def test_unsealed_or_invalid_identity_and_invalid_token_fail_closed(self):
        lib,s=self.make();self.prepare(lib,s);key=Identity.from_buffer_copy(self.key);key.model[:]=bytes(32)
        self.assertEqual(lib.nx_prefix_configure(s,C.byref(key)),-1);self.assertEqual(self.restore(lib,s),0)
        self.prepare(lib,s);id=np.array([-1],'i4');y=np.full(32,123,'f4')
        self.assertEqual(lib.nx_forward(s,ptr(id),1,3,ptr(y),TRACE()),-1)
        self.assertTrue((y==123).all());self.assertFalse(lib.nx_logits_v2(s));self.assertEqual(self.restore(lib,s),0)
    def test_numeric_failure_and_bad_past_require_rebuild(self):
        lib,s=self.make();self.prepare(lib,s);old=self.o.n1[0,0];self.o.n1[0,0]=np.nan
        try:
            id=np.array([4],'i4');self.assertEqual(lib.nx_forward(s,ptr(id),1,3,None,TRACE()),-2)
            self.assertEqual(self.restore(lib,s),0)
        finally:self.o.n1[0,0]=old
        self.prepare(lib,s);self.assertEqual(lib.nx_forward(s,ptr(id),1,2,None,TRACE()),-4);self.assertEqual(self.restore(lib,s),0)
        self.prepare(lib,s);self.assertEqual(self.restore(lib,s),1)
    def test_empty_skip_wrong_xml_and_nonfinal_receipts_rejected(self):
        for xml in (None,'<testsuites/>','<testsuites><testcase name="opt09_prefix" classname="test_opt09"><skipped/></testcase></testsuites>','<testsuites><testcase name="wrong" classname="test_opt09"/></testsuites>'):
            with tempfile.TemporaryDirectory() as d:
                p=Path(d)
                if xml is not None:(p/'results.xml').write_text(xml)
                with self.assertRaises(ValueError):validate(p,{'task':'OPT09'})
        for state in ('RUNNING','FAIL'):
            with tempfile.TemporaryDirectory() as d:
                p=Path(d);(p/'manifest.json').write_text(json.dumps(dict(status=state,exit_code=1)))
                with self.assertRaises(ValueError):receipt(p)

if __name__=='__main__':unittest.main()
