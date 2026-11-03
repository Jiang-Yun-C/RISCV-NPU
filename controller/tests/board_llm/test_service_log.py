import unittest
import numpy as np
from software.boot.t25_service_log import VerifyLog


class ServiceLog(unittest.TestCase):
    def fixture(self):
        golden=dict(logits=np.array([[1,2,3],[4,6,5]],dtype='<f4'),kv=np.arange(8,dtype='<f4').reshape(1,2,2,2),
            input_ids=np.array([1],dtype='<u4'),output_ids=np.array([2,1],dtype='<u4'))
        limits={'cumulative':{k:dict(atol=0,rtol=0,nrmse=0) for k in ('kv','logits_24_layers')}}
        lines=[]
        def words(array):return ' '.join(f'{x:08x}' for x in array.reshape(-1).view('<u4'))
        for step in range(2):
            lines+=['T25 STEP 00000001 '+f'{step+1:08x}','T25 LOGITS',words(golden['logits'][step])]
            for value in range(2):lines+=['T25 KV '+f'00000000 {value:08x} {step+1:08x}',words(golden['kv'][0,value,:step+1])]
            lines+=['T25 DUMP END']
        lines+=['T25 IDS 00000002 00000001','T25 METRICS '+ ' '.join(f'{k}={v:016x}' for k,v in
            dict(generated=2,prompt=1,kv=2,ce_calls=2,fallback_calls=0,stack_peak_bytes=128,first_token_ticks=10,total_ticks=20).items())]
        return golden,limits,lines

    def test_complete_board_output(self):
        g,l,lines=self.fixture();p=VerifyLog(g,l,layers=1,width=2)
        for line in lines:p.feed(line)
        self.assertEqual(p.finish()['compared_elements'],18)

    def test_missing_reordered_or_changed_data_fail(self):
        g,l,lines=self.fixture()
        variants=[lines[:-2],lines[:3]+lines[5:7]+lines[3:5]+lines[7:]]
        wrong=lines.copy();wrong[2]='7fc00000 40000000 40400000';variants.append(wrong)
        wrong=lines.copy();wrong[-2]='T25 IDS 00000001 00000002';variants.append(wrong)
        wrong=lines.copy();wrong[-1]=wrong[-1].replace('fallback_calls=0000000000000000','fallback_calls=0000000000000001');variants.append(wrong)
        for variant in variants:
            with self.subTest(variant=variant):
                with self.assertRaises(ValueError):
                    p=VerifyLog(g,l,layers=1,width=2)
                    for line in variant:p.feed(line)
                    p.finish()
