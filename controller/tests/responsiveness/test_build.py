"""Current-receipt relocation and cache identity checks; no hardware access."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import build_t27_responsive as build
import build_t27_streaming as common


class ResponsiveBuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.receipt = json.loads((build.BASELINE / "compile.COMMAND.json").read_text())

    def test_current_receipt_preserves_arithmetic_backend_and_all_sources(self):
        source, output = Path("/tmp/responsive source"), Path("/tmp/responsive output")
        actual = build.relocate(self.receipt, source, output, "/tool/rv32-gcc")
        old = self.receipt["argv"]
        old_source = next(a for a in old if a.endswith("/firmware/runtime/board/main.c")).removesuffix("/firmware/runtime/board/main.c")
        old_generated = str(Path(next(a for a in old if a.endswith("/tokenizer.S"))).parent)
        normalized = [old[0]] + [a.replace(str(source), old_source).replace(str(output), old_generated)
                                 for a in actual[1:] if not a.startswith("-ffile-prefix-map=")]
        self.assertEqual(normalized, [a for a in old if not a.startswith("-ffile-prefix-map=")])
        self.assertEqual(actual.count("-O3"), 1)
        self.assertEqual(sum(a.endswith("/led_control.c") for a in actual), 1)

    def test_ambiguous_or_changed_contract_is_rejected(self):
        for option in ("-O0", "-ffast-math", "-DNX_PREFIX_CAPTURE=0", "-DNX_HEAD_ARGMAX=0",
                       "-march=rv32imac", "-flto", "/stale/model.o", "-DNX_LED_BANK=1"):
            with self.subTest(option=option), self.assertRaises(ValueError):
                build.relocate(dict(self.receipt, argv=self.receipt["argv"] + [option]),
                               Path("/tmp/source"), Path("/tmp/build"), "cc")
        with self.assertRaises(ValueError):
            build.relocate(dict(self.receipt, source_content_id="old-or-unknown"),
                           Path("/tmp/source"), Path("/tmp/build"), "cc")

    def test_multi_led_is_explicit_and_bound_to_runtime_identity(self):
        source, output = ROOT, Path("/tmp/multi-led-build")
        original = build.relocate(self.receipt, source, output, "cc")
        bank = build.relocate(self.receipt, source, output, "cc", multi_led=True)
        self.assertNotIn("-DNX_LED_BANK=1", original)
        self.assertEqual(bank.count("-DNX_LED_BANK=1"), 1)
        self.assertEqual([a for a in bank if a != "-DNX_LED_BANK=1"], original)
        old, _ = common.runtime_identity(source, original, "compiler-a")
        new, _ = common.runtime_identity(source, bank, "compiler-a")
        self.assertNotEqual(old["T27_BACKEND_SHA256"], new["T27_BACKEND_SHA256"])

    def test_action_prompt_and_selection_are_explicit_template_identity_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)
            paths = ("firmware/runtime/port/tokenizer.c", "firmware/runtime/board/led_control.c",
                     "firmware/runtime/board/service_options.h")
            for name in paths:
                p = source / name; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(name)
            original, _ = common.runtime_identity(source, ["-O3"], "compiler-a")
            for name in paths:
                p = source / name; saved = p.read_text(); p.write_text(saved + " changed")
                changed, _ = common.runtime_identity(source, ["-O3"], "compiler-a")
                self.assertNotEqual(original["T27_TEMPLATE_SHA256"], changed["T27_TEMPLATE_SHA256"])
                p.write_text(saved)

    def test_plan_requires_no_compiler_and_makes_no_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "new-build"
            run = subprocess.run([sys.executable, "-B", str(ROOT / "scripts/build_t27_responsive.py"),
                                  "--output", str(output), "--cc", "missing-test-rv32-compiler"],
                                 capture_output=True, text=True, check=True, timeout=30)
            plan = json.loads(run.stdout)
            self.assertEqual(plan["status"], "PLAN_ONLY")
            self.assertEqual(plan["errors"], [])
            self.assertEqual(plan["missing"], ["compiler: missing-test-rv32-compiler"])
            self.assertFalse(plan["build_executed"])
            self.assertFalse(output.exists())
            self.assertNotEqual(plan["source_content_id"], build.BASELINE_CID)

    def test_missing_compiler_blocks_build_without_creating_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "new-build"
            run = subprocess.run([sys.executable, "-B", str(ROOT / "scripts/build_t27_responsive.py"),
                                  "--output", str(output), "--cc", "missing-test-rv32-compiler", "--build"],
                                 capture_output=True, text=True, timeout=30)
            self.assertEqual(run.returncode, 2, run.stderr)
            self.assertEqual(json.loads(run.stdout)["status"], "BUILD_BLOCKED_MISSING_OR_INVALID_INPUTS")
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
