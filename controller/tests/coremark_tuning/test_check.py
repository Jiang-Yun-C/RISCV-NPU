"""Reject corruptions of actual retained RTL captures, not synthetic performance."""
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
EXPORT = HERE.parents[2]
EVIDENCE = EXPORT / "verification/competition_v2/coremark_tuning/raw"
BUILDS = EXPORT / "verification/competition_v2/coremark_builds"
spec = importlib.util.spec_from_file_location("real_tuning_checker", HERE / "check.py")
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


@unittest.skipUnless(EVIDENCE.is_dir() and BUILDS.is_dir(), "retained real RTL evidence required")
class RetainedEvidence(unittest.TestCase):
    def test_actual_captures_bind_to_current_builds(self):
        result = checker.check(EVIDENCE, BUILDS)
        self.assertEqual(result["status"], "PASS_ISOLATED_RTL_TUNING")
        self.assertEqual(len(result["cases"]), 10)
        self.assertFalse(result["formal_score_available"])

    def rejected(self, mutate):
        with tempfile.TemporaryDirectory(prefix="tuning-negative-") as tmp:
            raw = Path(tmp) / "raw"
            shutil.copytree(EVIDENCE, raw)
            path = raw / "tuned-performance.json"
            record = json.loads(path.read_text())
            mutate(record)
            path.write_text(json.dumps(record))
            with self.assertRaises(ValueError):
                checker.check(raw, BUILDS)

    def test_changed_crc_rejected(self):
        self.rejected(lambda r: r.update(uart=r["uart"].replace("0xe714", "0x0000")))

    def test_changed_binary_rejected(self):
        self.rejected(lambda r: r.update(binary_sha256="0" * 64))

    def test_different_latency_rejected(self):
        self.rejected(lambda r: r.update(read_latency=4))

    def test_different_simulator_rejected(self):
        self.rejected(lambda r: r.update(simulator_version="different-test-simulator"))

    def test_wrong_tuning_flags_rejected(self):
        self.rejected(lambda r: r.update(uart=r["uart"].replace("-funroll-loops", "-fno-unroll-loops")))

    def test_short_capture_cannot_be_relabelled_formal(self):
        self.rejected(lambda r: r.update(uart=r["uart"].replace("formal=0 ", "formal=1 ")))


if __name__ == "__main__":
    unittest.main()
