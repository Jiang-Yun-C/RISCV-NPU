import ctypes,json,subprocess,tempfile,unittest,zlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
class Job(ctypes.Structure):
    _fields_=[(k,ctypes.c_uint32) for k in ('abi','opcode','input','output','words','xor_mask')]
class Driver(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.d=Path(cls.tmp.name)
        tools=json.loads((ROOT/'docs/spec/toolchain-lock.json').read_text())['tools'];cc=tools['host_cc']['path']
        flags=['-std=c11','-O2','-Wall','-Wextra','-Werror','-I',str(ROOT/'software/include'),'-I',str(ROOT/'firmware/drivers/accel')]
        src=str(ROOT/'firmware/drivers/accel/accel.c')
        subprocess.run([cc,*flags,'-shared','-fPIC',src,'-o',str(cls.d/'driver.so')],check=True,capture_output=True)
        subprocess.run([cc,*flags,src,str(ROOT/'tests/accel/host_state.c'),'-o',str(cls.d/'state')],check=True,capture_output=True)
        cls.lib=ctypes.CDLL(str(cls.d/'driver.so'));cls.lib.nx_accel_validate_job.argtypes=[ctypes.POINTER(Job)]
        cls.lib.nx_accel_crc32.argtypes=[ctypes.POINTER(ctypes.c_uint32),ctypes.c_uint32];cls.lib.nx_accel_crc32.restype=ctypes.c_uint32
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def test_state_machine_edges(self):
        result=subprocess.run([str(self.d/'state')],check=True,capture_output=True,text=True)
        self.assertIn('PASS host state:',result.stdout)
    def test_partition_boundaries(self):
        regions=json.loads((ROOT/'docs/spec/memory-map-v1.json').read_text())['ddr_regions']
        for r in regions:
            base=int(r['base'],0);end=base+r['size_bytes']
            for address in (base-16,base,base+16,end-16,end,end+16):
                for output in (False,True):
                    j=Job(1,0x54503133,0xac001000,0xba001000,4,0)
                    if output:j.output=address
                    else:j.input=address
                    allowed=any(int(v['base'],0)<=address and address+16<=int(v['base'],0)+v['size_bytes'] and
                        v['name'] in (('kv','workspace','shared_io') if output else ('weights','kv','workspace','shared_io')) for v in regions)
                    with self.subTest(address=hex(address),output=output):self.assertEqual(self.lib.nx_accel_validate_job(ctypes.byref(j)),0 if allowed else -4)
    def test_length_overflow_and_priority(self):
        for count in (0x40000000,0x80000000,0xffffffff):self.assertEqual(self.lib.nx_accel_validate_job(ctypes.byref(Job(1,7,0xac000000,0xba000000,count,0))),-4)
        for j,status in [(Job(1,7,0xac000000,0xba000000,4,0),-3),(Job(2,7,0,0,0,0),-2),(Job(1,7,0,0,0,0),-1),(Job(1,0x54503133,0xac000004,0xba000000,4,0),-5)]:self.assertEqual(self.lib.nx_accel_validate_job(ctypes.byref(j)),status)
    def test_overlap_and_shape(self):
        for offset in (0,16,32,48):self.assertEqual(self.lib.nx_accel_validate_job(ctypes.byref(Job(1,0x54503133,0xac000000,0xac000000+offset,16,0))),-4)
        self.assertEqual(self.lib.nx_accel_validate_job(ctypes.byref(Job(1,0x54503133,0xac000000,0xba000000,17,0))),-3)
    def test_program_crc(self):
        data=bytes(range(128));words=(ctypes.c_uint32*32).from_buffer_copy(data)
        self.assertEqual(self.lib.nx_accel_crc32(words,len(data)),zlib.crc32(data))
