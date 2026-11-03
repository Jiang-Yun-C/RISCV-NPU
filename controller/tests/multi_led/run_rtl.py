#!/usr/bin/env python3
"""Simulate the actual LED-bank peripheral and physical-top display selector.

No FPGA tool, programming, external port, physical DUT or prerecorded response is used.
Both existing local-read configurations must pass. The outer vendor DDR/PLL
top is parsed as a source for its real selector, not elaborated as a full board.
"""
import argparse
import hashlib
import json
import importlib.metadata
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SOURCES = [
    "rtl/interfaces/axi4_if.sv", "rtl/soc/t03_uart_tx.sv", "rtl/soc/t17_uart.sv",
    "rtl/ce64/nx_ce64_local.sv", "board/mes2l676-200hp/led_native_top.v",
    "tests/multi_led/tb_bank.sv",
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verilator", default="verilator")
    parser.add_argument("--make-flags", help="Optional flags for the local simulator C++ build")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = {"status": "RUNNING", "scope": "actual production local RTL + actual display mux digital simulation",
              "sources": {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in SOURCES},
              "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "simulator": subprocess.check_output([args.verilator, "--version"], text=True).strip(),
              "cases": [], "hardware_actions": 0, "full_board_simulation": "NOT_RUN",
              "place_route": "NOT_RUN", "bitstream": "NOT_RUN", "physical_led": "NOT_OBSERVED"}
    try:
        report["python_verilator_package"] = importlib.metadata.version("verilator")
    except importlib.metadata.PackageNotFoundError:
        pass
    report["commands"] = []
    for fast in (0, 1):
        command = [args.verilator, "--binary", "--timing", "--assert", "-j", "2", "-Wno-fatal",
                   "--top-module", "tb_bank", "-GFAST=" + str(fast),
                   "--Mdir", str(output / ("obj" + str(fast)))] + [str(ROOT / p) for p in SOURCES]
        if args.make_flags:
            command += ["-MAKEFLAGS", args.make_flags]
        report["commands"].append(command)
        with (output / ("build" + str(fast) + ".log")).open("w") as log:
            build = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=120)
        if build.returncode:
            report.update(status="BUILD_FAILED", failed_configuration=fast)
            break
        run = subprocess.run([str(output / ("obj" + str(fast)) / "Vtb_bank")],
                             cwd=output, capture_output=True, text=True, timeout=30)
        (output / ("run" + str(fast) + ".log")).write_text(run.stdout + run.stderr)
        print(run.stdout, end="")
        records = [json.loads(line[7:]) for line in run.stdout.splitlines() if line.startswith("RESULT ")]
        if run.returncode or len(records) != 1 or records[0].get("status") != "PASS":
            report.update(status="SIMULATION_FAILED", failed_configuration=fast)
            break
        report["cases"].append(records[0])
    else:
        report["status"] = "PASS"
    report["inputs_stable"] = report["sources"] == {
        p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in SOURCES}
    if not report["inputs_stable"]:
        report["status"] = "SOURCE_CHANGED_DURING_RUN"
    (output / "RESULT.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "sources"}, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
