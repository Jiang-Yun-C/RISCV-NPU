"""The persistent worker can retry bounds, never data errors or live captures."""
import sys,tempfile,unittest,json
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'scripts'))
import finalize_t24_offline as watcher
class RetryPolicy(unittest.TestCase):
    def candidate(self,state='FAIL',category='completion',cycles=950000000,detail='bounded wait for real CPU exit'):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'parent';d=p/'artifacts/cocotb/head-seed1';d.mkdir(parents=True)
            (p/'manifest.json').write_text(json.dumps({'status':state}))
            (d/'case.json').write_text(json.dumps({'max_cycles':950000000}))
            (d/'checks.json').write_text(json.dumps({'first_failure':{'category':category,'detail':detail}}))
            (d/'progress.txt').write_text(f'{cycles} 1 11\n')
            with patch.object(watcher,'ROOT',Path(td)):return watcher.head_timeout('parent')
    def test_observed_head_bound(self):self.assertTrue(self.candidate())
    def test_data_failure_is_never_retried(self):self.assertFalse(self.candidate(category='data'))
    def test_running_capture_is_never_retried(self):self.assertFalse(self.candidate(state='RUNNING'))
    def test_early_completion_failure_is_not_a_bound(self):self.assertFalse(self.candidate(cycles=1000000))
    def test_other_completion_failure_is_not_a_bound(self):self.assertFalse(self.candidate(detail='real firmware exit'))
    def launch(self,status=None,elaborated=True):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);synth=root/'evidence/T24_SYNTH/resource';synth.mkdir(parents=True)
            if elaborated:(synth/'elaborated.v').write_text('module Core;endmodule')
            case=root/'evidence/T24_LOWERED/converted'
            if status:
                case.mkdir(parents=True);(case/'manifest.json').write_text(json.dumps({'status':status}))
            cfg={'runs':{'coral_synthesis':'evidence/T24_SYNTH/resource','coral_functional':'evidence/T24_LOWERED/converted'}}
            with patch.object(watcher,'ROOT',root):return watcher.functional_launch(cfg)
    def test_fresh_conversion_is_launched(self):self.assertEqual(self.launch()[0],'converted')
    def test_unfinished_elaboration_is_not_launched(self):self.assertIsNone(self.launch(elaborated=False))
    def test_existing_job_is_never_duplicated(self):
        for status in ('RUNNING','PASS','FAIL'):
            with self.subTest(status=status):self.assertIsNone(self.launch(status))
if __name__=='__main__':unittest.main()
