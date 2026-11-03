#!/usr/bin/env python3
"""Independently recount bounded RTL observations and compare whole-run profiles."""
import argparse
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FIELDS = "cycle fetch_pc decode_pc execute_pc memory_pc writeback_pc retire_instruction valid_mask stuck_mask fire_mask remove_mask fetch_flush retire execute_stall conditional_branch branch_pc mispredict pending_writes data_bus_hazard data_refilling execute_load_valid execute_store_valid axi_fire_mask axi_backpressure_mask i_read_wait d_read_wait write_response_wait".split()
WIDTHS = [64,32,32,32,32,32,32,5,5,5,4,1,1,1,1,32,1,3,1,1,1,1,7,7,1,1,1]


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def recount(rows):
    n = len(rows)
    total = lambda key: sum(r[key] for r in rows)
    count = {"active_cycles": n, "retired": total("retire"),
        "no_retire_cycles": n - total("retire"), "execute_stall_cycles": total("execute_stall"),
        "conditional_branches": total("conditional_branch"), "conditional_mispredicts": total("mispredict"),
        "i_read_wait_cycles": total("i_read_wait"), "d_read_wait_cycles": total("d_read_wait"),
        "write_response_wait_cycles": total("write_response_wait"),
        "data_bus_hazard_cycles": total("data_bus_hazard"), "data_refilling_cycles": total("data_refilling"),
        "pending_write_cycles": sum(r["pending_writes"] != 0 for r in rows),
        "max_pending_writes": max((r["pending_writes"] for r in rows), default=0),
        "execute_load_fires": sum(bool(r["execute_load_valid"] and r["fire_mask"] & 4) for r in rows),
        "execute_store_fires": sum(bool(r["execute_store_valid"] and r["fire_mask"] & 4) for r in rows),
        "fetch_flush_cycles": total("fetch_flush")}
    for key, column, bits in (("stage_valid_cycles", "valid_mask", 5), ("stage_stuck_cycles", "stuck_mask", 5),
        ("stage_fire_cycles", "fire_mask", 5), ("axi_handshakes", "axi_fire_mask", 7),
        ("axi_backpressure_cycles", "axi_backpressure_mask", 7)):
        count[key] = [sum((r[column] >> bit) & 1 for r in rows) for bit in range(bits)]
    return count


def validate(path):
    result = json.loads(path.read_text())
    sources = {"rtl_sha256": ROOT / "t27/cpu/T09Cpu.v",
        "register_init_sha256": ROOT / "t27/cpu/T09Cpu.v_toplevel_RegFilePlugin_regFile.bin",
        "harness_sha256": HERE / "cpu_profile.cpp", "profile_header_sha256": HERE / "pipeline_profile.hpp",
        "signal_configuration_sha256": HERE / "signals.vlt"}
    require(all(result.get(key) == sha(file) for key, file in sources.items()), "current source identity differs from measured source")
    require(result["status"] == "PASS_ISOLATED_CPU_RTL" and result["process_exit_code"] == 0 and result["exit_code"] == 0xC021,
            "CPU did not complete successfully")
    require(result.get("input_hashes_stable") is True and result.get("hold_reset") is False and not result["error"],
            "run inputs changed or CPU held in reset")
    require(result["memory_model"]["kind"] == "bounded_behavioral_axi_not_soc_ddr", "unexpected memory model")
    spec = importlib.util.spec_from_file_location("coremark_validator", ROOT / "scripts/build_coremark.py")
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    require(len(re.findall(r"^CM_PORT version=1 formal=0 ", result["uart"], re.M)) == 1,
            "pipeline evidence must explicitly identify a debug workload")
    log = module.validate_log(result["uart"], require_formal=False)
    require(log["crc_valid"] and not log["formal_run_log_valid"] and not log["release_qualified"]
            and log["coremark"] is None and log["coremark_per_mhz"] is None,
            "a profile must remain an unqualified debug experiment")
    final_crc = re.findall(r"^\[0\]crcfinal\s*:\s*0x([0-9a-fA-F]+)\s*$", result["uart"], re.M)
    require(len(final_crc) == 1, "ambiguous final CRC")
    profile = result["pipeline_profile"]
    whole, trace = profile["whole_program"], profile["trace"]
    require(profile["schema"] == 1 and profile["sampling"] == "pre_rising_edge_active_cycles_only", "profile schema mismatch")
    require(trace["triggered"] and trace["complete"] and 1 <= trace["samples"] <= 16384
            and trace["samples"] == trace["requested_samples"], "missing or incomplete bounded trace")
    require(whole["active_cycles"] == result["total"]["cycles"] - 12, "active cycle count must exclude exactly 12 reset cycles")
    for a, b in (("retired", "retired"), ("execute_stall_cycles", "stalls"),
                 ("conditional_branches", "branches"), ("conditional_mispredicts", "mispredicts")):
        require(whole[a] == result["total"][b], "original and profile counters disagree: " + a)
    require(whole["stage_fire_cycles"][4] == whole["retired"] > 0, "writeback retirement mismatch")
    require(whole["stage_stuck_cycles"][2] == whole["execute_stall_cycles"], "execute stall mismatch")
    for index, key in ((1, "i_read_beats"), (3, "d_read_beats"), (5, "d_write_beats")):
        require(whole["axi_handshakes"][index] == result["total"][key], "original and profile AXI counters disagree")
    require(whole["no_retire_cycles"] + whole["retired"] == whole["active_cycles"], "no-retirement count mismatch")
    require(0 <= whole["conditional_mispredicts"] <= whole["conditional_branches"] <= whole["active_cycles"], "conditional branch bounds")
    for key, value in whole.items():
        values = value if isinstance(value, list) else [value]
        require(all(type(v) is int and 0 <= v <= whole["active_cycles"] for v in values), "counter bounds: " + key)
    require(whole["max_pending_writes"] <= 7, "pending-write field bounds")
    files = {}
    for kind in ("csv", "vcd"):
        item = result["trace_files"][kind]
        require(Path(item["name"]).name == item["name"], "trace path must be a basename")
        file = path.parent / item["name"]
        require(sha(file) == item["sha256"], "trace hash mismatch: " + kind)
        files[kind] = file
    with files["csv"].open(newline="") as stream:
        reader = csv.DictReader(stream)
        require(reader.fieldnames == FIELDS, "CSV field mapping differs")
        rows = [{key: int(value) for key, value in row.items()} for row in reader]
    require(len(rows) == trace["samples"] and len(rows) > 0, "CSV sample count")
    require(rows[0]["cycle"] == trace["first_cycle"] and rows[-1]["cycle"] == trace["last_cycle"], "trace bounds")
    for i, row in enumerate(rows):
        require(row["cycle"] == rows[0]["cycle"] + i, "trace must be contiguous")
        require(all(0 <= row[key] < 1 << width for key, width in zip(FIELDS, WIDTHS)), "signal width mismatch")
        require(row["stuck_mask"] & ~row["valid_mask"] == 0, "stuck mask must be gated with valid")
        for stage in range(5):
            valid, stuck = (row["valid_mask"] >> stage) & 1, (row["stuck_mask"] >> stage) & 1
            remove = 0 if stage == 0 else (row["remove_mask"] >> (stage - 1)) & 1
            require((row["fire_mask"] >> stage) & 1 == (valid and not stuck and not remove), "stage fire equation")
        require(row["retire"] == (row["fire_mask"] >> 4) & 1, "WB fire must equal retire")
        require(row["execute_stall"] == (row["stuck_mask"] >> 2) & 1, "execute stall signal mismatch")
        require(not row["mispredict"] or row["conditional_branch"], "mispredict denominator is conditional branches")
        require(not row["conditional_branch"] or (row["fire_mask"] & 8 and row["branch_pc"] == row["memory_pc"]), "branch stage mismatch")
        require(not row["execute_load_valid"] or (row["valid_mask"] & 4 and not row["execute_store_valid"]), "load indication mismatch")
        require(not row["execute_store_valid"] or (row["valid_mask"] & 4), "store indication mismatch")
        require(row["axi_fire_mask"] & row["axi_backpressure_mask"] == 0, "AXI handshake and backpressure overlap on same channel")
    require(recount(rows) == trace["counters"], "independent CSV recount differs from profile")
    trigger_index = trace["trigger_cycle"] - rows[0]["cycle"]
    require(trigger_index == trace["pretrigger_samples"] and 0 <= trigger_index < len(rows), "pretrigger range")
    hit = rows[trigger_index]
    kind = trace["trigger_kind"]
    if kind == "mispredict":
        flag, pc = hit["mispredict"], hit["branch_pc"]
    elif kind == "retire":
        flag, pc = hit["retire"], hit["writeback_pc"]
    else:
        require(kind == "data-wait", "unknown trigger")
        flag, pc = hit["d_read_wait"] and hit["valid_mask"] & 4, hit["execute_pc"]
    require(flag and trace["symbol_start"] <= pc < trace["symbol_end_exclusive"], "trigger is outside actual ELF function")
    require(result["symbol"]["start"] == trace["symbol_start"] and result["symbol"]["end_exclusive"] == trace["symbol_end_exclusive"]
            and result["symbol"]["elf_load_bytes_match_binary"] is True, "ELF trigger binding")
    # Independently decode the cycle-sampled VCD and require every CSV field.
    declarations, samples, time_ns, sample = {}, [], None, {}
    for line in files["vcd"].read_text().splitlines():
        if line.startswith("$var "):
            parts = line.split(); declarations[parts[3]] = (parts[4], int(parts[2]))
        elif line.startswith("#"):
            time_ns = int(line[1:])
        elif line.startswith("b"):
            value, key = line[1:].split(); sample[key] = int(value, 2)
        elif line == "1clock":
            require(len(sample) == len(FIELDS), "incomplete VCD sample")
            samples.append((time_ns, sample)); sample = {}
    require(len(samples) == len(rows), "VCD sample count")
    for i, key in enumerate(FIELDS):
        require(declarations.get("s" + str(i)) == (key, WIDTHS[i]), "VCD declaration mapping")
    for (time_ns, sample), row in zip(samples, rows):
        require(time_ns == row["cycle"] * 10 + 5, "VCD logical cycle framing")
        require(all(sample["s" + str(i)] == row[key] for i, key in enumerate(FIELDS)), "VCD/CSV value mismatch")
    if "uninstrumented_comparison" in result:
        require(result["uninstrumented_comparison"]["identical"] is True, "passive instrumentation changed execution")
    return {"file": path.name, "result_sha256": sha(path), "binary_sha256": result["binary_sha256"],
        "elf_sha256": result["elf_sha256"], "rtl_sha256": result["rtl_sha256"],
        "register_init_sha256": result["register_init_sha256"],
        "harness_sha256": result["harness_sha256"], "profile_header_sha256": result["profile_header_sha256"],
        "signal_configuration_sha256": result["signal_configuration_sha256"],
        "memory_model": result["memory_model"], "coremark_debug": log, "final_crc": final_crc[0].lower(),
        "whole_program": whole,
        "whole_program_cpi": whole["active_cycles"] / whole["retired"],
        "conditional_mispredict_percent": 100 * whole["conditional_mispredicts"] / whole["conditional_branches"] if whole["conditional_branches"] else None,
        "trace": trace, "trace_files": result["trace_files"], "symbol": result["symbol"],
        "source_identity_verified": True,
        "uninstrumented_comparison": result.get("uninstrumented_comparison")}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("results", type=Path, nargs="+")
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args(argv)
    if a.output.exists():
        p.error("refusing to overwrite comparison")
    runs = [validate(path) for path in a.results]
    first = runs[0]
    same = ("rtl_sha256", "register_init_sha256", "harness_sha256", "profile_header_sha256",
            "signal_configuration_sha256", "memory_model", "final_crc")
    for r in runs[1:]:
        require(all(r[k] == first[k] for k in same), "profile run environment or final CRC mismatch")
        require(all(r["coremark_debug"][k] == first["coremark_debug"][k] for k in ("mode", "iterations", "clock_hz")), "CoreMark workload mismatch")
    comparisons = []
    for r in runs[1:]:
        b, c = first["coremark_debug"]["cycles"], r["coremark_debug"]["cycles"]
        comparisons.append({"baseline": first["file"], "candidate": r["file"],
            "timed_kernel_cycle_reduction_percent": 100 * (b - c) / b,
            "timed_kernel_throughput_increase_percent": 100 * (b / c - 1),
            "whole_program_counter_delta_candidate_minus_baseline": {
                key: r["whole_program"][key] - value for key, value in first["whole_program"].items() if isinstance(value, int)}})
    summary = {"schema": "t09-passive-pipeline-comparison-v1", "status": "PASS",
        "scope": "actual unchanged RTL; behavioral AXI timing; simulated sampled traces only; no physical ILA capture, board score, or full-model result",
        "formal_coremark_score": None, "physical_ila_performed": False,
        "counter_semantics": "whole-program event counts overlap; CPI includes setup and reporting; do not sum waits or attribute whole-program deltas exclusively to timed kernel",
        "checks": ["CPU completed", "official debug CRCs", "raw64 timing", "trace hashes", "signal widths and stage fire equations",
                   "contiguous bound and actual-symbol trigger", "independent CSV recount", "every VCD signal equals CSV", "same execution environment"],
        "runs": runs, "comparisons": comparisons}
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({"status": "PASS", "runs": len(runs), "comparisons": comparisons}, indent=2))


if __name__ == "__main__":
    main()
