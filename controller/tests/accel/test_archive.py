"""Archive metadata cannot redefine the required matrix in its sealed source."""
import copy
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
from evidence import content_id,sha256,write_json
from run_t13 import verify_archive


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)
        self.registered={
            'task':'T13','max_delay':3,'negative_cases':[],
            'suites':{'smoke':['control-seed1','small-seed1']}}
        self.config=dict(copy.deepcopy(self.registered),suite='smoke',
                         selected_cases=['control-seed1','small-seed1'])

    def reject(self,pattern):
        # Hashes are deliberately recomputed: an accidental regenerated config
        # must still be checked against the originally registered source matrix.
        write_json(self.path/'config.json',self.config)
        raw=json.dumps(self.registered).encode()
        with tarfile.open(self.path/'source.tar.gz','w:gz') as tar:
            entry=tarfile.TarInfo('configs/t13-accel.json');entry.size=len(raw)
            tar.addfile(entry,io.BytesIO(raw))
        import hashlib
        files={'configs/t13-accel.json':hashlib.sha256(raw).hexdigest()}
        manifest={
            'task_id':'T13','run_id':'fixture','status':'PASS','exit_code':0,
            'source':{'files':files,'sha256':content_id(files)},
            'config':{'sha256':sha256(self.path/'config.json')},
            'cases':{name:{} for name in self.config['selected_cases']},
            'artifacts':{name:sha256(self.path/name) for name in ('source.tar.gz','config.json')}}
        write_json(self.path/'manifest.json',manifest)
        write_json(self.path/'commands.json',[{'status':'PASS'}])
        write_json(self.path/'checks.json',{'checks':[{'status':'PASS'}]})
        (self.path/'exit-status.txt').write_text('0\n')
        with self.assertRaisesRegex(ValueError,pattern):verify_archive(self.path)

    def test_empty_matrix_cannot_pass(self):
        self.config['selected_cases']=[]
        self.reject('registered matrix|unknown suite')

    def test_omitted_case_cannot_pass(self):
        self.config['selected_cases']=['control-seed1']
        self.reject('registered matrix|unknown suite')

    def test_duplicate_case_cannot_replace_required_case(self):
        self.config['selected_cases']=['control-seed1','control-seed1']
        self.reject('required matrix|registered matrix')

    def test_rewritten_suite_cannot_change_source_contract(self):
        self.config['suites']['smoke']=['control-seed1']
        self.config['selected_cases']=['control-seed1']
        self.reject('registered matrix|unknown suite')

    def test_unknown_suite_cannot_bypass_requirements(self):
        self.config['suite']='unregistered'
        self.reject('registered matrix|unknown suite')

    def test_rehashed_timing_config_is_rejected(self):
        self.config['max_delay']=0
        self.reject('registered matrix')


if __name__=='__main__':unittest.main()
