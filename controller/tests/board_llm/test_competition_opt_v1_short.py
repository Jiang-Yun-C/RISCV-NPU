"""Host protocol/guardrail tests, supplementary to actual RTL and full golden."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
from software.boot.competition_opt_v1_short import calls, allowed, decode_request, compare
from scripts.run_competition_opt_v1_short import Budget, validate_identity
from scripts.ce64_case import validate


def sample(case='S', variant='B'):
    prompt={'S':[0,255,1023], 'P':[0,255,1023,0,255,1023]}[case]
    output=[2,3,4] if case=='S' else [2]
    f=len(prompt)+len(output)-1
    ce, counts=calls(len(prompt),len(output),variant)
    golden=dict(input_ids=np.array(prompt), output_ids=np.array(output))
    rows=[f'T25 STEP {min(i+1,len(prompt)):08x} {max(0,i-len(prompt)+2):08x}' for i in range(f)]
    rows+=['T25 IDS '+' '.join(f'{x:08x}' for x in output)]
    m=dict(session=2,stop=2,prompt=len(prompt),generated=len(output),kv=f,ce_calls=ce,cpu_calls=0,fallback_calls=0,
           first_token_ticks=30 if case=='S' else 41,prefill_ticks=20,decode_ticks=10 if case=='S' else 0,total_ticks=40,stack_peak_bytes=1000)
    rows+=['T25 METRICS '+' '.join(f'{k}={v:016x}' for k,v in m.items())]
    rows+=['T25 PROFILE CUMULATIVE '+''.join(f'{i:08x} ticks={100+i:016x} calls={n:016x} ' for i,n in enumerate(counts)), 'T25 READY']
    return ('\n'.join(rows)+'\n').encode(),golden


class ShortChecks(unittest.TestCase):
    def test_dispatch_formulas(self):
        self.assertEqual(calls(6,1,'A')[0],1014)
        self.assertEqual(calls(6,1,'B')[0],1009)
        self.assertEqual(calls(6,1,'B')[1][7],1)
        self.assertEqual(calls(6,1,'B',True)[0],1014)
        self.assertEqual(calls(3,3,'B')[0],843)

    def test_whitelist(self):
        for value in (':ids 3 0 255 1023',':verify 1 0',':ids 1 0'):
            self.assertTrue(allowed(value))
        for value in (':ids 32 0',':verify 32 0',':reload',':ids 3 1 2 3',':pressure on\n:reload'):
            self.assertFalse(allowed(value))

    def test_profile_delta_and_decode_numerator(self):
        raw,gold=sample();x=decode_request(raw,'S','B',gold,{},[(0,0)]*8)
        self.assertEqual(x['decode_tok_s'],25000000)
        self.assertEqual(x['profile_delta'][7]['calls'],3)

    def test_one_output_has_no_decode_rate(self):
        raw,gold=sample('P');self.assertIsNone(decode_request(raw,'P','B',gold,{},[(0,0)]*8)['decode_tok_s'])

    def test_bad_requests_rejected(self):
        raw,gold=sample()
        cases=[raw.replace(b'T25 READY\n',b''),raw.replace(b'T25 IDS ',b'T25 WRONG '),
               raw+raw,raw.replace(b'generated=0000000000000003',b'generated=0000000000000002'),
               raw.replace(b'fallback_calls=0000000000000000',b'fallback_calls=0000000000000001'),
               raw.replace(b'decode_ticks=000000000000000a',b'decode_ticks=0000000000000000'),
               raw.replace(b'T25 STEP 00000001 00000000\n',b''),
               raw.replace(b'T25 READY',b'T25 ERROR fffffff9\nT25 READY')]
        for value in cases:
            with self.subTest(value=value[:30]),self.assertRaises(ValueError):
                decode_request(value,'S','B',gold,{},[(0,0)]*8)
        with self.assertRaises(ValueError):decode_request(raw,'S','B',gold,{},[(1000,1000)]*8)

    def test_early_eos_refuses_speed(self):
        raw,gold=sample();gold['output_ids']=np.array([2])
        with self.assertRaises(ValueError):decode_request(raw,'S','B',gold,{})

    def test_xml_missing_empty_skipped_and_failed_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)
            with self.assertRaises(ValueError):validate(path,{'task':'CE64'})
            for xml in ('<testsuites/>', '<testsuites><testcase name="ce64_soc" classname="test_ce64_soc"><skipped/></testcase></testsuites>',
                        '<testsuites><testcase name="ce64_soc" classname="test_ce64_soc"><failure/></testcase></testsuites>'):
                (path/'results.xml').write_text(xml)
                with self.assertRaises(ValueError):validate(path,{'task':'CE64'})

    def test_budget_survives_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            tick=[0];path=Path(folder)/'budget.json';b=Budget(path,lambda:tick[0])
            tick[0]=1100;b.save()
            second=Budget(path,lambda:tick[0]);self.assertEqual(second.left(),100)
            with self.assertRaises(TimeoutError):second.require(101)
            tick[0]+=100;self.assertEqual(second.left(),0)

    def test_boot_identity_required(self):
        identity={k:'0'*64 for k in ('application_sha256','loader_rom_sha256','bitstream_sha256','model_sha256','tokenizer_sha256')}
        identity.update(clock_hz=125000000,route='CE64_API_V2_ROUTE_2')
        boot=('T25 SD EXPECT APP '+('0'*64)+' MODEL '+('0'*64)+'\nT25 MODEL '+('0'*64)+' TOKENIZER '+('0'*64)+
              '\nT25 SERVICE v1 CE64_CANDIDATE_UNQUALIFIED total=512 max_new=128\nT25 READY\n').encode()
        validate_identity(identity,boot)
        with self.assertRaises(ValueError):validate_identity(identity,boot.replace(b'T25 MODEL',b'T25 OTHER'))
        identity['clock_hz']=100000000
        with self.assertRaises(ValueError):validate_identity(identity,boot)

    def test_compare_refuses_missing_or_mismatched_data(self):
        with self.assertRaises(ValueError):compare({'status':'FAIL'},{'status':'PASS'})
        a=dict(status='PASS',speed_eligible=True,variant='A',identity=dict(model_sha256='a',tokenizer_sha256='b',clock_hz=125000000,route='ce'),results=[])
        b=copy.deepcopy(a);b['variant']='B';b['identity']['model_sha256']='wrong'
        with self.assertRaises(ValueError):compare(a,b)

    def test_compare_accepts_B_before_A_without_resetting_ledger(self):
        identity=dict(model_sha256='m',tokenizer_sha256='t',clock_hz=125000000,route='CE64_API_V2_ROUTE_2')
        results=[dict(case=c,output_ids=[2],ttft_seconds=12,total_seconds=12,decode_tok_s=None) for c in ('S','P')]
        a=dict(status='PASS',speed_eligible=True,variant='A',identity=identity,results=results,
               measurement_ledger_id='1'*32,cumulative_measurement_seconds=900,elapsed_seconds=300,
               golden_manifest_sha256='g',thresholds_sha256='t')
        b=copy.deepcopy(a);b.update(variant='B',cumulative_measurement_seconds=600,elapsed_seconds=500)
        b['results']=[dict(x,ttft_seconds=8,total_seconds=8) for x in results]
        self.assertEqual(compare(a,b)['samples'][0]['ttft_speedup'],1.5)
        a['cumulative_measurement_seconds']=800
        with self.assertRaises(ValueError):compare(a,b)


if __name__=='__main__':unittest.main()
