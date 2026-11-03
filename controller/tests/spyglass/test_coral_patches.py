"""Reject drift or unsafe destinations before applying generated RTL fixes."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import coral_rtl
from evidence import EvidenceRun


class CoralPatchIdentity(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run = EvidenceRun(self.root, "TEST", "patch")
        self.rtl = self.run.build / "rtl"
        self.rtl.mkdir()
        self.patch_dir = self.root / "patches"
        self.patch_dir.mkdir()
        self.before, self.after = "module a;\nendmodule\n", "module b;\nendmodule\n"
        self.identity = dict(before_sha256=self.digest(self.before), after_sha256=self.digest(self.after))
        self.spec = dict(files={"design.sv": self.identity}, patch="fix.patch", upstream_commit="locked")
        (self.patch_dir / "fix.patch").write_text("--- a/design.sv\n+++ b/design.sv\n@@ -1,2 +1,2 @@\n-module a;\n+module b;\n endmodule\n")
        self.save_spec()
        (self.rtl / "design.sv").write_text(self.before)
        self.override = patch.object(coral_rtl, "PATCH_DIR", self.patch_dir)
        self.override.start()
        self.addCleanup(self.override.stop)

    @staticmethod
    def digest(text):
        return hashlib.sha256(text.encode()).hexdigest()

    def save_spec(self):
        (self.patch_dir / "manifest.json").write_text(json.dumps(self.spec))

    def test_real_patch_and_archive_then_reject_reapplication(self):
        coral_rtl.apply_patches(self.run, self.rtl)
        self.assertEqual((self.rtl / "design.sv").read_text(), self.after)
        archive = self.run.path / "artifacts/coral-patches/rtl"
        self.assertEqual((archive / "design.sv").read_text(), self.after)
        self.assertEqual(json.loads((archive / "receipt.json").read_text())["files"], self.spec["files"])
        with self.assertRaisesRegex(ValueError, "input identity"):
            coral_rtl.apply_patches(self.run, self.rtl)

    def test_all_inputs_checked_before_first_mutation(self):
        self.spec["files"]["missing.sv"] = self.identity
        self.save_spec()
        with self.assertRaisesRegex(ValueError, "input identity"):
            coral_rtl.apply_patches(self.run, self.rtl)
        self.assertEqual((self.rtl / "design.sv").read_text(), self.before)
        self.assertFalse(self.run.steps)

    def test_changed_upstream_rejected_without_mutation(self):
        (self.rtl / "design.sv").write_text(self.before + "// new upstream\n")
        with self.assertRaisesRegex(ValueError, "input identity"):
            coral_rtl.apply_patches(self.run, self.rtl)
        self.assertFalse(self.run.steps)

    def test_wrong_output_identity_rejected(self):
        self.identity["after_sha256"] = "0" * 64
        self.save_spec()
        with self.assertRaisesRegex(ValueError, "output identity"):
            coral_rtl.apply_patches(self.run, self.rtl)

    def test_external_checkout_and_symlink_rejected(self):
        with self.assertRaisesRegex(ValueError, "fresh directory"):
            coral_rtl.apply_patches(self.run, self.root)
        alias = self.run.build / "external"
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "fresh directory"):
            coral_rtl.apply_patches(self.run, alias)


if __name__ == "__main__":
    unittest.main()
