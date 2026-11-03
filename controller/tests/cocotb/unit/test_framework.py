import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'tests/cocotb')]
from cocotb_case import validate
from common.axi import SparseMemory,AxiMonitor
from common.checks import Checks


class ResultGate(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)
        self.cfg=dict(case_id='cpu',run_id='unique',seed=1,profile='soft',fixture_sha256='a',golden_sha256='b',python_prefix=sys.prefix,cocotb_version='2.1.0')
        self.xml='<testsuites><testsuite><testcase name="cpu_execution" classname="test_cpu"/></testsuite></testsuites>'
        (self.path/'results.xml').write_text(self.xml)
        cats={n:1 for n in ('axi_request','axi_response','axi_stability','axi_write','signature','trap','interrupt',
                            'mret','cache','branch','fault','uart','execution','completion','counters')}
        self.report=dict(self.cfg,status='PASS',first_failure=None,runtime={'prefix':sys.prefix,'cocotb':'2.1.0'},categories=cats,check_count=sum(cats.values()))
        self.save()
        for name in ('observations.json','cpu.vcd'): (self.path/name).write_text('x'*101)
        (self.path/'simulation.log').write_text('Running on VCS; cocotb v2.1.0')

    def save(self): (self.path/'checks.json').write_text(json.dumps(self.report))
    def reject(self):
        with self.assertRaises((ValueError,ET.ParseError,KeyError)): validate(self.path,self.cfg)
    def test_valid(self): self.assertEqual(validate(self.path,self.cfg)['check_count'],15)
    def test_missing_xml(self): (self.path/'results.xml').unlink();self.reject()
    def test_malformed_xml(self): (self.path/'results.xml').write_text('<broken');self.reject()
    def test_zero_tests(self): (self.path/'results.xml').write_text('<testsuites/>');self.reject()
    def test_duplicate_test(self):
        (self.path/'results.xml').write_text(self.xml.replace('</testsuite>','<testcase name="cpu_execution" classname="test_cpu"/></testsuite>'));self.reject()
    def test_skip_failure_error(self):
        for tag in ('skipped','failure','error'):
            with self.subTest(tag=tag):
                (self.path/'results.xml').write_text(self.xml.replace('/>',f'><{tag}/></testcase>'));self.reject()
    def test_wrong_test_identity(self): (self.path/'results.xml').write_text(self.xml.replace('cpu_execution','empty'));self.reject()
    def test_missing_checks(self): (self.path/'checks.json').unlink();self.reject()
    def test_wrong_embedded_environment(self): self.report['runtime']['cocotb']='2.0.1';self.save();self.reject()
    def test_zero_checks(self): self.report['categories']={};self.report['check_count']=0;self.save();self.reject()
    def test_count_mismatch(self): self.report['check_count']=999;self.save();self.reject()
    def test_old_run(self): self.report['run_id']='old';self.save();self.reject()
    def test_stale_file(self):
        with self.assertRaises(ValueError): validate(self.path,self.cfg,10**30)
    def test_failed_scoreboard(self): self.report['status']='FAIL';self.save();self.reject()
    def test_missing_observations(self): (self.path/'observations.json').unlink();self.reject()
    def test_fatal_zero_exit(self): (self.path/'simulation.log').write_text('VCS cocotb v2.1.0 Fatal: fake');self.reject()


class BusContract(unittest.TestCase):
    def test_sparse_bytes(self):
        mem=SparseMemory();self.assertEqual(mem.read(0xb4000000),0)
        mem.write(0xb4000000,0x12345678,15);mem.write(0xb4000001,0xab00,2)
        self.assertEqual(mem.read(0xb4000000),0x1234ab78)
        self.assertEqual(mem.read(0xbbfffffc),0)
    def test_t04_observed_memory_agreement(self):
        import hashlib
        fixture=json.loads((ROOT/'tests/cocotb/fixtures/t04-memory-subset.json').read_text())
        for name,expected_hash in fixture['source'].items():
            self.assertEqual(hashlib.sha256((ROOT/name).read_bytes()).hexdigest(),expected_hash)
        mem=SparseMemory()
        for request in fixture['writes']:
            for i,(data,mask) in enumerate(zip(request['data'],request['strobes'])):
                mem.write(request['addr']+i*(1<<request['size']),data,mask)
        count=0
        for request in fixture['reads']:
            for i,value in enumerate(request['expected']):
                self.assertEqual(mem.read_transfer(request['addr']+i*(1<<request['size']),request['size']),value,request['name'])
                count+=1
        self.assertGreater(count,1000)
    def test_error_map(self):
        for address,resp in ((0x10000,0),(0xb4300000,2),(0xbc000000,3),(0xffffffff,3),(0,3)):
            self.assertEqual(SparseMemory.response(address),resp)
        self.assertEqual(SparseMemory.response(0x10000,True),3)
    def test_unsolicited_read_rejected(self):
        checks=Checks();m=AxiMonitor('i',checks)
        with self.assertRaises(AssertionError):
            m.sample(dict(ar_valid=0,ar_ready=0,ar_addr=0,ar_len=0,r_valid=1,r_ready=1,r_data=0,r_resp=0,r_last=1),1,False,0)
    def test_stalled_payload_rejected(self):
        m=AxiMonitor('i',Checks())
        v=dict(ar_valid=1,ar_ready=0,ar_addr=0xb4000000,ar_len=7,r_valid=0,r_ready=1,r_data=0,r_resp=0,r_last=0)
        m.sample(v,1,False,0);v['ar_addr']+=32
        with self.assertRaises(AssertionError): m.sample(v,2,False,0)
    def test_early_last_rejected(self):
        m=AxiMonitor('i',Checks())
        v=dict(ar_valid=1,ar_ready=1,ar_addr=0xb4000000,ar_len=7,r_valid=0,r_ready=1,r_data=0,r_resp=0,r_last=0)
        m.sample(v,1,False,0);v.update(ar_valid=0,r_valid=1,r_last=1)
        with self.assertRaises(AssertionError): m.sample(v,2,False,0)

if __name__=='__main__': unittest.main()
