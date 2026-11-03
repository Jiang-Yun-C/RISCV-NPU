"""Collector recovery cannot promote missing exits or reopen frozen archives."""
import json,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'scripts'))
from recover_t24 import restore,wrapper_exit

class Recovery(unittest.TestCase):
    def test_completed_archives_are_immutable(self):
        for status in ('PASS','FAIL'):
            with self.subTest(status=status),tempfile.TemporaryDirectory() as td:
                p=Path(td);raw=json.dumps(dict(status=status,finished_at='2026-10-12'))
                (p/'manifest.json').write_text(raw)
                with self.assertRaisesRegex(ValueError,'unfinished RUNNING'):restore(p)
                self.assertEqual((p/'manifest.json').read_text(),raw)
    def test_observed_success(self):self.assertEqual(wrapper_exit('EXIT_CODE=0 MARKER=T24_SYNTH_COMPLETE PRESENT=True\n'),0)
    def test_observed_failure(self):self.assertEqual(wrapper_exit('EXIT_CODE=1 MARKER=T24_SYNTH_COMPLETE PRESENT=False\n'),1)
    def test_missing_marker_overrides_zero_exit(self):self.assertEqual(wrapper_exit('EXIT_CODE=0 MARKER=T24_SYNTH_COMPLETE PRESENT=False\n'),1)
    def test_missing_record_is_not_completion(self):
        with self.assertRaisesRegex(ValueError,'missing or ambiguous'):wrapper_exit('Process Synthesize done\n')
    def test_duplicate_records_rejected(self):
        with self.assertRaisesRegex(ValueError,'missing or ambiguous'):wrapper_exit('EXIT_CODE=0 MARKER=T24_SYNTH_COMPLETE PRESENT=True\n'*2)

if __name__=='__main__':unittest.main()
