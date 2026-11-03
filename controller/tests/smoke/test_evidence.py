"""Failure-path tests for the evidence contract, without acquiring VCS licenses."""
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from evidence import EvidenceRun, StepFailure
from check_smoke import check_host, check_vcd


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        self.run = EvidenceRun(self.root, "TEST", "fixture")

    def test_nonzero_preserves_streams_and_command(self):
        with self.assertRaises(StepFailure):
            self.run.execute("failure", [sys.executable, "-c",
                             "import sys; print('partial result'); print('bad input', file=sys.stderr); sys.exit(7)"], 5)
        self.run.finish(1)
        commands = json.loads((self.run.path / "commands.json").read_text())
        self.assertEqual(commands[0]["exit_code"], 7)
        self.assertIn("partial result", (self.run.path / commands[0]["stdout"]).read_text())
        self.assertIn("bad input", (self.run.path / commands[0]["stderr"]).read_text())
        self.assertEqual(json.loads((self.run.path / "manifest.json").read_text())["status"], "FAIL")

    def test_timeout_kills_descendants(self):
        marker = self.root / "escaped-child"
        child = "import pathlib,time; time.sleep(0.8); pathlib.Path(" + repr(str(marker)) + ").write_text('bad')"
        parent = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c'," + repr(child) + "]); time.sleep(20)"
        with self.assertRaises(StepFailure) as caught:
            self.run.execute("timeout", [sys.executable, "-c", parent], 0.15)
        self.assertEqual(caught.exception.exit_code, 124)
        time.sleep(0.9)
        self.assertFalse(marker.exists(), "timed-out child survived")
        self.assertEqual(self.run.steps[0]["exit_code"], 124)

    def test_missing_tool_is_nonzero_and_logged(self):
        with self.assertRaises(StepFailure) as caught:
            self.run.execute("missing", [self.root / "missing-executable"], 5)
        self.assertEqual(caught.exception.exit_code, 127)
        self.assertTrue((self.run.path / "logs/missing.stderr.log").read_text())

    def test_existing_result_cannot_be_overwritten(self):
        before = (self.run.path / "manifest.json").read_bytes()
        with self.assertRaises(FileExistsError):
            EvidenceRun(self.root, "TEST", "fixture")
        self.assertEqual(before, (self.run.path / "manifest.json").read_bytes())

    def test_path_traversal_rejected(self):
        with self.assertRaises(ValueError):
            EvidenceRun(self.root, "TEST", "../escape")

    def test_process_success_does_not_override_failed_check(self):
        self.run.execute("zero", [sys.executable, "-c", "print('ordinary output')"], 5)
        with self.assertRaises(StepFailure):
            self.run.check("result", False, "missing pass marker")
        self.assertEqual(self.run.checks[-1]["status"], "FAIL")
        self.assertEqual(self.run.finish(0), 1, "failed checks must never finalize as PASS")

    def test_python_checker_rejects_wrong_host_result(self):
        output = self.root / "bad.json"
        output.write_text('{"seed":1,"dot":0}')
        with self.assertRaisesRegex(ValueError, "mismatch"):
            check_host(output, 1)

    def test_vcd_checker_rejects_header_only_file(self):
        wave = self.root / "header.vcd"
        wave.write_text("$timescale 1ps $end\n$enddefinitions $end\n")
        with self.assertRaises(ValueError):
            check_vcd(wave, 1)


if __name__ == "__main__":
    unittest.main()
