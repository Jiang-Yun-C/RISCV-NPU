#!/usr/bin/env python3
"""Independently check the fixed CoreMark/greedy isolated-RTL A/B matrix.

Reads evidence only; never executes a compiler, simulator or board operation.
Use --memory-builds and --coremark-identity/--coremark-builds to additionally
bind captured binary hashes to retained build receipts and actual bytes.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
VOCAB = 151936
COREMARK = {
    "coremark-O2-ten": ("performance", "O2", False, "O2-debug-10"),
    "coremark-O3-ten": ("performance", "O3", False, "O3-debug-10"),
    "coremark-O3-lto-ten": ("performance", "O3", True, "O3-lto-debug-10"),
    "coremark-O2-validation-ten": ("validation", "O2", False, "O2-validation-10"),
    "coremark-O3-validation-ten": ("validation", "O3", False, "O3-validation-10"),
}
MEMORY = {
    "memory-baseline-valid-O2": (0, 0, VOCAB - 2, 3 * VOCAB - 2),
    "memory-candidate-valid-O2": (0, 0, VOCAB - 2, VOCAB),
    "memory-candidate-valid-O3": (0, 0, VOCAB - 2, VOCAB),
    "memory-baseline-tie-O2": (1, 0, 19, 3 * VOCAB - 2),
    "memory-candidate-tie-O2": (1, 0, 19, VOCAB),
    "memory-candidate-signed_zero-O2": (2, 0, 23, VOCAB),
    "memory-candidate-late_nan-O2": (3, 0xfffffffe, 0x12345678, VOCAB),
}
COUNTERS = ("cycles", "retired", "stalls", "branches", "mispredicts",
            "i_read_beats", "d_read_beats", "d_write_beats", "workspace_read_beats")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text())


def one(pattern, text, label):
    values = re.findall(pattern, text, re.M)
    require(len(values) == 1, "need exactly one " + label)
    return values[0]


def integer(value):
    return type(value) is int and value >= 0


def check_counters(counters):
    require(all(integer(counters.get(key)) for key in COUNTERS), "missing/negative/noninteger counters")
    require(counters["retired"] <= counters["cycles"], "retirements exceed cycles")
    require(counters["stalls"] <= counters["cycles"], "stalls exceed cycles")
    require(counters["mispredicts"] <= counters["branches"] <= counters["retired"], "branch bounds")
    require(counters["workspace_read_beats"] <= counters["d_read_beats"], "workspace reads exceed D reads")
    require(all(counters[key] <= counters["cycles"] for key in ("i_read_beats", "d_read_beats", "d_write_beats")),
            "one-channel beats exceed cycles")


def check_common(record, identities, negative=False):
    for key, value in identities.items():
        require(record.get(key) == value, "CPU/register-init/harness identity mismatch: " + key)
    require(re.fullmatch(r"[0-9a-f]{64}", record.get("binary_sha256", "")) is not None, "missing binary identity")
    require(record.get("read_latency") == 3 and record.get("write_latency") == 3, "different behavioral memory latency")
    require(record.get("hold_reset") is negative, "wrong reset-control setting")
    check_counters(record["total"])
    check_counters(record["window"])
    require(record["total"]["cycles"] > 0, "empty run")
    require(all(record["window"][key] <= record["total"][key] for key in COUNTERS), "window exceeds total counters")
    model = record.get("memory_model")
    if model is not None:
        expected = {"kind": "bounded_behavioral_axi_not_soc_ddr", "read_extra_wait_cycles": 3,
                    "write_extra_wait_cycles": 3, "earliest_external_read_response_cycles_after_ar": 4,
                    "earliest_external_write_response_cycles_after_last_w": 4, "local_sram_extra_wait_cycles": 1}
        require(all(model.get(key) == value for key, value in expected.items()), "memory-model description mismatch")
        require(model.get("window_boundary") == "excludes start marker W handshake; includes stop marker W handshake",
                "measurement boundary mismatch")
    if negative:
        require(record.get("status") == "FAIL" and record.get("process_exit_code") == 1, "negative control unexpectedly passed")
        require(record.get("exit_code") == 0 and record.get("uart") == "", "negative control executed firmware")
        require(record.get("error") == "cycle limit reached", "wrong negative-control failure")
        require(all(record["total"][key] == 0 for key in COUNTERS if key != "cycles"), "activity while held in reset")
        require(all(record["window"][key] == 0 for key in COUNTERS), "negative-control measurement window")
        require(record.get("marker_starts") == 0 and record.get("marker_stops") == 0, "markers while held in reset")
    else:
        require(record.get("status") == "PASS_ISOLATED_CPU_RTL" and record.get("process_exit_code") == 0,
                "simulator did not complete successfully")
        require(record.get("exit_code") == 0xc021 and record.get("error") == "", "missing successful CPU completion")
        require(record["total"]["retired"] > 0, "no real CPU retirements")


def check_coremark(record, expected, validator):
    mode, opt, lto, _ = expected
    text = record["uart"]
    require(one(r"^CM_PORT version=1 formal=([01]) ", text, "formal-mode flag") == "0",
            "expected an explicitly nonformal debug run")
    result = validator(text, expected_hz=125000000, expected_mode=mode, require_formal=False)
    require(result["iterations"] == 10 and result["crc_valid"] is True, "wrong CoreMark workload")
    require(result["formal_run_log_valid"] is False and result["release_qualified"] is False,
            "short CoreMark execution mislabeled formal")
    require(result["coremark"] is None and result["coremark_per_mhz"] is None, "short run published a score")
    require(0 < result["cycles"] < record["total"]["cycles"] and result["seconds"] < 10, "CoreMark timing bounds")
    require("T21_SHORT_DEBUG_ONLY iterations=10 data=2000" in text, "missing debug identity")
    require(record.get("marker_starts") == 0 and record.get("marker_stops") == 0, "unexpected CoreMark markers")
    require(all(record["window"][key] == 0 for key in COUNTERS), "unexpected CoreMark marker window")
    flags_text = one(r"^Compiler flags\s*:\s*(.+)$", text, "compiler flags")
    flags = flags_text.split()
    require([arg for arg in flags if arg.startswith("-O")] == ["-" + opt], "wrong CoreMark optimization")
    require(("-flto" in flags) is lto, "wrong CoreMark LTO setting")
    require({"-ffp-contract=off", "-fno-fast-math", "-march=rv32imf_zicsr_zifencei", "-mabi=ilp32f",
             "-DITERATIONS=10", "-DTOTAL_DATA_SIZE=2000", "-DMULTITHREAD=1", "-DCOREMARK_FORMAL=0",
             "-DMEM_METHOD=MEM_STACK", "-D" + mode.upper() + "_RUN=1"} <= set(flags), "missing benchmark contract")
    require(not any("COREMARK_HOST_TEST" in arg for arg in flags), "host fixture cannot be target evidence")
    normalized = [arg for arg in flags if arg not in ("-O2", "-O3", "-flto", "-DPERFORMANCE_RUN=1", "-DVALIDATION_RUN=1")]
    result.update(final_crc=one(r"^\[0\]crcfinal\s*:\s*0x([0-9a-fA-F]{4})\s*$", text, "final CRC").lower(),
                  optimization=opt, lto=lto, compiler_flags=flags_text,
                  compiler_version=one(r"^Compiler version\s*:\s*(.+)$", text, "compiler version"),
                  memory_location=one(r"^Memory location\s*:\s*(.+)$", text, "memory location"),
                  binary_sha256=record["binary_sha256"])
    return result, normalized


def check_memory(record, expected):
    case, status, token, reads = expected
    require(record.get("marker_starts") == 1 and record.get("marker_stops") == 1, "need exactly one complete marker pair")
    start, stop = record.get("marker_start_cycle"), record.get("marker_stop_cycle")
    require(integer(start) and integer(stop) and 0 < start < stop <= record["total"]["cycles"], "invalid marker bounds")
    require(stop - start == record["window"]["cycles"], "marker interval differs from window cycles")
    fields = one(r"^MEMBENCH case=([0-9a-f]{8}) count=([0-9a-f]{8}) ticks=([0-9a-f]{16}) "
                 r"status=([0-9a-f]{8}) token=([0-9a-f]{8}) pass=([0-9a-f]{8})\r?$",
                 record["uart"], "MEMBENCH result")
    actual_case, count, ticks, actual_status, actual_token, passed = map(lambda x: int(x, 16), fields)
    require((actual_case, count, actual_status, actual_token, passed) == (case, VOCAB, status, token, 1),
            "incorrect full-vocabulary semantic result")
    require(0 < ticks <= record["window"]["cycles"], "firmware ticks outside marker window")
    require(record["window"]["workspace_read_beats"] == reads, "unexpected logits read count")
    require(record["total"]["workspace_read_beats"] == reads, "logits read outside measured call")
    return {"case": case, "count": count, "status": actual_status, "token": actual_token,
            "firmware_cycles": ticks, "marker_cycles": record["window"]["cycles"],
            "workspace_read_beats": reads, "workspace_read_bytes": reads * 4,
            "window": record["window"], "binary_sha256": record["binary_sha256"]}


def speed(before, after):
    return {"before_cycles": before, "after_cycles": after,
            "cycle_reduction_percent": 100.0 * (before - after) / before,
            "throughput_ratio": before / after,
            "throughput_increase_percent": 100.0 * (before / after - 1.0)}


def bind_memory(builds, records):
    compilers, normalized = set(), []
    for name in MEMORY:
        folder = Path(builds) / name.removeprefix("memory-")
        receipt = read_json(folder / "BUILD_RESULT.json")
        require(receipt.get("status") == "BUILD_PASS_EXECUTION_REQUIRED" and receipt.get("exit_code") == 0,
                "memory probe build failed: " + name)
        require(receipt.get("bin_sha256") == sha(folder / "benchmark.bin") == records[name]["binary_sha256"],
                "memory binary identity mismatch: " + name)
        require(receipt.get("elf_sha256") == sha(folder / "benchmark.elf"), "memory ELF identity mismatch")
        require(receipt.get("full_vocabulary") == VOCAB and receipt.get("elf_flags") == 2, "memory probe geometry/ABI")
        require(receipt.get("variant") + "-" + receipt.get("case") + "-" + receipt.get("optimization") == folder.name,
                "memory build profile mismatch")
        require([arg for arg in receipt["argv"] if arg.startswith("-O")] == ["-" + receipt["optimization"]],
                "memory compiler optimization differs from receipt")
        require([arg for arg in receipt["argv"] if arg.startswith("-DMEMBENCH_CASE=")]
                == ["-DMEMBENCH_CASE=" + str(MEMORY[name][0])], "memory compiler case differs from receipt")
        flags = [arg for arg in receipt["argv"] if arg.startswith("-")
                 and arg not in ("-I", "-T", "-o", "-O2", "-O3")
                 and not arg.startswith(("-DMEMBENCH_CASE=", "-Wl,-Map="))]
        require({"-ffp-contract=off", "-fno-fast-math", "-march=rv32imf_zicsr_zifencei", "-mabi=ilp32f"} <= set(flags),
                "memory build numerical/ISA contract missing")
        normalized.append(flags)
        compilers.add((receipt["compiler_file_sha256"], receipt["compiler_version"]))
        for filename, checksum in receipt["inputs"].items():
            if "/firmware/runtime/reference/" in filename and receipt["variant"] == "baseline":
                continue
            suffixes = ("firmware/runtime/reference/nx_reference.c", "firmware/runtime/reference/nx_reference.h",
                        "firmware/runtime/board/start.S", "firmware/cpu/start.S", "firmware/runtime/board/link.ld",
                        "tests/cpu_memory_rtl/firmware.c")
            matched = [suffix for suffix in suffixes if filename.endswith("/" + suffix)]
            require(len(matched) == 1 and sha(ROOT / matched[0]) == checksum, "memory build source identity changed")
    require(len(compilers) == 1 and all(flags == normalized[0] for flags in normalized), "unmatched memory compiler/flags")
    return {"actual_binary_and_elf_bytes_checked": True, "matching_compiler_and_flags": True,
            "current_candidate_sources_checked": True, "baseline_source": "retained receipt hashes; baseline file not required"}


def bind_coremark(identity_file, builds, records, summaries):
    identity = read_json(identity_file)
    cases = {Path(item["original"]).parent.name: item for item in identity["cases"]}
    compilers = set()
    for name, (_, opt, lto, original) in COREMARK.items():
        item = cases[original]
        require(item.get("binary_identical") is True and item.get("sha256") == records[name]["binary_sha256"],
                "final CoreMark binary identity mismatch: " + name)
        if builds is not None:
            folder = Path(builds) / Path(item["final"]).parent.name
            receipt = read_json(folder / "BUILD_RECEIPT.json")
            require(sha(folder / "coremark.bin") == item["sha256"] == receipt["elf"]["bin_sha256"], "CoreMark bytes mismatch")
            require(sha(folder / "coremark.elf") == receipt["elf_sha256"], "CoreMark ELF mismatch")
            require(receipt.get("status") == "BUILT_NOT_EXECUTED" and receipt.get("build_exit_code") == 0,
                    "CoreMark build failed")
            require(receipt.get("source_inputs_stable") is True, "CoreMark source changed during build")
            require(receipt.get("opt") == opt and receipt.get("lto") is lto, "CoreMark build profile mismatch")
            require(receipt["reported_compiler_flags"] == summaries[name]["compiler_flags"], "UART/build compiler flags differ")
            for filename, checksum in receipt["source_sha256"].items():
                path = (ROOT / filename).resolve()
                require(path.is_relative_to(ROOT.resolve()) and sha(path) == checksum, "CoreMark build source identity changed")
            compilers.add((receipt["compiler_sha256"], receipt["compiler_cc1"]["sha256"], receipt["libgcc"]["sha256"]))
    if builds is not None:
        require(len(compilers) == 1, "CoreMark compiler/libgcc differs across profiles")
    return {"final_identity_manifest_checked": True, "actual_binary_and_elf_bytes_checked": builds is not None,
            "current_source_hashes_and_matching_compiler_checked": builds is not None}


def check(results, memory_builds=None, coremark_identity=None, coremark_builds=None):
    spec = importlib.util.spec_from_file_location("t27_coremark_checker", ROOT / "scripts/build_coremark.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.check_upstream(ROOT / "firmware/coremark/upstream")
    names = tuple(COREMARK) + tuple(MEMORY) + ("negative-held-reset",)
    records = {name: read_json(Path(results) / (name + ".json")) for name in names}
    identities = {"rtl_sha256": sha(ROOT / "t27/cpu/T09Cpu.v"),
                  "register_init_sha256": sha(ROOT / "t27/cpu/T09Cpu.v_toplevel_RegFilePlugin_regFile.bin"),
                  "harness_sha256": sha(ROOT / "tests/cpu_rtl/cpu_main.cpp")}
    for name, record in records.items():
        check_common(record, identities, negative=name == "negative-held-reset")
    versions = {record.get("simulator_version") for record in records.values()}
    require(len(versions) == 1 and None not in versions, "different/missing simulator version")
    coremark, normalized = {}, []
    for name, expected in COREMARK.items():
        summary, flags = check_coremark(records[name], expected, module.validate_log)
        coremark[name] = summary
        normalized.append(flags)
    require(all(flags == normalized[0] for flags in normalized), "non-optimization CoreMark compiler flags differ")
    require(len({value["compiler_version"] for value in coremark.values()}) == 1, "CoreMark compiler version differs")
    require(len({value["memory_location"] for value in coremark.values()}) == 1, "CoreMark memory placement differs")
    for mode in ("performance", "validation"):
        require(len({value["final_crc"] for value in coremark.values() if value["mode"] == mode}) == 1,
                "final CRC differs across " + mode + " profiles")
    memory = {name: check_memory(records[name], expected) for name, expected in MEMORY.items()}
    require(records["negative-held-reset"]["binary_sha256"] == records["memory-candidate-valid-O2"]["binary_sha256"],
            "negative control did not use the measured candidate binary")
    bindings = {"memory": None, "coremark": None}
    if memory_builds is not None:
        bindings["memory"] = bind_memory(memory_builds, records)
    if coremark_builds is not None:
        require(coremark_identity is not None, "--coremark-builds requires --coremark-identity")
    if coremark_identity is not None:
        bindings["coremark"] = bind_coremark(coremark_identity, coremark_builds, records, coremark)
    perf = lambda name: coremark[name]["cycles"]
    mem = lambda name: memory[name]["marker_cycles"]
    reduction = 100.0 * ((3 * VOCAB - 2) - VOCAB) / (3 * VOCAB - 2)
    return {"schema": "t27-isolated-rtl-independent-comparison-v1", "status": "PASS",
            "scope": "unchanged T09 CPU; behavioral AXI with read/write extra waits 3/3; isolated kernels only",
            "not_measured": ["formal CoreMark", "board DDR/native-drain/PHY", "full-model or TTFT speedup"],
            "formal_coremark_score": None, "release_qualified": False,
            "checked_result_count": len(records), "identities": identities,
            "simulator_version": next(iter(versions)),
            "memory_model": {"read_extra_wait_cycles": 3, "write_extra_wait_cycles": 3,
                             "first_possible_external_response_cycles": 4, "local_sram_extra_wait_cycles": 1},
            "inputs": {name + ".json": sha(Path(results) / (name + ".json")) for name in names},
            "build_bindings": bindings, "coremark": coremark, "memory": memory,
            "negative_control": "PASS: held reset, no retirements/UART/completion, expected cycle-limit failure",
            "comparisons": {
                "coremark_performance_O2_to_O3": speed(perf("coremark-O2-ten"), perf("coremark-O3-ten")),
                "coremark_performance_O3_to_O3_LTO": speed(perf("coremark-O3-ten"), perf("coremark-O3-lto-ten")),
                "coremark_validation_O2_to_O3": speed(perf("coremark-O2-validation-ten"), perf("coremark-O3-validation-ten")),
                "greedy_source_change_at_O2": speed(mem("memory-baseline-valid-O2"), mem("memory-candidate-valid-O2")),
                "greedy_candidate_O2_to_O3": speed(mem("memory-candidate-valid-O2"), mem("memory-candidate-valid-O3")),
                "greedy_uncached_read_reduction_percent": reduction}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="new JSON path; never overwrite earlier evidence")
    parser.add_argument("--memory-builds", type=Path)
    parser.add_argument("--coremark-identity", type=Path)
    parser.add_argument("--coremark-builds", type=Path)
    args = parser.parse_args(argv)
    try:
        require(not args.output.exists(), "refusing to overwrite an earlier comparison")
        result = check(args.results, args.memory_builds, args.coremark_identity, args.coremark_builds)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x") as out:
            json.dump(result, out, indent=2)
            out.write("\n")
        print(json.dumps({"status": result["status"], "checked_result_count": result["checked_result_count"],
                          "comparisons": result["comparisons"], "formal_coremark_score": None}, indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        print("RESULT_CHECK_FAILED: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
