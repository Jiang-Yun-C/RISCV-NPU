"""Independent content checks; process exit zero alone is not acceptance."""
import argparse
import json
from pathlib import Path
import re


def require(condition, message):
    if not condition:
        raise ValueError(message)


def check_host(path, seed):
    import numpy as np
    from safetensors.numpy import load_file, save_file

    observed = json.loads(path.read_text())
    a = np.array([((seed + i * 17) & 255) - 128 for i in range(16)], dtype=np.int32)
    b = np.arange(16, dtype=np.int32) * 3 - 19
    golden = int(np.dot(a.astype(np.int64), b.astype(np.int64)))
    require(observed == {"seed": seed, "dot": golden}, "host C / NumPy mismatch")
    tensor_path = path.parent / "smoke.safetensors"
    save_file({"a": a, "b": b}, str(tensor_path))
    restored = load_file(str(tensor_path))
    require(np.array_equal(restored["a"], a) and np.array_equal(restored["b"], b),
            "safetensors roundtrip mismatch")
    return {"dot": golden, "elements": 16, "safetensors_roundtrip": "PASS"}


def check_elf(path, entry):
    from elftools.elf.elffile import ELFFile

    with path.open("rb") as stream:
        elf = ELFFile(stream)
        require(elf.elfclass == 32 and elf.little_endian, "expected ELF32 little endian")
        require(elf["e_machine"] == "EM_RISCV" and elf["e_type"] == "ET_EXEC", "wrong ELF target")
        require(elf["e_flags"] == 0, "expected ILP32 soft-float without RVC/RVE")
        require(elf["e_entry"] == entry, "unexpected entry point")
        loads = [seg for seg in elf.iter_segments() if seg["p_type"] == "PT_LOAD"]
        require(any(seg["p_flags"] & 1 and seg["p_vaddr"] <= entry <
                    seg["p_vaddr"] + seg["p_filesz"] for seg in loads), "entry is not executable")
        require(all(seg["p_vaddr"] >= entry and seg["p_vaddr"] + seg["p_memsz"] <= entry + 16384
                    for seg in loads), "ELF exceeds smoke RAM")
        symtab = elf.get_section_by_name(".symtab")
        require(symtab is not None and symtab.get_symbol_by_name("smoke_main"), "missing smoke_main")
        attrs = elf.get_section_by_name(".riscv.attributes")
        require(attrs is not None and b"rv32i" in attrs.data() and b"_m" in attrs.data(),
                "missing RV32IM attributes")
    return {"class": 32, "machine": "RISC-V", "abi": "ilp32", "entry": entry,
            "cpu_executed": False}


def check_vcd(path, seed):
    # A deliberately small reader for this fixture's uncompressed scalar/vector VCD.
    content = path.read_text()
    require("$enddefinitions $end" in content, "incomplete VCD header")
    header, body = content.split("$enddefinitions $end", 1)
    require(re.search(r"\$timescale\s+1\s*ps\s+\$end", header), "unexpected timescale")
    signals = {}
    for line in header.splitlines():
        fields = line.split()
        if fields and fields[0] == "$var":
            signals[fields[4]] = fields[3]
    require(all(name in signals for name in ("clk", "reset", "value", "cycles")), "missing signals")
    events = {code: [] for code in signals.values()}
    now, timestamps = 0, []
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("$"):
            continue
        if line.startswith("#"):
            now = int(line[1:])
            require(not timestamps or now >= timestamps[-1], "non-monotonic VCD time")
            timestamps.append(now)
            continue
        if line[0] in "bB":
            bits, code = line[1:].split()
        elif line[0] in "01xXzZ":
            bits, code = line[0], line[1:]
        else:
            continue
        if code in events:
            value = None if any(c in bits.lower() for c in "xz") else int(bits, 2)
            events[code].append((now, value))
    require(timestamps and max(timestamps) >= 100000, "truncated VCD body")
    value_events = events[signals["value"]]
    for cycle, time in enumerate(range(25000, 100000, 10000), start=1):
        require((time, (seed + cycle * 3) & 0xffffffff) in value_events,
                f"counter mismatch at {time} ps")
    require(events[signals["cycles"]][-1][1] == 8, "expected eight cycles")
    require(sum(v == 1 for _, v in events[signals["clk"]]) == 10, "wrong clock edge count")
    require((20000, 0) in events[signals["reset"]], "reset did not release")
    return {"format": "VCD", "timescale": "1ps", "cycles_checked": 8,
            "end_ps": max(timestamps), "signals": sorted(signals)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=["host", "elf", "vcd"])
    parser.add_argument("path", type=Path)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--entry", type=int, default=65536)
    args = parser.parse_args()
    result = {"host": lambda: check_host(args.path, args.seed),
              "elf": lambda: check_elf(args.path, args.entry),
              "vcd": lambda: check_vcd(args.path, args.seed)}[args.kind]()
    print(json.dumps({"status": "PASS", "kind": args.kind, "details": result}, sort_keys=True))


if __name__ == "__main__":
    main()
