"""Independent protocol differential checks and fail-closed archive mutations."""
import copy
import ctypes as C
import hashlib
import io
import json
from pathlib import Path
import random
import subprocess
import sys
import tarfile
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT),str(ROOT/'scripts'),str(ROOT/'tests/application/t20')]
from software.application_v2.program import execute,parse,ProgramError
from prepare import prepare,expected
from evidence import sha256,content_id,write_json
from run_t20 import verify_archive

class State(C.Structure):_fields_=[('temperature',C.c_int32),('light',C.c_uint32),('epoch',C.c_uint32),('sampled_at',C.c_uint32)]
class Action(C.Structure):_fields_=[('device',C.c_uint32),('value',C.c_uint32)]
class Result(C.Structure):_fields_=[('actions',Action*8),('count',C.c_uint32),('read_mask',C.c_uint32)]
NAMES=['OK','FORMAT','RANGE','UNSUPPORTED','STATE','STALE','NACK','TIMEOUT','DUPLICATE','REQUEST_ID']

class ExecutorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();library=Path(cls.tmp.name)/'app.so'
        subprocess.run(['gcc','-std=c11','-shared','-fPIC','-O2','-Wall','-Wextra','-Werror','-Wno-misleading-indentation',str(ROOT/'firmware/application/application.c'),'-o',str(library)],check=True)
        cls.lib=C.CDLL(str(library));cls.lib.app_parse.argtypes=[C.c_void_p,C.c_char_p,C.c_size_t]
        cls.lib.app_evaluate.argtypes=[C.c_void_p,C.POINTER(State),C.c_uint32,C.c_uint32,C.POINTER(Result)]
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def run_program(self,text,state=None,epoch=1,now=200,sampled=100):
        state=state or {'temperature':31,'light':10};p=C.create_string_buffer(16384);r=Result()
        rc=self.lib.app_parse(p,text.encode(),len(text.encode()))
        if not rc:rc=self.lib.app_evaluate(p,C.byref(State(state['temperature'],state['light'],epoch,sampled)),1,now,C.byref(r))
        return dict(error=NAMES[rc] if rc else None,actions=[['pwm' if a.device else 'led',a.value] for a in r.actions[:r.count]],
            readings={k:state[k] for k,b in [('temperature',1),('light',2)] if r.read_mask&b})
    def test_all_recorded_model_outputs(self):
        fixture=prepare(ROOT/'evidence/T20_MODEL/acceptance-20261008-v1')
        for i in range(8):
            for row in fixture['groups']['dev'+str(i)]:
                with self.subTest(case=row['name']):self.assertEqual(self.run_program(row['intent'],row['state']),row['expected'])
    def test_all_parser_faults(self):
        fixture=prepare(ROOT/'evidence/T20_MODEL/acceptance-20261008-v1')
        for i in range(8):
            for row in fixture['groups']['fault'+str(i)]:
                if row['origin']=='EXPLICIT_FAULT_MUTATION':
                    with self.subTest(case=row['name']):self.assertEqual(self.run_program(row['intent']),row['expected'])
    def test_all_directed_programs(self):
        for row in prepare(ROOT/'evidence/T20_MODEL/acceptance-20261008-v1')['groups']['directed']:
            with self.subTest(case=row['name']):self.assertEqual(self.run_program(row['intent'],row['state']),row['expected'])
    def test_fresh_multi_condition_outputs(self):
        for row in prepare(ROOT/'evidence/T20_MODEL/acceptance-20261008-v3')['groups']['multi']:
            if row['origin']=='CPU_STATE_PRECONDITION':continue
            with self.subTest(case=row['name']):
                self.assertTrue(row['semantic_pass'])
                self.assertEqual(self.run_program(row['intent'],row['state']),row['semantic_expected'])
    def test_random_independent_condition_semantics(self):
        rng=random.Random(20261008)
        for _ in range(500):
            sensor=rng.choice(['temperature','light']);cmp=rng.choice(['>','<','>=','<=']);threshold=rng.randint(0,100)
            program=[['if',sensor,cmp,threshold,[['pwm',rng.randint(0,100)]],[['led',rng.randint(0,1)]]],['read',sensor]]
            state=dict(temperature=rng.randint(-40,125),light=rng.randint(0,100000))
            self.assertEqual(self.run_program(json.dumps(program),state),execute(program,state))
    def test_stale_future_and_wrap(self):
        for now,sampled,status in [(1000101,100,'STALE'),(100,101,'STALE'),(20,0xfffffff0,None),(1000100,100,None)]:
            self.assertEqual(self.run_program('[["led",1]]',now=now,sampled=sampled)['error'],status)
    def test_state_range_and_epoch(self):
        for state in [dict(temperature=-41,light=0),dict(temperature=126,light=0),dict(temperature=0,light=100001)]:
            self.assertEqual(self.run_program('[["led",1]]',state)['error'],'STATE')
        self.assertEqual(self.run_program('[["led",1]]',epoch=2)['error'],'STATE')
    def test_atomic_rejection_after_valid_prefix(self):
        self.assertEqual(self.run_program('[["led",1],["pwm",101]]'),dict(error='RANGE',actions=[],readings={}))
    def test_unselected_branch_validated(self):
        text='[["if","temperature",">",100,[["pwm",101]],[["led",1]]]]'
        self.assertEqual(self.run_program(text)['error'],'RANGE')
    def test_duplicate_and_sequential_different_values(self):
        self.assertEqual(self.run_program('[["led",1],["led",1]]')['error'],'DUPLICATE')
        self.assertEqual(self.run_program('[["led",1],["led",0]]')['actions'],[['led',1],['led',0]])
    def test_selected_action_capacity(self):
        node=['if','temperature','>',0,[['pwm',n] for n in range(8)],[]]
        self.assertEqual(self.run_program(json.dumps([node,['led',1]]))['error'],'FORMAT')
    def test_full_node_budget(self):
        child=['if','light','>',0,[['read','light']]*8,[['read','light']]*8]
        self.assertEqual(self.run_program(json.dumps([child,child]))['error'],'FORMAT')
    def test_utf8_control_and_json_limits(self):
        for text in ['[["led",1]]\x00','[["led",1]]'+(' '*4096),'[["le\x01d",1]]','[["led",NaN]]','[["led",Infinity]]']:
            self.assertEqual(self.run_program(text)['error'],'FORMAT')

class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.path=Path(self.tmp.name)
        self.registered=dict(suites={'smoke':['short-seed1','directed-seed1']},max_delay=3)
        self.config={**copy.deepcopy(self.registered),'suite':'smoke','selected_cases':['short-seed1','directed-seed1']}
    def reject(self):
        write_json(self.path/'config.json',self.config);raw=json.dumps(self.registered).encode();files={'configs/t20-application.json':hashlib.sha256(raw).hexdigest()}
        with tarfile.open(self.path/'source.tar.gz','w:gz') as tar:
            info=tarfile.TarInfo('configs/t20-application.json');info.size=len(raw);tar.addfile(info,io.BytesIO(raw))
        write_json(self.path/'manifest.json',dict(task_id='T20',status='PASS',exit_code=0,source=dict(files=files,sha256=content_id(files)),config_sha256=sha256(self.path/'config.json'),cases={n:{} for n in self.config['selected_cases']},artifacts={}))
        (self.path/'exit-status.txt').write_text('0\n')
        with self.assertRaisesRegex(ValueError,'registered matrix'):verify_archive(self.path)
    def test_empty_matrix(self):self.config['selected_cases']=[];self.reject()
    def test_missing_case(self):self.config['selected_cases']=['short-seed1'];self.reject()
    def test_duplicate_case(self):self.config['selected_cases']=['short-seed1']*2;self.reject()
    def test_rewritten_suite(self):self.config['suites']['smoke']=['short-seed1'];self.config['selected_cases']=['short-seed1'];self.reject()
    def test_unknown_suite(self):self.config['suite']='custom';self.reject()
    def test_rehashed_timing(self):self.config['max_delay']=0;self.reject()

if __name__=='__main__':unittest.main()
