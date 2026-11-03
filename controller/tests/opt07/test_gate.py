import tempfile,unittest,json
from pathlib import Path
from scripts.cocotb_case import validate
from scripts.verify_opt07 import verify

class Gate(unittest.TestCase):
    def test_xml_empty_skipped_or_wrong_test_is_rejected(self):
        for xml in (None,'<testsuites/>','<testsuites><testcase name="opt07_swiglu" classname="test_opt07"><skipped/></testcase></testsuites>',
                    '<testsuites><testcase name="wrong" classname="test_opt07"/></testsuites>'):
            with tempfile.TemporaryDirectory() as d:
                p=Path(d)
                if xml is not None:(p/'results.xml').write_text(xml)
                with self.assertRaises(ValueError):validate(p,{'task':'OPT07'})
    def test_running_or_failed_archive_cannot_be_accepted(self):
        for state,exit_code in [('RUNNING',None),('FAIL',1)]:
            with tempfile.TemporaryDirectory() as d:
                p=Path(d);(p/'manifest.json').write_text(json.dumps(dict(task_id='OPT07',status=state,exit_code=exit_code)))
                with self.assertRaises(ValueError):verify(p)

if __name__=='__main__':unittest.main()
