"""Fabricated unit fixtures exercise consistency, never claim board execution.

The positive fixture deliberately uses stand-in bitstream/CPU/ELF contents and
fabricated counts. Passing it proves validator behavior, not physical origin;
every resulting report must retain independently_authenticated_board_origin=false.
No such fixture is saved or published as an actual competition result.
"""
import copy
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("competition_report", ROOT / "scripts/report_coremark_competition.py")
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)


def elf_fixture(payload):
    data = bytearray(84 + len(payload))
    data[:7] = b"\x7fELF\x01\x01\x01"
    struct.pack_into("<HHIIIIIHHHHHH", data, 16, 2, 243, 1, 0xb4000000, 52, 0, 2,
                     52, 32, 1, 0, 0, 0)
    struct.pack_into("<8I", data, 52, 1, 84, 0xb4000000, 0xb4000000,
                     len(payload), len(payload), 7, 4)
    data[84:] = payload
    return bytes(data)


class Fixture:
    def __init__(self, root):
        self.root = Path(root)
        self.session = report.template()
        self.session["maximum_clock_deviation_ppm"] = 1000
        hardware = self.session["hardware"]
        hardware.update(device_id="UNIT-TEST-DEVICE", cpu_instance="top.soc.cpu", soc_top="top",
                        clock_configuration_id="test-clock-config", memory_configuration_id="test-memory-config",
                        bitstream=self.save("hardware/test.bit", b"UNIT TEST STAND-IN, NOT A BITSTREAM"),
                        cpu_rtl=self.save("hardware/test.v", b"// UNIT TEST STAND-IN, NOT A CPU\n"))
        self.identity = {"execution_origin": "physical_board", "synthetic": False,
                         "device_id": hardware["device_id"], "bitstream_sha256": hardware["bitstream"]["sha256"],
                         "cpu_rtl_sha256": hardware["cpu_rtl"]["sha256"],
                         "clock_configuration_id": hardware["clock_configuration_id"],
                         "memory_configuration_id": hardware["memory_configuration_id"]}
        self.clock = {**self.identity, "method": "independent_reference_counter",
                      "reference_hz": 10000000, "reference_description": "unit-test reference only",
                      "reference_evidence": self.save("clock/reference.txt", b"fabricated reference record\n"),
                      "counter_capture": self.save("clock/counts.csv", b"reference_ticks,core_cycles\n10000000,125000000\n"),
                      "uncertainty_ppm": 100,
                      "domains": {"icache_to_core": {"numerator": 1, "denominator": 1},
                                  "dcache_to_core": {"numerator": 1, "denominator": 1},
                                  "memory_interface_to_core": {"numerator": 1, "denominator": 1},
                                  "memory_interface_name": "test native user clock, not transfer rate",
                                  "evidence": self.save("clock/domains.txt", b"fabricated domain relation\n")}}
        self.receipts = {}; self.captures = {}; self.logs = {}
        for index, mode in enumerate(("performance", "validation")):
            build = report.coremark.build_plan("fixture-gcc", self.root / mode, "O3", mode)
            payload = struct.pack("<I", 0x13 + index * 0x100000)
            elf = elf_fixture(payload)
            build.update(status="BUILT_NOT_EXECUTED", build_exit_code=0, source_inputs_stable=True,
                         compiler_sha256="a" * 64, compiler_cc1={"sha256": "b" * 64},
                         libgcc={"sha256": "c" * 64}, compiler_version="fixture GCC 12.2.0",
                         elf_sha256=report.digest(elf), elf={"bin_sha256": report.digest(payload)})
            self.receipts[mode] = build
            self.logs[mode] = self.make_log(mode, build)
            self.captures[mode] = {**self.identity, "run_id": "fixture-" + mode,
                                   "captured_at": "2026-10-28T15:00:00Z",
                                   "binary_sha256": report.digest(payload),
                                   "uart_sha256": report.digest(self.logs[mode].encode())}
            self.session["runs"][mode].update(elf=self.save(mode + "/coremark.elf", elf),
                                               binary=self.save(mode + "/coremark.bin", payload))
        self.resources = [self.resource("cpu", 5000, "top.soc.cpu"),
                          self.resource("whole_soc", 50000, "top")]
        self.timing = {"device_id": hardware["device_id"], "bitstream_sha256": hardware["bitstream"]["sha256"],
                       "implementation_stage": "post_route", "routing_complete": True,
                       "constrained_core_hz": 125000000, "unconstrained_endpoints": 0,
                       "setup_wns_ns": 0.097, "hold_wns_ns": 0.041, "setup_tns_ns": 0,
                       "hold_tns_ns": 0, "tool_version": "fixture PDS",
                       "raw_report": self.save("timing/raw.txt", b"fabricated timing report\n")}
        self.write()

    def save(self, name, data):
        if isinstance(data, dict):
            data = (json.dumps(data, sort_keys=True) + "\n").encode()
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return {"path": name, "sha256": report.digest(data)}

    def resource(self, scope, lut, hierarchy):
        return {"scope": scope, "device_id": self.identity["device_id"],
                "bitstream_sha256": self.identity["bitstream_sha256"], "hierarchy": hierarchy,
                "covers_entire_hierarchy": True, "implementation_stage": "post_route",
                "tool_version": "fixture PDS", "lut_definition": "CLMA LUT + CLMS LUT",
                "lut_count": lut, "raw_report": self.save("resources/" + scope + ".txt", b"fabricated LUT report\n")}

    def configured_clock(self, uncertainty=None):
        for key in ("reference_hz", "reference_description", "reference_evidence", "counter_capture"):
            self.clock.pop(key)
        self.clock.update(method="documented_clock_configuration", input_clock_hz=25000000,
                          input_clock_description="unit-test configured oscillator only",
                          effective_multiplier=5, effective_divider=1, uncertainty_ppm=uncertainty,
                          input_clock_evidence=self.save("clock/input.txt", b"fabricated oscillator specification\n"),
                          configuration_evidence=self.save("clock/pll.txt", b"fabricated PLL configuration\n"))

    def make_log(self, mode, build, cycles=5000000000, iterations=8000):
        seconds = cycles / build["clock_hz"]
        crc = report.coremark.CRC[mode]
        lines = [f"CM_PORT version=1 formal=1 hz={build['clock_hz']} data=2000 mode={mode} requested_iterations=0",
                 "CoreMark Size : 666", f"Total ticks : {cycles & 0xffffffff}",
                 f"Total time (secs): {seconds:.6f}", f"Iterations/Sec : {iterations / seconds:.6f}",
                 f"Iterations : {iterations}", "Compiler version : GCC12.2.0",
                 "Compiler flags : " + build["reported_compiler_flags"],
                 "Memory location : " + build["memory_location"]]
        for name, value in crc.items():
            lines.append(("" if name == "seedcrc" else "[0]") + name + " : 0x" + value)
        lines += ["[0]crcfinal : 0x1234"]
        if seconds >= 10:
            lines += ["Correct operation validated. See README.md for run and reporting rules."]
        else:
            lines += ["ERROR! Must execute for at least 10 secs for a valid result!", "Errors detected"]
        lines += [f"CM_TICKS high={cycles >> 32:08x} low={cycles & 0xffffffff:08x}", "CM_DONE"]
        return "\n".join(lines) + "\n"

    def write(self):
        self.session["clock_measurement"] = self.save("clock/receipt.json", self.clock)
        for mode in ("performance", "validation"):
            self.captures[mode]["uart_sha256"] = report.digest(self.logs[mode].encode())
            self.session["runs"][mode].update(
                uart=self.save(mode + "/uart.txt", self.logs[mode].encode()),
                build_receipt=self.save(mode + "/BUILD_RECEIPT.json", self.receipts[mode]),
                capture_receipt=self.save(mode + "/CAPTURE_RECEIPT.json", self.captures[mode]))
        self.session["resources"] = [self.save("resources/" + str(i) + ".json", r) for i, r in enumerate(self.resources)]
        self.session["timing"] = self.save("timing/receipt.json", self.timing) if self.timing is not None else None
        self.path = self.root / "session.json"
        self.path.write_text(json.dumps(self.session) + "\n")


class CompetitionEvidence(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="coremark-fabricated-unit-")
        self.addCleanup(self.tmp.cleanup)
        self.fixture = Fixture(self.tmp.name)

    def check(self):
        self.fixture.write()
        return report.check_session(self.fixture.path)

    def rejected(self, pattern):
        with self.assertRaisesRegex((report.EvidenceError, ValueError), pattern):
            self.check()

    def test_pairing_metrics_and_explicit_trust_boundary(self):
        r = self.check()
        self.assertEqual(r["status"], "EVIDENCE_CONSISTENT")
        self.assertFalse(r["competition_approval"])
        self.assertFalse(r["independently_authenticated_board_origin"])
        self.assertEqual(r["metrics"]["coremark_iterations_per_second"], "200")
        self.assertEqual(r["metrics"]["coremark_per_mhz"], "1.6")
        self.assertEqual([x["coremark_per_lut"] for x in r["metrics"]["resource_efficiency"]], ["0.04", "0.004"])
        self.assertIsNone(r["metrics"]["fmax_hz"])
        self.assertIn("cpu", report.render_markdown(r))

    def test_auto_iteration_request_resolves_to_positive_actual_iterations(self):
        self.assertEqual(self.fixture.receipts["performance"]["iterations"], 0)
        self.assertEqual(self.check()["performance"]["iterations"], 8000)

    def test_configured_frequency_remains_explicitly_nominal(self):
        self.fixture.configured_clock()
        r = self.check()
        self.assertEqual(r["clock"]["frequency_basis"], "configured")
        self.assertIsNone(r["clock"]["measured_hz"])
        self.assertIsNone(r["clock"]["uncertainty_ppm"])
        self.assertIsNone(r["metrics"]["coremark_iterations_per_second"])
        self.assertEqual(r["metrics"]["configured_frequency_coremark_iterations_per_second"], "200")
        self.assertEqual(r["metrics"]["coremark_per_mhz"], "1.6")
        self.assertEqual(r["performance"]["duration_basis"], "configured_nominal_only")
        self.assertIsNone(r["performance"]["seconds_from_independent_clock"])
        self.assertEqual(r["metrics"]["resource_efficiency"][0]["configured_frequency_coremark_per_lut"], "0.04")
        self.assertIsNone(r["metrics"]["resource_efficiency"][0]["coremark_per_lut"])
        self.assertIn("配置频率名义值", report.render_markdown(r))

    def test_configured_frequency_uncertainty_is_used_when_supplied(self):
        self.fixture.configured_clock(uncertainty=100)
        for mode in self.fixture.logs:
            self.fixture.logs[mode] = self.fixture.make_log(mode, self.fixture.receipts[mode], 1250000000)
        self.rejected("upper frequency uncertainty bound")

    def test_configured_frequency_needs_real_configuration_artifact_identity(self):
        self.fixture.configured_clock()
        self.fixture.clock["configuration_evidence"]["sha256"] = "e" * 64
        self.rejected("configuration evidence file identity")

    def test_configured_frequency_disagreement_rejected(self):
        self.fixture.configured_clock()
        self.fixture.clock["input_clock_hz"] = 30000000
        self.rejected("beyond the explicit tolerance")

    def test_requires_both_seed_sets(self):
        self.fixture.session["runs"]["validation"] = copy.deepcopy(self.fixture.session["runs"]["performance"])
        # Save manually so fixture writer does not restore distinct file refs.
        self.fixture.path.write_text(json.dumps(self.fixture.session))
        with self.assertRaisesRegex(ValueError, "matching formal seed-set"):
            report.check_session(self.fixture.path)

    def test_debug_marker_rejected_even_with_forged_formal_header(self):
        self.fixture.logs["performance"] = "T21_SHORT_DEBUG_ONLY\n" + self.fixture.logs["performance"]
        self.rejected("short debug")

    def test_short_test_rejected(self):
        self.fixture.logs["performance"] = self.fixture.make_log("performance", self.fixture.receipts["performance"], 1000000)
        self.rejected("at least 10")

    def test_simulation_capture_rejected(self):
        self.fixture.captures["performance"]["execution_origin"] = "rtl_simulation"
        self.rejected("physical-board")

    def test_synthetic_capture_rejected(self):
        self.fixture.captures["validation"]["synthetic"] = True
        self.rejected("physical-board")

    def test_synthetic_clock_rejected(self):
        self.fixture.clock["synthetic"] = True
        self.rejected("physical-board")

    def test_no_frequency_inferred_from_constraint(self):
        self.fixture.clock["method"] = "pds_clock_constraint"
        self.rejected("independent reference")

    def test_physical_duration_uses_independent_clock_and_uncertainty(self):
        for mode in self.fixture.logs:
            self.fixture.logs[mode] = self.fixture.make_log(mode, self.fixture.receipts[mode], 1250000000)
        self.rejected("upper frequency uncertainty bound")

    def test_wrong_frequency_rejected(self):
        self.fixture.clock["counter_capture"] = self.fixture.save("clock/counts.csv", b"reference_ticks,core_cycles\n10000000,150000000\n")
        self.rejected("beyond the explicit tolerance")

    def test_cpu_soc_denominators_cannot_be_swapped(self):
        self.fixture.resources[0]["hierarchy"] = "top"
        self.rejected("entire explicitly selected hierarchy")

    def test_lut_stage_and_definition_are_required(self):
        del self.fixture.resources[0]["implementation_stage"]
        self.rejected("implementation stage")
        self.fixture.resources[0]["implementation_stage"] = "post_route"
        del self.fixture.resources[0]["lut_definition"]
        self.rejected("lut_definition")

    def test_zero_or_negative_lut_count_rejected(self):
        self.fixture.resources[0]["lut_count"] = 0
        self.rejected("positive integer")

    def test_unmatched_bitstream_rejected(self):
        self.fixture.captures["validation"]["bitstream_sha256"] = "e" * 64
        self.rejected("identity mismatch")

    def test_changed_deployed_binary_rejected(self):
        self.fixture.captures["validation"]["binary_sha256"] = "e" * 64
        self.rejected("deployed binary")

    def test_compiler_options_must_match_outside_seeds_and_iterations(self):
        receipt = self.fixture.receipts["validation"]
        flags = receipt["reported_compiler_flags"]
        receipt["reported_compiler_flags"] = flags.replace("-O3", "-O2")
        receipt["command"] = [x.replace("-O3", "-O2") for x in receipt["command"]]
        self.fixture.logs["validation"] = self.fixture.logs["validation"].replace(flags, receipt["reported_compiler_flags"])
        self.rejected("options differ")

    def test_host_clock_define_rejected(self):
        self.fixture.receipts["performance"]["command"].append("-DCOREMARK_HOST_TEST=1")
        self.rejected("synthetic host test clock")

    def test_changed_algorithm_hash_rejected(self):
        self.fixture.receipts["performance"]["source_sha256"]["firmware/coremark/upstream/core_matrix.c"] = "e" * 64
        self.rejected("unchanged official")

    def test_libraries_must_match(self):
        self.fixture.receipts["validation"]["libgcc"]["sha256"] = "e" * 64
        self.rejected("toolchain binary identities")

    def test_negative_timing_slack_rejected_without_fmax_inference(self):
        self.fixture.timing["setup_wns_ns"] = -0.001
        self.rejected("does not close")

    def test_missing_resources_and_timing_stay_unmeasured(self):
        self.fixture.resources = []; self.fixture.timing = None
        r = self.check()
        self.assertEqual(r["metrics"]["resource_efficiency"], [])
        self.assertEqual(r["timing"]["status"], "NOT_PROVIDED")
        self.assertIsNone(r["metrics"]["fmax_hz"])

    def test_raw_file_tamper_rejected(self):
        self.fixture.write()
        (self.fixture.root / "performance/uart.txt").write_text("tampered")
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            report.check_session(self.fixture.path)

    def test_existing_outputs_are_not_overwritten(self):
        target = self.fixture.root / "report.json"
        target.write_text("existing evidence")
        code = report.main([str(self.fixture.path), "--output", str(target)])
        self.assertEqual(code, 2)
        self.assertEqual(target.read_text(), "existing evidence")

    def test_empty_template_has_no_fabricated_measurements(self):
        self.assertIsNone(report.template()["maximum_clock_deviation_ppm"])
        self.assertIsNone(report.template()["hardware"]["bitstream"]["sha256"])
        self.assertEqual(report.template()["resources"], [])
        for kind in ("clock", "clock-configured", "capture", "resource-cpu", "resource-soc", "timing"):
            self.assertIsNone(report.template(kind)["device_id"])
        self.assertIsNone(report.template("clock")["reference_hz"])
        self.assertIsNone(report.template("resource-cpu")["lut_count"])


if __name__ == "__main__":
    unittest.main()
