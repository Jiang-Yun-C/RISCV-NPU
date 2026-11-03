"""Adversarial report/feature acceptance and AXI adapter elaboration checks."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from evidence import EvidenceRun
from run_spyglass import prepare_scopes, prepare_coral, tcl_word, reset_constraint, external_constraints
from spyglass_support import accept_reports, boundary_wrapper, license_status


class Reports(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def report(self, goal="lint/lint_rtl", errors=0, warnings=0, waived=0, overlimit=0, complete=True):
        path = self.root / "project/consolidated_reports" / ("dut_" + goal.replace("/", "_"))
        path.mkdir(parents=True, exist_ok=True)
        (path / "spyglass.log").write_text(
            "SpyGlass Predictive Analyzer - Version SpyGlass_vX-2025.06\n" +
            "Ac_license01 clock-reset No - SETUP -\n" +  # Rule catalog is not a denial.
            f"Reported Messages: 0 Fatals, {errors} Errors, {warnings} Warnings, 0 Infos\n" +
            ("SpyGlass Exit Code 0\nSpyGlass run completed at 12:00\n" if complete else ""))
        rows = "".join(f"[{n+1}] E001 Alias Error rtl.sv {n+1} 10 bad design\n" for n in range(errors))
        rows += "".join(f"[{n+errors+1}] W001 Alias Warning rtl.sv {n+2} 10 width issue\n" for n in range(warnings))
        (path / "moresimple.rpt").write_text(
            f"Number of Waived Messages : {waived}\nNumber of Overlimit Messages : {overlimit}\n" + rows)
        return path

    def accept(self, goals=("lint/lint_rtl",), code=0, text=""):
        return accept_reports(self.root, "dut", goals, code, text, "X-2025.06")

    def test_complete_clean_report_passes_despite_license_rule_catalog(self):
        self.report()
        result = self.accept()
        self.assertEqual(result["decision"], "PASS")
        self.assertTrue(result["analysis_completed"])

    def test_zero_exit_without_reports_fails(self):
        result = self.accept()
        self.assertEqual(result["decision"], "FAIL")
        self.assertIsNone(result["goals"][0]["errors"])

    def test_errors_with_zero_exit_fail(self):
        self.report(errors=1)
        result = self.accept()
        self.assertEqual(result["decision"], "FAIL")
        self.assertTrue(result["analysis_completed"])

    def test_new_warning_fails_and_retains_rule_and_site(self):
        self.report(warnings=1)
        result = self.accept()
        self.assertEqual(result["decision"], "FAIL")
        self.assertEqual(result["goals"][0]["warnings_by_rule"], {"W001": 1})
        self.assertEqual(result["goals"][0]["findings"][0]["line"], 2)

    def test_all_cdc_goals_required(self):
        self.report("cdc/cdc_setup_check")
        result = self.accept(("cdc/cdc_setup_check", "cdc/cdc_verify_struct"))
        self.assertEqual(result["decision"], "FAIL")
        self.report("cdc/cdc_verify_struct", errors=2)
        self.assertEqual(self.accept(("cdc/cdc_setup_check", "cdc/cdc_verify_struct"))["decision"], "FAIL")

    def test_wrong_top_cannot_supply_report(self):
        self.report()
        result = accept_reports(self.root, "other", ["lint/lint_rtl"], 0, "", "X-2025.06")
        self.assertEqual(result["decision"], "FAIL")

    def test_truncated_run_rejected(self):
        self.report(complete=False)
        self.assertFalse(self.accept()["analysis_completed"])

    def test_missing_detail_rejected(self):
        path = self.report()
        (path / "moresimple.rpt").unlink()
        self.assertEqual(self.accept()["decision"], "FAIL")

    def test_detail_count_disagreement_rejected(self):
        path = self.report(warnings=1)
        file = path / "moresimple.rpt"
        file.write_text(file.read_text().split("[1]")[0])
        result = self.accept()
        self.assertIn("detail_count_mismatch_warnings", result["goals"][0]["failed_checks"])

    def test_waivers_and_overlimit_rejected(self):
        for kwargs in ({"waived": 1}, {"overlimit": 2}):
            with self.subTest(kwargs=kwargs):
                self.report(**kwargs)
                self.assertEqual(self.accept()["decision"], "FAIL")

    def test_missing_count_not_zero(self):
        path = self.report()
        (path / "spyglass.log").write_text("SpyGlass Exit Code 0\nSpyGlass run completed at now\n")
        self.assertFalse(self.accept()["analysis_completed"])

    def test_hex_ids_and_blank_aliases_are_real_diagnostics(self):
        path = self.report(errors=1, warnings=1)
        file = path / "moresimple.rpt"
        file.write_text(file.read_text().replace("[1] E001 Alias", "[1A] E001      ").replace("[2] W001 Alias", "[FF] W001      "))
        result = self.accept()
        self.assertTrue(result["analysis_completed"])
        self.assertEqual(len(result["goals"][0]["findings"]), 2)

    def test_synthesis_error_means_incomplete_elaboration(self):
        path = self.report(errors=1)
        file = path / "moresimple.rpt"
        file.write_text(file.read_text().replace("Error rtl.sv", "SynthesisError rtl.sv"))
        result = self.accept()
        self.assertFalse(result["analysis_completed"])
        self.assertIn("elaboration_incomplete", result["goals"][0]["failed_checks"])

    def test_uppercase_info_is_counted(self):
        path = self.report()
        log = path / "spyglass.log"
        log.write_text(log.read_text().replace("0 Infos", "1 Infos"))
        with (path / "moresimple.rpt").open("a") as f:
            f.write("[ABC] checkCMD Alias INFO N.A. 0 10 informational message\n")
        self.assertEqual(self.accept()["decision"], "PASS")

    def test_syntax_rows_are_fatal_and_incomplete(self):
        path = self.report()
        log = path / "spyglass.log"
        log.write_text(log.read_text().replace("0 Fatals", "1 Fatals"))
        with (path / "moresimple.rpt").open("a") as f:
            f.write("[0] STX_VE_481 STX_VE_481 Syntax design.sv 16 1000 Syntax error near display\n")
        result = self.accept()
        self.assertFalse(result["analysis_completed"])
        self.assertEqual(result["goals"][0]["fatals"], 1)
        self.assertEqual(result["goals"][0]["findings"][0]["severity"], "Syntax")
        self.assertNotIn("detail_count_mismatch_fatals", result["goals"][0]["failed_checks"])

    def test_unsupported_sv_elaboration_is_counted_as_error(self):
        path = self.report(errors=1)
        file = path / "moresimple.rpt"
        file.write_text(file.read_text().replace("E001 Alias Error", "ELAB_6312      ElaborationError"))
        result = self.accept()
        self.assertFalse(result["analysis_completed"])
        self.assertNotIn("detail_count_mismatch_errors", result["goals"][0]["failed_checks"])
        self.assertEqual(result["goals"][0]["findings"][0]["rule"], "ELAB_6312")

    def test_tool_version_and_process_failure_rejected(self):
        path = self.report()
        self.assertEqual(self.accept(code=124)["decision"], "FAIL")
        log = path / "spyglass.log"
        log.write_text(log.read_text().replace("X-2025.06", "Y-2026.06"))
        self.assertEqual(self.accept()["decision"], "FAIL")

    def test_checkout_denial_rejected_even_with_clean_reports(self):
        self.report()
        result = self.accept(text="Error: failed to obtain required license")
        self.assertEqual(result["decision"], "BLOCKED_LICENSE")
        self.assertFalse(result["analysis_completed"])


class Licenses(unittest.TestCase):
    def test_ready_requires_server_vendor_and_exact_available_feature(self):
        server = "license server UP\nsnpslmd: UP\n"
        seat = "Users of lint_func: (Total of 99 licenses issued; Total of 0 licenses in use)"
        self.assertEqual(license_status(server + seat, 0, "lint_func"), "ready")
        self.assertEqual(license_status(server + seat, 0, "cdc_adv_checker"), "feature_not_reported")
        self.assertEqual(license_status(server + seat.replace("0 licenses in use", "99 licenses in use"), 0, "lint_func"), "feature_exhausted")
        self.assertEqual(license_status(server + seat, 1, "lint_func"), "probe_failed")
        self.assertEqual(license_status(seat, 0, "lint_func"), "license_server_unavailable")

    def test_context_denial_not_server_down(self):
        for message in ("Operation not permitted", "FlexNet (-15,570:1)", "EPERM"):
            self.assertEqual(license_status(message, 1, "lint_func"), "execution_context_blocked")


class Integration(unittest.TestCase):
    def test_reset_models_match_real_edge_sensitivity(self):
        import argparse
        import re
        config = json.loads((ROOT / "configs/spyglass.json").read_text())
        with tempfile.TemporaryDirectory() as tmp:
            scopes = prepare_scopes(EvidenceRun(tmp, "TEST"), config,
                                    argparse.Namespace(cpu_build=[], coral_rtl=None, scope=None))
            for scope in scopes:
                name = scope["name"]
                spec = config["scopes"][name]
                source = (ROOT / "rtl/soc" / (name + ".sv")).read_text()
                sensitivities = re.findall(r"always(?:_ff)?\s*@\s*\(([^)]*)\)", source)
                self.assertTrue(sensitivities, name)
                self.assertTrue(all(s.strip() == "posedge clk" for s in sensitivities), name)
                self.assertIn(f"reset -name {spec['reset']} -value {spec['active']} -sync\n", scope["sgdc"])
            for name in ("t17_uart", "t18_spi"):
                self.assertFalse(next(s for s in scopes if s["name"] == name)["constraints_complete"])

    def test_missing_or_invalid_reset_kind_cannot_default_to_async(self):
        for kind in (None, "", "asynchronous", "sync -soft"):
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                reset_constraint("reset", 1, kind)

    def test_external_inputs_have_independent_domains_and_keep_signoff_open(self):
        config = json.loads((ROOT / "configs/spyglass.json").read_text())
        for name, port in (("t17_uart", "rx"), ("t18_spi", "miso")):
            spec = config["scopes"][name]
            text, limits = external_constraints(spec, [port, "clk"])
            clock = spec["external_clock_models"][port]["clock"]
            self.assertIn(f"-domain {clock}", text)
            self.assertIn(f'abstract_port -ports "{port}" -clock "{clock}"', text)
            self.assertNotIn('-clock "clk"', text)
            self.assertTrue(limits)

    def test_external_input_typos_and_synchronous_clock_alias_are_rejected(self):
        with self.assertRaises(ValueError):
            external_constraints(dict(asynchronous_inputs=["typo"]), ["rx"])
        with self.assertRaises(ValueError):
            external_constraints(dict(external_clock_models={"rx": {}}), ["rx"])
        with self.assertRaises(ValueError):
            external_constraints(dict(asynchronous_inputs=["rx"], external_clock_models={
                "rx": dict(clock="clk", period_ns=10)}), ["rx"])

    def test_coral_import_retains_order_headers_and_macro_changes(self):
        config = json.loads((ROOT / "configs/spyglass.json").read_text())
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "generated"
            directory.mkdir()
            (directory / "filelist.f").write_text("+incdir+.\n+define+USE_GENERIC\n+define+TB_SUPPORT\npkg.sv\nRvvCoreMiniAxi.sv\n")
            (directory / "pkg.sv").write_text("package pkg; endpackage\n")
            (directory / "RvvCoreMiniAxi.sv").write_text("module RvvCoreMiniAxi(input io_aclk, io_aresetn); endmodule\n")
            (directory / "header.svh").write_text("`define X 1\n")
            run = EvidenceRun(tmp, "TEST")
            scope = prepare_coral(run, config, directory)
            self.assertEqual([p.name for p in scope["files"]], ["pkg.sv", "RvvCoreMiniAxi.sv"])
            self.assertEqual(scope["defines"], ["USE_GENERIC", "SYNTHESIS"])
            self.assertEqual(scope["macro_changes"]["removed"], ["TB_SUPPORT"])
            self.assertTrue((scope["incdir"] / "header.svh").is_file())
            self.assertFalse(scope["constraints_complete"])
            self.assertIn("reset -name io_aresetn -value 0 -async\n", scope["sgdc"])

    def test_adapter_directions_and_widths(self):
        source = (ROOT / "rtl/soc/nx_accel_bridge.sv").read_text()
        interface = (ROOT / "rtl/interfaces/axi4_if.sv").read_text()
        wrapper, top, inputs = boundary_wrapper("nx_accel_bridge", source, interface,
                                               {"cpu": [32, 1], "memory": [32, 1], "coral": [128, 6]})
        self.assertIn("input wire [31:0] cpu__wdata", wrapper)
        self.assertIn("output wire [127:0] coral__wdata", wrapper)
        self.assertIn("input wire [5:0] coral__rid", wrapper)
        self.assertIn("assign coral.rid = coral__rid;", wrapper)
        self.assertIn("assign coral__wdata = coral.wdata;", wrapper)
        self.assertIn("cpu__wdata", inputs)
        with self.assertRaises(ValueError):
            boundary_wrapper("nx_accel_bridge", source, interface, {"cpu": [32, 1]})

    def test_tcl_rejects_unbalanced_values(self):
        self.assertEqual(tcl_word("/path with spaces/file.sv"), "{/path with spaces/file.sv}")
        for value in ("bad}path", "bad\npath", "bad\\path"):
            with self.assertRaises(ValueError):
                tcl_word(value)

    @unittest.skipUnless(shutil.which("verilator"), "independent Verilator elaborator unavailable")
    def test_all_project_adapters_elaborate_with_real_interface(self):
        import argparse
        config = json.loads((ROOT / "configs/spyglass.json").read_text())
        with tempfile.TemporaryDirectory() as tmp:
            run = EvidenceRun(tmp, "TEST")
            scopes = prepare_scopes(run, config, argparse.Namespace(cpu_build=[], coral_rtl=None, scope=None))
            self.assertEqual(len(scopes), 8)
            for scope in scopes:
                with self.subTest(scope=scope["name"]):
                    proc = subprocess.run([shutil.which("verilator"), "--lint-only", "--Wno-fatal", "--top-module", scope["top"],
                                           "--Mdir", str(run.build / scope["name"]), *map(str, scope["files"])],
                                          capture_output=True, text=True, timeout=60)
                    self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)


class EntryPoint(unittest.TestCase):
    """Exercise the real CLI in an isolated checkout using controlled tool output."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for name in ("scripts", "configs"):
            (self.root / name).mkdir()
        for name in ("run_spyglass.py", "spyglass_support.py", "evidence.py"):
            shutil.copy2(ROOT / "scripts" / name, self.root / "scripts" / name)
        shutil.copytree(ROOT / "rtl", self.root / "rtl")
        (self.root / "Makefile").write_text("# isolated acceptance test\n")
        config = json.loads((ROOT / "configs/spyglass.json").read_text())
        config["scopes"] = {"t03_uart_tx": config["scopes"]["t03_uart_tx"]}
        if config.get("serial_timing_contract"):
            contract = Path(config["serial_timing_contract"])
            (self.root / contract).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / contract, self.root / contract)
        (self.root / "configs/spyglass.json").write_text(json.dumps(config))
        home = self.root / "tool"
        (home / "bin").mkdir(parents=True)
        for goal in [g for s in config["stages"].values() for g in s["goals"]]:
            path = home / "GuideWare/latest/block/rtl_handoff" / (goal + ".spq")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# fake goal; not a licensed EDA result\n")
        spyglass = home / "bin/spyglass"
        spyglass.write_text("#!" + sys.executable + "\n" + '''import os, sys, re
from pathlib import Path
Path("invoked").write_text("yes")
mode = os.environ.get("FAKE_SPYGLASS_MODE", "clean")
if mode == "empty": sys.exit(0)
project = Path(sys.argv[sys.argv.index("-project") + 1])
if mode == "changed-input":
    Path(os.environ["FAKE_SOURCE"]).write_text("// changed during analysis\\n")
if mode == "changed-snapshot":
    source = re.search(r"read_file -type verilog \\{([^}]+)\\}", project.read_text())[1]
    Path(source).write_text("// changed executed snapshot\\n")
errors = int(mode == "error")
for goal in sys.argv[sys.argv.index("-goals") + 1].split():
    out = Path("project/consolidated_reports") / ("t03_uart_tx_" + goal.replace("/", "_"))
    out.mkdir(parents=True)
    (out / "spyglass.log").write_text("SpyGlass_vX-2025.06\\nReported Messages: 0 Fatals, " + str(errors) + " Errors, 0 Warnings, 0 Infos\\nSpyGlass Exit Code 0\\nSpyGlass run completed at now\\n")
    (out / "moresimple.rpt").write_text("Number of Waived Messages : 0\\nNumber of Overlimit Messages : 0\\n" + ("[A] W336    Error rtl.sv 30 10 Blocking assignment\\n" if errors else ""))
''')
        spyglass.chmod(0o755)
        lmutil = home / "lmutil"
        lmutil.write_text("#!" + sys.executable + "\n" + '''import os,sys
feature = sys.argv[sys.argv.index("-f") + 1]
print("license server UP\\nsnpslmd: UP")
if os.environ.get("FAKE_SPYGLASS_MODE") != "blocked":
    print("Users of " + feature + ": (Total of 9 licenses issued; Total of 0 licenses in use)")
''')
        lmutil.chmod(0o755)
        self.env = dict(os.environ, SPYGLASS_HOME=str(home), SPYGLASS_LMUTIL=str(lmutil),
                        SNPSLMD_LICENSE_FILE="test-only", FAKE_SOURCE=str(self.root / "rtl/soc/t03_uart_tx.sv"))

    def launch(self, mode="clean", extra=()):
        env = dict(self.env, FAKE_SPYGLASS_MODE=mode)
        proc = subprocess.run([sys.executable, self.root / "scripts/run_spyglass.py", "--run-id", mode, *extra],
                              cwd=self.root, env=env, capture_output=True, text=True, timeout=30)
        receipt = self.root / "evidence/SPYGLASS" / mode
        return proc, json.loads((receipt / "summary.json").read_text()), receipt

    def test_clean_reports_pass_and_survive_build_cleanup(self):
        proc, summary, receipt = self.launch()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(summary["decision"], "PASS")
        from evidence import sha256
        manifest = json.loads((receipt / "manifest.json").read_text())
        shutil.rmtree(self.root / "build")
        self.assertTrue(all(sha256(receipt / n) == h for n, h in manifest["artifacts"].items()))

    def test_zero_exit_with_no_reports_or_error_is_cli_failure(self):
        for mode in ("empty", "error"):
            with self.subTest(mode=mode):
                proc, summary, receipt = self.launch(mode)
                self.assertNotEqual(proc.returncode, 0)
                self.assertEqual(summary["decision"], "FAIL")
                self.assertEqual(json.loads((receipt / "commands.json").read_text())[-1]["exit_code"], 0)

    def test_missing_feature_blocks_before_tool_execution(self):
        proc, summary, receipt = self.launch("blocked")
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(summary["decision"], "BLOCKED_LICENSE")
        self.assertFalse(list((self.root / "build").rglob("invoked")))

    def test_inputs_changing_during_analysis_fail(self):
        for mode in ("changed-input", "changed-snapshot"):
            with self.subTest(mode=mode):
                shutil.copy2(ROOT / "rtl/soc/t03_uart_tx.sv", self.root / "rtl/soc/t03_uart_tx.sv")
                proc, summary, _ = self.launch(mode)
                self.assertNotEqual(proc.returncode, 0)
                self.assertEqual(summary["decision"], "FAIL")

    def test_existing_run_id_is_never_overwritten(self):
        proc, summary, receipt = self.launch()
        before = (receipt / "manifest.json").read_bytes()
        again, _, _ = self.launch()
        self.assertEqual(again.returncode, 2)
        self.assertEqual((receipt / "manifest.json").read_bytes(), before)

    def test_doctor_never_authorizes_analysis(self):
        proc, summary, _ = self.launch(extra=("--doctor", "--stage", "all"))
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(summary["decision"], "READY")
        self.assertFalse(summary["analysis_completed"])
        self.assertFalse(summary["authorizes_stage_pass"])
        self.assertFalse(list((self.root / "build").rglob("invoked")))


if __name__ == "__main__":
    unittest.main()
