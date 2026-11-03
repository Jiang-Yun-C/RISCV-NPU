"""Independent T03 checker: integer reference, ELF, retire stream and TX waveform."""
import argparse
from bisect import bisect_right
import csv
import json
from pathlib import Path
import re
from elftools.elf.elffile import ELFFile

MASK = 0xffffffff
ALLOWED_OPCODES = {0x03, 0x0f, 0x13, 0x17, 0x23, 0x33, 0x37, 0x63, 0x67, 0x6f, 0x73}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def mix(h, x):
    return (((h << 5) | (h >> 27)) ^ (x & MASK)) & MASK


def signed(x):
    return x if x < 2**31 else x - 2**32


def reference(seed):
    # Python arbitrary-precision operations, with explicit RV32 wrapping and
    # signed division toward zero (Python // alone would be incorrect).
    state = seed | 1
    h = 0x12345678
    def next_word():
        nonlocal state
        state ^= (state << 13) & MASK
        state ^= state >> 17
        state ^= (state << 5) & MASK
        return state
    for _ in range(32):
        a, b = next_word(), next_word() | 1
        sa, sb = signed(a), signed(b)
        q = (abs(sa) // abs(sb)) * (-1 if (sa < 0) != (sb < 0) else 1)
        for value in (a+b, a-b, a*b, (sa*sb) >> 32, (a*b) >> 32, (sa*b) >> 32,
                      q, a//b, sa-q*sb, a % b):
            h = mix(h, value)
    words = [(seed ^ (0x01020304 * (i+1))) & MASK for i in range(32)]
    words[0] = 0x5aa57f80
    words[1] = (words[1] & 0xffff0000) | 0x8001
    mem = 0
    for word in words + [words[i] ^ words[31-i] for i in range(16)]:
        mem = mix(mem, word)
    sig = mix(mix(mix(h, mem), 0x40380000), seed) ^ 0x54303301
    return {"SEED": seed, "ARITH": h, "MEM": mem, "SOFTFP": 0x40380000,
            "ILLEGAL": 1, "TIMER": 1, "SIGNATURE": sig}


def elf_info(path):
    with path.open("rb") as stream:
        elf = ELFFile(stream)
        require(elf.elfclass == 32 and elf.little_endian and elf["e_machine"] == "EM_RISCV"
                and elf["e_type"] == "ET_EXEC", "ELF must be RV32 little-endian executable")
        require(elf["e_flags"] == 0, "ELF must use ILP32 soft float, no C/A/F/D defaults")
        require(elf["e_entry"] == 0x80000000, "reset vector mismatch")
        attrs = elf.get_section_by_name(".riscv.attributes")
        require(attrs is not None, "missing ISA attributes")
        match = re.search(rb"rv32[^\x00]+", attrs.data())
        require(match is not None, "missing rv32 ISA string")
        arch = match.group().decode()
        extensions = [re.sub(r"\d+p\d+$", "", ext) for ext in arch[4:].split("_")]
        require(set(extensions) >= {"i", "m", "zicsr", "zifencei"}
                and set(extensions) <= {"i", "m", "zicsr", "zifencei", "zmmul"}, "unexpected ISA: " + arch)
        symbols = {s.name: s["st_value"] for s in elf.get_section_by_name(".symtab").iter_symbols()}
        for name in ("_start", "main", "trap_entry", "illegal_site", "fence_target", "fence_patch_test",
                     "__data_start", "__data_load", "__data_end", "__bss_start", "__bss_end",
                     "__stack_top", "__stack_bottom", "__mulsf3", "__addsf3"):
            require(name in symbols, "missing symbol: " + name)
        require(symbols["__data_start"] == 0x80008000
                and symbols["__data_load"] != symbols["__data_start"]
                and symbols["__data_end"] > symbols["__data_start"], "data copy layout missing")
        require(symbols["__bss_end"] > symbols["__bss_start"]
                and symbols["__bss_end"] <= symbols["__stack_bottom"]
                and symbols["__stack_top"] == 0x80010000, "BSS/stack layout mismatch")
        for seg in elf.iter_segments():
            if seg["p_type"] == "PT_LOAD":
                require(0x80000000 <= seg["p_vaddr"] <= seg["p_vaddr"] + seg["p_memsz"] <= 0x80010000,
                        "runtime load outside RAM")
                require(0x80000000 <= seg["p_paddr"] <= seg["p_paddr"] + seg["p_filesz"] <= 0x80008000,
                        "preload must leave data/BSS poisoned")
        text = elf.get_section_by_name(".text")
        raw, base = text.data(), text["sh_addr"]
        instructions = {base+i: int.from_bytes(raw[i:i+4], "little") for i in range(0, len(raw), 4)}
    return {"arch": arch, "abi": "ilp32", "entry": 0x80000000, "symbols": symbols,
            "instructions": instructions}


def check_elf(directory):
    info = elf_info(directory / "firmware.elf")
    dis = (directory / "firmware.dis").read_text()
    rows = re.findall(r"^\s*([0-9a-f]+):\s+([0-9a-f]+)\s+([^\n]+)", dis, re.M)
    require(rows, "empty disassembly")
    for address, word, assembly in rows:
        pc, insn = int(address, 16), int(word, 16)
        if pc == info["symbols"]["illegal_site"]:
            require(insn == 0xffffffff, "intentional illegal test instruction changed")
        else:
            require(len(word) == 8 and insn & 3 == 3 and insn & 0x7f in ALLOWED_OPCODES,
                    f"unsupported instruction in disassembly: {address} {assembly}")
    require("__mulsf3>" in dis and "__addsf3>" in dis and "fence.i" in dis,
            "soft-float helpers / FENCE.I missing")
    binary = (directory / "firmware.bin").read_bytes()
    with (directory / "firmware.elf").open("rb") as stream:
        for seg in ELFFile(stream).iter_segments():
            if seg["p_type"] == "PT_LOAD" and seg["p_filesz"]:
                offset = seg["p_paddr"] - 0x80000000
                require(binary[offset:offset+seg["p_filesz"]] == seg.data(), "BIN / ELF preload mismatch")
    return {k: v for k, v in info.items() if k != "instructions"}


def read_vcd(path):
    signals, events, groups = {}, {}, []
    header = True
    now, changes, previous_time = 0, {}, -1
    text = path.read_text()
    require(re.search(r"\$timescale\s+1\s*ps\s+\$end", text[:4096]), "VCD timescale must be 1ps")
    for line in text.splitlines():
        line = line.strip()
        if header:
            fields = line.split()
            if fields and fields[0] == "$var":
                signals[fields[4]] = fields[3]
                events.setdefault(fields[3], [])
            if "$enddefinitions" in line:
                header = False
            continue
        if not line or line.startswith("$"): continue
        if line.startswith("#"):
            if changes: groups.append((now, changes))
            now, changes = int(line[1:]), {}
            require(now >= previous_time, "VCD time moved backwards")
            previous_time = now
        else:
            if line[0] in "bB":
                bits, code = line[1:].split()
            elif line[0] in "01xXzZ":
                bits, code = line[0], line[1:]
            else: raise ValueError("unexpected VCD syntax")
            if code in events:
                value = None if any(c in bits.lower() for c in "xz") else int(bits, 2)
                changes[code] = value
                events[code].append((now, value))
    if changes: groups.append((now, changes))
    require(not header and groups, "incomplete VCD")
    wanted = ("clk", "reset", "uart_tx", "retire_valid", "retire_pc", "retire_instruction",
              "exception_pending", "csr_redirect", "csr_target", "timer_irq", "signature", "exit_valid", "exit_code")
    require(all(n in signals for n in wanted), "missing VCD observation signals")
    return signals, events, groups, now


def check_wave(path, uart, result, trace, redirects):
    signals, events, groups, end = read_vcd(path)
    def seq(name): return events[signals[name]]
    require(seq("reset")[0][1] == 1 and (100000, 0) in seq("reset"), "reset sequence mismatch")
    require(seq("signature")[-1][1] == result["signature"] and seq("exit_code")[-1][1] == 0x600d0003
            and seq("exit_valid")[-1][1] == 1, "waveform missing CPU completion")
    require(any(v == 1 for _, v in seq("exception_pending"))
            and any(v == 1 for _, v in seq("timer_irq")), "waveform missing exception/IRQ")
    require(end >= (result["cycles"]-1)*10000, "waveform truncated before completion")
    values, observed, observed_redirects, exception_cycles = {}, [], [], 0
    clock_edges = []
    for time, changes in groups:
        # TB logs pre-NBA values on rising edge; sample the preceding stable state.
        if changes.get(signals["clk"]) == 1:
            clock_edges.append(time)
            if values.get(signals["reset"]) == 0 and values.get(signals["retire_valid"]) == 1:
                pc, insn = values.get(signals["retire_pc"]), values.get(signals["retire_instruction"])
                require(pc is not None and insn is not None, "unknown retired PC/instruction in waveform")
                observed.append((time//10000+1, pc, insn))
            if values.get(signals["reset"]) == 0:
                exception_cycles += values.get(signals["exception_pending"]) == 1
                if values.get(signals["csr_redirect"]) == 1:
                    observed_redirects.append((time//10000+1, values.get(signals["csr_target"]),
                        values.get(signals["exception_pending"]), values.get(signals["timer_irq"])))
        values.update(changes)
    require(all(b-a == 10000 for a, b in zip(clock_edges, clock_edges[1:])), "clock period mismatch")
    require(observed == trace, "retire CSV does not match independent waveform samples")
    require(observed_redirects == redirects and exception_cycles == result["exception_cycles"],
            "CSR redirect / exception observation differs from waveform")
    tx = seq("uart_tx")
    times = [t for t, _ in tx]
    def bit_at(time):
        index = bisect_right(times, time)-1
        require(index >= 0, "UART sampling before first event")
        return tx[index][1]
    decoded, busy_until, previous = bytearray(), 0, 1
    for time, bit in tx:
        if previous == 1 and bit == 0 and time >= busy_until:
            require(bit_at(time+80000) == 0, "bad VCD UART start")
            data = [bit_at(time+240000+i*160000) for i in range(8)]
            require(all(v in (0, 1) for v in data), "unknown VCD UART data")
            require(bit_at(time+1520000) == 1, "bad VCD UART stop")
            decoded.append(sum(v << i for i, v in enumerate(data)))
            busy_until = time+1600000
        previous = bit
    require(bytes(decoded) == uart, "UART pin waveform differs from decoded log")
    return {"end_ps": end, "retire_samples": len(observed), "uart_bytes": len(decoded)}


def check_execution(directory, seed):
    info = elf_info(directory / "firmware.elf")
    symbols, code = info["symbols"], info["instructions"]
    uart = (directory / "uart.log").read_bytes()
    lines = uart.decode("ascii").splitlines()
    require(len(lines) == 13 and lines[:2] == ["Hello T03", "BOOT OK"] and lines[-1] == "T03 PASS",
            "unexpected/missing UART output")
    require(lines[6] == "FENCE.I OK", "FENCE.I status missing")
    parsed = {}
    for line in lines:
        if "=" in line:
            name, value = line.split("=")
            require(name not in parsed and re.fullmatch("[0-9a-f]{8}", value), "malformed UART field")
            parsed[name] = int(value, 16)
    expected = reference(seed)
    require(set(parsed) == set(expected) | {"CYCLES", "RETIRED"}, "unexpected UART fields")
    require(all(parsed[k] == v for k, v in expected.items()), f"independent arithmetic/signature mismatch: {parsed} != {expected}")
    result = json.loads((directory / "simulation.json").read_text())
    require(result["signature"] == expected["SIGNATURE"] and result["exit_code"] == 0x600d0003,
            "CPU MMIO signature or exit mismatch")
    require(result["uart_bytes"] == len(uart) and 100 < parsed["RETIRED"] < result["retired"]
            and parsed["CYCLES"] < result["cycles"] <= 200000, "counter mismatch")
    trace = []
    with (directory / "retire.csv").open() as stream:
        for row in csv.DictReader(stream):
            cycle, pc, insn = int(row["cycle"]), int(row["pc"], 16), int(row["instruction"], 16)
            require(not trace or cycle > trace[-1][0], "retire cycles not strictly increasing")
            require(insn & 0x7f in ALLOWED_OPCODES and insn & 3 == 3, "retired unsupported ISA instruction")
            expected_insn = 0x02a00513 if pc == symbols["fence_target"] else code.get(pc)
            require(insn == expected_insn, f"retired code differs from ELF at {pc:08x}: {insn:08x}")
            trace.append((cycle, pc, insn))
    require(len(trace) == result["retired"] and trace[0][1] == 0x80000000, "retirement count/entry mismatch")
    pcs = {pc for _, pc, _ in trace}
    for symbol in ("main", "trap_entry", "__mulsf3", "__addsf3", "fence_patch_test", "fence_target"):
        require(symbols[symbol] in pcs, "CPU never executed " + symbol)
    require(sum(insn == 0x30200073 for _, _, insn in trace) == 2, "expected two MRET instructions")
    require(any(insn == 0x0000100f for _, _, insn in trace), "FENCE.I never retired")
    muldiv = {insn >> 12 & 7 for _, _, insn in trace if insn & 0x7f == 0x33 and insn >> 25 == 1}
    require(muldiv == set(range(8)), "not all eight M operations executed")
    with (directory / "events.csv").open() as stream:
        events = list(csv.DictReader(stream))
    require(len(events) == result["redirects"] and sum(int(e["target"], 16) == symbols["trap_entry"] for e in events) == 2,
            "expected illegal instruction and timer trap entries")
    require(any(int(e["target"], 16) == symbols["illegal_site"]+4 for e in events), "illegal instruction recovery missing")
    redirects = [(int(e["cycle"]), int(e["target"], 16), int(e["exception_pending"]), int(e["timer_irq"])) for e in events]
    wave = check_wave(directory / "cpu.vcd", uart, result, trace, redirects)
    return {"status": "PASS", "reference": expected, "observed": parsed, "simulation": result,
            "waveform": wave, "scope": "real RV32IM CPU, PRELOAD, no cache/predictor/FPU/board qualification"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=("elf", "execution"))
    parser.add_argument("directory", type=Path)
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()
    result = check_elf(args.directory) if args.kind == "elf" else check_execution(args.directory, args.seed)
    (args.directory / (args.kind+"-check.json")).write_text(json.dumps(result, indent=2)+"\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
