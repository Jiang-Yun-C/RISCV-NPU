#!/usr/bin/env python3
"""Build/run isolated unchanged T09 RTL; no board, serial device or EDA signoff."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
RTL = ROOT / "t27/cpu/T09Cpu.v"
INIT = ROOT / "t27/cpu/T09Cpu.v_toplevel_RegFilePlugin_regFile.bin"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def identity():
    return {"rtl_sha256": sha(RTL), "register_init_sha256": sha(INIT),
            "harness_sha256": sha(HERE / "cpu_main.cpp")}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=("build", "run"))
    p.add_argument("--directory", type=Path, required=True)
    p.add_argument("--verilator", default="verilator")
    p.add_argument("--verilator-root")
    p.add_argument("--binary", type=Path)
    p.add_argument("--output", type=Path)
    p.add_argument("--max-cycles", type=int, default=20000000)
    p.add_argument("--read-latency", type=int, default=3,
                   help="extra response wait cycles; first possible R is parameter+1 cycles after AR")
    p.add_argument("--write-latency", type=int, default=3,
                   help="extra response wait cycles; first possible B is parameter+1 cycles after last W")
    p.add_argument("--hold-reset", action="store_true")
    a = p.parse_args(argv)
    d = a.directory.resolve()
    env = dict(os.environ)
    if a.verilator_root:
        env["VERILATOR_ROOT"] = str(Path(a.verilator_root).resolve())
    receipt = d / "BUILD.json"
    if a.action == "build":
        if d.exists():
            raise SystemExit("refusing to overwrite an existing simulator build directory")
        before = identity()
        d.mkdir(parents=True)
        shutil.copy2(INIT, d / INIT.name)
        command = [a.verilator, "--cc", "--exe", "--build", "-j", "2", "-Wno-fatal",
                   "--top-module", "T09Cpu", "--Mdir", str(d / "obj"),
                   "-CFLAGS", "-O2 -std=c++17", str(RTL), str(HERE / "cpu_main.cpp")]
        with (d / "compile.log").open("w") as log:
            run = subprocess.run(command, cwd=d, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=300)
        stable = identity() == before and sha(d / INIT.name) == before["register_init_sha256"]
        record = {**before, "command": command, "exit_code": run.returncode,
                  "input_hashes_stable": stable,
                  "verilator_version": subprocess.run([a.verilator, "--version"], env=env,
                      capture_output=True, text=True, check=True).stdout.strip()}
        receipt.write_text(json.dumps(record, indent=2) + "\n")
        if run.returncode or not stable:
            raise SystemExit("simulator build failed; see " + str(d / "compile.log"))
        print(json.dumps(record, indent=2))
        return
    if not a.binary or not a.output:
        p.error("run needs --binary and --output")
    if a.max_cycles < 1 or min(a.read_latency, a.write_latency) < 0:
        p.error("cycle limit must be positive and latencies nonnegative")
    built = json.loads(receipt.read_text())
    if built["exit_code"] or built.get("input_hashes_stable") is False or any(built.get(k) != v for k, v in identity().items()):
        raise SystemExit("simulator inputs differ from its successful build")
    if sha(d / INIT.name) != built["register_init_sha256"]:
        raise SystemExit("runtime register-init copy differs from the verified CPU input")
    if a.output.exists():
        raise SystemExit("refusing to overwrite a previous simulation result")
    a.output.parent.mkdir(parents=True, exist_ok=True)
    command = [str(d / "obj/VT09Cpu"), str(a.binary.resolve()), str(a.output.resolve()),
               str(a.max_cycles), str(a.read_latency), str(a.write_latency), str(int(a.hold_reset))]
    start = time.monotonic()
    run = subprocess.run(command, cwd=d, capture_output=True, text=True, timeout=300)
    result = json.loads(a.output.read_text())
    result.update(identity())
    result.update(binary_sha256=sha(a.binary), command=command, process_exit_code=run.returncode,
                  host_wall_seconds=time.monotonic()-start, simulator_version=built["verilator_version"])
    result["memory_model"] = {
        "kind": "bounded_behavioral_axi_not_soc_ddr",
        "read_extra_wait_cycles": a.read_latency,
        "write_extra_wait_cycles": a.write_latency,
        "earliest_external_read_response_cycles_after_ar": a.read_latency + 1,
        "earliest_external_write_response_cycles_after_last_w": a.write_latency + 1,
        "local_sram_extra_wait_cycles": 1,
        "window_boundary": "excludes start marker W handshake; includes stop marker W handshake",
        "pass_meaning": "CPU completion only; workload CRC/result checks are additionally required",
    }
    a.output.write_text(json.dumps(result, indent=2) + "\n")
    print(run.stdout, end="")
    if run.stderr:
        print(run.stderr, end="")
    print("RESULT", a.output.resolve())
    raise SystemExit(run.returncode)


if __name__ == "__main__":
    main()
