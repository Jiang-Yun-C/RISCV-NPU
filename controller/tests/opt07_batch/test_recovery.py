import json,tempfile,unittest
from pathlib import Path
from scripts.verify_opt07 import verify

class Recovery(unittest.TestCase):
    def case(self,d,reason,failed_check=False):
        p=Path(d);(p/'manifest.json').write_text(json.dumps(dict(task_id='OPT07',status='FAIL',exit_code=1)))
        (p/'failure.txt').write_text(reason+'\n');(p/'exit-status.txt').write_text('1\n')
        checks=[dict(name='sources-unchanged',status='PASS')]
        if failed_check:checks.append(dict(name='functional-test',status='FAIL'))
        (p/'checks.json').write_text(json.dumps(dict(checks=checks)))
        return p
    def test_general_failure_cannot_be_recovered(self):
        with tempfile.TemporaryDirectory() as d:
            p=self.case(d,'AssertionError: numerical mismatch')
            with self.assertRaises(ValueError):verify(p,True)
    def test_known_exception_cannot_hide_a_failed_check(self):
        with tempfile.TemporaryDirectory() as d:
            p=self.case(d,"r.check('baseline-preserved',all(sha256(b/n)==h for n,h in baseline.items()),'Frozen B')\nTypeError: unsupported operand type(s) for /: 'dict' and 'str'",True)
            with self.assertRaises(ValueError):verify(p,True)
    def test_default_never_accepts_failed_raw_manifest(self):
        with tempfile.TemporaryDirectory() as d:
            p=self.case(d,'TypeError: failed')
            with self.assertRaises(ValueError):verify(p)

if __name__=='__main__':unittest.main()
