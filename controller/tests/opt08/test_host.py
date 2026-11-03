import ctypes as C
import subprocess,tempfile,unittest
from pathlib import Path
import numpy as np
from model_tools.numeric_v1 import quantize
ROOT=Path(__file__).resolve().parents[2]
class Host(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.libs=[]
        ref=ROOT/'variants/opt08/firmware/runtime/reference'
        for mode in (0,1):
            p=Path(cls.tmp.name)/f'mode{mode}.so'
            subprocess.run(['gcc','-std=c11','-O2','-fopenmp','-ffp-contract=off','-fno-fast-math','-shared','-fPIC','-DNX_SMALL',f'-DNX_OPT08_REUSE={mode}','-I',str(ref),str(ref/'nx_reference.c'),str(ROOT/'tests/opt08/small.c'),'-lm','-o',str(p)],check=True)
            lib=C.CDLL(str(p));lib.replay.argtypes=[C.c_int,C.c_void_p,C.c_void_p];lib.replay.restype=C.c_int
            lib.nx_quantize.argtypes=[C.c_void_p,C.c_int,C.c_int,C.c_void_p,C.c_void_p];lib.nx_quantize.restype=C.c_int
            cls.libs.append(lib)
        p=Path(cls.tmp.name)/'full.so'
        subprocess.run(['gcc','-std=c11','-O2','-fopenmp','-ffp-contract=off','-fno-fast-math','-shared','-fPIC','-I',str(ref),str(ref/'nx_reference.c'),'-lm','-o',str(p)],check=True)
        cls.full=C.CDLL(str(p));cls.full.nx_quantize.argtypes=[C.c_void_p,C.c_int,C.c_int,C.c_void_p,C.c_void_p];cls.full.nx_quantize.restype=C.c_int
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def test_small_forward_ids_reset_and_atomic_failure(self):
        results=[]
        for lib in self.libs:
            data=np.empty(64*3,np.float32);meta=np.zeros(12,np.uint64)
            self.assertEqual(lib.replay(0,data.ctypes.data,meta.ctypes.data),0)
            self.assertEqual(tuple(meta[4:8]),(0,0,0,1))
            self.assertEqual(meta[0],24 if lib==self.libs[0] else 15)
            self.assertEqual(meta[1],0 if lib==self.libs[0] else 9)
            results.append((data.copy(),meta.copy()))
        np.testing.assert_array_equal(results[0][0].view('u4'),results[1][0].view('u4'))
        np.testing.assert_array_equal(results[0][1][2:],results[1][1][2:])
    def test_tail_extremes_and_half_ties(self):
        rng=np.random.default_rng(20261019)
        for k in (1,63,64):
            x=rng.normal(size=(4,k)).astype('f4');x[0]=0;x[1,0]=np.finfo('f4').tiny
            if k==64:x[2]=np.arange(64,dtype='f4')-31.5
            aq,sa=quantize(x)
            for lib in self.libs:
                q=np.empty_like(aq);s=np.empty_like(sa)
                self.assertEqual(lib.nx_quantize(x.ctypes.data,4,k,q.ctypes.data,s.ctypes.data),0)
                np.testing.assert_array_equal(q,aq);np.testing.assert_array_equal(s.view('u4'),sa.view('u4'))
    def test_nonfinite_preserves_outputs(self):
        for lib in self.libs:
            for value in (np.nan,np.inf,-np.inf):
                x=np.ones((1,64),'f4');x[0,-1]=value;q=np.full_like(x,77,dtype='i1');s=np.full((1,1),123,'f4')
                self.assertEqual(lib.nx_quantize(x.ctypes.data,1,64,q.ctypes.data,s.ctypes.data),-2)
                self.assertTrue((q==77).all());self.assertTrue((s==123).all())
    def test_production_width_and_k65_tail(self):
        rng=np.random.default_rng(7)
        for k in (65,896,4864):
            x=rng.normal(size=(4,k)).astype('f4');x[0]=np.float32(-0.0);x[1,0]=np.finfo('f4').max;x[2]=np.nextafter(np.float32(0),np.float32(1))
            aq,sa=quantize(x);q=np.empty_like(aq);s=np.empty_like(sa)
            self.assertEqual(self.full.nx_quantize(x.ctypes.data,4,k,q.ctypes.data,s.ctypes.data),0)
            np.testing.assert_array_equal(q,aq);np.testing.assert_array_equal(s.view('u4'),sa.view('u4'))
if __name__=='__main__':unittest.main()
