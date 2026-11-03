#!/usr/bin/env python3
"""Build baseline/candidate exact-source RV32 greedy probes; never access a board.

The supplied baseline is the immutable pre-optimization source directory. Both
variants use the same harness, compiler and startup/linker; only nx_reference.c
and its matching header come from that variant. Real target execution is a
separate step in tests/cpu_rtl. No score or cycle speedup is inferred by a build.
"""
import argparse
import hashlib
import json
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CASES = {"valid": 0, "tie": 1, "signed_zero": 2, "late_nan": 3}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def compile_probe(compiler, baseline, candidate, variant, case, optimization, out):
    source = baseline if variant == "baseline" else candidate
    reference = source / "firmware/runtime/reference/nx_reference.c"
    header = source / "firmware/runtime/reference/nx_reference.h"
    startup = candidate / "firmware/runtime/board/start.S"
    cpu_startup = candidate / "firmware/cpu/start.S"
    linker = candidate / "firmware/runtime/board/link.ld"
    firmware = HERE / "firmware.c"
    inputs = {str(path): digest(path) for path in (reference, header, startup, cpu_startup, linker, firmware)}
    command = [compiler, "-std=c11", "-DNX_PORTABLE", "-DHARD_FLOAT",
               "-DMEMBENCH_CASE=" + str(CASES[case]),
               "-march=rv32imf_zicsr_zifencei", "-mabi=ilp32f", "-" + optimization,
               "-ffp-contract=off", "-fno-fast-math", "-fno-strict-aliasing",
               "-ffreestanding", "-fno-builtin", "-fno-pic", "-nostdlib", "-nostartfiles",
               "-msmall-data-limit=0", "-ffunction-sections", "-fdata-sections",
               "-Wall", "-Wextra", "-Werror", "-Wno-misleading-indentation", "-Wno-unknown-pragmas",
               "-I", str(header.parent), "-T", str(linker), "-Wl,--gc-sections", "-Wl,--build-id=none",
               "-Wl,--undefined=nx_greedy", "-Wl,-Map=" + str(out / "benchmark.map"),
               str(startup), str(firmware), str(reference), "-lgcc", "-o", str(out / "benchmark.elf")]
    out.mkdir(parents=True, exist_ok=False)
    receipt = {"schema": 1, "variant": variant, "case": case, "optimization": optimization,
               "status": "BUILDING", "argv": command, "inputs": inputs,
               "compiler_path": compiler, "compiler_file_sha256": digest(compiler),
               "full_vocabulary": 151936, "logits_address": "0xac000000",
               "measurement_scope": "exact T09 CPU + separately configured behavioral memory; no board timing",
               "board_operations": False}
    start = time.monotonic()
    try:
        version = subprocess.run([compiler, "--version"], capture_output=True, text=True, check=True, timeout=10)
        receipt["compiler_version"] = version.stdout.strip()
        with (out / "compile.log").open("wb") as log:
            result = subprocess.run(command, cwd=out, stdout=log, stderr=subprocess.STDOUT, timeout=120, check=False)
        receipt["exit_code"] = result.returncode
        if result.returncode:
            raise ValueError("compiler failed; see compile.log")
        data = (out / "benchmark.elf").read_bytes()
        parser = runpy.run_path(str(candidate / "tests/models/prepare_image.py"))["parse_elf"]
        entry, segments, flags = parser(data, base=0xb4000000, capacity=8 * 1024 * 1024)
        if entry != 0xb4000000 or flags != 2 or len(segments) != 1 or segments[0].address != entry:
            raise ValueError("expected one ILP32F RV32 PT_LOAD at 0xb4000000")
        symbols = runpy.run_path(str(candidate / "scripts/build_t27_streaming.py"))["elf_symbols"](data)
        if not {"_start", "main", "nx_greedy"} <= symbols:
            raise ValueError("required production greedy or startup symbol absent")
        binary = segments[0].data
        (out / "benchmark.bin").write_bytes(binary)
        if any(digest(path) != value for path, value in inputs.items()):
            raise ValueError("source changed during build")
        receipt.update(status="BUILD_PASS_EXECUTION_REQUIRED", entry=entry, elf_flags=flags,
                       elf_sha256=digest(out / "benchmark.elf"), bin_sha256=digest(out / "benchmark.bin"),
                       binary_bytes=len(binary), memory_bytes=segments[0].memory_size)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        receipt.update(status="BUILD_FAILED", error=str(error))
    receipt["build_wall_seconds"] = time.monotonic() - start
    (out / "BUILD_RESULT.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-source", type=Path, required=True)
    parser.add_argument("--source", type=Path, default=ROOT)
    parser.add_argument("--cc", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case", choices=("all",) + tuple(CASES), default="all")
    parser.add_argument("--optimization", choices=("O2", "O3", "both"), default="O2")
    parser.add_argument("--variant", choices=("both", "baseline", "candidate"), default="both")
    args = parser.parse_args(argv)
    compiler = shutil.which(args.cc)
    if not compiler:
        parser.error("compiler is unavailable: " + args.cc)
    output, candidate, baseline = args.output.resolve(), args.source.resolve(), args.baseline_source.resolve()
    if output.exists():
        parser.error("refusing existing output directory")
    for source in (baseline, candidate):
        for name in ("firmware/runtime/reference/nx_reference.c", "firmware/runtime/reference/nx_reference.h"):
            if not (source / name).is_file():
                parser.error("missing actual source: " + str(source / name))
    cases = CASES if args.case == "all" else (args.case,)
    optimizations = ("O2", "O3") if args.optimization == "both" else (args.optimization,)
    variants = ("baseline", "candidate") if args.variant == "both" else (args.variant,)
    receipts = []
    for optimization in optimizations:
        for case in cases:
            for variant in variants:
                out = output / (variant + "-" + case + "-" + optimization)
                receipt = compile_probe(compiler, baseline, candidate, variant, case, optimization, out)
                receipts.append({"path": str(out), "status": receipt["status"]})
                if receipt["status"] != "BUILD_PASS_EXECUTION_REQUIRED":
                    print(json.dumps(receipts, indent=2))
                    return 1
    (output / "builds.json").write_text(json.dumps(receipts, indent=2) + "\n")
    print(json.dumps(receipts, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
