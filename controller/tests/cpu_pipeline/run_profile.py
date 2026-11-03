#!/usr/bin/env python3
"""Read-only T09 pipeline profile with a small symbol-triggered CSV/VCD capture."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RTL = ROOT / "t27/cpu/T09Cpu.v"
INIT = RTL.with_name("T09Cpu.v_toplevel_RegFilePlugin_regFile.bin")
BASE = 0xB4000000


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def identity():
    return {"rtl_sha256": sha(RTL), "register_init_sha256": sha(INIT),
            "harness_sha256": sha(HERE / "cpu_profile.cpp"),
            "profile_header_sha256": sha(HERE / "pipeline_profile.hpp"),
            "signal_configuration_sha256": sha(HERE / "signals.vlt")}


def symbol_range(elf_path, binary_path, name):
    """Require the symbols and loaded bytes to describe the actual executed RV32 image."""
    elf, binary = elf_path.read_bytes(), binary_path.read_bytes()
    if len(elf) < 52 or elf[:7] != b"\x7fELF\x01\x01\x01":
        raise ValueError("expected ELF32 little-endian version 1")
    h = struct.unpack_from("<16sHHIIIIIHHHHHH", elf)
    if h[1:4] != (2, 243, 1) or h[4] != BASE or h[8] != 52 or h[9] != 32 or h[11] != 40:
        raise ValueError("expected executable RV32 ELF with platform entry and standard headers")
    if not 0 < len(binary) <= 8 << 20:
        raise ValueError("binary outside program window")
    def span(offset, size):
        if offset < 0 or size < 0 or offset + size > len(elf):
            raise ValueError("ELF range out of bounds")
        return elf[offset:offset + size]
    span(h[5], h[9] * h[10]); span(h[6], h[11] * h[12])
    covered = 0
    for i in range(h[10]):
        pt, off, va, pa, size, mem, flags, align = struct.unpack_from("<8I", elf, h[5] + i * 32)
        if pt != 1 or not size:
            continue
        if size > mem or pa < BASE or pa + size > BASE + len(binary):
            raise ValueError("ELF file-backed load segment outside supplied binary")
        if binary[pa - BASE:pa - BASE + size] != span(off, size):
            raise ValueError("ELF load bytes differ from supplied binary")
        covered += size
    if not covered:
        raise ValueError("ELF has no file-backed load segment")
    sections = [struct.unpack_from("<10I", elf, h[6] + i * 40) for i in range(h[12])]
    found = set()
    for sec in sections:
        if sec[1] != 2:
            continue
        if sec[9] != 16 or sec[5] % 16 or sec[6] >= len(sections):
            raise ValueError("malformed ELF symbol table")
        strings = sections[sec[6]]
        names = span(strings[4], strings[5])
        entries = span(sec[4], sec[5])
        for i in range(0, len(entries), 16):
            no, value, size, info, other, index = struct.unpack_from("<IIIBBH", entries, i)
            if no >= len(names):
                raise ValueError("symbol string outside string table")
            symbol = names[no:].split(b"\0", 1)[0].decode("ascii", errors="replace")
            if symbol == name and info & 15 == 2 and index < len(sections) and sections[index][2] & 4:
                found.add((value, size))
    if len(found) != 1:
        raise ValueError("expected exactly one executable function symbol: " + name)
    value, size = found.pop()
    if not size or value < BASE or value + size > BASE + len(binary):
        raise ValueError("function symbol outside supplied program image")
    return {"name": name, "start": value, "end_exclusive": value + size, "size_bytes": size,
            "elf_load_bytes_match_binary": True}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=("build", "run"))
    p.add_argument("--directory", type=Path, required=True)
    p.add_argument("--verilator", default="verilator")
    p.add_argument("--verilator-root")
    p.add_argument("--binary", type=Path)
    p.add_argument("--elf", type=Path)
    p.add_argument("--output", type=Path)
    p.add_argument("--symbol", default="core_bench_list")
    p.add_argument("--trigger", choices=("retire", "mispredict", "data-wait"), default="mispredict")
    p.add_argument("--trace-samples", type=int, default=1024)
    p.add_argument("--pretrigger-samples", type=int, default=128)
    p.add_argument("--max-cycles", type=int, default=20000000)
    p.add_argument("--read-latency", type=int, default=3)
    p.add_argument("--write-latency", type=int, default=3)
    p.add_argument("--reference-result", type=Path,
                   help="require identical UART, full-program counters and exit state to prior uninstrumented run")
    a = p.parse_args(argv)
    d = a.directory.resolve()
    env = dict(os.environ)
    if a.verilator_root:
        env["VERILATOR_ROOT"] = str(Path(a.verilator_root).resolve())
    receipt = d / "BUILD.json"
    if a.action == "build":
        if d.exists():
            p.error("refusing to overwrite a simulator build directory")
        before = identity()
        d.mkdir(parents=True)
        shutil.copy2(INIT, d / INIT.name)
        command = [a.verilator, "--cc", "--exe", "--build", "-j", "2", "-Wno-fatal",
                   "--top-module", "T09Cpu", "--Mdir", str(d / "obj"),
                   "-CFLAGS", "-O2 -std=c++17", str(HERE / "signals.vlt"),
                   str(RTL), str(HERE / "cpu_profile.cpp")]
        code, timed_out = None, False
        with (d / "compile.log").open("w") as log:
            try:
                code = subprocess.run(command, cwd=d, env=env, stdout=log,
                                      stderr=subprocess.STDOUT, timeout=300).returncode
            except subprocess.TimeoutExpired:
                timed_out = True
        stable = identity() == before and sha(d / INIT.name) == before["register_init_sha256"]
        record = {**before, "command": command, "exit_code": code, "timed_out": timed_out,
                  "input_hashes_stable": stable,
                  "verilator_version": subprocess.run([a.verilator, "--version"], env=env,
                      capture_output=True, text=True, check=True).stdout.strip()}
        if code == 0:
            record["simulator_sha256"] = sha(d / "obj/VT09Cpu")
        receipt.write_text(json.dumps(record, indent=2) + "\n")
        if code != 0 or not stable:
            raise SystemExit("profile build failed; see " + str(d / "compile.log"))
        print(json.dumps(record, indent=2))
        return
    if not a.binary or not a.elf or not a.output:
        p.error("run needs --binary, --elf and --output")
    if not 1 <= a.trace_samples <= 16384 or not 0 <= a.pretrigger_samples < a.trace_samples:
        p.error("trace samples must be 1..16384, with smaller nonnegative pretrigger")
    if a.max_cycles < 1 or min(a.read_latency, a.write_latency) < 0:
        p.error("cycle limit must be positive and latencies nonnegative")
    built = json.loads(receipt.read_text())
    before = identity()
    if built.get("exit_code") != 0 or built.get("input_hashes_stable") is not True or any(built.get(k) != v for k, v in before.items()):
        p.error("simulator inputs differ from successful build")
    if sha(d / INIT.name) != built["register_init_sha256"] or sha(d / "obj/VT09Cpu") != built["simulator_sha256"]:
        p.error("runtime simulator or register-init copy differs from build")
    output = a.output.resolve()
    csv, vcd = output.with_suffix(".trace.csv"), output.with_suffix(".trace.vcd")
    if any(f.exists() for f in (output, csv, vcd)):
        p.error("refusing to overwrite profile or trace artifacts")
    symbol = symbol_range(a.elf, a.binary, a.symbol)
    inputs = {"binary_sha256": sha(a.binary), "elf_sha256": sha(a.elf)}
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [str(d / "obj/VT09Cpu"), str(a.binary.resolve()), str(output),
               str(a.max_cycles), str(a.read_latency), str(a.write_latency), "0", str(csv), str(vcd),
               str(symbol["start"]), str(symbol["end_exclusive"]), a.trigger,
               str(a.trace_samples), str(a.pretrigger_samples)]
    start = time.monotonic()
    run = subprocess.run(command, cwd=d, capture_output=True, text=True, timeout=300)
    result = json.loads(output.read_text())
    result.update(before)
    result.update(inputs)
    result.update(command=command, process_exit_code=run.returncode,
                  host_wall_seconds=time.monotonic() - start,
                  simulator_version=built["verilator_version"],
                  simulator_sha256=built["simulator_sha256"], symbol=symbol,
                  runner_sha256=sha(Path(__file__)))
    result["input_hashes_stable"] = (before == identity() and inputs == {
        "binary_sha256": sha(a.binary), "elf_sha256": sha(a.elf)})
    result["trace_files"] = {"csv": {"name": csv.name, "sha256": sha(csv)},
                             "vcd": {"name": vcd.name, "sha256": sha(vcd)}}
    result["memory_model"] = {
        "kind": "bounded_behavioral_axi_not_soc_ddr",
        "read_extra_wait_cycles": a.read_latency,
        "write_extra_wait_cycles": a.write_latency,
        "earliest_external_read_response_cycles_after_ar": a.read_latency + 1,
        "earliest_external_write_response_cycles_after_last_w": a.write_latency + 1,
        "local_sram_extra_wait_cycles": 1,
    }
    if a.reference_result:
        ref = json.loads(a.reference_result.read_text())
        fields = ("status", "binary_sha256", "rtl_sha256", "register_init_sha256", "read_latency",
                  "write_latency", "hold_reset", "last_pc", "exit_code", "total", "window", "uart")
        differences = [k for k in fields if result.get(k) != ref.get(k)]
        result["uninstrumented_comparison"] = {"reference_file": a.reference_result.name,
            "reference_sha256": sha(a.reference_result), "compared_fields": list(fields),
            "identical": not differences, "different_fields": differences}
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(run.stdout, end="")
    if run.stderr:
        print(run.stderr, end="")
    print("RESULT", output)
    if run.returncode or not result["input_hashes_stable"] or not result["pipeline_profile"]["trace"]["complete"] or result.get("uninstrumented_comparison", {}).get("identical") is False:
        raise SystemExit("profile run failed or lacks a complete unchanged trace")


if __name__ == "__main__":
    main()
