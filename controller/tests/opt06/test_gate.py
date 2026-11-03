import copy,json,tempfile,unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from scripts.cocotb_case import validate
from scripts.analyze_t25_stream import analyze
from software.demo_console.server import validate_command
class Gate(unittest.TestCase):
    def test_xml_must_exist_contain_exact_test_and_no_skip(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)
            for xml in (None,'<testsuites/>','<testsuites><testcase name="wrong" classname="test_opt06"/></testsuites>','<testsuites><testcase name="opt06_stream" classname="test_opt06"><skipped/></testcase></testsuites>'):
                if xml is not None:(p/'results.xml').write_text(xml)
                with self.assertRaises(ValueError):validate(p,{'task':'OPT06'})
    def test_maximum_text_bridge_bounds(self):
        self.assertEqual(validate_command(':text 8 你好'),':text 8 你好\n'.encode())
        for value in (':text 0 x',':text 129 x',':text 1 ',':text 1.5 x',':text ١ x',':text 1 a\nb'):
            with self.assertRaises(ValueError):validate_command(value)
    def test_legacy_metrics_have_no_visible_claim(self):
        x=analyze(b'T25 METRICS first_token_ticks=000000000000007d total_ticks=00000000000000fa generated=0000000000000001 decode_ticks=0000000000000000\n')
        self.assertIsNone(x['requests'][0]['visible_ttft_seconds']);self.assertIsNone(x['requests'][0]['decode_seconds_per_token'])
if __name__=='__main__':unittest.main()
