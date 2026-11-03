#!/usr/bin/env python3
"""Plan or compile the real T27 streaming application; never program hardware.

The default is a read-only plan. --build requires the real generated production
assets (full_weights.h, t25_identity.h and tokenizer.nxt) and an RV32 compiler.
The immutable parent receipt supplies every existing arithmetic/backend flag.
--profile baseline preserves its -O2 build. --profile optimized selects -O3
uniformly for the application; it is an A/B candidate, not a measured speedup.
Both profiles keep the same ISA, floating-point semantics and backend choices.
A successful link is a software build result, not model/board qualification.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import shutil
import struct
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
GENERATED = ("full_weights.h", "t25_identity.h", "tokenizer.nxt")
REQUIRED_SYMBOLS = {"main", "nxs_open", "nxs_update", "nxs_finish", "nxs_abort", "nxs_wire", "nxs_timing"}
BUILD_PROFILES = {"baseline": "-O2", "optimized": "-O3"}
TOKENIZER_ASSEMBLY = '''.section .rodata.t25_tokenizer,"a",@progbits
.balign 16
.global t25_tokenizer
.global t25_tokenizer_end
t25_tokenizer:
.incbin "tokenizer.nxt"
t25_tokenizer_end:
'''


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def rewrite_command(receipt, source, output, compiler, profile="baseline", enhancements=False,
                    kv_tail_direct=False, pv_long=False, head_argmax=False):
    """Relocate the recorded link without dropping numerical/backend flags."""
    source, output = Path(source).resolve(), Path(output).resolve()
    original = receipt["argv"]
    if profile not in BUILD_PROFILES:
        raise ValueError("unknown build profile: " + str(profile))
    # The profile is the only owner of optimization flags. Otherwise a late
    # -O0/-Ofast or an inherited LTO switch could make the recorded choice false.
    if [arg for arg in original if arg.startswith("-O")] != ["-O2"]:
        raise ValueError("parent receipt requires exactly one -O2 optimization flag")
    if any(arg.startswith("-flto") or arg == "-fwhole-program" for arg in original):
        raise ValueError("LTO/whole-program optimization is not qualified by these profiles")
    # Optional features have one owner too: the explicit CLI choice. An old
    # receipt must not silently enable, disable or redefine the selected path.
    feature_names = ("NX_T27_SERVICE_ENHANCEMENTS", "NX_PROFILE_INTEGER", "NX_PREFIX_CAPTURE",
                     "NX_KV_TAIL_DIRECT", "NX_PV_LONG", "NX_HEAD_ARGMAX")
    if any(arg == "-D" + name or arg.startswith("-D" + name + "=") or
           arg == "-U" + name for arg in original for name in feature_names):
        raise ValueError("parent receipt contains an explicitly owned optional feature")
    main_suffix = "/firmware/runtime/board/main.c"
    mains = [x for x in original if x.endswith(main_suffix)]
    tokenizers = [x for x in original if x.endswith("/tokenizer.S")]
    if len(mains) != 1 or len(tokenizers) != 1:
        raise ValueError("parent receipt needs exactly one production main and tokenizer.S")
    old_source = mains[0][:-len(main_suffix)]
    old_generated = str(Path(tokenizers[0]).parent)
    command = [str(compiler)]
    after_output = False
    for arg in original[1:]:
        if after_output:
            command.append(str(output / "application.elf"))
            after_output = False
        elif arg == "-o":
            command.append(arg)
            after_output = True
        elif arg.startswith("-Wl,-Map="):
            command.append("-Wl,-Map=" + str(output / "application.map"))
        elif arg.startswith("-ffile-prefix-map="):
            continue
        elif arg == "-O2":
            command.append(BUILD_PROFILES[profile])
        elif arg == old_generated or arg.startswith(old_generated + "/"):
            command.append(str(output) + arg[len(old_generated):])
        elif arg == old_source or arg.startswith(old_source + "/"):
            command.append(str(source) + arg[len(old_source):])
        else:
            command.append(arg)
    if after_output or "-o" not in command:
        raise ValueError("parent receipt has no valid ELF output")
    if any(x.endswith((".o", ".a")) for x in command):
        raise ValueError("fresh build refuses prebuilt object/archive inputs")
    stream = str(source / "firmware/runtime/port/stream.c")
    if stream not in command:
        runtime = str(source / "firmware/runtime/port/runtime.c")
        command.insert(command.index(runtime) + 1, stream)
    if enhancements:
        for relative in ("firmware/runtime/port/prefix.c", "firmware/runtime/port/control.c"):
            path = str(source / relative)
            if path not in command:
                command.insert(command.index(stream) + 1, path)
        command[1:1] = ["-DNX_T27_SERVICE_ENHANCEMENTS=1", "-DNX_PROFILE_INTEGER=1", "-DNX_PREFIX_CAPTURE=1"]
    for selected, name in ((kv_tail_direct, "NX_KV_TAIL_DIRECT"), (pv_long, "NX_PV_LONG"),
                           (head_argmax, "NX_HEAD_ARGMAX")):
        if selected:
            command.insert(1, "-D" + name + "=1")
    command[1:1] = [f"-ffile-prefix-map={source}=.", f"-ffile-prefix-map={output}=."]
    if any(old_source in x or old_generated in x for x in command):
        # Building from the exact historical path is valid as well.
        unresolved = [x for x in command if (old_source in x and str(source) != old_source)
                      or (old_generated in x and str(output) != old_generated)]
        if unresolved:
            raise ValueError("unrelocated historical paths: " + repr(unresolved))
    required = {"-DNX_PV_SHARED=1", "-DT27_M4_HANDOFF=1", "-DNX_OPT07_DEFAULT=0",
                "-DNX_T25_CE64", "-DNX_CE_BOARD_BOOT", "-march=rv32imf_zicsr_zifencei",
                "-mabi=ilp32f", "-ffp-contract=off", "-fno-fast-math"}
    if not required <= set(command):
        raise ValueError("parent receipt does not carry this T27 production contract")
    # Presence alone is insufficient: GCC accepts the last conflicting option.
    # Refuse an ambiguous receipt instead of silently changing model arithmetic.
    singleton_prefixes = ("-march=", "-mabi=", "-ffp-contract=",
                          "-DNX_PV_SHARED=", "-DT27_M4_HANDOFF=",
                          "-DNX_OPT07_DEFAULT=")
    for prefix in singleton_prefixes:
        values = [arg for arg in command if arg.startswith(prefix)]
        if len(values) != 1 or values[0] not in required:
            raise ValueError("conflicting production option: " + prefix)
    unsafe_math = {"-ffast-math", "-funsafe-math-optimizations", "-fassociative-math",
                   "-freciprocal-math", "-ffinite-math-only", "-fno-signed-zeros"}
    if unsafe_math.intersection(command):
        raise ValueError("profile refuses options that relax the floating-point contract")
    return command


def runtime_identity(source, command, compiler_hash):
    """Bind in-process KV reuse to the actual sources, options and compiler.

    No address/short text key substitutes for these digests. Reset/reload or
    any execution-config change invalidates runtime KV independently.
    """
    source = Path(source)
    def files_under(folders):
        return {str(p.relative_to(source)): sha256(p) for folder in folders
                for p in sorted((source / folder).rglob("*"))
                if p.is_file() and p.suffix in (".c", ".h", ".S", ".sv", ".v")}
    def digest(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    flags = [arg for arg in command if arg.startswith("-") and not arg.startswith(("-ffile-prefix-map=", "-Wl,-Map="))]
    identities = {
        # Both message framing and the selected system prompt determine the
        # reusable token prefix. Bind the action prompt and selection logic
        # explicitly; an old generated identity header must not be reused.
        "T27_TEMPLATE_SHA256": digest({
            "template_sources": {name: sha256(source / name) for name in (
                "firmware/runtime/port/tokenizer.c",
                "firmware/runtime/board/led_control.c",
                "firmware/runtime/board/service_options.h")},
            "prefix_contract": 3}),
        "T27_NUMERIC_SHA256": digest({"sources": files_under(("firmware/runtime/reference", "firmware/runtime/port")), "flags": flags, "compiler_sha256": compiler_hash}),
        "T27_BACKEND_SHA256": digest({"sources": files_under(("firmware/drivers", "rtl", "firmware/runtime/board", "board", "t27/cpu")), "flags": flags, "prefill_rows": 4}),
    }
    header = "/* Generated from this build's actual source inventory and options. */\n"
    header += "".join(f'#define {name} "{value}"\n' for name, value in identities.items())
    return identities, header


def profile_record(command, profile):
    """Record the applied options, separately from paths and generated assets."""
    flags = [arg for arg in command[1:]
             if arg.startswith("-") and arg not in ("-I", "-T", "-o")
             and not arg.startswith(("-ffile-prefix-map=", "-Wl,-Map="))]
    encoded = json.dumps(flags, separators=(",", ":")).encode()
    return {"name": profile, "optimization_flag": BUILD_PROFILES[profile],
            "lto": False, "effective_flags": flags,
            "effective_flags_sha256": hashlib.sha256(encoded).hexdigest(),
            "performance_status": "NOT_MEASURED_BY_BUILD_TOOL",
            "comparison_requirement": "same source/assets/compiler/platform; compare target latency and results"}


def asset_check(generated, source):
    """Check genuine supplied identities; do not create substitute weights."""
    generated, source = Path(generated), Path(source)
    missing = [str(generated / name) for name in GENERATED if not (generated / name).is_file()]
    if missing:
        return {"missing": missing, "errors": [], "identities": {}}
    identities = {name: sha256(generated / name) for name in GENERATED}
    header = (generated / "t25_identity.h").read_text()
    values = {}
    errors = []
    for macro in ("T25_MODEL_SHA256", "T25_TOKENIZER_SHA256"):
        match = re.search(r'^\s*#\s*define\s+' + macro + r'\s+"([0-9a-fA-F]{64})"\s*$', header, re.M)
        if not match:
            errors.append("missing literal identity macro " + macro)
        else:
            values[macro] = match[1].lower()
    if values.get("T25_TOKENIZER_SHA256") != identities["tokenizer.nxt"]:
        errors.append("tokenizer.nxt SHA256 differs from T25_TOKENIZER_SHA256")
    manifest = source / "docs/spec/model-pack-v1-manifest.json"
    if not manifest.is_file():
        errors.append("missing pinned model manifest " + str(manifest))
    elif values.get("T25_MODEL_SHA256") != json.loads(manifest.read_text())["sha256"]:
        errors.append("T25_MODEL_SHA256 differs from the candidate pinned model manifest")
    data = (generated / "tokenizer.nxt").read_bytes()
    if len(data) < 128 or struct.unpack_from("<3I", data) != (0x31544b4e, 1, len(data)):
        errors.append("tokenizer.nxt does not have a complete NKT1 v1 header")
    if len(data) > 5630976:
        errors.append("tokenizer.nxt exceeds the existing derived index budget")
    return {"missing": [], "errors": errors, "identities": identities, "declared": values}


def elf_symbols(data):
    """Read defined ELF32 symbols without requiring host objdump support."""
    shoff = struct.unpack_from("<I", data, 32)[0]
    entsize, count = struct.unpack_from("<HH", data, 46)
    if entsize != 40 or not count or shoff + count * entsize > len(data):
        raise ValueError("missing/truncated ELF32 section table")
    sections = [struct.unpack_from("<10I", data, shoff + i * entsize) for i in range(count)]
    names = set()
    for section in sections:
        if section[1] != 2:  # SHT_SYMTAB
            continue
        _, _, _, _, offset, size, link, _, _, symsize = section
        if link >= count or symsize != 16 or size % symsize or offset + size > len(data):
            raise ValueError("invalid ELF32 symbol table")
        strings = sections[link]
        if strings[4] + strings[5] > len(data):
            raise ValueError("truncated ELF32 string table")
        table = data[strings[4]:strings[4] + strings[5]]
        for pos in range(offset, offset + size, symsize):
            name, _, _, _, _, defined = struct.unpack_from("<IIIBBH", data, pos)
            if defined and name < len(table):
                end = table.find(b"\0", name)
                if end < 0:
                    raise ValueError("unterminated ELF32 symbol name")
                names.add(table[name:end].decode("ascii", errors="strict"))
    return names


def inspect_application(path, source=ROOT):
    # Reuse the project's bounded ELF loader parser rather than trusting objcopy.
    parser = runpy.run_path(str(Path(source) / "tests/models/prepare_image.py"))["parse_elf"]
    data = Path(path).read_bytes()
    entry, segments, flags = parser(data, base=0xb4000000, capacity=8 * 1024 * 1024)
    if entry != 0xb4000000 or flags != 2 or len(segments) != 1 or segments[0].address != entry:
        raise ValueError("requires one PT_LOAD at 0xb4000000 and exact ILP32F ELF flags")
    names = elf_symbols(data)
    if not REQUIRED_SYMBOLS <= names:
        raise ValueError("production streaming symbols absent: " + repr(sorted(REQUIRED_SYMBOLS - names)))
    segment = segments[0]
    return segment.data, {"entry": entry, "elf_flags": flags, "pt_load_count": len(segments),
                          "file_bytes": len(segment.data), "memory_bytes": segment.memory_size,
                          "streaming_symbols": sorted(REQUIRED_SYMBOLS)}


def source_inventory(source):
    files = {}
    for folder in ("firmware", "software/include"):
        for path in sorted((Path(source) / folder).rglob("*")):
            if path.is_file() and path.suffix in (".c", ".h", ".S", ".ld"):
                files[str(path.relative_to(source))] = sha256(path)
    files["docs/spec/model-pack-v1-manifest.json"] = sha256(Path(source) / "docs/spec/model-pack-v1-manifest.json")
    return files


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generated", type=Path, required=True, help="directory containing real production headers and tokenizer.nxt")
    parser.add_argument("--output", type=Path, required=True, help="new directory; existing output is never overwritten")
    parser.add_argument("--source", type=Path, default=ROOT)
    parser.add_argument("--baseline-receipt", type=Path, default=ROOT.parent / "context/PRODUCTION_COMPILE.json")
    parser.add_argument("--cc", default="riscv32-unknown-elf-gcc")
    parser.add_argument("--profile", choices=tuple(BUILD_PROFILES), default="baseline",
                        help="baseline: parent -O2; optimized: -O3 A/B candidate, same numerical contract")
    parser.add_argument("--require-baseline-compiler", action="store_true", help="require the exact compiler SHA from the immutable parent receipt")
    parser.add_argument("--service-enhancements", action="store_true", help="enable exact prefix reuse, integer profiling and session-bound cancellation")
    parser.add_argument("--kv-tail-direct", action="store_true", help="enable leased direct K/V tail output")
    parser.add_argument("--pv-long", action="store_true", help="enable capability-gated long-context PV")
    parser.add_argument("--head-argmax", action="store_true", help="enable capability-gated head token selection")
    parser.add_argument("--all-enhancements", action="store_true", help="enable service, K/V tail, long PV and head argmax together")
    parser.add_argument("--timeout", type=int, default=120)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--build", action="store_true", help="execute the application link after all input checks")
    mode.add_argument("--dry-run", action="store_true", help="print the build plan only (the default)")
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    features = {name: bool(getattr(args, name) or args.all_enhancements)
                for name in ("service_enhancements", "kv_tail_direct", "pv_long", "head_argmax")}
    source, generated, output = args.source.resolve(), args.generated.resolve(), args.output.resolve()
    try:
        baseline = json.loads(args.baseline_receipt.read_text())
        compiler = shutil.which(args.cc)
        command = rewrite_command(baseline, source, output, compiler or args.cc, args.profile,
                                  *features.values())
        assets = asset_check(generated, source)
        missing_sources = [x for x in command if x.endswith((".c", ".ld", ".S"))
                           and x != str(output / "tokenizer.S") and not Path(x).is_file()]
        compiler_hash = sha256(compiler) if compiler else None
        identities, identity_header = runtime_identity(source, command, compiler_hash) if features["service_enhancements"] else ({}, "")
        compiler_matches = bool(compiler_hash and compiler_hash == baseline.get("compiler_sha256"))
        errors = list(assets["errors"])
        if args.require_baseline_compiler and compiler and not compiler_matches:
            errors.append("selected compiler differs from the baseline compiler SHA256")
        if output.exists():
            errors.append("output already exists; choose a new build directory")
        plan = {"schema": 1, "status": "PLAN_ONLY", "build_executed": False,
                "programming_performed": False, "source": str(source), "generated": str(generated),
                "output": str(output), "argv": command, "cwd": str(output),
                "build_profile": profile_record(command, args.profile),
                "service_enhancements": features["service_enhancements"], "features": features,
                "runtime_identities": identities,
                "baseline_receipt_sha256": sha256(args.baseline_receipt),
                "baseline_source_content_id": baseline.get("source_content_id"),
                "compiler_sha256": compiler_hash, "compiler_matches_baseline": compiler_matches,
                "missing": assets["missing"] + missing_sources + ([] if compiler else ["compiler: " + args.cc]),
                "errors": errors, "assets": assets,
                "deployment_status": "NOT_DEPLOYABLE: requires matching trusted-loader ROM, SD image and candidate qualification"}
        if not args.build:
            print(json.dumps(plan, indent=2, ensure_ascii=False))
            return 0
        if plan["missing"] or plan["errors"]:
            plan["status"] = "BUILD_BLOCKED_MISSING_OR_INVALID_INPUTS"
            print(json.dumps(plan, indent=2, ensure_ascii=False))
            return 2
        output.mkdir(parents=True, exist_ok=False)
        for name in GENERATED:
            shutil.copy2(generated / name, output / name)
        (output / "tokenizer.S").write_text(TOKENIZER_ASSEMBLY)
        if features["service_enhancements"]:
            (output / "t27_runtime_identity.h").write_text(identity_header)
            plan["runtime_identity_header_sha256"] = sha256(output / "t27_runtime_identity.h")
        plan["build_input_inventory"] = source_inventory(source)
        plan["build_input_inventory_sha256"] = hashlib.sha256(json.dumps(plan["build_input_inventory"], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        plan["tokenizer_assembly_sha256"] = sha256(output / "tokenizer.S")
        plan["build_executed"] = True
        start = time.monotonic()
        try:
            with (output / "compile.log").open("wb") as log:
                result = subprocess.run(command, cwd=output, stdout=log, stderr=subprocess.STDOUT, timeout=args.timeout, check=False)
            plan["exit_code"] = result.returncode
            if result.returncode:
                raise ValueError("compiler failed; see compile.log")
            binary, details = inspect_application(output / "application.elf", source)
            (output / "application.bin").write_bytes(binary)
            plan.update(status="APPLICATION_BUILD_PASS_NOT_BOARD_QUALIFIED", elf=details,
                        elf_sha256=sha256(output / "application.elf"),
                        application_bin_sha256=sha256(output / "application.bin"))
            # This is an identity report only. It does not mutate trusted.h or ROM.
            plan["required_new_trusted_app_sha256"] = plan["application_bin_sha256"]
            if source_inventory(source) != plan["build_input_inventory"]:
                raise ValueError("source changed during build; discard this candidate")
            if any(sha256(output / name) != assets["identities"][name] for name in GENERATED):
                raise ValueError("generated assets changed during build; discard this candidate")
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            plan.update(status="APPLICATION_BUILD_FAILED", failure=str(exc))
        plan["wall_seconds"] = time.monotonic() - start
        (output / "BUILD_RESULT.json").write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n")
        print(json.dumps({k: v for k, v in plan.items() if k != "build_input_inventory"}, indent=2, ensure_ascii=False))
        return 0 if plan["status"] == "APPLICATION_BUILD_PASS_NOT_BOARD_QUALIFIED" else 1
    except (OSError, ValueError, KeyError) as exc:
        print("BUILD_INPUT_ERROR: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
