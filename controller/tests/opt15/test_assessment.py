import copy
import json
from pathlib import Path
import unittest
from scripts.opt15_model import assess, bound, ledger, matrices

ROOT=Path(__file__).resolve().parents[2]


class AssessmentTests(unittest.TestCase):
    def setUp(self):
        self.cfg=json.loads((ROOT/'configs/opt15-gemmini-assessment.json').read_text())
        self.records=matrices(json.loads((ROOT/'docs/spec/model-pack-v1-manifest.json').read_text()))

    def test_exact_full_model_bytes(self):
        rows=ledger(self.records,1,1)
        self.assertEqual(len(rows),169)
        self.assertEqual(sum(r['group_restores'] for r in rows),7718144)
        self.assertEqual(sum(r['Wq_read_bytes'] for r in rows),493961216)
        self.assertEqual(sum(r['Sw_read_bytes'] for r in rows),30872576)

    def test_prefill_only_last_row_head(self):
        rows=ledger(self.records,4,4)
        self.assertEqual(sum(r['m'] for r in rows if r['op']=='head'),1)
        self.assertEqual(sum(r['group_restores'] for r in rows),4*5591040+2127104)
        tail=ledger(self.records,5,4)
        self.assertTrue(all(r['weight_loads']==2 for r in tail if r['op']!='head'))

    def test_spill_is_not_only_final_logits(self):
        b=bound(ledger(self.records,1,1),self.cfg['candidates'][0],self.cfg)
        self.assertEqual(b['totals']['partial_int32_write_bytes'],30872576)
        self.assertEqual(b['partial_write_transactions_floor'],482384)
        self.assertGreater(b['seconds_floor'],4)

    def test_128_byte_port_still_misses_target(self):
        b=bound(ledger(self.records,1,1),self.cfg['candidates'][1],self.cfg)
        self.assertGreater(b['seconds_floor'],2)
        self.assertLess(b['drain_cycles_floor']/125000000,2)
        self.assertEqual(b['exclusive_bus_cycles_floor'],b['read_cycles_floor']+b['drain_cycles_floor'])

    def test_no_rejection_of_new_coalescing_design(self):
        for cap in (256,512):
            c=copy.deepcopy(self.cfg['candidates'][0]);c['dma_maxbytes']=cap
            with self.assertRaisesRegex(ValueError,'new assessment'):bound(ledger(self.records,1,1),c,self.cfg)
        self.cfg['coalesce_across_upstream_requests']=True
        with self.assertRaises(ValueError):bound(ledger(self.records,1,1),self.cfg['candidates'][0],self.cfg)

    def test_no_restoration_semantic_shortcut(self):
        c=copy.deepcopy(self.cfg['candidates'][0]);c['restore']='FULL_K_INT32_THEN_SCALE'
        with self.assertRaises(ValueError):bound(ledger(self.records,1,1),c,self.cfg)

    def test_persistent_cache_saves_reads_on_every_pass(self):
        b=bound(ledger(self.records,9,4),self.cfg['candidates'][0],self.cfg)
        self.assertEqual(b['weight_passes'],3)
        self.assertEqual(b['persistent_cache_credit_bytes'],3*(24*1024+98304))

    def test_unknowns_are_not_zeros(self):
        a=assess(ROOT)
        self.assertFalse(a['selected_for_OPT16'])
        self.assertIsNone(a['decode_prediction_seconds'])
        self.assertIsNone(a['full_path_upper_seconds'])
        self.assertEqual(a['adopted_savings']['cycles'],0)
        self.assertTrue(all(x['resources']['frequency_signoff_hz'] is None for x in a['comparisons']))


if __name__=='__main__':unittest.main()
