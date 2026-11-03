import unittest
import numpy as np
from software.boot.t25_dump_log import DumpLog


class FinalDump(unittest.TestCase):
    def fixture(self):
        g=dict(logits=np.array([1,2],dtype='<f4'),kv=np.array([[[[3,4]],[[5,6]]]],dtype='<f4'))
        limits={'cumulative':{k:dict(atol=0,rtol=0,nrmse=0) for k in ('kv','logits_24_layers')}}
        lines=['T25 LOGITS','3f800000 40000000','T25 KV 00000000 00000000 00000001',
            '40400000 40800000','T25 KV 00000000 00000001 00000001','40a00000 40c00000','T25 DUMP END','T25 READY']
        return g,limits,lines

    def test_final_state(self):
        g,l,lines=self.fixture();p=DumpLog(g,l)
        for line in lines:p.feed(line)
        self.assertEqual(p.finish()['compared_elements'],6)

    def test_incomplete_reordered_changed_and_nonfinite_fail(self):
        g,l,lines=self.fixture();bad=[]
        bad.append(lines[:6]);changed=lines.copy();changed[2]=changed[4];bad.append(changed)
        for words in ['7fc00000 40000000','3f800000 40000001']:
            changed=lines.copy();changed[1]=words;bad.append(changed)
        for candidate in bad:
            with self.subTest(candidate=candidate):
                with self.assertRaises(ValueError):
                    p=DumpLog(g,l)
                    for line in candidate:p.feed(line)
                    p.finish()
