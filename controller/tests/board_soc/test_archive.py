"""Fail-closed T24 acceptance: a rehashed archive cannot shrink the matrix."""
import json,sys,tarfile,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'scripts'))
from evidence import content_id,sha256,write_json
from run_t24 import verify_archive

class Matrix(unittest.TestCase):
    def reject(self,mutate,reason='frozen matrix'):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);registered=json.loads((ROOT/'configs/t24-soc-board.json').read_text())
            c={**registered,'suite':'full','selected_cases':list(registered['suites']['full'])}
            files={'configs/t24-soc-board.json':sha256(ROOT/'configs/t24-soc-board.json')}
            with tarfile.open(p/'source.tar.gz','w:gz') as tar:tar.add(ROOT/'configs/t24-soc-board.json',arcname='configs/t24-soc-board.json')
            write_json(p/'commands.json',[{'status':'PASS'}]);write_json(p/'checks.json',{'checks':[{'status':'PASS'}]});(p/'exit-status.txt').write_text('0\n')
            m=dict(task_id='T24',status='PASS',exit_code=0,source={'files':files,'sha256':content_id(files)},cases={n:{} for n in c['selected_cases']})
            mutate(c,m);write_json(p/'config.json',c);m['config']={'sha256':sha256(p/'config.json')};m['artifacts']={n:sha256(p/n) for n in ('source.tar.gz','config.json')};write_json(p/'manifest.json',m)
            with self.assertRaisesRegex(ValueError,reason):verify_archive(p)
    def test_missing_head(self):self.reject(lambda c,m:m['cases'].pop('head-seed1'))
    def test_rehashed_shortened_full(self):
        def shorten(c,m):c['selected_cases'].remove('head-seed1');m['cases'].pop('head-seed1')
        self.reject(shorten)
    def test_empty_case_set(self):self.reject(lambda c,m:m.update(cases={}))
    def test_disabled_backpressure(self):self.reject(lambda c,m:c['cases']['control-seed1'].update(max_delay=0))
    def test_wrong_task(self):self.reject(lambda c,m:m.update(task_id='T16'),'not a completed T24 PASS')
    def test_running_archive(self):self.reject(lambda c,m:m.update(status='RUNNING'),'not a completed T24 PASS')

if __name__=='__main__':unittest.main()
