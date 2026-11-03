import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'scripts/application_v2'))
from software.application_v2.program import execute, parse, score, ProgramError


class ProgramTests(unittest.TestCase):
    state={'temperature':30,'light':150,'led':0,'pwm':0}

    def test_comparison_boundaries_and_counterfactuals(self):
        for cmp,expected in [('>',0),('<',0),('>=',1),('<=',1)]:
            plan=[['if','temperature',cmp,30,[['led',1]],[['led',0]]]]
            self.assertEqual(execute(plan,self.state)['actions'],[['led',expected]])
        plan=[['if','temperature','>',30,[['pwm',75]],[['pwm',0]]]]
        self.assertEqual(execute(plan,dict(self.state,temperature=31))['actions'],[['pwm',75]])
        self.assertEqual(execute(plan,dict(self.state,temperature=29))['actions'],[['pwm',0]])

    def test_atomic_rejection_before_actions_and_unselected_branch(self):
        for plan,error in [([['led',1],['pwm',101]],'RANGE'),
                           ([['led',1],['reject','UNSUPPORTED']],'UNSUPPORTED'),
                           ([['if','temperature','>',100,[['pwm',-1]],[]]],'RANGE')]:
            self.assertEqual(execute(plan,self.state),{'actions':[],'readings':{},'error':error})

    def test_schema_order_and_readings(self):
        plan=[['led',1],['led',0],['read','temperature'],['read','light']]
        self.assertEqual(execute(plan,self.state),{'actions':[['led',1],['led',0]],'readings':{'temperature':30,'light':150},'error':None})
        for plan in [[['pwm',True]],[['led',1.0]],[['pwm','50']],{},[['nonsense',0]],[['if','temperature','==',30,[],[]]]]:
            self.assertEqual(execute(plan,self.state)['error'],'FORMAT')
        self.assertEqual(execute([['pwm',0]],dict(self.state,temperature=float('nan')))['error'],'STATE')
        with self.assertRaises(ProgramError):parse('[["pwm",NaN]]')

    def test_malformed_input_cannot_count_as_unsupported_refusal(self):
        for plan in [[['read']], [['read',[]]], [['if',[], '>',30,[],[]]], [['if','temperature',[],30,[],[]]]]:
            self.assertEqual(execute(plan,self.state)['error'],'FORMAT')
        case={'state':self.state,'legal':False,'program':[['reject','UNSUPPORTED']],
              'expected':{'actions':[],'readings':{},'error':'UNSUPPORTED'}}
        self.assertFalse(score(case,'[["read"]]','eos')['pass'])
        for state in [None,[],dict(self.state,temperature=10**1000)]:
            self.assertEqual(execute([['led',1]],state)['error'],'STATE')

    def test_correct_action_with_wrong_program_is_not_a_pass(self):
        plan=[['if','temperature','>',25,[['led',1]],[['led',0]]]]
        case={'state':self.state,'legal':True,'program':plan,'expected':execute(plan,self.state)}
        self.assertFalse(score(case,'[["led",1]]','eos')['pass'])
        self.assertTrue(score(case,json.dumps(plan),'eos')['pass'])
        self.assertFalse(score(case,json.dumps(plan),'max_new_tokens')['pass'])

    def test_frozen_labels_with_independent_executor(self):
        corpora={}
        for split,size in [('train',2048),('dev',50),('heldout',200)]:
            rows=[json.loads(l) for l in (Path(__file__).parent/f'{split}.jsonl').read_text().splitlines()]
            self.assertEqual(len(rows),size)
            corpora[split]={r['instruction'] for r in rows}
            for r in rows:self.assertEqual(execute(r['program'],r['state']),r['expected'],r['id'])
        for a,b in [('train','dev'),('train','heldout'),('dev','heldout')]:self.assertFalse(corpora[a]&corpora[b])


class AdapterTests(unittest.TestCase):
    def test_reload_defaults_cannot_enable_sampling(self):
        from types import SimpleNamespace
        from transformers import Qwen2Config, Qwen2ForCausalLM
        from common import generation_policy
        model=Qwen2ForCausalLM(Qwen2Config(vocab_size=32,hidden_size=16,intermediate_size=32,
                                        num_hidden_layers=1,num_attention_heads=2,num_key_value_heads=1))
        model.generation_config.transformers_version='4.57.6'
        model.generation_config.do_sample=True
        model.generation_config.repetition_penalty=1.1
        policy=generation_policy(model,SimpleNamespace(bos_token_id=0,eos_token_id=1,pad_token_id=0),{'max_new_tokens':128})
        self.assertFalse(policy.do_sample)
        self.assertEqual(policy.repetition_penalty,1.0)
        self.assertEqual(policy.max_new_tokens,128)

    def test_zero_adapter_and_merged_linear(self):
        import torch
        from lora import LoRALinear, merge
        torch.manual_seed(10)
        base=torch.nn.Linear(7,5,dtype=torch.float64)
        x=torch.randn(3,7,dtype=torch.float64)
        expected=base(x).detach()
        layer=LoRALinear(base,2,4)
        self.assertTrue(torch.equal(layer(x),expected))
        with torch.no_grad():layer.b.normal_()
        before=layer(x).detach()
        model=torch.nn.Module();model.layer=layer
        merge(model)
        torch.testing.assert_close(model.layer(x),before,rtol=1e-12,atol=1e-12)


if __name__=='__main__':unittest.main()
