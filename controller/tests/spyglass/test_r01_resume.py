"""Recovery must reject identity drift before accepting preserved raw cases."""
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import resume_r01
from evidence import write_json


class RecoveryIntegrity(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.path = self.root/'evidence/T17/r01-resume-v1'
        self.path.mkdir(parents=True)
        self.manifest = dict(task_id='T17', run_id='r01-resume-v1', status='RUNNING')
        write_json(self.path/'manifest.json', self.manifest)
        write_json(self.path/'commands.json', [])
        write_json(self.path/'checks.json', dict(checks=[]))

    def test_wrong_run_identity_rejected(self):
        self.manifest['run_id'] = 'historical-run'
        write_json(self.path/'manifest.json', self.manifest)
        with patch.object(resume_r01, 'ROOT', self.root), self.assertRaisesRegex(ValueError, 'identity mismatch'):
            resume_r01.restore('T17', 'r01-resume-v1')

    def test_duplicate_original_launch_rejected(self):
        write_json(self.path/'commands.json', [dict(name='case-a'), dict(name='case-a')])
        with patch.object(resume_r01, 'ROOT', self.root), self.assertRaisesRegex(ValueError, 'duplicate step'):
            resume_r01.restore('T17', 'r01-resume-v1')

    def test_stale_case_identity_rejected(self):
        with patch.object(resume_r01, 'ROOT', self.root):
            run = resume_r01.restore('T17', 'r01-resume-v1')
            directory = run.build/'cocotb/control-seed1'
            directory.mkdir(parents=True)
            write_json(directory/'case.json', dict(task='T17', case_id='control-seed1',
                       run_id='r01-static-fix-v1', negative=None))
            with self.assertRaisesRegex(ValueError, 'case identity mismatch'):
                resume_r01.qualify_case(run, SimpleNamespace(__name__='run_t17'), 'control-seed1')


if __name__ == '__main__':
    unittest.main()
