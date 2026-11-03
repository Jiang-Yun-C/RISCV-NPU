import ctypes as C
from pathlib import Path
import subprocess,tempfile,unittest
import numpy as np
from software.reference.runtime import library,ptr
from tests.opt07.host import samples
ROOT=Path(__file__).resolve().parents[2]

class Host(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();p=Path(cls.temp.name)/'test.so'
        subprocess.run(['gcc','-std=c11','-O2','-ffp-contract=off','-fno-fast-math','-fopenmp','-shared','-fPIC','-I',str(ROOT/'build/OPT05/opt05-freeze-20261019-v6/repo/firmware/runtime/reference'),str(ROOT/'variants/opt07/firmware/runtime/reference/nx_reference.c'),'-lm','-o',str(p)],check=True)
        cls.lib=library(p);cls.lib.nx_opt07_configure.argtypes=[C.c_int,C.c_int]
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()
    def call(self,mode,g,u,force=0):
        self.assertEqual(self.lib.nx_opt07_configure(mode,force),0);y=np.empty_like(g)
        self.assertEqual(self.lib.nx_swiglu(ptr(g),ptr(u),len(g),ptr(y)),0);return y
    def test_guarded_matches_original_including_zero_sign(self):
        for _,g,u in samples():
            np.testing.assert_array_equal(self.call(3,g,u).view('u4'),self.call(0,g,u).view('u4'))
    def test_random_input_and_signed_up(self):
        rng=np.random.default_rng(19)
        for _ in range(48):
            g=rng.uniform(-128,128,4864).astype('f4');u=rng.uniform(-100,100,4864).astype('f4')
            np.testing.assert_array_equal(self.call(3,g,u).view('u4'),self.call(0,g,u).view('u4'))
    def test_every_lut_boundary_and_neighbours(self):
        x=np.arange(257,dtype='f4')/16
        g=np.concatenate([np.nextafter(x,-np.inf),x,np.nextafter(x,np.inf),np.array([16.5,17.,np.nextafter(np.float32(17),-np.inf)],np.float32)])
        u=np.resize(np.array([0.,-0.,1.,-1.,127.,1e10],np.float32),len(g))
        np.testing.assert_array_equal(self.call(3,g,u).view('u4'),self.call(0,g,u).view('u4'))
    def test_fallback_and_configuration_rejection(self):
        for mode in range(4):
            _,g,u=next(iter(samples()))
            np.testing.assert_array_equal(self.call(mode,g,u,1).view('u4'),self.call(0,g,u).view('u4'))
        for mode,force in [(-1,0),(4,0),(3,2)]:self.assertEqual(self.lib.nx_opt07_configure(mode,force),-1)
    def test_nonfinite_rejected_before_any_write(self):
        for mode in range(4):
            self.lib.nx_opt07_configure(mode,0)
            for val in [np.nan,np.inf,-np.inf]:
                for field in [0,1]:
                    g=np.ones(65,np.float32);u=g.copy();y=np.full(65,123,np.float32)
                    [g,u][field][-1]=val
                    self.assertEqual(self.lib.nx_swiglu(ptr(g),ptr(u),65,ptr(y)),-2);self.assertTrue((y==123).all())

if __name__=='__main__':unittest.main()
