#!/usr/bin/env python3
"""Check retained real-RTL compiler-tuning evidence; never report a formal score."""
import argparse
import importlib.util
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


BUILD = module("competition_tuning_build", ROOT / "scripts/build_coremark.py")
OLD = module("competition_tuning_rtl_checks", ROOT / "tests/cpu_rtl/check_results.py")
# name -> build directory, seed set, extra external wait cycles
CASES = {
    "O2-performance": ("final-O2-debug-10", "performance", 3),
    "O2-validation": ("final-O2-validation-10", "validation", 3),
    "O3-performance": ("final-O3-debug-10", "performance", 3),
    "O3-validation": ("final-O3-validation-10", "validation", 3),
    "unroll-performance": ("O3-unroll-debug-10", "performance", 3),
    "unroll-validation": ("O3-unroll-validation-10", "validation", 3),
    "tuned-performance": ("O3-tuned-debug-10", "performance", 3),
    "tuned-validation": ("O3-tuned-validation-10", "validation", 3),
    "O3-external-wait15": ("final-O3-debug-10", "performance", 15),
    "tuned-external-wait15": ("O3-tuned-debug-10", "performance", 15),
}


def check(evidence, builds):
    evidence, builds = Path(evidence), Path(builds)
    identities = {
        "rtl_sha256": OLD.sha(ROOT / "t27/cpu/T09Cpu.v"),
        "register_init_sha256": OLD.sha(ROOT / "t27/cpu/T09Cpu.v_toplevel_RegFilePlugin_regFile.bin"),
        "harness_sha256": OLD.sha(ROOT / "tests/cpu_rtl/cpu_main.cpp"),
    }
    compiler_ids, simulator_versions, rows = set(), set(), {}
    for name, (folder, seed, delay) in CASES.items():
        run_path, directory = evidence / (name + ".json"), builds / folder
        run = OLD.read_json(run_path)
        receipt = OLD.read_json(directory / "BUILD_RECEIPT.json")
        OLD.require(all(run.get(k) == v for k, v in identities.items()), "CPU/harness identity: " + name)
        OLD.require(run.get("status") == "PASS_ISOLATED_CPU_RTL" and run.get("process_exit_code") == 0
                    and run.get("exit_code") == 0xc021 and run.get("error") == ""
                    and run.get("hold_reset") is False, "CPU execution did not pass: " + name)
        OLD.check_counters(run["total"])
        OLD.check_counters(run["window"])
        OLD.require(run["total"]["retired"] > 0, "no actual retirements")
        simulator_version = run.get("simulator_version")
        OLD.require(isinstance(simulator_version, str) and simulator_version.strip(), "missing simulator version")
        simulator_versions.add(simulator_version)
        OLD.require(all(x == 0 for x in run["window"].values()) and
                    run.get("marker_starts") == run.get("marker_stops") == 0, "unexpected marker window")
        OLD.require(run.get("read_latency") == run.get("write_latency") == delay, "memory latency mismatch")
        model = run.get("memory_model")
        # Older parent captures predate the explicit description; their same
        # harness hash and read/write parameters identify that fixed model.
        if model is not None:
            expected = {"kind": "bounded_behavioral_axi_not_soc_ddr", "read_extra_wait_cycles": delay,
                        "write_extra_wait_cycles": delay,
                        "earliest_external_read_response_cycles_after_ar": delay + 1,
                        "earliest_external_write_response_cycles_after_last_w": delay + 1,
                        "local_sram_extra_wait_cycles": 1}
            OLD.require(all(model.get(k) == v for k, v in expected.items()), "memory-model description changed")
        OLD.require(receipt.get("status") == "BUILT_NOT_EXECUTED" and receipt.get("source_inputs_stable") is True
                    and receipt.get("build_exit_code") == 0, "unverified build")
        for source, digest in receipt["source_sha256"].items():
            path = (ROOT / source).resolve()
            OLD.require(path.is_relative_to(ROOT.resolve()) and OLD.sha(path) == digest,
                        "current build source identity differs: " + source)
        OLD.require(OLD.sha(directory / "coremark.bin") == receipt["elf"]["bin_sha256"]
                    == run["binary_sha256"], "captured binary identity differs")
        OLD.require(OLD.sha(directory / "coremark.elf") == receipt["elf_sha256"] and
                    OLD.sha(directory / "coremark.map") == receipt["map_sha256"], "ELF/map identity differs")
        payload, metadata = BUILD.parse_elf((directory / "coremark.elf").read_bytes())
        OLD.require(payload == (directory / "coremark.bin").read_bytes(), "bin differs from ELF load image")
        text = run["uart"]
        result = BUILD.validate_log(text, expected_mode=seed, require_formal=False)
        OLD.require(result["iterations"] == 10 and result["formal_run_log_valid"] is False and
                    result["coremark"] is None and result["coremark_per_mhz"] is None,
                    "short debug data cannot be a formal score")
        OLD.require("CM_PORT version=1 formal=0 " in text and
                    0 < result["cycles"] < run["total"]["cycles"], "invalid measurement boundary")
        final_crc = OLD.one(r"^\[0\]crcfinal\s*:\s*0x([0-9a-fA-F]{4})\s*$", text, "final CRC").lower()
        OLD.require(final_crc == ("fcaf" if seed == "performance" else "c64e"), "final CRC differs")
        flags = OLD.one(r"^Compiler flags\s*:\s*(.+)$", text, "compiler flags")
        OLD.require(flags == receipt["reported_compiler_flags"], "captured flags differ from build")
        expected_tuning = ("unroll-no-if-conversion" if name.startswith("tuned")
                           else "unroll" if name.startswith("unroll") else "none")
        expected_opt = "O2" if name.startswith("O2-") else "O3"
        plan = BUILD.build_plan("cc", "/tmp/unused-competition-tuning", opt=expected_opt,
                                mode="debug" if seed == "performance" else "debug-validation",
                                iterations=10, tuning=expected_tuning)
        OLD.require(flags == plan["reported_compiler_flags"] and
                    receipt.get("tuning") == expected_tuning, "unexpected compiler profile")
        compiler_ids.add((receipt["compiler_sha256"], receipt["compiler_version"],
                          receipt["compiler_cc1"]["sha256"], receipt["libgcc"]["sha256"]))
        rows[name] = {"mode": seed, "cycles": result["cycles"], "iterations": 10,
                      "crc_valid": True, "final_crc": final_crc,
                      "binary_bytes": metadata["file_bytes"], "binary_sha256": run["binary_sha256"],
                      "tuning": expected_tuning, "external_extra_wait_cycles": delay,
                      "result_sha256": OLD.sha(run_path), "formal_coremark": None,
                      "formal_coremark_per_mhz": None}
    OLD.require(len(compiler_ids) == 1, "different compiler/libgcc in the comparison")
    OLD.require(len(simulator_versions) == 1, "different simulators in the comparison")
    comparisons = {}
    for name, before, after in (
            ("tuned_vs_plain_O3_performance", "O3-performance", "tuned-performance"),
            ("tuned_vs_plain_O3_validation", "O3-validation", "tuned-validation"),
            ("tuned_vs_original_O2_performance", "O2-performance", "tuned-performance"),
            ("tuned_vs_original_O2_validation", "O2-validation", "tuned-validation"),
            ("tuned_vs_plain_O3_external_wait15", "O3-external-wait15", "tuned-external-wait15")):
        comparisons[name] = OLD.speed(rows[before]["cycles"], rows[after]["cycles"])
    return {"schema": "t27-topic1-coremark-tuning-checked-v1", "status": "PASS_ISOLATED_RTL_TUNING",
            "scope": "10-iteration real T09 RTL, bounded behavioral AXI; neither formal CoreMark nor board/SoC performance",
            "cpu_identity": identities, "compiler_version": next(iter(compiler_ids))[1],
            "simulator_version": next(iter(simulator_versions)),
            "cases": rows, "comparisons": comparisons,
            "binary_growth_bytes_vs_O3": rows["tuned-performance"]["binary_bytes"] - rows["O3-performance"]["binary_bytes"],
            "formal_score_available": False, "board_tested": False,
            "latency_scope": "15 is an extra wait parameter, first external response earliest 16 cycles; local SRAM remains earliest 2 cycles"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--builds", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.output.exists():
            raise ValueError("output exists; preserve previous evidence")
        result = check(args.evidence, args.builds)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps({"status": result["status"], "cases": len(result["cases"]),
                          "formal_score_available": False, "output": str(args.output)}))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print("CoreMark tuning: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
