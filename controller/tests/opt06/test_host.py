import ctypes as C,json,random,subprocess,tempfile,unittest
from pathlib import Path
from tests.runtime.tokenizer_reference import official
from software.boot.t25_stream import Stream,timing
ROOT=Path(__file__).resolve().parents[2]
class Host(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();d=Path(cls.tmp.name)
        cls.ref,_=official();cls.libs=[]
        b=ROOT/'build/OPT05/opt05-freeze-20261019-v6/repo/firmware/runtime/port';v=ROOT/'variants/opt06/firmware/runtime/port'
        for i,port in enumerate((b,v)):
            lib=d/f'lib{i}.so';cmd=['gcc','-O2','-std=c11','-shared','-fPIC','-I',str(port),'-I',str(b),str(ROOT/'tests/opt06/host.c'),str(port/'runtime.c'),str(b/'tokenizer.c')]
            cmd+=['-DBASELINE'] if i==0 else [str(v/'stream.c')]
            subprocess.run(cmd+['-o',str(lib)],check=True);dll=C.CDLL(str(lib));dll.events.restype=C.c_char_p;cls.libs.append(dll)
        cls.table=(ROOT/'tests/cocotb/fixtures/runtime/tokenizer/tokenizer.nxt').read_bytes();cls.storage=C.create_string_buffer(cls.table)
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def run_case(self,ids,prompt=1,maximum=None,capacity=16384,enabled=1):
        maximum=maximum or min(128,len(ids));args=(C.c_uint32*len(ids))(*ids);results=[]
        for lib in self.libs:
            out=C.create_string_buffer(16384);meta=(C.c_uint32*136)()
            rc=lib.replay(self.storage,len(self.table),args,len(ids),prompt,maximum,capacity,enabled,out,meta)
            results.append((rc,list(meta),out.raw[:meta[4]],lib.events().decode()))
        return results
    def test_random_decode_and_ablation_match_original_runtime(self):
        rng=random.Random(601)
        for j in range(100):
            ids=self.ref.encode(''.join(rng.choices('中文🌍AB\n👩\u200d👦',k=12)),add_special_tokens=False).ids+[151645]
            baseline,new=self.run_case(ids,enabled=j%2)
            self.assertEqual(new[0],0);self.assertEqual(new[1][:4],baseline[1][:4]);self.assertEqual(new[1][8:8+new[1][2]],baseline[1][8:8+baseline[1][2]])
            actual=ids[:new[1][2]];self.assertEqual(new[2].decode(),self.ref.decode(actual,skip_special_tokens=True))
            if j%2:
                s=Stream()
                for line in new[3].splitlines():s.feed(line)
                self.assertTrue(s.ended);self.assertEqual(s.text,new[2].decode());self.assertEqual(s.ids,actual)
            else:self.assertEqual(new[3],'')
    def test_eos_empty_context_maximum(self):
        for ids,p,m in [([151645],1,8),([151665,151645],1,8),([0,151645],511,8),([0],512,1),([0,1],1,1)]:
            a,b=self.run_case(ids,p,m);self.assertEqual(a[1][:4],b[1][:4]);self.assertEqual(b[2].decode(),self.ref.decode(b[1][8:8+b[1][2]],skip_special_tokens=True))
    def test_capacity_cannot_commit(self):
        ids=self.ref.encode('中🌍',add_special_tokens=False).ids
        a,b=self.run_case(ids,capacity=2)
        self.assertEqual(a[0],0);self.assertEqual(b[0],-4);self.assertEqual(b[1][0],4);self.assertEqual(b[1][2],0)
        s=Stream()
        for line in b[3].splitlines():s.feed(line)
        self.assertTrue(s.aborted);self.assertFalse(s.ended)
    def test_bad_frames_rejected(self):
        _,r=self.run_case([0,151645]);lines=r[3].splitlines()
        for bad in [lines[0].replace('STREAM 1','STREAM 2'),lines[1].replace('index=0000000000000001','index=0000000000000002')]:
            s=Stream()
            if bad!=lines[0]:s.feed(lines[0])
            with self.assertRaises(ValueError):s.feed(bad)
if __name__=='__main__':unittest.main()
