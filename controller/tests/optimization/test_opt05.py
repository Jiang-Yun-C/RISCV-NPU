"""Behavioral checks for context, transaction splitting and honest timing."""
import copy
import json
from pathlib import Path
import unittest

from scripts.opt05_model import (matrix_cost, split_bytes, schedule, reconcile,
                                evaluate_timeline, expand_counter, decode_metrics)

ROOT=Path(__file__).resolve().parents[2]


class ModelTests(unittest.TestCase):
    def test_page_split(self):
        self.assertEqual(split_bytes(4080,64,16,512),[16,48])
        self.assertEqual(split_bytes(4092,56,4,128),[4,52])
        self.assertEqual(split_bytes(0,304,4,128),[128,128,48])

    def test_scale_rows_cross_pages(self):
        cost=matrix_cost(1,129,896)
        self.assertEqual(cost['commands']['scale_read'],130)
        self.assertEqual(cost['commands']['weight_read'],129*14)
        self.assertEqual(cost['commands']['output_write'],33)

    def test_tail_output_is_not_padded(self):
        cost=matrix_cost(1,131,896)
        self.assertEqual(cost['commands']['output_write'],35)
        self.assertEqual(cost['ce_dma_write_bytes'],131*4)

    def test_m4_does_not_claim_m1_output_packing(self):
        one,four=matrix_cost(1,128,896),matrix_cost(4,128,896)
        self.assertEqual(four['macs'],4*one['macs'])
        self.assertEqual(four['tensors_bytes']['Wq'],one['tensors_bytes']['Wq'])
        self.assertEqual(four['commands']['output_write'],512)
        self.assertEqual(one['commands']['output_write'],32)

    def test_invalid_shapes_rejected(self):
        for args in [(0,128,896),(5,128,896),(1,0,896),(1,128,897)]:
            with self.assertRaises(ValueError):matrix_cost(*args)

    def test_decode_is_g_minus_one(self):
        plan=schedule(3,3)
        self.assertEqual(len(plan),5)
        self.assertEqual([b['phase'] for b in plan].count('decode'),2)
        self.assertEqual(sum(b['head'] for b in plan),3)

    def test_context_boundaries(self):
        self.assertEqual(sum(x['emits_token'] for x in schedule(511,1)),1)
        full=schedule(512,0)
        self.assertEqual(len(full),512)
        self.assertEqual(sum(x['emits_token'] for x in full),0)
        self.assertTrue(full[-1]['head'])
        for args in [(512,1),(511,2),(3,0),(0,2),(513,0)]:
            with self.assertRaises(ValueError):schedule(*args)

    def test_prefix_context_does_not_restart(self):
        blocks=schedule(32,8,24)
        self.assertEqual(blocks[0]['context'],25)
        self.assertEqual(blocks[-1]['context'],39)
        self.assertEqual(len(blocks),15)

    def test_unknown_timing_propagates(self):
        rows=[dict(duration_key='a'),dict(duration_key='b')]
        self.assertEqual(evaluate_timeline(rows,dict(a=2,b=3))['seconds'],5)
        self.assertIsNone(evaluate_timeline(rows,dict(a=2))['seconds'])

    def test_overlap_and_bad_duration_fail(self):
        with self.assertRaises(ValueError):evaluate_timeline([dict(duration_key='a',overlap=True)],dict(a=1))
        for x in [-1,float('nan'),float('inf')]:
            with self.assertRaises(ValueError):evaluate_timeline([dict(duration_key='a')],dict(a=x))

    def test_counter_wrap_and_ambiguity(self):
        self.assertEqual(expand_counter(0xfffffff0,16,64),32)
        with self.assertRaises(ValueError):expand_counter(1,2,1<<32)
        with self.assertRaises(ValueError):expand_counter(0,20,2)

    def test_one_token_has_no_throughput(self):
        self.assertIsNone(decode_metrics([125000000],1)['tok_s'])
        result=decode_metrics([125000000,250000000,500000000],3)
        self.assertEqual(result['intervals'],2)
        self.assertAlmostEqual(result['tok_s'],2/3)
        self.assertIsNone(result['p95_seconds'])

    def test_missing_token_times_fail(self):
        with self.assertRaises(ValueError):decode_metrics([1],3)
        with self.assertRaises(ValueError):decode_metrics([1,1],2)

    def test_corrupt_profile_and_fallback_fail(self):
        samples=[json.loads(l) for l in (ROOT/'evidence/OPT04/opt04-completion-20261018-v1/samples.jsonl').read_text().splitlines()]
        sample=next(s for s in samples if s['variant']=='B' and s['case']=='S')
        result=reconcile(sample)
        self.assertEqual(result['unclassified_ticks'],598128022)
        self.assertFalse(result['dispatch_added_to_total'])
        bad=copy.deepcopy(sample);bad['profile_delta'][0]['calls']+=1
        with self.assertRaises(ValueError):reconcile(bad)
        bad=copy.deepcopy(sample);bad['metrics']['fallback_calls']=1
        with self.assertRaises(ValueError):reconcile(bad)
        bad=copy.deepcopy(sample);bad['metrics']['total_ticks']=1
        with self.assertRaises(ValueError):reconcile(bad)


if __name__=='__main__':unittest.main()
