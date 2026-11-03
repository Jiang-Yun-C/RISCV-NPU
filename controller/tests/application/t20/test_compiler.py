"""Whole-output provenance, actual request replay, and UART byte boundaries."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT),str(ROOT/'scripts'),str(ROOT/'tests/application/t20')]
from software.application_v2.compiler import compile_request
from software.application_v2.serial_control import frame
from prepare import verify_model
from evidence import sha256,write_json
MODEL=ROOT/'evidence/T20_MODEL/acceptance-20261008-v3'

class ReplayModel:
    def __init__(self,steps):self.steps=list(steps);self.calls=[]
    def generate(self,tokenizer,messages):
        step=self.steps[len(self.calls)];self.calls.append(messages)
        if messages!=step['messages']:raise AssertionError('model input changed during provenance replay')
        return {k:copy.deepcopy(step[k]) for k in ('text','stop','output_ids')}

class CompilerTests(unittest.TestCase):
    def test_every_fresh_model_request_selects_exact_original_candidate(self):
        for row in map(json.loads,(MODEL/'results.jsonl').read_text().splitlines()):
            with self.subTest(case=row['id']):
                model=ReplayModel(row['candidates']);r=compile_request(model,None,row['input'],row['state'])
                self.assertEqual(len(model.calls),len(row['candidates']))
                for k in ('text','output_ids','stop','selected_route','selected_prompt'):self.assertEqual(r[k],row[k])
                self.assertTrue(any(all(r[k]==s[k] for k in ('text','output_ids','stop')) for s in row['candidates']))
    def test_primary_without_eos_cannot_trigger_extension(self):
        class Model:
            def generate(self,tokenizer,messages):return dict(text='[["if","light",">",1,[],[]]]',stop='max_new_tokens',output_ids=[1])
        r=compile_request(Model(),None,'任意文字',dict(temperature=1,light=2,led=0,pwm=0))
        self.assertEqual(r['stop'],'max_new_tokens');self.assertEqual(len(r['candidates']),1)
    def test_uart_header_counts_utf8_bytes(self):
        packet=frame(12,5,'打开灯。','[["led",1]]');header,text,intent,_=packet.split(b'\n')
        self.assertEqual(list(map(int,header.split())),[12,5,len(text),len(intent)])
        self.assertEqual(text.decode(),'打开灯。')
    def test_uart_rejects_ambiguous_or_oversized_payload(self):
        for args in [(0,1,'x','[]'),(0xffffffff,1,'x','[]'),(1,1,'x\x00','[]'),(1,1,'中'*1366,'[]'),(1,1,'x','[]'*2049)]:
            with self.assertRaises(ValueError):frame(*args)

class ModelArchiveTests(unittest.TestCase):
    def tamper(self,mutate,message):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'model';shutil.copytree(MODEL,path)
            rows=list(map(json.loads,(path/'results.jsonl').read_text().splitlines()));mutate(rows[0])
            (path/'results.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows))
            summary=json.loads((path/'summary.json').read_text());summary['results_sha256']=sha256(path/'results.jsonl');write_json(path/'summary.json',summary)
            m=json.loads((path/'manifest.json').read_text());m['result']=summary
            for n in ('results.jsonl','summary.json'):m['artifacts'][n]=sha256(path/n)
            write_json(path/'manifest.json',m)
            with self.assertRaisesRegex(ValueError,message):verify_model(path)
    def test_rehashed_selected_tokens_must_belong_to_model_call(self):
        self.tamper(lambda r:r['output_ids'].append(123),'whole model output')
    def test_rehashed_prompt_cannot_substitute_expected_answer(self):
        self.tamper(lambda r:r['candidates'][0]['messages'][1].update(content='oracle answer'),'prompt/input identity')

if __name__=='__main__':unittest.main()
