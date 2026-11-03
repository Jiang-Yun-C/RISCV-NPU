"""Inventory refuses changed raw diagnostics, source drift and stale reviews."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from audit_r01 import inventory
from evidence import content_id, sha256, write_json
from spyglass_support import accept_reports


class InventoryIntegrity(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        source = self.path / "sources/dut.sv"
        source.parent.mkdir()
        source.write_text("module dut(input clk); endmodule\n")
        files = {"sources/dut.sv": sha256(source)}
        write_json(self.path / "source-manifest.json", {"files": files, "sha256": content_id(files)})
        write_json(self.path / "config.json", {"expected_version": "X-2025.06"})
        reports = self.path / "artifacts/lint-dut/project/consolidated_reports/dut_lint_lint_rtl"
        reports.mkdir(parents=True)
        (reports / "spyglass.log").write_text("SpyGlass_vX-2025.06\nReported Messages: 0 Fatals, 0 Errors, 1 Warnings, 0 Infos\nSpyGlass Exit Code 0\nSpyGlass run completed at now\n")
        (reports / "moresimple.rpt").write_text(f"Number of Waived Messages : 0\nNumber of Overlimit Messages : 0\n[1] W486 Warning {source} 1 10 width diagnostic\n")
        (self.path / "logs").mkdir()
        for kind in ("stdout", "stderr"):
            (self.path / f"logs/lint-dut.{kind}.log").write_text("")
        accepted = accept_reports(self.path / "artifacts/lint-dut", "dut", ["lint/lint_rtl"], 0, "", "X-2025.06")
        self.check = dict(scope="dut", stage="lint", goals_requested=["lint/lint_rtl"], **accepted)
        self.summary = dict(scopes=["dut"], checks=[self.check], decision="FAIL")
        self.save()
        self.reviews = {"entries": [dict(scope="dut", rule="W486", source="sources/dut.sv", line=1,
            message_sha256=hashlib.sha256(b"width diagnostic").hexdigest(), source_sha256=sha256(source),
            reason="Reviewed exact site", next_action="Retain warning under existing zero-warning gate")]}

    def save(self):
        write_json(self.path / "summary.json", self.summary)

    def test_review_retains_warning_and_design_failure(self):
        got = inventory(self.path, self.reviews)
        self.assertEqual(got["counts"], dict(findings=1, open=0, reviewed_retained=1))
        self.assertEqual(got["lint_decision"], "FAIL")
        self.assertFalse(got["findings"][0]["authorizes_waiver"])
        self.assertEqual(inventory(self.path)["counts"]["open"], 1)

    def test_source_drift_is_rejected(self):
        (self.path / "sources/dut.sv").write_text("module changed; endmodule\n")
        with self.assertRaisesRegex(ValueError, "source identity"):
            inventory(self.path)

    def test_source_inventory_digest_is_rejected(self):
        manifest = json.loads((self.path / "source-manifest.json").read_text())
        manifest["sha256"] = "0" * 64
        write_json(self.path / "source-manifest.json", manifest)
        with self.assertRaisesRegex(ValueError, "inventory digest"):
            inventory(self.path)

    def test_raw_report_edit_is_rejected(self):
        p = next((self.path / "artifacts").rglob("moresimple.rpt"))
        p.write_text(p.read_text().replace("width diagnostic", "different diagnostic"))
        with self.assertRaisesRegex(ValueError, "raw report differs"):
            inventory(self.path)

    def test_stale_and_duplicate_reviews_are_rejected(self):
        self.reviews["entries"][0]["line"] = 2
        with self.assertRaisesRegex(ValueError, "stale/unmatched"):
            inventory(self.path, self.reviews)
        self.reviews["entries"] *= 2
        with self.assertRaisesRegex(ValueError, "duplicate"):
            inventory(self.path, self.reviews)

    def test_incomplete_scope_is_rejected(self):
        self.check["analysis_completed"] = False
        self.save()
        with self.assertRaisesRegex(ValueError, "incomplete lint"):
            inventory(self.path)


if __name__ == "__main__":
    unittest.main()
