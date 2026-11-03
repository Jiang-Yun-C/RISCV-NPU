#!/usr/bin/env python3
"""Plan/build the responsiveness candidate from the current deployed receipt.

Default: read-only plan. --build links a new application with the original
ISA, -O3, floating-point contract and backend switches. It never accesses a
board, writes media, rebuilds an FPGA bitstream or changes trusted-loader ROM.
The resulting application still needs a matching authenticated deployment.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

import build_t27_streaming as common

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT.parent.parent
BASELINE = PACKAGE / "reference_repo/evidence/T27/t27-led-control-20261031-v2/application-r2"
BASELINE_CID = "5006443a81b3c9cf547b9f5008c32d2c6345392d94a11af98ea2d331356129bf"
MACROS = {
    "NX_HEAD_ARGMAX": "1", "NX_PV_LONG": "1", "NX_KV_TAIL_DIRECT": "1",
    "NX_T27_SERVICE_ENHANCEMENTS": "1", "NX_PROFILE_INTEGER": "1",
    "NX_PREFIX_CAPTURE": "1", "NX_PV_SHARED": "1", "T27_M4_HANDOFF": "1",
    "NX_OPT07_DEFAULT": "0",
}


def inventory(source):
    """Same relative-path/SHA256 content-ID convention as the frozen source."""
    return {p.relative_to(source).as_posix(): common.sha256(p)
            for p in sorted(source.rglob("*")) if p.is_file()
            and not any(part in (".git", ".pytest_cache", "__pycache__")
                        for part in p.relative_to(source).parts)
            and p.suffix != ".pyc"}


def content_id(files):
    return hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def relocate(receipt, source, output, compiler, multi_led=False):
    original = receipt["argv"]
    if receipt.get("source_content_id") != BASELINE_CID:
        raise ValueError("receipt is not the packaged current deployed candidate")
    expected = {
        "-march=": "-march=rv32imf_zicsr_zifencei", "-mabi=": "-mabi=ilp32f",
        "-O": "-O3", "-ffp-contract=": "-ffp-contract=off",
    }
    for prefix, value in expected.items():
        if [arg for arg in original if arg.startswith(prefix)] != [value]:
            raise ValueError("unexpected/conflicting production option " + prefix)
    for name, value in MACROS.items():
        declarations = [a for a in original if a == "-D" + name or a == "-U" + name
                        or a.startswith("-D" + name + "=")]
        if declarations != ["-D" + name + "=" + value]:
            raise ValueError("unexpected/conflicting production macro " + name)
    required = {"-fno-fast-math", "-fno-strict-aliasing", "-DNX_PORTABLE", "-DHARD_FLOAT",
                "-DNX_T25_CE64", "-DNX_CE_BOARD_BOOT", "-include"}
    if not required.issubset(original):
        raise ValueError("current production contract is incomplete")
    unsafe = {"-ffast-math", "-funsafe-math-optimizations", "-fassociative-math",
              "-freciprocal-math", "-ffinite-math-only", "-fno-signed-zeros"}
    if unsafe.intersection(original) or any(a.startswith("-flto") for a in original):
        raise ValueError("unqualified arithmetic/LTO option in receipt")
    if any(a.endswith((".o", ".a")) for a in original):
        raise ValueError("fresh candidate refuses inherited object/archive files")
    if any(a == "-DNX_LED_BANK" or a.startswith("-DNX_LED_BANK=") or a == "-UNX_LED_BANK" for a in original):
        raise ValueError("the --multi-led option exclusively owns NX_LED_BANK")
    suffix = "/firmware/runtime/board/main.c"
    mains = [a for a in original if a.endswith(suffix)]
    tables = [a for a in original if a.endswith("/tokenizer.S")]
    if len(mains) != 1 or len(tables) != 1 or original.count("-o") != 1:
        raise ValueError("ambiguous production sources/output")
    old_source, old_generated = mains[0][:-len(suffix)], str(Path(tables[0]).parent)
    command = [str(compiler)]
    next_output = False
    for arg in original[1:]:
        if next_output:
            command.append(str(output / "application.elf")); next_output = False
        elif arg == "-o":
            command.append(arg); next_output = True
        elif arg.startswith("-ffile-prefix-map="):
            continue
        elif arg.startswith("-Wl,-Map="):
            command.append("-Wl,-Map=" + str(output / "application.map"))
        elif arg == old_generated or arg.startswith(old_generated + "/"):
            command.append(str(output) + arg[len(old_generated):])
        elif arg == old_source or arg.startswith(old_source + "/"):
            command.append(str(source) + arg[len(old_source):])
        else:
            command.append(arg)
    command.insert(1,"-DNX_APP_IRQ=1")
    command.insert(command.index("-lgcc"),str(source/"firmware/runtime/board/irq_events.c"))
    if next_output:
        raise ValueError("missing output path")
    command[1:1] = [f"-ffile-prefix-map={source}=.", f"-ffile-prefix-map={output}=."]
    if multi_led:
        command.insert(1, "-DNX_LED_BANK=1")
    unresolved = [a for a in command if (old_source in a and str(source) != old_source)
                  or (old_generated in a and str(output) != old_generated)]
    if unresolved:
        raise ValueError("unrelocated historical paths: " + repr(unresolved))
    return command


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT)
    parser.add_argument("--receipt", type=Path, default=BASELINE / "compile.COMMAND.json")
    parser.add_argument("--generated", type=Path, default=BASELINE)
    parser.add_argument("--output", type=Path, required=True, help="new directory outside source/generated trees")
    parser.add_argument("--cc", default="riscv32-unknown-elf-gcc")
    parser.add_argument("--multi-led", action="store_true",
                        help="enable the four-LED bank; requires the matching NEW FPGA bitstream")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--build", action="store_true", help="compile/link only; no hardware or media actions")
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    try:
        source, generated, output = args.source.resolve(), args.generated.resolve(), args.output.resolve()
        if output == source or source in output.parents or output == generated or generated in output.parents:
            raise ValueError("output must be outside source/generated trees")
        receipt = json.loads(args.receipt.read_text())
        compiler = shutil.which(args.cc)
        command = relocate(receipt, source, output, compiler or args.cc, args.multi_led)
        assets = common.asset_check(generated, source)
        files = inventory(source); cid = content_id(files)
        compiler_hash = common.sha256(compiler) if compiler else None
        identities, header = common.runtime_identity(source, command, compiler_hash)
        missing_sources = [a for a in command if a.endswith((".c", ".h", ".ld", ".S"))
                           and a != str(output / "tokenizer.S") and not Path(a).is_file()]
        plan = {"status": "PLAN_ONLY", "build_executed": False, "hardware_actions": 0,
                "source_content_id": cid, "baseline_source_content_id": BASELINE_CID,
                "source_files": len(files), "source": str(source), "output": str(output),
                "multi_led": args.multi_led,
                "hardware_requirement": ("NEW_LED_BANK_RTL_AND_BITSTREAM_REQUIRED" if args.multi_led
                                         else "existing_LED0_interface; no bank register access"),
                "argv": command, "cwd": str(output), "compiler_sha256": compiler_hash,
                "receipt_sha256": common.sha256(args.receipt), "runtime_identities": identities,
                "assets": assets, "missing": assets["missing"] + missing_sources
                + ([] if compiler else ["compiler: " + args.cc]),
                "errors": list(assets["errors"]) + (["output already exists"] if output.exists() else []),
                "deployment_status": "NOT_DEPLOYED; new app hash requires matching trusted-loader ROM and SD image",
                "performance_status": "NO_NEW_BOARD_MEASUREMENT"}
        if not args.build:
            print(json.dumps(plan, indent=2, ensure_ascii=False)); return 0
        if plan["missing"] or plan["errors"]:
            plan["status"] = "BUILD_BLOCKED_MISSING_OR_INVALID_INPUTS"
            print(json.dumps(plan, indent=2, ensure_ascii=False)); return 2
        output.mkdir(parents=True, exist_ok=False)
        for name in common.GENERATED:
            shutil.copy2(generated / name, output / name)
        (output / "tokenizer.S").write_text(common.TOKENIZER_ASSEMBLY)
        (output / "t27_runtime_identity.h").write_text(header)
        (output / "diag_identity.h").write_text('#define NX_DIAG_CID "' + cid + '"\n')
        plan["generated_headers"] = {name: common.sha256(output / name)
                                     for name in ("t27_runtime_identity.h", "diag_identity.h")}
        plan["build_input_inventory"] = files
        plan["build_executed"] = True
        start = time.monotonic()
        try:
            with (output / "compile.log").open("wb") as log:
                result = subprocess.run(command, cwd=output, stdout=log, stderr=subprocess.STDOUT,
                                        timeout=args.timeout, check=False)
            plan["exit_code"] = result.returncode
            if result.returncode:
                raise ValueError("compiler failed; see compile.log")
            binary, elf = common.inspect_application(output / "application.elf", source)
            if inventory(source) != files:
                raise ValueError("source changed during build; discard candidate")
            if any(common.sha256(output / name) != assets["identities"][name] for name in common.GENERATED):
                raise ValueError("assets changed during build; discard candidate")
            (output / "application.bin").write_bytes(binary)
            plan.update(status="APPLICATION_BUILD_PASS_NOT_BOARD_QUALIFIED", elf=elf,
                        elf_sha256=common.sha256(output / "application.elf"),
                        application_bin_sha256=common.sha256(output / "application.bin"),
                        required_new_trusted_app_sha256=common.sha256(output / "application.bin"))
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            plan.update(status="APPLICATION_BUILD_FAILED", failure=str(exc))
        plan["wall_seconds"] = time.monotonic() - start
        (output / "BUILD_RESULT.json").write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n")
        print(json.dumps({k: v for k, v in plan.items() if k != "build_input_inventory"}, indent=2, ensure_ascii=False))
        return 0 if plan["status"] == "APPLICATION_BUILD_PASS_NOT_BOARD_QUALIFIED" else 1
    except (OSError, ValueError, KeyError) as exc:
        print("BUILD_INPUT_ERROR: " + str(exc), file=sys.stderr); return 2


if __name__ == "__main__":
    raise SystemExit(main())
