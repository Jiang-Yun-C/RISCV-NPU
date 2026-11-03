"""Meaningful negative controls for raw-wire, denominator and semantic scoring."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from software.competition_semantics import evaluate

spec = importlib.util.spec_from_file_location("semantic_fixture", Path(__file__).with_name("make_fixture.py"))
fixture = importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)


class SemanticEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory(prefix="semantic-evidence-tests-")
        self.root = Path(self.scratch.name)
        self.run = fixture.make(self.root / "run")

    def tearDown(self):
        self.scratch.cleanup()

    def edit_export(self, case_id, transform):
        path = self.run.parent / "exports" / (case_id + ".json")
        record = evaluate.load(path);transform(record)
        path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf8")

    def score(self):return evaluate.score_run(self.run)

    def test_fixture_end_to_end_is_explicitly_not_model_accuracy(self):
        result = self.score()
        self.assertEqual(result["protocol"], {"accepted": 24, "total": 24})
        self.assertEqual(result["diagnostic_semantic_agreement"]["passed"], 24)
        self.assertIsNone(result["declared_live_model_semantics"]["accuracy_including_missing_and_failed"])
        self.assertEqual(len(result["paired_virtual_states"]), 5)
        self.assertTrue(all(x["semantic_pair_pass"] for x in result["paired_virtual_states"].values()))
        self.assertTrue(all(not x["physical_sensor_pair_verified"] for x in result["paired_virtual_states"].values()))
        self.assertEqual(result["physical_evidence"]["actuator_operations_by_this_tool"], 0)

    def test_empty_run_has_no_fake_zero_percent_measurement(self):
        for path in (self.run.parent / "exports").iterdir():path.unlink()
        result = self.score()
        self.assertEqual(result["status"], "NO_CAPTURE_DATA")
        self.assertEqual(result["missing_exports"], 24)
        self.assertIsNone(result["declared_live_model_semantics"]["accuracy_including_missing_and_failed"])

    def test_missing_timeout_stays_in_denominator(self):
        (self.run.parent / "exports/sem-24.json").unlink()
        manifest = evaluate.load(self.run);manifest["records"][-1]["attempt_status"] = "timeout"
        self.run.write_text(json.dumps(manifest))
        result = self.score()
        self.assertEqual(result["diagnostic_semantic_agreement"]["total"], 24)
        self.assertEqual(result["diagnostic_semantic_agreement"]["passed"], 23)
        self.assertIn("no export: timeout", result["records"][-1]["issues"])

    def test_self_reported_complete_and_metrics_do_not_override_bad_wire(self):
        def change(record):
            record["raw"] = record["raw"].replace("T25 READY\n", "")
            record.pop("rawChunks");record["complete"] = True;record["metrics"] = {"accuracy": 1}
        self.edit_export("sem-01", change)
        self.assertFalse(self.score()["records"][0]["protocol_accepted"])

    def test_raw_chunk_disagreement_rejected(self):
        self.edit_export("sem-01", lambda r: r.update(raw=r["raw"].replace("led", "pwm")))
        self.assertFalse(self.score()["records"][0]["protocol_accepted"])

    def test_missing_receive_chunk_rejected(self):
        self.edit_export("sem-01", lambda r: r["rawChunks"].pop(1))
        self.assertFalse(self.score()["records"][0]["protocol_accepted"])

    def test_wrong_request_cannot_reuse_good_output(self):
        self.edit_export("sem-01", lambda r: r.update(command="unrelated input"))
        self.assertFalse(self.score()["records"][0]["protocol_accepted"])

    def test_constant_action_cannot_fake_conditional_semantics(self):
        _, commands, contract, _ = evaluate.cases_and_commands()
        path = self.run.parent / "exports/sem-09.json"
        path.write_text(json.dumps(fixture.export_record(commands["sem-09"], '[["led",0]]', contract)))
        row = self.score()["records"][8]
        self.assertTrue(row["protocol_accepted"])
        self.assertEqual(row["virtual_execution"], row["expected"])
        self.assertFalse(row["program_match"])
        self.assertFalse(row["semantic_pass"])

    def test_correct_truncated_program_is_not_eos_success(self):
        _, commands, contract, _ = evaluate.cases_and_commands()
        path = self.run.parent / "exports/sem-01.json"
        path.write_text(json.dumps(fixture.export_record(commands["sem-01"], '[["led",1]]', contract, eos=False)))
        row = self.score()["records"][0]
        self.assertTrue(row["protocol_accepted"]);self.assertFalse(row["semantic_pass"])

    def test_same_range_error_cannot_hide_wrong_requested_integer(self):
        _, commands, contract, _ = evaluate.cases_and_commands()
        path = self.run.parent / "exports/sem-23.json"
        path.write_text(json.dumps(fixture.export_record(commands["sem-23"], '[["pwm",-2]]', contract)))
        row = self.score()["records"][22]
        self.assertTrue(row["protocol_accepted"])
        self.assertEqual(row["virtual_execution"], row["expected"])
        self.assertEqual(row["virtual_execution"]["validation"], "RANGE")
        self.assertFalse(row["program_match"])
        self.assertFalse(row["semantic_pass"])
        self.assertFalse(row["live_model_pass"])

    def test_duplicate_export_path_and_dataset_changes_rejected(self):
        original = evaluate.load(self.run);modified = copy.deepcopy(original)
        modified["records"][1]["export"] = modified["records"][0]["export"]
        self.run.write_text(json.dumps(modified))
        with self.assertRaises(ValueError):self.score()
        original["dataset_sha256"] = "0" * 64;self.run.write_text(json.dumps(original))
        with self.assertRaises(ValueError):self.score()

    def test_live_failure_counts_and_identity_is_required(self):
        def change(record):
            record["source"] = "live";record["fixture"] = False;record.pop("identity")
        self.edit_export("sem-01", change)
        report = self.score();row = report["records"][0]
        self.assertTrue(row["semantic_pass"]);self.assertFalse(row["live_model_pass"])
        self.assertEqual(report["declared_live_model_semantics"]["accuracy_including_missing_and_failed"], 0)
        self.assertEqual(report["declared_live_model_semantics"]["total_frozen_cases"], 24)

    def test_clock_domains_never_subtracted_from_each_other(self):
        def change(record):
            record["timing"]["host"]["clock"] = "wrong.clock"
            record["timing"]["browser"].pop("write_start")
            record["timing"]["browser"]["first_visible_receive"] = 999999
            record["clockHz"] = 100000000
        self.edit_export("sem-01", change)
        self.assertEqual(self.score()["records"][0]["latencies_s"], {})

    def test_existing_cpu_duplicate_action_rule_is_used(self):
        with tempfile.TemporaryDirectory() as directory:
            oracle = evaluate.Executor(directory)
            result = oracle.execute('[["led",1],["led",1]]', {"temperature":24,"light":400})
            self.assertEqual(result, {"validation":"DUPLICATE","actions":[],"readings":{}})

    def test_multi_request_export_cannot_choose_best_result(self):
        def change(record):record["raw"] += record["raw"];record.pop("rawChunks")
        self.edit_export("sem-01", change)
        self.assertFalse(self.score()["records"][0]["protocol_accepted"])


if __name__ == "__main__":unittest.main()
