"""Rejection validity, applicability and missing-evidence regression tests."""
import copy
import json
from pathlib import Path
import unittest

from scripts.opt16_model import assess, proof
from scripts.verify_opt16 import validate_decision

ROOT = Path(__file__).resolve().parents[2]


class GateTests(unittest.TestCase):
    def setUp(self):
        self.a = assess(ROOT/'variants/opt13', ROOT)
        self.pack = json.loads((ROOT/'docs/spec/model-pack-v1-manifest.json').read_text())
        self.workloads = json.loads((ROOT/'configs/opt05-workloads.json').read_text())
        self.budgets = json.loads((ROOT/'configs/opt05-budgets.json').read_text())

    def check_decision(self, value):
        return validate_decision(value, self.pack, self.workloads, self.budgets)

    def test_full_vocabulary_rejection(self):
        self.assertEqual(self.check_decision(self.a)['necessary_cycles'], 401343488)
        self.assertEqual(self.a['decode_seconds_floor'], 3.210747904)
        self.assertGreater(self.a['layer_groups']*52/125000000, 2)

    def test_reduced_bound_cannot_be_reported(self):
        a = copy.deepcopy(self.a); a['decode_cycles_floor'] = 250000000
        with self.assertRaisesRegex(ValueError,'independent projection bound'): self.check_decision(a)

    def test_unknown_visible_phase_is_not_zero(self):
        a = copy.deepcopy(self.a); a['workloads'][0]['visible_ttft_seconds']['conservative'] = 0
        with self.assertRaisesRegex(ValueError,'unknown phase'): self.check_decision(a)

    def test_one_head_for_m4(self):
        a = copy.deepcopy(self.a); a['workloads'][0]['prefill_plus_one_head_cycles_floor'] += 3*a['head_groups']*52
        with self.assertRaisesRegex(ValueError,'workload bound'): self.check_decision(a)

    def test_context_512_has_no_visible_token(self):
        rows = [x for x in self.a['workloads'] if x['prompt'] == 512]
        self.assertTrue(rows); self.assertTrue(all(not x['ttft_metric_applicable'] for x in rows))
        self.assertTrue(all(x['decode_mean_seconds']['conservative'] is None for x in rows))

    def test_warm_prefix_is_not_free_first_request(self):
        rows = [x for x in self.a['workloads'] if x['prefix'] > 0]
        self.assertTrue(rows); self.assertTrue(all(x['first_request_must_add_prefix_preparation'] for x in rows))

    def test_missing_workload_fails(self):
        a = copy.deepcopy(self.a); a['workloads'].pop()
        with self.assertRaisesRegex(ValueError,'coverage'): self.check_decision(a)

    def test_no_go_cannot_activate_board(self):
        a = copy.deepcopy(self.a); a['decision'] = 'GO'
        with self.assertRaisesRegex(ValueError,'cannot authorize GO'): self.check_decision(a)

    def test_controller_refactor_invalidates_bound(self):
        source = (ROOT/'variants/opt13/rtl/ce64/nx_ce64_control.sv').read_text()
        with self.assertRaisesRegex(ValueError,'controller'):
            proof(source.replace('state<=RAM_WAIT','state<=return_state'))

    def test_signoff_frequency_is_not_assumed(self):
        a = copy.deepcopy(self.a); a['frequency_signoff_hz'] = 125000000
        with self.assertRaisesRegex(ValueError,'signoff claimed'): self.check_decision(a)


if __name__ == '__main__': unittest.main()
