import json,os,sys,tempfile,time,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'scripts'))
from evidence import write_json,sha256
from sim_v1 import receipt,case_inventory,check_replays,checked_path

class GateRejection(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.p=Path(self.tmp.name)/'original';self.p.mkdir()
        self.m=dict(task_id='T09',run_id='original',status='PASS',exit_code=0,source={'sha256':'fixture'},cases={'case':{'checks':1}})
        write_json(self.p/'manifest.json',self.m);write_json(self.p/'commands.json',[dict(name='case-case',status='PASS',exit_code=0,argv=['simv'],timeout_seconds=10)]);write_json(self.p/'checks.json',{'checks':[dict(status='PASS')]});(self.p/'exit-status.txt').write_text('0\n')
        self.d=self.p/'artifacts/cocotb/case';self.d.mkdir(parents=True)
        self.c=dict(case_id='case',run_id='original',seed=1,profile='soft',fixture_sha256='input',golden_sha256='golden',simulator_sha256='binary',test_mode='PRELOAD',max_cycles=100,negative=None)
        self.r=dict(self.c,status='PASS',first_failure=None,categories={'data':1},check_count=1,sequence_sha256='same')
        write_json(self.d/'case.json',self.c);write_json(self.d/'checks.json',self.r);write_json(self.d/'case-status.json',dict(status='PASS',exit_code=0,started_ns=1));(self.d/'results.xml').write_text('<testsuites><testsuite><testcase name="cpu_execution" classname="test_cpu"/></testsuite></testsuites>');(self.d/'simulation.log').write_text('VCS cocotb v2.1.0')
    def inventory(self):return case_inventory(self.p,self.m,'CURRENT_EXECUTION')
    def test_valid(self):self.assertEqual(self.inventory()[0]['checks'],1);receipt(self.p)
    def test_missing_xml(self):
        (self.d/'results.xml').unlink()
        with self.assertRaises(OSError):self.inventory()
    def test_skip_xml(self):
        (self.d/'results.xml').write_text('<testsuites><testsuite><testcase><skipped/></testcase></testsuite></testsuites>')
        with self.assertRaises(ValueError):self.inventory()
    def test_empty_xml(self):
        (self.d/'results.xml').write_text('<testsuites/>')
        with self.assertRaises(ValueError):self.inventory()
    def test_duplicate_xml(self):
        (self.d/'results.xml').write_text('<testsuites><testcase/><testcase/></testsuites>')
        with self.assertRaises(ValueError):self.inventory()
    def test_zero_checks(self):
        self.r.update(check_count=0,categories={});write_json(self.d/'checks.json',self.r)
        with self.assertRaises(ValueError):self.inventory()
    def test_wrong_run_id(self):
        self.r['run_id']='replacement';write_json(self.d/'checks.json',self.r)
        with self.assertRaises(ValueError):self.inventory()
    def test_old_xml(self):
        write_json(self.d/'case-status.json',dict(status='PASS',exit_code=0,started_ns=time.time_ns()+10**9))
        with self.assertRaises(ValueError):self.inventory()
    def test_unexplained_fatal(self):
        (self.d/'simulation.log').write_text('VCS Fatal: actual protocol failure')
        with self.assertRaises(ValueError):self.inventory()
    def test_nonzero_exit(self):
        (self.p/'exit-status.txt').write_text('1')
        with self.assertRaises(ValueError):receipt(self.p)
    def test_relabel(self):
        self.m['run_id']='another';write_json(self.p/'manifest.json',self.m)
        with self.assertRaises(ValueError):receipt(self.p)
    def test_manifest_replaced(self):
        with self.assertRaises(ValueError):receipt(self.p,manifest_hash='wrong')
    def test_artifact_corrupt(self):
        self.m['artifacts']={'checks.json':'wrong'};write_json(self.p/'manifest.json',self.m)
        with self.assertRaises(ValueError):receipt(self.p)
    def test_path_escape(self):
        with self.assertRaises(ValueError):checked_path(self.p,'../outside')
    def test_same_seed_sequence_changed(self):
        with self.assertRaises(ValueError):check_replays([dict(case_id='case',sequence_sha256='a'),dict(case_id='case-replay',sequence_sha256='b')])
    def test_missing_replay_origin(self):
        with self.assertRaises(ValueError):check_replays([dict(case_id='case-replay',sequence_sha256='b')])
if __name__=='__main__':unittest.main()
