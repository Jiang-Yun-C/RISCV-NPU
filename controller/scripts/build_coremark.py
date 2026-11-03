#!/usr/bin/env python3
"""Build an unchanged EEMBC CoreMark workload for the current T27 CPU.

No hardware I/O. The default prints a plan; --build makes ELF/bin/map/receipt.
Both -O2 and -O3 use identical source, seed, memory, ISA and floating-point
semantics. --lto is an optional separate experiment, never an implied default.
--tuning is an explicit O3 code-generation experiment; algorithms stay intact.
--validate-log checks a complete captured UART log against raw 64-bit cycles.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
PORT = ROOT / "firmware/coremark"
UPSTREAM_COMMIT = "1f483d5b8316753a742cbf5590caf5bd0a4e4777"
ALGORITHMS = ("core_list_join.c", "core_main.c", "core_matrix.c", "core_state.c", "core_util.c")
CRC = {
    "performance": {"seedcrc": "e9f5", "crclist": "e714", "crcmatrix": "1fd7", "crcstate": "8e3a"},
    "validation": {"seedcrc": "18f2", "crclist": "e3c1", "crcmatrix": "0747", "crcstate": "8d84"},
}
TUNING_FLAGS = {
    "none": (),
    "unroll": ("-funroll-loops",),
    "unroll-no-if-conversion": ("-funroll-loops", "-fno-if-conversion", "-fno-if-conversion2"),
}


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check_upstream(path):
    path = Path(path)
    manifest = json.loads((path / "UPSTREAM.json").read_text())
    if manifest.get("commit") != UPSTREAM_COMMIT or manifest.get("algorithms_modified") is not False:
        raise ValueError("unexpected CoreMark upstream identity")
    required = set(ALGORITHMS) | {"coremark.h", "LICENSE.md", "coremark.md5"}
    if not required <= manifest["files"].keys():
        raise ValueError("upstream manifest misses a required source/license")
    for name, expected in manifest["files"].items():
        file = path / name
        if not file.resolve().is_relative_to(path.resolve()):
            raise ValueError("invalid upstream manifest path")
        data = file.read_bytes()
        blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        if (hashlib.sha256(data).hexdigest() != expected["sha256"]
                or blob != expected["git_blob_sha1"] or len(data) != expected["bytes"]):
            raise ValueError("modified upstream source: " + name)
    return manifest


def build_plan(cc, output, opt="O2", mode="performance", iterations=0,
               hz=125000000, lto=False, memory="stack", tuning="none"):
    if opt not in ("O2", "O3") or mode not in ("performance", "validation", "debug", "debug-validation"):
        raise ValueError("unsupported benchmark profile")
    if memory not in ("stack", "ddr"):
        raise ValueError("unsupported memory placement")
    if tuning not in TUNING_FLAGS or (tuning != "none" and opt != "O3"):
        raise ValueError("named tuning profiles require O3; use tuning=none for O2")
    if not 0 <= iterations <= 0x7fffffff or not 0 < hz <= 0xffffffff:
        raise ValueError("iterations/clock outside RV32 port range")
    if mode.startswith("debug") and not iterations:
        raise ValueError("debug mode requires an explicit positive iteration count")
    output = Path(output).resolve()
    upstream = PORT / "upstream"
    check_upstream(upstream)
    run = "validation" if mode in ("validation", "debug-validation") else "performance"
    flags = ["-std=c11", "-" + opt, "-march=rv32imf_zicsr_zifencei", "-mabi=ilp32f",
             "-DHARD_FLOAT", "-ffp-contract=off", "-fno-fast-math", "-fno-strict-aliasing",
             "-ffreestanding", "-fno-builtin", "-fno-pic", "-nostdlib", "-nostartfiles",
             "-msmall-data-limit=0", "-ffunction-sections", "-fdata-sections",
             "-fstack-usage", "-DHAS_FLOAT=1", "-DHAS_STDIO=0", "-DHAS_PRINTF=0",
             "-DHAS_TIME_H=0", "-DUSE_CLOCK=0", "-DMAIN_HAS_NOARGC=1",
             "-DMULTITHREAD=1", "-DTOTAL_DATA_SIZE=2000", "-DSEED_METHOD=SEED_VOLATILE",
             "-DMEM_METHOD=" + ("MEM_STACK" if memory == "stack" else "MEM_STATIC"),
             "-D" + run.upper() + "_RUN=1", "-DITERATIONS=" + str(iterations),
             "-DCOREMARK_FORMAL=" + str(int(not mode.startswith("debug"))),
             "-DCOREMARK_REPORT_METADATA=1", "-DCM_CPU_HZ=" + str(hz) + "u"]
    flags.extend(TUNING_FLAGS[tuning])
    if lto:
        flags.append("-flto")
    reported_flags = " ".join(flags)
    location = ("code=DDR@0xb4000000; data=local-SRAM-stack@0x20000; " if memory == "stack"
                else "code=DDR@0xb4000000; data=DDR-static; stack=local-SRAM@0x20000; ")
    location += "I/D=16KiB-2way-32B; D=write-through; single-context; core_hz=" + str(hz)
    sources = [ROOT / "firmware/runtime/board/start.S"]
    sources += [upstream / name for name in ALGORITHMS]
    sources += [PORT / "core_portme.c", PORT / "core_portme_printf.c"]
    command = [str(cc), *flags, '-DFLAGS_STR="' + reported_flags + '"',
               '-DMEM_LOCATION="' + location + '"',
               "-I", str(PORT), "-I", str(upstream),
               "-ffile-prefix-map=" + str(ROOT) + "=.",
               "-ffile-prefix-map=" + str(output) + "=.",
               "-T", str(ROOT / "firmware/runtime/board/link.ld"),
               "-Wl,--gc-sections", "-Wl,--build-id=none", "-Wl,-Map=" + str(output / "coremark.map"),
               *map(str, sources), "-lgcc", "-o", str(output / "coremark.elf")]
    identity_files = sources + [PORT / "core_portme.h", PORT / "core_portme_timer.h",
                               ROOT / "firmware/cpu/start.S", ROOT / "firmware/runtime/board/link.ld",
                               upstream / "coremark.h", upstream / "UPSTREAM.json", Path(__file__)]
    return {"schema": "t27-coremark-build-v1", "upstream_commit": UPSTREAM_COMMIT,
            "opt": opt, "lto": lto, "tuning": tuning,
            "tuning_flags": list(TUNING_FLAGS[tuning]), "mode": mode, "run_seed_set": run,
            "iterations": iterations, "clock_hz": hz, "total_data_size": 2000,
            "memory": memory, "memory_location": location,
            "reported_compiler_flags": reported_flags, "command": command,
            "source_sha256": {str(p.relative_to(ROOT)): sha256(p) for p in identity_files},
            "scope": "offline ELF build; not a CoreMark score or board qualification"}


def parse_elf(data):
    if len(data) < 52 or data[:7] != b"\x7fELF\x01\x01\x01":
        raise ValueError("requires little-endian ELF32")
    elf_type, machine, elf_version = struct.unpack_from("<HHI", data, 16)
    entry, phoff = struct.unpack_from("<II", data, 24)
    flags = struct.unpack_from("<I", data, 36)[0]
    ehsize, phsize, phnum = struct.unpack_from("<HHH", data, 40)
    if (elf_type != 2 or elf_version != 1 or ehsize != 52 or machine != 243
            or entry != 0xb4000000 or flags != 2 or phsize != 32):
        raise ValueError("ELF must be RV32 ILP32F, no compressed ISA, entry 0xb4000000")
    segments = []
    for i in range(phnum):
        offset = phoff + i * phsize
        if offset + 32 > len(data):
            raise ValueError("truncated ELF program headers")
        typ, off, va, pa, fs, ms, permissions, align = struct.unpack_from("<8I", data, offset)
        if typ != 1:
            continue
        if va != pa or off + fs > len(data) or fs > ms or fs == 0 or not permissions & 1:
            raise ValueError("invalid load segment")
        segments.append((va, fs, ms, permissions, data[off:off + fs]))
    if len(segments) != 1 or segments[0][0] != entry or segments[0][2] > 8 * 1024 * 1024:
        raise ValueError("requires one T27 application PT_LOAD within 8 MiB")
    va, fs, ms, permissions, payload = segments[0]
    return payload, {"entry": entry, "elf_flags": flags, "file_bytes": fs,
                     "memory_bytes": ms, "permissions": permissions,
                     "bin_sha256": hashlib.sha256(payload).hexdigest()}


def _one(pattern, text, label):
    values = re.findall(pattern, text, re.M)
    if len(values) != 1:
        raise ValueError("need exactly one " + label)
    return values[0]


def validate_log(text, expected_hz=125000000, expected_mode=None, require_formal=True):
    formal, hz, size, mode, requested = _one(
        r"^CM_PORT version=1 formal=([01]) hz=(\d+) data=(\d+) mode=(performance|validation) requested_iterations=(\d+)\r?$",
        text, "port identity")
    hz, size, requested = int(hz), int(size), int(requested)
    if hz <= 0 or expected_hz <= 0:
        raise ValueError("clock must be positive")
    if hz != expected_hz or size != 2000 or (expected_mode and mode != expected_mode):
        raise ValueError("clock/data/seed-set identity mismatch")
    if require_formal and formal != "1":
        raise ValueError("debug run cannot be a formal result")
    high, low = _one(r"^CM_TICKS high=([0-9a-fA-F]{8}) low=([0-9a-fA-F]{8})\r?$", text, "64-bit timing record")
    cycles = (int(high, 16) << 32) | int(low, 16)
    if not cycles:
        raise ValueError("zero measured cycles")
    _one(r"^CM_DONE\r?$", text, "completion marker")
    if "CM_TRAP" in text:
        raise ValueError("CPU trap invalidates the run")
    iterations = int(_one(r"^Iterations\s*:\s*(\d+)\s*$", text, "iteration count"))
    if not iterations or (requested and requested != iterations):
        raise ValueError("iteration identity mismatch")
    reported_ticks = int(_one(r"^Total ticks\s*:\s*(\d+)\s*$", text, "upstream ticks"))
    if reported_ticks != (cycles & 0xffffffff):
        raise ValueError("RV32 upstream low-word ticks disagree with CM_TICKS")
    if int(_one(r"^CoreMark Size\s*:\s*(\d+)\s*$", text, "algorithm data size")) != 666:
        raise ValueError("unexpected per-algorithm working set")
    seconds = cycles / hz
    reported_seconds = float(_one(r"^Total time \(secs\):\s*([0-9]+(?:\.[0-9]+)?)\s*$", text, "seconds"))
    if abs(reported_seconds - seconds) > max(0.00000051, abs(seconds) * 1e-14):
        raise ValueError("printed time disagrees with raw cycles and clock")
    for name, expected in CRC[mode].items():
        actual = _one(r"^(?:\[0\])?" + name + r"\s*:\s*0x([0-9a-fA-F]+)\s*$", text, name)
        if int(actual, 16) != int(expected, 16):
            raise ValueError("failed official " + name + " CRC")
    _one(r"^\[0\]crcfinal\s*:\s*0x([0-9a-fA-F]+)\s*$", text, "final CRC")
    short_warning = "ERROR! Must execute for at least 10 secs for a valid result!"
    if seconds >= 10:
        if "ERROR!" in text or "Errors detected" in text or "Correct operation validated." not in text:
            raise ValueError("upstream validation did not succeed")
    else:
        if require_formal:
            raise ValueError("formal CoreMark requires at least 10 measured seconds")
        if text.count("ERROR!") != 1 or short_warning not in text or "Errors detected" not in text:
            raise ValueError("short run contains an unexplained error")
    score = iterations / seconds
    printed_rate = float(_one(r"^Iterations/Sec\s*:\s*([0-9]+(?:\.[0-9]+)?)\s*$", text, "iteration rate"))
    if abs(printed_rate - score) > max(0.00000051, abs(score) * 1e-14):
        raise ValueError("printed rate disagrees with raw cycles")
    return {"schema": "t27-coremark-log-validation-v1", "mode": mode, "clock_hz": hz,
            "iterations": iterations, "cycles": cycles, "seconds": seconds,
            "cycles_per_iteration": cycles / iterations,
            "crc_valid": True, "formal_run_log_valid": formal == "1" and seconds >= 10,
            "release_qualified": False,
            "coremark": score if formal == "1" and seconds >= 10 and mode == "performance" else None,
            "coremark_per_mhz": score / (hz / 1000000) if formal == "1" and seconds >= 10 and mode == "performance" else None,
            "scope": "one reported run; a formal release also needs matching performance and validation runs, build identity, and independently verified clock/memory conditions"}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cc", default="riscv32-unknown-elf-gcc")
    p.add_argument("--output", "--out", type=Path, default=ROOT / "build/coremark")
    p.add_argument("--opt", choices=("O2", "O3"), default="O2")
    p.add_argument("--lto", action="store_true")
    p.add_argument("--tuning", choices=tuple(TUNING_FLAGS), default="none",
                   help="explicit O3 code-generation tuning; none preserves the existing default")
    p.add_argument("--mode", choices=("performance", "validation", "debug", "debug-validation"), default="performance")
    p.add_argument("--iterations", type=int, default=0)
    p.add_argument("--hz", type=int, default=125000000)
    p.add_argument("--memory", choices=("stack", "ddr"), default="stack")
    p.add_argument("--build", action="store_true")
    p.add_argument("--validate-log", type=Path)
    p.add_argument("--allow-short", action="store_true", help="accept CRC-correct short execution, without reporting a score")
    args = p.parse_args(argv)
    try:
        if args.validate_log:
            result = validate_log(args.validate_log.read_text(), args.hz,
                                  None if args.mode.startswith("debug") else args.mode, not args.allow_short)
            print(json.dumps(result, indent=2))
            return 0
        compiler = shutil.which(args.cc) or args.cc
        plan = build_plan(compiler, args.output, args.opt, args.mode, args.iterations,
                          args.hz, args.lto, args.memory, args.tuning)
        if not args.build:
            plan["compiler_available"] = shutil.which(args.cc) is not None
            print(json.dumps(plan, indent=2))
            return 0
        if not shutil.which(args.cc):
            raise ValueError("RV32 GCC unavailable: " + args.cc + "; use --cc with a compatible compiler")
        output = args.output.resolve()
        if output.exists():
            raise ValueError("output already exists; use a new directory to preserve prior evidence: " + str(output))
        output.mkdir(parents=True, exist_ok=False)
        plan["compiler_sha256"] = sha256(compiler)
        version = subprocess.run([compiler, "--version"], text=True, capture_output=True, check=True)
        plan["compiler_version"] = version.stdout.strip()
        target_flags = ["-march=rv32imf_zicsr_zifencei", "-mabi=ilp32f"]
        for name, query in (("compiler_cc1", "-print-prog-name=cc1"),
                            ("libgcc", "-print-libgcc-file-name")):
            selected = subprocess.run([compiler, *target_flags, query], text=True,
                                      capture_output=True, check=True).stdout.strip()
            plan[name] = {"path": selected, "sha256": sha256(selected) if Path(selected).is_file() else None}
        (output / "build-plan.json").write_text(json.dumps(plan, indent=2) + "\n")
        started = time.monotonic()
        try:
            result = subprocess.run(plan["command"], text=True, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, cwd=output, timeout=180)
        except subprocess.TimeoutExpired as exc:
            captured = exc.stdout or ""
            if isinstance(captured, bytes):
                captured = captured.decode("utf-8", errors="replace")
            (output / "build.log").write_text(captured)
            receipt = {**plan, "status": "BUILD_TIMEOUT", "build_exit_code": None,
                       "build_wall_seconds": time.monotonic() - started,
                       "executed_on_target": False, "formal_score": None}
            (output / "BUILD_RECEIPT.json").write_text(json.dumps(receipt, indent=2) + "\n")
            raise ValueError("compiler exceeded 180 seconds; failure receipt retained in " + str(output)) from exc
        (output / "build.log").write_text(result.stdout)
        receipt = {**plan, "build_exit_code": result.returncode,
                   "build_wall_seconds": time.monotonic() - started,
                   "executed_on_target": False, "formal_score": None}
        changed_inputs = [name for name, expected in plan["source_sha256"].items()
                          if not (ROOT / name).is_file() or sha256(ROOT / name) != expected]
        receipt["source_inputs_stable"] = not changed_inputs
        if changed_inputs:
            receipt.update(status="SOURCE_CHANGED_DURING_BUILD", changed_inputs=changed_inputs)
            (output / "BUILD_RECEIPT.json").write_text(json.dumps(receipt, indent=2) + "\n")
            raise ValueError("source changed during compile; do not use this ELF")
        if result.returncode:
            receipt["status"] = "BUILD_FAILED"
        else:
            payload, metadata = parse_elf((output / "coremark.elf").read_bytes())
            (output / "coremark.bin").write_bytes(payload)
            receipt.update(status="BUILT_NOT_EXECUTED", elf=metadata,
                           elf_sha256=sha256(output / "coremark.elf"),
                           map_sha256=sha256(output / "coremark.map"))
        (output / "BUILD_RECEIPT.json").write_text(json.dumps(receipt, indent=2) + "\n")
        print(json.dumps({"status": receipt["status"], "output": str(output),
                          "exit_code": result.returncode, "formal_score": None}, indent=2))
        if result.returncode:
            print(result.stdout, file=sys.stderr)
        return int(result.returncode != 0)
    except (ValueError, OSError, KeyError, subprocess.SubprocessError) as exc:
        print("CoreMark: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
