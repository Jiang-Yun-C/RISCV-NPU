"""Negative gate controls: a receipt PASS must never become board GO."""
import copy,json,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT)]
from opt10_r1_copy_bound import assess
from verify_opt10_r1_copy_bound import validate

class CopyBoundTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pack=json.loads((ROOT/'docs/spec/model-pack-v1-manifest.json').read_text())
        cls.budget=json.loads((ROOT/'configs/opt05-budgets.json').read_text())
        cls.result=assess(ROOT/'build/OPT16_CANDIDATE/opt10-r1-candidate-20261020-v10/repo',ROOT)
    def check_rejected(self,key,value):
        data=copy.deepcopy(self.result);data[key]=value
        with self.assertRaises(ValueError):validate(data,self.pack,self.budget)
    def test_actual_negative(self):
        self.assertEqual(validate(self.result,self.pack,self.budget)['necessary_cycles'],467009536)
    def test_go_rejected(self):self.check_rejected('decision','GO')
    def test_false_board_gate_rejected(self):self.check_rejected('board_gate','GO')
    def test_missing_projection_rejected(self):self.check_rejected('projections',168)
    def test_repeated_head_rejected(self):self.check_rejected('head_output_words',4*151936)
    def test_free_write_drain_rejected(self):self.check_rejected('per_word_serial_drain_cycles',0)
    def test_incorrect_bound_rejected(self):self.check_rejected('decode_cycles_floor',250000000)
    def test_clock_change_rejected(self):self.check_rejected('clock_hz',250000000)
    def test_unknown_prediction_zero_rejected(self):self.check_rejected('integrated_prediction_seconds',0)
    def test_unmeasured_decode_zero_rejected(self):self.check_rejected('actual_decode_seconds',0)
    def test_frequency_signoff_invented_rejected(self):self.check_rejected('frequency_signoff_hz',125000000)
    def test_goal_relaxation_rejected(self):
        budget=copy.deepcopy(self.budget);budget['decode_seconds_per_token_max']=4
        with self.assertRaises(ValueError):validate(self.result,self.pack,budget)
    def test_head_geometry_rejected(self):
        pack=copy.deepcopy(self.pack)
        next(e for e in pack['directory'] if e['name']=='model.embed_tokens.weight')['shape'][0]=1000
        with self.assertRaises(ValueError):validate(self.result,pack,self.budget)

if __name__=='__main__':unittest.main()
