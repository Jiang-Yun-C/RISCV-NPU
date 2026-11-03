import ctypes
import hashlib
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'software/boot'),str(ROOT/'tests/boot/sd'),str(ROOT/'tests/cocotb')]
from sd_image import build,audit,header,digest
from card import crc7,crc16

class SdTests(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.d=Path(self.temp.name)
    def image(self):
        app=self.d/'app';app.write_bytes(bytes(range(256))*9)
        model=ROOT/'tests/cocotb/fixtures/model_pack/legal-tail/model.nxpack'
        return app,model,self.d/'card.img'
    def test_rebuild_and_all_offsets(self):
        a,m,p=self.image();first=build(a,m,p);other=self.d/'repeat.img';second=build(a,m,other)
        self.assertEqual(first,second);self.assertEqual(p.read_bytes(),other.read_bytes());self.assertEqual(audit(p),first)
        b=p.read_bytes();self.assertEqual(b[512:512+a.stat().st_size],a.read_bytes());start=struct.unpack_from('<I',b,68)[0]
        self.assertEqual(b[start*512:start*512+m.stat().st_size],m.read_bytes())
    def test_truncation_and_trailing_sectors(self):
        a,m,p=self.image();build(a,m,p);raw=p.read_bytes()
        for invalid in (raw[:-1],raw[:-512],raw+bytes(512)):
            p.write_bytes(invalid)
            with self.assertRaises(ValueError):audit(p)
    def test_crc_and_payload_damage(self):
        a,m,p=self.image();build(a,m,p);raw=p.read_bytes()
        for offset in (20,512,len(raw)-513):
            b=bytearray(raw);b[offset]^=1;p.write_bytes(b)
            with self.assertRaises(ValueError):audit(p)
    def test_rehashed_invalid_media_spans(self):
        a,m,p=self.image();build(a,m,p);raw=bytearray(p.read_bytes());struct.pack_into('<I',raw,68,1);struct.pack_into('<I',raw,508,zlib.crc32(raw[:508]));p.write_bytes(raw)
        with self.assertRaises(ValueError):audit(p)
    def test_address_and_entry_boundaries(self):
        for base,entry,n in ((0x10000,0x10000,100),(0xb7ff0000,0xb7ff0000,1),(0xb4000000,0xb4000001,10),(0xb4000000,0xb4000010,16)):
            with self.assertRaises(ValueError):header(n,'00'*32,64,'00'*32,base,entry)
    def test_sd_crc_known_vectors(self):
        self.assertEqual(crc7(bytes.fromhex('4000000000')),0x95);self.assertEqual(crc7(bytes.fromhex('48000001aa')),0x87)
        self.assertEqual(crc16(bytes([255])*512),0x7fa1);self.assertEqual(crc16(b'123456789'),0x31c3)
    def test_rom_sha_against_independent_hashlib(self):
        cc=shutil.which('gcc');self.assertIsNotNone(cc)
        library=self.d/'sha.so';subprocess.run([cc,'-shared','-fPIC','-O2',str(ROOT/'firmware/boot/sd_loader/sha256.c'),'-o',str(library)],check=True)
        lib=ctypes.CDLL(str(library));lib.nx_sha_init.argtypes=[ctypes.c_void_p];lib.nx_sha_add.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_uint];lib.nx_sha_end.argtypes=[ctypes.c_void_p,ctypes.c_void_p]
        for n in (0,1,55,56,63,64,65,128,513,8193):
            data=bytes((i*29+7)%256 for i in range(n));state=ctypes.create_string_buffer(256);out=ctypes.create_string_buffer(32);lib.nx_sha_init(state)
            for i in range(0,n,17):block=data[i:i+17];lib.nx_sha_add(state,block,len(block))
            lib.nx_sha_end(state,out);self.assertEqual(out.raw,hashlib.sha256(data).digest())
if __name__=='__main__':unittest.main()
