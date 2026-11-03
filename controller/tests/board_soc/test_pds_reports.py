"""Reject incomplete or failing primary reports before any static claim."""
import re,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'scripts'))
from pds.t24_static_reports import signal_inventory,timing_tables
PARENT=ROOT/'evidence/T24_PDS_REPORTS/t23-parser-plumbing-20261012-v1'
class ReportGates(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.map=(PARENT/'test_ddr.dmr').read_text();cls.timing=(PARENT/'test_ddr.rtr').read_text()
    def test_frozen_actual_reports(self):
        self.assertEqual({k:len(v) for k,v in signal_inventory(self.map).items()}, {'Clock Signal':5,'Reset Signal':43,'CE Signal':276})
        self.assertEqual(len(timing_tables(self.timing)),10)
    def test_missing_reset_inventory(self):
        with self.assertRaisesRegex(ValueError,'missing Reset'):signal_inventory(self.map.replace('Reset Signal:','Missing Reset:'))
    def test_query_handle_is_not_an_endpoint(self):
        text=self.map.replace('refclk_inbuf','@tcicmdresult62')
        with self.assertRaisesRegex(ValueError,'invalid Clock'):signal_inventory(text)
    def test_other_tool_report_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'tool identity'):signal_inventory(self.map.replace('build 178169','build 113398'))
    def test_one_missing_corner_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'ten corner'):timing_tables(self.timing.replace('Hold Summary(Fast Corner):','Missing Summary(Fast Corner):'))
    def test_zero_exit_cannot_hide_negative_slack(self):
        text=re.sub(r'(Setup Summary\(Slow Corner\):\n.*?\n\s*\S+\s+\S+\s+)(\d+\.\d+)(\s+\d+\.\d+\s+0\s+\d+)',r'\g<1>-0.001\g<3>',self.timing,count=1,flags=re.S)
        self.assertNotEqual(text,self.timing)
        with self.assertRaisesRegex(ValueError,'failed timing'):timing_tables(text)
    def test_undefined_or_nan_slack_is_rejected(self):
        for value in ('nan','undefined'):
            text=re.sub(r'(Setup Summary\(Slow Corner\):\n.*?\n\s*\S+\s+\S+\s+)(\d+\.\d+)(\s+\d+\.\d+\s+0\s+\d+)',r'\g<1>'+value+r'\g<3>',self.timing,count=1,flags=re.S)
            with self.subTest(value=value),self.assertRaises(ValueError):timing_tables(text)
if __name__=='__main__':unittest.main()
