"""Reject a different tool/receipt before qualifying a new DDR image."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts/pds'))
from tool_identity import checked_tool, implementation_tool, sha


class ToolIdentity(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.home=self.root/'pds';self.ev=self.root/'receipt'
        (self.home/'bin').mkdir(parents=True);(self.ev/'logs').mkdir(parents=True)
        (self.home/'bin/pds_shell').write_bytes(b'tool-binary')
        license_file=self.root/'license';license_file.write_bytes(b'unchanged-license')
        self.contract=self.root/'contract.json'
        value={'home':str(self.home),'resolved_home':str(self.home),'version':'2024.2','build':'178169',
               'binary_sha256':{'pds_shell':sha(self.home/'bin/pds_shell')},
               'license':{'path':str(license_file),'sha256':sha(license_file)}}
        self.contract.write_text(json.dumps(value));(self.ev/'pds-toolchain.json').write_text(json.dumps(value))
        (self.ev/'manifest.json').write_text(json.dumps({'status':'PASS'}))
        (self.ev/'checks.json').write_text(json.dumps({'checks':[{'status':'PASS'}]}))
        self.env={'PDS_HOME':str(self.home),'PANGO_LICENSE_FILE':str(license_file)}
        (self.ev/'effective-environment.json').write_text(json.dumps(self.env))
        (self.ev/'logs/doctor.stdout.log').write_text('2024.2\nPDS_LICENSE_PROBE_OK\nLICENSE=PASS\n')

    def test_checked_receipt_and_environment(self):
        with patch.dict(os.environ,self.env):
            _,identity=checked_tool(self.contract,self.ev,True)
        self.assertEqual(identity['build'],'178169')

    def test_wrong_execution_home_rejected(self):
        with patch.dict(os.environ,dict(self.env,PDS_HOME='/wrong/tool')):
            with self.assertRaisesRegex(ValueError,'execution environment'):
                checked_tool(self.contract,self.ev,True)

    def test_altered_binary_rejected(self):
        (self.home/'bin/pds_shell').write_bytes(b'old-version')
        with self.assertRaisesRegex(ValueError,'binary changed'):
            checked_tool(self.contract,self.ev)

    def test_other_contract_rejected(self):
        (self.ev/'pds-toolchain.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'another contract'):
            checked_tool(self.contract,self.ev)

    def test_bound_receipt_drift_rejected(self):
        _,identity=checked_tool(self.contract,self.ev)
        run=self.root/'implementation';run.mkdir()
        (run/'pds-toolchain.json').write_bytes(self.contract.read_bytes())
        (run/'inputs.json').write_text(json.dumps({'tool_identity':identity}))
        implementation_tool(run)
        (self.ev/'logs/doctor.stdout.log').write_text('2024.2\nPDS_LICENSE_PROBE_OK\nLICENSE=PASS\nmodified')
        with self.assertRaisesRegex(ValueError,'binding changed'):
            implementation_tool(run)


if __name__=='__main__':unittest.main()
