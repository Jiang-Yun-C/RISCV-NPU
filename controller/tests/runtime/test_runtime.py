import ctypes as C
import json
from pathlib import Path
import random
import struct
import subprocess
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(Path(__file__).parent)]
from model_tools.export_tokenizer import export
from tokenizer_reference import CTokenizer,Decoder,Tokenizer

class Arena(C.Structure):
    _fields_=[('base',C.c_void_p),('address',C.c_uint32),('capacity',C.c_uint32),('used',C.c_uint32),('peak',C.c_uint32)]

class RuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.dir=Path(cls.tmp.name)
        lib=cls.dir/'lib.so'
        subprocess.run(['gcc','-std=c11','-O2','-shared','-fPIC',str(ROOT/'firmware/runtime/port/tokenizer.c'),str(ROOT/'firmware/runtime/port/runtime.c'),'-o',str(lib)],check=True)
        export(cls.dir/'tokenizer');cls.c=CTokenizer(lib,cls.dir/'tokenizer/tokenizer.nxt');cls.lib=cls.c.lib
        cls.lib.nxr_file_span.argtypes=[C.c_uint64,C.c_uint64,C.c_uint64,C.c_uint64,C.c_void_p]
        cls.lib.nxr_arena_init.argtypes=[C.c_void_p,C.c_void_p,C.c_uint32,C.c_uint32]
        cls.lib.nxr_alloc.argtypes=[C.c_void_p,C.c_uint64,C.c_uint64,C.c_uint32,C.c_void_p,C.c_void_p]
        cls.lib.nxr_arena_rewind.argtypes=[C.c_void_p]
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def test_wide_file_span_random_and_overflow(self):
        rng=random.Random(12)
        for _ in range(500):
            off=rng.randrange(1<<64);count=rng.randrange(1<<34);item=rng.randrange(1,1<<34);size=rng.randrange(1<<64);end=C.c_uint64(123)
            valid=count*item<1<<64 and off+count*item<=size
            rc=self.lib.nxr_file_span(off,count,item,size,C.byref(end));self.assertEqual(rc,0 if valid else -4)
            self.assertEqual(end.value,off+count*item if valid else 123)
        end=C.c_uint64();self.assertEqual(self.lib.nxr_file_span(1<<32,8,4,(1<<32)+32,C.byref(end)),0);self.assertEqual(end.value,(1<<32)+32)
    def test_arena_regions_alignment_exhaustion_rewind(self):
        raw=C.create_string_buffer(8192);base=(C.addressof(raw)+4095)&~4095;a=Arena()
        for address in (0x80000000,0xb8000000,0xbc000000,0xfffffff0):self.assertEqual(self.lib.nxr_arena_init(C.byref(a),base,address,4096),-4)
        self.assertEqual(self.lib.nxr_arena_init(C.byref(a),base,0xb4800000,4096),0)
        pointer=C.c_void_p();address=C.c_uint32()
        self.assertEqual(self.lib.nxr_alloc(C.byref(a),1,16,16,C.byref(pointer),C.byref(address)),0);first=pointer.value
        self.assertEqual(self.lib.nxr_alloc(C.byref(a),1,16,256,C.byref(pointer),C.byref(address)),0)
        self.assertEqual(pointer.value%256,0);self.assertEqual(address.value%256,0)
        before=(a.used,pointer.value,address.value)
        self.assertEqual(self.lib.nxr_alloc(C.byref(a),1,4096,16,C.byref(pointer),C.byref(address)),-4)
        self.assertEqual((a.used,pointer.value,address.value),before)
        self.lib.nxr_arena_rewind(C.byref(a));self.assertEqual(a.peak,272)
        self.lib.nxr_alloc(C.byref(a),1,16,16,C.byref(pointer),C.byref(address));self.assertEqual(pointer.value,first)
    def test_text_byte_limit(self):
        self.assertEqual(len(self.c.encode('1'*4096)),4096)
        with self.assertRaisesRegex(ValueError,'-4'):self.c.encode('1'*4097)
    def test_utf8_rejects_overlong_surrogate_truncation(self):
        for raw in (b'\xc0\x80',b'\xed\xa0\x80',b'\xf4\x90\x80\x80',b'\x80',b'\xe4\xb8'):
            with self.assertRaisesRegex(ValueError,'-12'):self.c.encode(raw)
    def test_encoding_failure_has_no_partial_publication(self):
        out=(C.c_uint32*2)(111,222);count=C.c_size_t(17)
        rc=self.lib.nxt_encode(C.byref(self.c.state),self.c.work,b'123456',6,out,2,C.byref(count))
        self.assertEqual(rc,-4);self.assertEqual(list(out),[111,222]);self.assertEqual(count.value,17)
    def test_decoder_retry_after_output_overflow(self):
        ids=self.c.encode('中文');d=Decoder();copy=bytes(d);out=C.create_string_buffer(100);count=C.c_size_t(7)
        rc=self.lib.nxt_decode(C.byref(self.c.state),C.byref(d),ids[0],0,0,out,0,C.byref(count))
        self.assertEqual(rc,-4);self.assertEqual(bytes(d),copy);self.assertEqual(count.value,7)
        self.assertEqual(self.c.decode(ids)[0],'中文')
    def test_special_tokens_and_padded_vocab(self):
        ids=self.c.encode('<|im_end|><tool_call>中</tool_call>');self.assertEqual(ids[0],151645)
        self.assertEqual(self.c.decode(ids)[0],'<tool_call>中</tool_call>')
        self.assertEqual(self.c.decode([151665,151935])[0],'')
    def test_template_rejects_unimplemented_tool_role(self):
        with self.assertRaisesRegex(ValueError,'-1'):self.c.template([{'role':'tool','content':'x'}])
    def test_table_header_offsets_counts_rejected(self):
        source=(self.dir/'tokenizer/tokenizer.nxt').read_bytes()
        for index,value in [(0,0),(1,2),(2,0),(3,1),(4,0xffffffff),(10,0xffffffff),(11,0),(12,0xffffffff),(15,127),(18,len(source)+16)]:
            raw=bytearray(source);struct.pack_into('<I',raw,index*4,value);storage=C.create_string_buffer(bytes(raw));t=Tokenizer()
            self.assertNotEqual(self.lib.nxt_init(C.byref(t),storage,len(raw)),0,(index,value))
    def test_official_normalization_and_fragments(self):
        self.assertEqual(self.c.encode('e\u0301'),self.c.encode('é'))
        self.assertEqual(self.c.encode('\u1100\u1161\u11a8'),self.c.encode('각'))
        # Every individual decoder return is valid UTF-8, even when a token ends
        # in the middle of an emoji scalar.
        text='中文🌍👩\u200d👦';actual,fragments=self.c.decode(self.c.encode(text));self.assertEqual(actual,text)
        for fragment in fragments:fragment.encode().decode('utf8')

if __name__=='__main__':unittest.main()
