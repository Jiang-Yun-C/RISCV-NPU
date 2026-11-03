"""Rehashed metadata may not silently remove T16 mandatory coverage."""
import hashlib,json,sys,tarfile,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'scripts'))
from evidence import content_id,sha256,write_json,EvidenceRun
from run_t16 import verify_archive,capture_changes,archive
class ArchiveMatrix(unittest.TestCase):
    def candidate(self,td):
        p=Path(td);registered=json.loads((ROOT/'configs/t16-soc-accel.json').read_text());config={**registered,'suite':'full','selected_cases':registered['suites']['full']}
        write_json(p/'config.json',config);write_json(p/'commands.json',[{'status':'PASS'}]);write_json(p/'checks.json',{'checks':[{'status':'PASS'}]});(p/'exit-status.txt').write_text('0\n')
        files={'configs/t16-soc-accel.json':sha256(ROOT/'configs/t16-soc-accel.json')}
        with tarfile.open(p/'source.tar.gz','w:gz') as tar:tar.add(ROOT/'configs/t16-soc-accel.json',arcname='configs/t16-soc-accel.json')
        manifest={'status':'PASS','exit_code':0,'config':{'sha256':sha256(p/'config.json')},'source':{'files':files,'sha256':content_id(files)},'artifacts':{'config.json':sha256(p/'config.json'),'source.tar.gz':sha256(p/'source.tar.gz')},'cases':{n:{} for n in config['selected_cases']}}
        return p,config,manifest
    def mutate(self,fn):
        with tempfile.TemporaryDirectory() as td:
            p,c,m=self.candidate(td);fn(c,m);write_json(p/'config.json',c);m['config']['sha256']=sha256(p/'config.json');m['artifacts']['config.json']=sha256(p/'config.json');write_json(p/'manifest.json',m)
            with self.assertRaisesRegex(ValueError,'registered case matrix'):verify_archive(p)
    def test_missing_full_head(self):self.mutate(lambda c,m:m['cases'].pop('head-seed1'))
    def test_empty_case_set(self):self.mutate(lambda c,m:m.update(cases={}))
    def test_rehashed_shortened_suite(self):
        def change(c,m):c['selected_cases'].remove('head-seed1');m['cases'].pop('head-seed1')
        self.mutate(change)
    def test_rehashed_memory_profile(self):self.mutate(lambda c,m:c['cases']['control-seed1'].update(max_delay=0))

class CaptureProvenance(unittest.TestCase):
    def test_archive_records_actual_file_digests(self):
        with tempfile.TemporaryDirectory() as td:
            run=EvidenceRun(td,'T16','archive-regression');(run.build/'tool-report.json').write_text('{}\n')
            archive(run);run.finish(0)
            manifest=json.loads((run.path/'manifest.json').read_text())
            self.assertEqual(manifest['artifacts']['artifacts/tool-report.json'],sha256(run.path/'artifacts/tool-report.json'))
    def reject(self,name):
        with self.assertRaisesRegex(ValueError,'execution or numerical source changed'):
            capture_changes({name:'old'},{name:'new'})
    def test_rtl_change_requires_new_capture(self):self.reject('rtl/soc/nx_shared_memory_arbiter.sv')
    def test_firmware_change_requires_new_capture(self):self.reject('firmware/drivers/accel/coral_linear.c')
    def test_numeric_change_requires_new_capture(self):self.reject('tests/soc_accel/scoreboard.py')
    def test_fixture_change_requires_new_capture(self):self.reject('tests/soc_accel/prepare.py')
    def test_postprocessing_only_revalidation(self):
        self.assertEqual(capture_changes({'tests/soc_accel/waveform.py':'old'},
            {'tests/soc_accel/waveform.py':'new','tests/soc_accel/test_waveform.py':'new'}),
            ['tests/soc_accel/test_waveform.py','tests/soc_accel/waveform.py'])
