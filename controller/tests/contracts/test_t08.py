"""Boundary and corrupted-contract acceptance, without pretending to run RTL."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
from check_t08 import load, validate_contract, validate_map, validate_tensor, validate_linear, coral_local


def tensor(address, shape, dtype='F32'):
    size = 1 if dtype == 'I8' else 4
    strides = []
    for d in reversed(shape):
        strides.insert(0, size); size *= d
    return dict(address=address, allocation_bytes=size, dtype=dtype, shape=shape,
                stride_bytes=strides, layout_id=1)


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.memory = load('docs/spec/memory-map-v1.json')
        self.caps = load('docs/spec/backend-capabilities-v1.json')
        self.manifest = load('docs/spec/operator-manifest.json')

    def request(self, m=1, n=128, k=896):
        return dict(api_version=1, route='CORAL_RVV', group_size=64,
                    a=tensor(0xba000000,[m,k]), wq=tensor(0x80000000,[n,k],'I8'),
                    sw=tensor(0xa0000000,[n,(k+63)//64]), bias=tensor(0xa7000000,[n]),
                    y=tensor(0xb0000000,[m,n]))

    def test_entire_network_and_capacity(self):
        r = validate_contract(self.memory,self.caps,self.manifest)
        self.assertEqual((r['operator_rows'],r['expanded_stages'],r['linear_stages'],r['cpu_stages']), (21,412,169,243))
        self.assertEqual((r['logical_model_bytes'],r['kv_bytes']),(525120000,15728640))

    def test_all_model_linear_shapes(self):
        for m in (1,2,3,4,7,512):
            for n,k in ((896,896),(128,896),(4864,896),(896,4864),(151936,896)):
                with self.subTest(m=m,n=n,k=k):
                    r=self.request(m,n,k)
                    # Largest all-logits output needs the full workspace region.
                    r['y']['address']=0xac100000
                    if m==512 and n==151936:
                        with self.assertRaisesRegex(ValueError,'EBOUNDS'):
                            validate_linear(r,self.memory,self.caps)
                    else:
                        result=validate_linear(r,self.memory,self.caps)
                        self.assertEqual(result['macs'],m*n*k)
                        self.assertEqual(result['native_calls'],(m//4+m%4)*((n+127)//128))

    def test_local_translation_and_holes(self):
        self.assertEqual(coral_local(self.memory,0x20030004,4),0x30004)
        self.assertEqual(coral_local(self.memory,0x20017ff0,16),0x17ff0)
        for a,n in ((0x30004,4),(0x20002000,4),(0x20017ff0,17),(0x20040000,4),(0x20000000,0)):
            with self.subTest(a=a,n=n), self.assertRaises(ValueError): coral_local(self.memory,a,n)

    def test_high_unsigned_address_and_exact_end(self):
        self.assertEqual(validate_tensor(tensor(0xbbfffff0,[4]),self.memory,True),(0xbbfffff0,0xbc000000))

    def test_address_overflow_and_crossing(self):
        for address, size in ((0xfffffff0,32),(0xa7fffff0,32),(0xbc000000,16),(0xb4000000,16),(0x20010000,16),(-16,16)):
            t=tensor(address,[4]); t['allocation_bytes']=size
            with self.subTest(address=address),self.assertRaisesRegex(ValueError,'EBOUNDS'):
                validate_tensor(t,self.memory)

    def test_readonly_weight_write(self):
        with self.assertRaisesRegex(ValueError,'EBOUNDS'):
            validate_tensor(tensor(0x80000000,[4]),self.memory,True)

    def test_bad_tensor_metadata(self):
        changes=[('address',0xac000001,'EALIGN'),('allocation_bytes',8,'EBOUNDS'),
                 ('layout_id',42,'EUNSUPPORTED'),('dtype','F16','EINVAL'),
                 ('shape',[0],'EINVAL'),('stride_bytes',[-4],'EINVAL'),
                 ('shape',[2**32],'EINVAL')]
        for key,value,code in changes:
            t=tensor(0xac000000,[4]);t[key]=value
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,code): validate_tensor(t,self.memory)

    def test_span_overflow_and_noncontiguous(self):
        t=tensor(0xac000000,[4]);t.update(shape=[2**32-1]*4,stride_bytes=[2**32-1]*4)
        with self.assertRaisesRegex(ValueError,'overflow'):validate_tensor(t,self.memory)
        t=tensor(0xac000000,[2,4]);t.update(stride_bytes=[32,4],allocation_bytes=64)
        with self.assertRaisesRegex(ValueError,'EUNSUPPORTED'):validate_tensor(t,self.memory)

    def test_linear_alias_and_shape_rejection(self):
        r=self.request();r['y']=tensor(0xba000000,[1,128])
        with self.assertRaisesRegex(ValueError,'overlapping'):validate_linear(r,self.memory,self.caps)
        r=self.request();r['sw']=tensor(0xa0000000,[128,13])
        with self.assertRaisesRegex(ValueError,'dimensions'):validate_linear(r,self.memory,self.caps)
        for key,value in [('api_version',2),('group_size',32),('route','VME')]:
            r=self.request();r[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError): validate_linear(r,self.memory,self.caps)

    def test_unsupported_k_and_optional_bias(self):
        with self.assertRaisesRegex(ValueError,'EUNSUPPORTED'):validate_linear(self.request(k=900),self.memory,self.caps)
        r=self.request();r['bias']=None
        self.assertEqual(validate_linear(r,self.memory,self.caps)['n'],128)
        self.assertEqual(validate_linear(self.request(m=7,n=129),self.memory,self.caps)['native_calls'],8)

    def test_map_corruption(self):
        for kind in ('overlap','cache','permission','translation','csr','boot'):
            m=copy.deepcopy(self.memory)
            if kind=='overlap':m['soc_regions'][0]['base']='0x00020000'
            if kind=='cache':m['ddr_regions'][2]['cache']='cacheable'
            if kind=='permission':m['coral']['external_write_regions'].append('weights')
            if kind=='translation':m['coral']['external_translation']='subtract_aperture'
            if kind=='csr':m['coral']['registers']['entry_pc']=16
            if kind=='boot':m['application_entry']='0x80000000'
            with self.subTest(kind=kind),self.assertRaises(ValueError):validate_map(m)

    def test_missing_operator_or_overclaimed_support(self):
        for kind in ('missing','duplicate','route','measured','pack','vme','context','numeric','repeat'):
            c=copy.deepcopy(self.caps)
            if kind=='missing':c['operations'].pop(6)
            if kind=='duplicate':c['operations'][6]=c['operations'][5]
            if kind=='route':c['operations'][7]['route']='CORAL_RVV'
            if kind=='measured':c['operations'][0]['measured_target_ticks']=0
            if kind=='pack':c['pack_layout_id']='invented'
            if kind=='vme':c['vme_enabled']=True
            if kind=='context':c['max_context']=2048
            if kind=='numeric':c['group_size']=32
            if kind=='repeat':c['operations'][1]['instances']=1
            with self.subTest(kind=kind),self.assertRaises(ValueError):validate_contract(self.memory,c,self.manifest)


if __name__=='__main__':unittest.main()
