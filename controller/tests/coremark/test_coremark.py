"""Behavioral tests for the port, official CRCs, build profile and log checks.

Host executions use controlled synthetic ticks and explicitly never produce a
formal score. Real CPU short-run evidence is collected separately by the RTL
runner; an official run additionally needs >=10 seconds and both seed sets.
"""
import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
PORT = ROOT / "firmware/coremark"
UPSTREAM = PORT / "upstream"
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("build_coremark", ROOT / "scripts/build_coremark.py")
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


def log_fixture(mode="performance", cycles=10000000000, formal=True, iterations=2000):
    """A fabricated log, used only to exercise validator rejection boundaries."""
    hz = 125000000
    seconds = cycles / hz
    crc = build.CRC[mode]
    lines = [f"CM_PORT version=1 formal={int(formal)} hz={hz} data=2000 mode={mode} requested_iterations={iterations}",
             "CoreMark Size    : 666", f"Total ticks      : {cycles & 0xffffffff}",
             f"Total time (secs): {seconds:.6f}", f"Iterations/Sec   : {iterations / seconds:.6f}",
             f"Iterations       : {iterations}"]
    for key, value in crc.items():
        lines.append(("" if key == "seedcrc" else "[0]") + key + " : 0x" + value)
    lines.append("[0]crcfinal : 0x1234")
    if seconds < 10:
        lines += ["ERROR! Must execute for at least 10 secs for a valid result!", "Errors detected"]
    else:
        lines.append("Correct operation validated. See README.md for run and reporting rules.")
    lines += [f"CM_TICKS high={cycles >> 32:08x} low={cycles & 0xffffffff:08x}", "CM_DONE"]
    return "\n".join(lines) + "\n"


class CoreMarkContract(unittest.TestCase):
    def test_upstream_files_match_pinned_git_objects(self):
        manifest = build.check_upstream(UPSTREAM)
        self.assertEqual(manifest["commit"], build.UPSTREAM_COMMIT)

    def test_changed_algorithm_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "upstream"
            shutil.copytree(UPSTREAM, copy)
            with (copy / "core_matrix.c").open("a") as stream:
                stream.write("\n/* deliberate test mutation */\n")
            with self.assertRaisesRegex(ValueError, "modified upstream"):
                build.check_upstream(copy)

    def test_o2_o3_change_only_optimization(self):
        a = build.build_plan("rv32-gcc", "/tmp/coremark-test-plan", "O2", "debug", 10)
        b = build.build_plan("rv32-gcc", "/tmp/coremark-test-plan", "O3", "debug", 10)
        self.assertEqual([s.replace("-O2", "-O3") for s in a["command"]], b["command"])
        self.assertEqual(a["source_sha256"], b["source_sha256"])
        self.assertIn("-ffp-contract=off", b["command"])
        self.assertIn("-fno-fast-math", b["command"])
        self.assertNotIn("-flto", b["command"])

    def test_lto_is_explicit(self):
        plan = build.build_plan("rv32-gcc", "/tmp/coremark-test-plan", lto=True)
        self.assertIn("-flto", plan["command"])

    def test_tuning_is_explicit_and_preserves_algorithm_and_numeric_contract(self):
        baseline = build.build_plan("rv32-gcc", "/tmp/coremark-test-plan", opt="O3")
        self.assertEqual(baseline["tuning"], "none")
        self.assertEqual(baseline["tuning_flags"], [])
        for tuning in ("unroll", "unroll-no-if-conversion"):
            plan = build.build_plan("rv32-gcc", "/tmp/coremark-test-plan", opt="O3", tuning=tuning)
            self.assertEqual(plan["source_sha256"], baseline["source_sha256"])
            self.assertEqual(plan["run_seed_set"], baseline["run_seed_set"])
            self.assertEqual(plan["memory_location"], baseline["memory_location"])
            self.assertEqual(plan["tuning_flags"], list(build.TUNING_FLAGS[tuning]))
            for flag in plan["tuning_flags"]:
                self.assertEqual(plan["command"].count(flag), 1)
                self.assertIn(flag, plan["reported_compiler_flags"])
            for flag in ("-ffp-contract=off", "-fno-fast-math", "-fno-strict-aliasing"):
                self.assertIn(flag, plan["command"])
            self.assertNotIn("-flto", plan["command"])

    def test_tuning_rejects_unrecognized_or_unsupported_profiles(self):
        for kwargs in ({"opt": "O2", "tuning": "unroll"},
                       {"opt": "O3", "tuning": "-Ofast"},
                       {"opt": "O3", "tuning": "unknown"}):
            with self.assertRaisesRegex(ValueError, "named tuning"):
                build.build_plan("rv32-gcc", "/tmp/coremark-test-plan", **kwargs)

    def test_debug_requires_nonzero_iterations(self):
        with self.assertRaisesRegex(ValueError, "positive iteration"):
            build.build_plan("cc", "/tmp/no-build", mode="debug")

    def test_unsafe_profiles_rejected(self):
        for kwargs in ({"opt": "Ofast"}, {"hz": 0}, {"iterations": -1}, {"iterations": 2**31}):
            with self.assertRaises(ValueError):
                build.build_plan("cc", "/tmp/no-build", **kwargs)

    def test_formal_beyond_32bit_wrap(self):
        result = build.validate_log(log_fixture())
        self.assertEqual(result["cycles"], 10000000000)
        self.assertEqual(result["seconds"], 80)
        self.assertEqual(result["coremark"], 25)

    def test_validation_seed_has_no_performance_score(self):
        result = build.validate_log(log_fixture("validation"), expected_mode="validation")
        self.assertTrue(result["formal_run_log_valid"])
        self.assertFalse(result["release_qualified"])
        self.assertIsNone(result["coremark"])

    def test_short_run_has_no_score_and_cannot_pass_formal(self):
        text = log_fixture(cycles=1000000, formal=False, iterations=1)
        with self.assertRaises(ValueError):
            build.validate_log(text)
        result = build.validate_log(text, require_formal=False)
        self.assertTrue(result["crc_valid"])
        self.assertIsNone(result["coremark"])
        self.assertFalse(result["formal_run_log_valid"])

    def test_formal_flag_cannot_waive_ten_seconds(self):
        with self.assertRaisesRegex(ValueError, "at least 10"):
            build.validate_log(log_fixture(cycles=1250000000 - 1))

    def test_boundary_exactly_ten_seconds(self):
        self.assertTrue(build.validate_log(log_fixture(cycles=1250000000))["formal_run_log_valid"])

    def test_wrong_clock_rejected(self):
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            build.validate_log(log_fixture(), expected_hz=100000000)
        with self.assertRaisesRegex(ValueError, "clock must be positive"):
            build.validate_log(log_fixture().replace("hz=125000000", "hz=0"), expected_hz=0)

    def test_bad_crc_rejected(self):
        with self.assertRaisesRegex(ValueError, "CRC"):
            build.validate_log(log_fixture().replace("0xe714", "0x0000"))

    def test_mixed_or_truncated_logs_rejected(self):
        for text in (log_fixture() * 2, log_fixture().replace("CM_DONE\n", ""),
                     log_fixture() + "CM_TRAP cause=00000002\n"):
            with self.assertRaises(ValueError):
                build.validate_log(text)

    def test_truncated_low_word_cannot_replace_full_cycles(self):
        text = log_fixture().replace("high=00000002", "high=00000000")
        with self.assertRaisesRegex(ValueError, "printed time"):
            build.validate_log(text)

    def test_forged_reported_rate_rejected(self):
        with self.assertRaisesRegex(ValueError, "printed rate"):
            build.validate_log(log_fixture().replace("Iterations/Sec   : 25.000000", "Iterations/Sec   : 50.000000"))


@unittest.skipUnless(shutil.which("gcc"), "native GCC required for C behavioral tests")
class NativePort(unittest.TestCase):
    def compile_run(self, sources, defines, opt="O2"):
        with tempfile.TemporaryDirectory(prefix="coremark-port-test-") as tmp:
            exe = Path(tmp) / "test"
            cmd = ["gcc", "-std=c11", "-" + opt, "-fno-strict-aliasing",
                   "-DCOREMARK_HOST_TEST=1", "-DITERATIONS=1", '-DFLAGS_STR="host-test-only"',
                   "-DHAS_FLOAT=1", "-DHAS_TIME_H=0", "-DUSE_CLOCK=0", "-DMAIN_HAS_NOARGC=1",
                   "-I", str(PORT), "-I", str(UPSTREAM), *defines,
                   *map(str, sources), "-o", str(exe)]
            built = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            result = subprocess.run([str(exe)], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return result.stdout

    def test_timer_precision_rollover_seed_and_report_variants(self):
        sources = [PORT / "core_portme.c", PORT / "core_portme_printf.c", HERE / "port_checks.c"]
        variants = [[], ["-DCM_CPU_HZ=125000000", "-DCOREMARK_REPORT_METADATA=1"],
                    ["-DCM_CPU_HZ=125000000", "-DCOREMARK_REPORT_METADATA=1", "-DVALIDATION_RUN=1"],
                    ["-DPROFILE_RUN=1", "-DTOTAL_DATA_SIZE=1200"]]
        for flags in variants:
            with self.subTest(flags=flags):
                self.assertIn("PASS:", self.compile_run(sources, flags))

    def test_formal_rejects_synthetic_host_timer(self):
        cmd = ["gcc", "-std=c11", "-x", "c", "-fsyntax-only", "-",
               "-DCOREMARK_HOST_TEST=1", "-DCOREMARK_FORMAL=1", "-DCM_CPU_HZ=125000000",
               "-I", str(PORT), "-I", str(UPSTREAM)]
        result = subprocess.run(cmd, input='#include "coremark.h"\n', text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Synthetic host test clocks", result.stderr)

    def test_unchanged_algorithms_both_seed_sets_o2_o3(self):
        sources = [UPSTREAM / name for name in build.ALGORITHMS]
        sources += [PORT / "core_portme.c", PORT / "core_portme_printf.c", HERE / "upstream_host.c"]
        for opt in ("O2", "O3"):
            for mode in ("performance", "validation"):
                with self.subTest(opt=opt, mode=mode):
                    log = self.compile_run(sources, ["-DCM_CPU_HZ=125000000", "-DCOREMARK_REPORT_METADATA=1",
                                                    "-D" + mode.upper() + "_RUN=1"], opt)
                    result = build.validate_log(log, expected_mode=mode, require_formal=False)
                    self.assertTrue(result["crc_valid"])
                    self.assertEqual(result["cycles"], 1000000)
                    self.assertIsNone(result["coremark"])


if __name__ == "__main__":
    unittest.main()
