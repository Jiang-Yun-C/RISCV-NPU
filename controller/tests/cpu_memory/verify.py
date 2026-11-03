#!/usr/bin/env python3
"""Differential native evidence for bounded CPU-memory changes.

Compile the immutable baseline and candidate source independently with strict
floating-point flags. Full-width operator probes are separate from the existing
small two-layer production-main fixture. No result is a board speedup or a
24-layer production-model qualification. --benchmark is optional and native only.
"""
import argparse
import ctypes as C
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import statistics
import subprocess
import time

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
REFERENCE = Path("firmware/runtime/reference/nx_reference.c")
COMMON = ["-std=c11", "-fno-strict-aliasing", "-ffp-contract=off", "-fno-fast-math",
          "-ffreestanding", "-fno-builtin", "-Wall", "-Wextra", "-Werror",
          "-Wno-misleading-indentation", "-Wno-unknown-pragmas", "-DNX_PORTABLE"]
VOCAB = 151936


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(command, **kwargs):
    result = subprocess.run(command, capture_output=True, check=True, timeout=60, **kwargs)
    return result


def build_probe(root, output, label, optimization, commands):
    target = output / (label + ".so")
    command = ["gcc", *COMMON, optimization, "-shared", "-fPIC", "-Wl,-Bsymbolic",
               '-DNX_REFERENCE_SOURCE="' + str(root / REFERENCE) + '"',
               "-I", str(root / "firmware/runtime/reference"), str(HERE / "probe.c"),
               "-lm", "-o", str(target)]
    run(command);commands.append(command)
    lib = C.CDLL(str(target))
    lib.memory_attention_probe.argtypes = [C.c_void_p] * 4 + [C.c_int] * 3 + [C.c_void_p]
    lib.memory_attention_probe.restype = C.c_int
    lib.memory_greedy_probe.argtypes = [C.c_void_p] * 3
    lib.memory_greedy_probe.restype = C.c_int
    lib.memory_greedy_repeat.argtypes = [C.c_void_p, C.c_uint]
    lib.memory_greedy_repeat.restype = C.c_uint64
    return label, lib


def check_greedy(libs):
    rng = np.random.default_rng(20261028)
    cases = []
    normal = rng.standard_normal(VOCAB).astype("<f4")
    cases.append(("random", normal, int(normal.argmax())))
    for label, values in (("increasing", np.arange(VOCAB, dtype="<f4")),
                          ("decreasing", -np.arange(VOCAB, dtype="<f4")),
                          ("all-negative", -np.abs(normal) - np.float32(1))):
        cases.append((label, values, int(values.argmax())))
    for label, zero in (("positive-zero", 0x00000000), ("negative-zero", 0x80000000)):
        values = np.full(VOCAB, zero, dtype="<u4").view("<f4")
        values.view("<u4")[1::2] ^= np.uint32(0x80000000)
        cases.append((label, values, 0))
    values = np.full(VOCAB, -1, dtype="<f4")
    values[[7, 511, VOCAB - 1]] = np.float32(42)
    cases.append(("first-tie", values, 7))
    values = np.zeros(VOCAB, dtype="<f4")
    values.view("<u4")[VOCAB // 2] = 1
    values.view("<u4")[VOCAB // 2 + 1] = 0x80000001
    cases.append(("subnormal", values, VOCAB // 2))
    values = np.full(VOCAB, -np.finfo(np.float32).max, dtype="<f4")
    values[13] = np.finfo(np.float32).max
    cases.append(("finite-extremes", values, 13))
    for seed in (1, 19, 991):
        bits = np.random.default_rng(seed).integers(0, 2**32, VOCAB, dtype="<u4")
        # Turn every nonfinite exponent into a finite one; retain sign/mantissa.
        bits[(bits & 0x7f800000) == 0x7f800000] ^= np.uint32(0x00800000)
        values = bits.view("<f4")
        cases.append((f"finite-bits-{seed}", values, int(values.argmax())))
    for label, bad in (("qnan", 0x7fc00123), ("snan", 0x7f800123),
                       ("positive-inf", 0x7f800000), ("negative-inf", 0xff800000)):
        for position in (0, 1, VOCAB // 2, VOCAB - 1):
            values = normal.copy()
            values[3] = np.finfo(np.float32).max
            values.view("<u4")[position] = bad
            cases.append((f"{label}-at-{position}", values, None))
    results = []
    for name, values, expected in cases:
        original = values.tobytes();observed = []
        for label, lib in libs:
            token = C.c_int32(-1234567);flags = C.c_int(-1)
            rc = lib.memory_greedy_probe(values.ctypes.data, C.byref(token), C.byref(flags))
            observed.append((rc, token.value, flags.value))
            assert values.tobytes() == original, (name, label, "input mutation")
            assert rc == (0 if expected is not None else -2), (name, label, rc)
            assert token.value == (expected if expected is not None else -1234567), (name, label, token.value)
        assert all(x == observed[0] for x in observed), (name, observed)
        results.append({"case": name, "status": observed[0][0], "token": observed[0][1],
                        "fp_exceptions": observed[0][2]})
    # Preserve null argument rejection, and allow a token destination alias that
    # is untouched until validation/selection completes (no restrict contract).
    for name, mode in (("null-logits", 0), ("null-token", 1), ("both-null", 2)):
        for label, lib in libs:
            token = C.c_int32(-1234567);flags = C.c_int(-1)
            rc = lib.memory_greedy_probe(None if mode != 1 else normal.ctypes.data,
                                        None if mode != 0 else C.byref(token), C.byref(flags))
            assert rc == -1 and token.value == -1234567, (name, label)
        results.append({"case": name, "status": -1})
    for invalid in (False, True):
        observations = []
        for label, lib in libs:
            values = normal.copy()
            if invalid:values.view("<u4")[-1] = 0x7fc01234
            original = values.copy();flags = C.c_int()
            rc = lib.memory_greedy_probe(values.ctypes.data, values.ctypes.data + 17 * 4,
                                        C.byref(flags))
            expected = original.copy()
            if not invalid:expected.view("<i4")[17] = int(original.argmax())
            assert values.tobytes() == expected.tobytes(), ("alias", invalid, label)
            observations.append((rc, values.tobytes(), flags.value))
        assert all(x == observations[0] for x in observations)
        results.append({"case": "alias-error" if invalid else "alias-success",
                        "status": observations[0][0]})
    return results


def check_attention(libs):
    rng = np.random.default_rng(20261028)
    qbase = rng.standard_normal((4, 896)).astype("<f4")
    kbase = rng.standard_normal((640, 128)).astype("<f4")
    vbase = rng.standard_normal((640, 128)).astype("<f4")
    results = [];words = 0

    def case(total, rows, kind, mode):
        nonlocal words
        q = qbase[:rows].copy();k = kbase.copy();v = vbase.copy()
        if kind == "large":q *= np.float32(32);k *= np.float32(32)
        elif kind == "signed-zero":
            q.fill(0);k.fill(0);v.view("<u4")[::2] = 0x80000000;v[1::2] = 0
        elif kind == "subnormal":
            q.view("<u4")[:] = 1;k.fill(1);v.view("<u4")[:] = 0x80000001
        elif kind == "qnan-Q":q.view("<u4")[0, 0] = 0x7fc00123
        elif kind == "snan-Q":q.view("<u4")[0, 0] = 0x7f800123
        elif kind == "infinite-K":k[0, 0] = np.inf
        elif kind == "nan-V":v.view("<u4")[0, 0] = 0x7fc00123
        elif kind == "finite-overflow":q.fill(np.finfo("f4").max);k.fill(np.finfo("f4").max)
        # Every causal boundary must ignore future KV. These are intentionally
        # NaNs so an accidental over-read changes the valid/error result.
        k[total:] = np.nan;v[total:] = np.nan
        originals = [a.tobytes() for a in (q, k, v)]
        observed = []
        for label, lib in libs:
            storage = np.full(rows * 896 + 16, 0x7fc07777, dtype="<u4")
            out = storage[8:-8].view("<f4");metadata = np.zeros(3, dtype="<u8")
            rc = lib.memory_attention_probe(q.ctypes.data, k.ctypes.data, v.ctypes.data,
                                             out.ctypes.data, rows, total - rows, mode,
                                             metadata.ctypes.data)
            assert np.all(storage[:8] == 0x7fc07777) and np.all(storage[-8:] == 0x7fc07777), (label, "guard")
            assert [a.tobytes() for a in (q, k, v)] == originals, (label, "input mutation")
            observed.append((rc, out.tobytes(), tuple(int(x) for x in metadata)))
        name = f"len{total}-m{rows}-{kind}-pv{mode}"
        for value in observed[1:]:
            assert value[0] == observed[0][0], (name, "status")
            assert value[2] == observed[0][2], (name, "PV handoff or FP exceptions")
            if value[0] == 0:assert value[1] == observed[0][1], (name, "FP32 bits")
        if mode in (0, 1, 2) and kind in ("normal", "large", "signed-zero", "subnormal"):
            assert observed[0][0] == 0, (name, "unexpected failure")
        if kind in ("qnan-Q", "snan-Q", "infinite-K", "nan-V", "finite-overflow"):
            assert observed[0][0] != 0, (name, "missing numeric failure")
        if mode in (3, 4) and total <= 64:
            assert observed[0][0] == (-4 if mode == 3 else -2), (name, "callback failure")
        if mode and total - rows + 1 > 64:
            assert observed[0][2][0] == 0, (name, "PV eligibility")
        if observed[0][0] == 0:words += rows * 896
        results.append({"case": name, "status": observed[0][0],
                        "pv_calls": observed[0][2][0], "fp_exceptions": observed[0][2][2]})

    # Cache/GQA grouping, pair-tree and hardware-PV eligibility boundaries;
    # cached softmax and the >512 fallback are both exercised at full D64.
    for total in (1, 2, 3, 4, 31, 32, 33, 45, 63, 64, 65, 127, 128, 129,
                  255, 256, 257, 511, 512, 513, 640):
        for rows in (1, 2, 3, 4):
            if rows > total:continue
            for kind in ("normal", "large", "signed-zero"):
                case(total, rows, kind, 0)
    for total in (32, 33, 63, 64, 65):
        for rows in (1, 4):
            for mode in (1, 2, 3, 4):case(total, rows, "normal", mode)
    for total in (1, 33, 64, 65, 513):
        for kind in ("subnormal", "qnan-Q", "snan-Q", "infinite-K", "nan-V", "finite-overflow"):
            case(total, 1, kind, 0)
    return {"cases": results, "valid_fp32_output_words_per_candidate": words,
            "scope": "native full-width D64 attention; host PV callback verifies handoff, not CE64"}


def build_model(root, output, assets, label, optimization, commands):
    target = output / (label + "-model")
    common_files = ["firmware/runtime/port/runtime.c", "firmware/runtime/port/model.c",
                    "firmware/runtime/port/tokenizer.c", "firmware/runtime/port/stream.c",
                    str(REFERENCE)]
    command = ["gcc", *COMMON, optimization, "-DNX_OPT13_TEST", "-DNX_T25_UART",
               "-DNX_T25_SERVICE_TEST", '-DNX_PRODUCTION_MAIN="' +
               str(root / "firmware/runtime/board/main.c") + '"',
               "-I", str(assets), "-I", str(root / "firmware/runtime/port"),
               "-I", str(root / "firmware/runtime/reference"),
               str(HERE / "native_model.c"), str(assets / "tokenizer.S"),
               *(str(root / p) for p in common_files), "-lm", "-o", str(target)]
    run(command);commands.append(command)
    return label, target


def check_model(builds, output):
    prompts = []
    for length in (1, 3, 4, 5, 13, 33, 64, 65):
        ids = " ".join(str((i * 7 + 1) % 32) for i in range(length))
        prompts.append(f":ids 8 {ids}\n")
    command = "".join(prompts) + ":ids 1 151936\n:ids 3 7\n"
    command += ":ids 1 " + " ".join(["1"] * 512) + "\n"
    cases = [("stream-on", command, []), ("stream-off", ":stream 0\n" + command, []),
             ("stack-failure", ":ids 3 7\n", ["stack-failure"])]
    rows = []
    for name, commands, args in cases:
        observed = []
        for label, binary in builds:
            raw = output / f"{label}-{name}-numeric.bin"
            result = run([str(binary), str(raw), *args], input=commands.encode())
            (output / f"{label}-{name}-wire.txt").write_bytes(result.stdout)
            observed.append((result.stdout, raw.read_bytes()))
        assert all(x == observed[0] for x in observed), (name, "wire or full valid logits/KV differ")
        if name == "stack-failure":
            assert b"T25 STREAM 1 ABORT" in observed[0][0]
            assert b"T25 IDS " not in observed[0][0]
        else:
            assert observed[0][0].count(b"T25 IDS ") == 10
            assert observed[0][0].count(b"T25 ERROR ") == 1
        rows.append({"case": name, "wire_bytes": len(observed[0][0]),
                     "numeric_bytes": len(observed[0][1]),
                     "wire_sha256": hashlib.sha256(observed[0][0]).hexdigest(),
                     "numeric_sha256": hashlib.sha256(observed[0][1]).hexdigest()})
    return {"cases": rows, "scope": "actual production main, NX_OPT13_TEST two-layer synthetic assets; full valid logits/KV byte comparison; fake UART/clock"}


def benchmark(libs):
    values = np.random.default_rng(1701).standard_normal(VOCAB).astype("<f4")
    repeats = 100;samples = {label: [] for label, _ in libs}
    expected = int(values.argmax()) * repeats
    for _, lib in libs:assert lib.memory_greedy_repeat(values.ctypes.data, 1) == expected // repeats
    for trial in range(7):
        order = libs[trial % len(libs):] + libs[:trial % len(libs)]
        for label, lib in order:
            start = time.perf_counter_ns()
            got = lib.memory_greedy_repeat(values.ctypes.data, repeats)
            elapsed = time.perf_counter_ns() - start
            assert got == expected
            samples[label].append(elapsed / repeats)
    median = {label: statistics.median(times) for label, times in samples.items()}
    return {"scope": "native CPU, hot 607744-byte logits, strict gcc builds; NOT RV32 cycles, board TTFT, DDR bandwidth, or CoreMark",
            "machine": platform.machine(), "repeats_per_sample": repeats,
            "samples_ns_per_call": samples, "median_ns_per_call": median,
            "baseline_time_divided_by_candidate": {k: median[libs[0][0]] / v for k, v in median.items()}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-source", required=True, type=Path)
    parser.add_argument("--candidate-source", default=ROOT, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--benchmark", action="store_true")
    args = parser.parse_args()
    old = args.baseline_source.resolve();new = args.candidate_source.resolve()
    output = args.output.resolve();output.mkdir(parents=True, exist_ok=False)
    assert old != new and (old / REFERENCE).is_file() and (new / REFERENCE).is_file()
    before = {"baseline": sha(old / REFERENCE), "candidate": sha(new / REFERENCE)}
    assert before["baseline"] != before["candidate"], "Differential needs an actual immutable old source"
    commands = []
    configs = [(old, "baseline-o2", "-O2"), (new, "candidate-o2", "-O2"),
               (new, "candidate-o3", "-O3")]
    libs = [build_probe(root, output, label, opt, commands) for root, label, opt in configs]
    result = {"source_sha256": before, "compiler": run(["gcc", "--version"]).stdout.decode().splitlines()[0],
              "greedy": check_greedy(libs), "attention": check_attention(libs)}
    print("PASS full-width greedy and attention differential", flush=True)
    assets = output / "assets";assets.mkdir()
    spec = importlib.util.spec_from_file_location("baseline_fixtures", old / "tests/production_streaming/fixtures.py")
    fixtures = importlib.util.module_from_spec(spec);spec.loader.exec_module(fixtures)
    fixtures.write_assets(assets)
    unchanged = ["firmware/runtime/board/main.c", "firmware/runtime/port/runtime.c",
                 "firmware/runtime/port/model.c", "firmware/runtime/port/tokenizer.c",
                 "firmware/runtime/port/stream.c"]
    for path in unchanged:assert sha(old / path) == sha(new / path), (path, "unrelated production change")
    builds = [build_model(root, output, assets, label, opt, commands) for root, label, opt in configs]
    result["production_model"] = check_model(builds, output)
    print("PASS production main/logits/KV/stream exact differential", flush=True)
    if args.benchmark:result["native_benchmark"] = benchmark(libs)
    assert before == {"baseline": sha(old / REFERENCE), "candidate": sha(new / REFERENCE)}, "Source mutated during run"
    result["commands"] = commands
    result["test_source_sha256"] = {p.name: sha(p) for p in (HERE / "verify.py", HERE / "probe.c", HERE / "native_model.c")}
    result["status"] = "PASS"
    (output / "RESULTS.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"status": "PASS", "greedy_cases": len(result["greedy"]),
                      "attention_cases": len(result["attention"]["cases"]),
                      "valid_fp32_words": result["attention"]["valid_fp32_output_words_per_candidate"],
                      "production_cases": len(result["production_model"]["cases"]),
                      "report": str(output / "RESULTS.json")}), flush=True)


if __name__ == "__main__":
    main()
