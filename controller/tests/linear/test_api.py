import ctypes,json,subprocess,sys,tempfile,unittest
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(Path(__file__).parent))
from prepare_linear import oracle
class Stats(ctypes.Structure):
    _fields_=[(k,ctypes.c_uint64) for k in 'session sequence tick_hz elapsed_ticks validate_ticks quantize_ticks upload_ticks execute_ticks download_ticks fallback_ticks other_ticks backend_cycles axi_read_bytes axi_write_bytes upload_bytes download_bytes macs'.split()]+[(k,ctypes.c_uint32) for k in 'valid_counters route fallback_reason output_valid'.split()]+[('status',ctypes.c_int32)]
class API(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.path=Path(cls.tmp.name)/'api.so'
        tools=json.loads((ROOT/'docs/spec/toolchain-lock.json').read_text())['tools'];src=ROOT/'firmware/drivers/accel'
        subprocess.run([tools['host_cc']['path'],'-std=c11','-O2','-ffp-contract=off','-fno-fast-math','-Wall','-Wextra','-Werror','-shared','-fPIC','-I'+str(ROOT/'software/include'),'-I'+str(src),str(src/'accel.c'),str(src/'linear_api.c'),str(ROOT/'tests/linear/api_host.c'),'-o',str(cls.path)],check=True,capture_output=True)
        cls.lib=ctypes.CDLL(str(cls.path));cls.lib.api_run.argtypes=[ctypes.c_void_p]*5+[ctypes.c_uint32]*3+[ctypes.c_int,ctypes.POINTER(Stats),ctypes.c_void_p,ctypes.c_void_p]
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def data(self,m=8,n=129,k=896):
        rng=np.random.default_rng(1515);x=rng.normal(0,.2,(m,k)).astype('f4');w=rng.integers(-127,128,(n,k),dtype='i1');sw=rng.uniform(.001,.1,(n,k//64)).astype('f4');bias=rng.normal(0,.1,n).astype('f4')
        return x,w,sw,bias
    def run_api(self,data,mode=0):
        x,w,sw,bias=data;m,k=x.shape;n=w.shape[0];y=np.full((m,n),100,dtype='f4');aq=np.empty((m,k),dtype='i1');sa=np.empty((m,k//64),dtype='f4');stats=Stats()
        args=[None if v is None else v.ctypes.data for v in (x,w,sw,bias,y)]
        status=self.lib.api_run(*args,m,n,k,mode,ctypes.byref(stats),aq.ctypes.data,sa.ctypes.data)
        return status,y,aq,sa,stats
    def test_cpu_route_and_quantization(self):
        for k in (896,4864):
            for m in (1,4,8):
                with self.subTest(k=k,m=m):
                    x,w,sw,b=self.data(m,129,k);status,y,aq,sa,s=self.run_api((x,w,sw,b));self.assertEqual(status,0)
                    amax=np.max(np.abs(x.reshape(m,-1,64)),axis=2);refscale=np.maximum(amax/np.float32(127),np.finfo('f4').tiny).astype('f4');refaq=np.rint(x.reshape(m,-1,64)/refscale[:,:,None]).astype('i1').reshape(m,k)
                    np.testing.assert_array_equal(sa.view('u4'),refscale.view('u4'));np.testing.assert_array_equal(aq,refaq)
                    np.testing.assert_array_equal(y,oracle(refaq,refscale,w,sw,b)['y']);self.assertEqual(s.output_valid,1);self.assertEqual(s.macs,m*129*k);self.assertGreater(s.fallback_ticks,0)
    def test_zero_min_normal_and_ties(self):
        x,w,sw,b=self.data(1,3);x[:]=0;x[0,:6]=[127,2.5,3.5,-2.5,-3.5,0];x[0,64]=np.nextafter(np.float32(0),np.float32(1))
        status,y,aq,sa,s=self.run_api((x,w,sw,None));self.assertEqual(status,0);self.assertEqual(list(aq[0,:6]),[127,2,4,-2,-4,0]);self.assertEqual(sa[0,1],np.finfo('f4').tiny);self.assertEqual(sa[0,2],0)
    def test_invalid_numeric_preserves_output(self):
        for kind in ('nan','inf','minus128','negative-scale','subnormal-scale','zero-scale-nonzero','bias-nan'):
            data=list(self.data(1,3));x,w,sw,b=data
            if kind=='nan':x[0,0]=np.nan
            if kind=='inf':x[0,0]=np.inf
            if kind=='minus128':w[0,0]=-128
            if kind=='negative-scale':sw[0,0]=-1
            if kind=='subnormal-scale':sw[0,0]=np.nextafter(np.float32(0),np.float32(1))
            if kind=='zero-scale-nonzero':sw[0,0]=0
            if kind=='bias-nan':b[0]=np.nan
            with self.subTest(kind=kind):
                status,y,aq,sa,s=self.run_api(data);self.assertEqual(status,-9);self.assertTrue(np.all(y==100));self.assertEqual(s.output_valid,0)
    def test_transport_failures_and_stale_completion(self):
        for mode,status in ((1,-11),(2,-7),(3,-8)):
            with self.subTest(mode=mode):
                result,y,aq,sa,s=self.run_api(self.data(1,3),mode);self.assertEqual(result,status);self.assertEqual(s.output_valid,0);self.assertEqual(s.sequence,1)
if __name__=='__main__':unittest.main()
