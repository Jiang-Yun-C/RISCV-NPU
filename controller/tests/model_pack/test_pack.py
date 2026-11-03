"""Acceptance tests for real corruption, independent numerics and loader bounds."""
import copy
import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from model_tools.export import write_pack
from model_tools.verify_pack import verify, PackError
from model_tools.pack_budget import calculate
from generate_fixtures import malformed, reseal, generate
from check_fixtures import check


class PackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.path = Path(cls.temp.name)
        cls.meta = dict(format='model-pack-v1', profile='fixture-v1', numeric_version='w8a8-g64-fp32-v1', group_size=64)
        w = np.zeros((3,65), dtype=np.float32)
        w[0,:3] = [127,1.5,-2.5]
        w[-1,-1] = -1
        write_pack(cls.path/'good.nxpack', [('model.embed_tokens.weight',w),
            ('fixture.bias',np.ones(3,dtype=np.float32)), ('fixture.norm',np.ones(65,dtype=np.float32))],
            {'vocab.json':b'{}'}, cls.meta, {'lm_head.weight':'model.embed_tokens.weight'})
        cls.good = (cls.path/'good.nxpack').read_bytes()

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def reject(self, data, code):
        p = self.path/'mutant.nxpack'
        p.write_bytes(data)
        with self.assertRaises(PackError) as caught:
            verify(p)
        self.assertEqual(caught.exception.code, code)

    def test_all_fault_classes(self):
        for name, code, data in malformed(self.good):
            with self.subTest(case=name):
                self.reject(data, code)

    def test_tied_head_and_tail_rows(self):
        p = verify(self.path/'good.nxpack')
        self.assertEqual(p.summary['aliases'],2)
        self.assertEqual(p.entries['lm_head.weight']['offset'],p.entries['model.embed_tokens.weight']['offset'])
        self.assertEqual(p.rows('lm_head.weight',0,1).shape,(1,65))
        self.assertEqual(p.rows('lm_head.weight',0,1)[0,1],2)
        self.assertEqual(p.rows('lm_head.weight',2,3)[0,-1],-127)

    def test_exact_file_identity(self):
        verify(self.path/'good.nxpack',expected_sha256=hashlib.sha256(self.good).hexdigest())
        with self.assertRaisesRegex(PackError,'E_CHECKSUM'):
            verify(self.path/'good.nxpack',expected_sha256='0'*64)

    def test_header_truncations(self):
        for length in (0,7,39,159):
            with self.subTest(length=length):self.reject(self.good[:length],'E_BOUNDS')

    def test_trailing_data(self):
        self.reject(self.good+bytes(64),'E_BOUNDS')

    def test_directory_count_bounded(self):
        b = bytearray(self.good)
        struct.pack_into('<I',b,32,0xffffffff)
        b[128:160]=hashlib.sha256(b[:128]).digest()
        self.reject(b,'E_BOUNDS')

    def test_reserved_header_bytes(self):
        b=bytearray(self.good);b[160]=1
        self.reject(b,'E_RESERVED')

    def test_reserved_entry_bytes(self):
        b=bytearray(self.good);b[192+224]=1
        self.reject(reseal(b),'E_RESERVED')

    def test_nonzero_K_padding(self):
        b=bytearray(self.good)
        offset=struct.unpack_from('<Q',b,192+160)[0]
        b[offset+65]=1
        self.reject(reseal(b,payload=True),'E_NUMERIC')

    def test_subnormal_scale(self):
        b=bytearray(self.good)
        offset=struct.unpack_from('<Q',b,192+256+160)[0]
        struct.pack_into('<I',b,offset,1)
        self.reject(reseal(b,payload=True),'E_NUMERIC')

    def test_nonfinite_bias(self):
        b=bytearray(self.good)
        offset=struct.unpack_from('<Q',b,192+512+160)[0]
        struct.pack_into('<I',b,offset,0x7f800000)
        self.reject(reseal(b,payload=True),'E_NUMERIC')

    def test_bad_name_padding(self):
        b=bytearray(self.good);b[192+127]=1
        self.reject(reseal(b),'E_METADATA')

    def test_zero_dimension(self):
        b=bytearray(self.good);struct.pack_into('<I',b,192+144,0)
        self.reject(reseal(b),'E_SHAPE')

    def test_wrong_tensor_layout(self):
        b=bytearray(self.good);struct.pack_into('<I',b,192+132,1)
        self.reject(reseal(b),'E_LAYOUT')

    def test_duplicate_json_key(self):
        p=self.path/'metadata-duplicate.nxpack'
        write_pack(p,[('a',np.ones(1,dtype=np.float32))],{},self.meta)
        b=bytearray(p.read_bytes())
        # Replace the blob with a valid-length JSON containing a duplicate key.
        at=192+256;off,length=struct.unpack_from('<QQ',b,at+160)
        value=b'{"x":1,"x":2}'
        b[off:off+length]=value+b' '*(length-len(value))
        self.reject(reseal(b,payload=True),'E_METADATA')

    def test_full_profile_requires_complete_inventory(self):
        p=self.path/'fake-full.nxpack'
        meta=dict(self.meta,profile='qwen2.5-0.5b-application-v2')
        write_pack(p,[('a',np.ones(1,dtype=np.float32))],{},meta)
        with self.assertRaisesRegex(PackError,'E_METADATA'):verify(p)

    def test_no_source_overwrite(self):
        with self.assertRaises(FileExistsError):
            write_pack(self.path/'good.nxpack',[('a',np.ones(1,dtype=np.float32))],{},self.meta)
        self.assertEqual((self.path/'good.nxpack').read_bytes(),self.good)

    def test_rows_bounds(self):
        p=verify(self.path/'good.nxpack')
        for lo,hi in [(-1,1),(0,0),(0,4),(3,4)]:
            with self.subTest(lo=lo,hi=hi),self.assertRaisesRegex(PackError,'E_BOUNDS'):
                p.rows('model.embed_tokens.weight',lo,hi)

    def test_independent_oracle_and_reproducible_fixtures(self):
        with tempfile.TemporaryDirectory() as folder:
            a,b=Path(folder)/'a',Path(folder)/'b'
            generate(a);generate(b)
            files=lambda p:{str(f.relative_to(p)):hashlib.sha256(f.read_bytes()).hexdigest() for f in p.rglob('*') if f.is_file()}
            self.assertEqual(files(a),files(b))
            self.assertGreater(check(a)['checks'],400000)

    def test_golden_corruption_detected_even_when_manifest_resealed(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'fixtures';idx=generate(p)
            spec=idx['cases'][0]['arrays']['y'];file=p/spec['file']
            a=np.load(file,allow_pickle=False);a[0,0]+=1;np.save(file,a)
            spec['sha256']=hashlib.sha256(file.read_bytes()).hexdigest()
            (p/'manifest.json').write_text(json.dumps(idx))
            with self.assertRaisesRegex(PackError,'E_REFERENCE'):check(p)

    def test_budget_addresses_and_capacity_failure(self):
        p=verify(self.path/'good.nxpack')
        p.metadata['dimensions']=json.loads((ROOT/'docs/spec/operator-manifest.json').read_text())['dimensions']
        r=calculate(p)
        self.assertEqual(r['kv_fp32_bytes'],15728640)
        self.assertFalse(r['full_model_dequantization'])
        self.assertEqual(r['allocations']['cpu_private'][-1]['soc_address'],0xb7ff0000)
        memory=json.loads((ROOT/'docs/spec/memory-map-v1.json').read_text())
        next(x for x in memory['ddr_regions'] if x['name']=='workspace')['size_bytes']=1024
        with self.assertRaises(ValueError):calculate(p,memory)


if __name__ == '__main__':unittest.main()
