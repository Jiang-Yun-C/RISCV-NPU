import copy,json,sys,tempfile,unittest,tarfile
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'tests/end_to_end'),str(ROOT/'tests/cocotb'),str(ROOT/'tests/soc_accel')]
from model_prepare import prepare
from model_scoreboard import score
from evidence import sha256,content_id,write_json
from run_t19 import verify_archive

class CheckerControls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.path=Path(cls.tmp.name);cls.fixture=prepare(cls.path/'fixture',{},'smoke');cls.golden=json.loads((cls.path/'fixture/golden.json').read_text());cls.arrays=np.load(cls.path/'fixture/golden.npz')
        rows=[]
        for i,v in enumerate([0,0,1,2*2*9*16*4,len(cls.golden['jobs'])]):rows.append((1,i,v))
        for step in range(2):rows.extend([(100+step,0,0),(100+step,1,step+1)])
        for i in range(len(cls.golden['jobs'])):rows.extend((700+i,z,v) for z,v in enumerate([2,1,0,0,100]))
        for key in cls.golden['specs']:rows.extend((int(key),i,int(v)) for i,v in enumerate(cls.arrays[key].view('u4').flat))
        for i,count in enumerate([2,10,28,8,4,4,8,2]):rows.extend([(4,2*i,100),(4,2*i+1,count)])
        cls.rows=rows
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def write(self,rows):d=self.path/'candidate';d.mkdir(exist_ok=True);(d/'cpu-output.txt').write_text(''.join('%d %d %d\n'%r for r in rows));return d
    def test_bad_reference_reports_first_numeric_difference(self):
        with self.assertRaisesRegex(AssertionError,'data:.*index'):score(self.write(self.rows),self.fixture,self.golden,self.path/'fixture',negative='bad-golden')
    def test_bad_kv_reports_layer_token_and_index(self):
        with self.assertRaisesRegex(AssertionError,'kv:.*cache_k'):score(self.write(self.rows),self.fixture,self.golden,self.path/'fixture',negative='bad-kv')
    def test_missing_stage_is_rejected(self):
        group=int(next(k for k,v in self.golden['specs'].items() if v['stage']=='logits'))
        with self.assertRaisesRegex(AssertionError,'output_set'):score(self.write([r for r in self.rows if r[0]!=group]),self.fixture,self.golden,self.path/'fixture')
    def test_duplicate_stage_output_is_rejected(self):
        with self.assertRaisesRegex(AssertionError,'unique CPU trace'):score(self.write(self.rows+[self.rows[-1]]),self.fixture,self.golden,self.path/'fixture')

class ArchiveMatrix(unittest.TestCase):
    def test_rehashed_empty_omitted_duplicate_or_rewritten_matrix_rejected(self):
        for kind in ('empty','omitted','duplicate','rewrite','unknown'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as temp:
                d=Path(temp);reg=json.loads((ROOT/'configs/t19-model-integration.json').read_text());cfg=copy.deepcopy(reg);cfg.update(suite='full',selected_cases=reg['suites']['full'].copy());cases={n:{} for n in cfg['selected_cases']}
                if kind=='empty':cfg['selected_cases']=[];cases={}
                elif kind=='omitted':cfg['selected_cases'].pop();cases.pop('continuous-seed1')
                elif kind=='duplicate':cfg['selected_cases'].append(cfg['selected_cases'][0])
                elif kind=='rewrite':cfg['cases']['smoke-seed1']['max_delay']=0
                else:cfg['suite']='unknown'
                write_json(d/'config.json',cfg);write_json(d/'commands.json',[{'status':'PASS'}]);write_json(d/'checks.json',{'checks':[{'status':'PASS'}]});(d/'exit-status.txt').write_text('0\n')
                name='configs/t19-model-integration.json';files={name:sha256(ROOT/name)}
                with tarfile.open(d/'source.tar.gz','w:gz') as tar:tar.add(ROOT/name,arcname=name)
                write_json(d/'manifest.json',dict(task_id='T19',status='PASS',exit_code=0,artifacts={'config.json':sha256(d/'config.json')},config={'sha256':sha256(d/'config.json')},source={'files':files,'sha256':content_id(files)},cases=cases))
                with self.assertRaisesRegex(ValueError,'registered matrix'):verify_archive(d)
