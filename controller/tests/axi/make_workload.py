#!/usr/bin/env python3
"""Create timing-independent AXI stimulus and a byte-oriented expected result."""
import argparse
import json
from pathlib import Path
import random
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "models"))
from prepare_image import prepare


def elf_fixture():
    # Two PT_LOADs, explicit little endian word at entry, sparse 16 MiB BSS.
    data = bytearray(0x300)
    data[:16] = b"\x7fELF\x01\x01\x01" + bytes(9)
    struct.pack_into("<HHIIIIIHHHHHH", data, 16, 2, 243, 1, 0x80010000, 52, 0, 0, 52, 32, 2, 0, 0, 0)
    struct.pack_into("<8I", data, 52, 1, 0x100, 0x80010000, 0x80010000, 32, 32, 5, 0x100)
    struct.pack_into("<8I", data, 84, 1, 0x200, 0x81000000, 0x81000000, 32, 0x1000000, 6, 0x100)
    data[0x100:0x120] = bytes.fromhex("78563412") + bytes(range(4, 32))
    data[0x200:0x220] = bytes(range(0xA0, 0xC0))
    return bytes(data)


def addresses(t):
    step = 1 << t["size"]
    start = t["addr"]
    span = step*t["beats"]
    for beat in range(t["beats"]):
        if t["burst"] == 0:
            address = start
        elif t["burst"] == 2:
            address = start//span*span + (start % span + beat*step) % span
        else:
            address = start if beat == 0 else start//step*step+beat*step
        yield address, (address//step+1)*step


def generate(directory, width=32, mode="PRELOAD", image_format="elf", id_bits=4):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    lanes = width//8
    full = lanes.bit_length()-1
    rng = random.Random(4004)  # Data/requests identical across all timing seeds.
    memory = {}
    if mode == "PRELOAD":
        raw = elf_fixture() if image_format == "elf" else bytes.fromhex("78563412")+bytes(range(4, 64))
        image = directory / ("fixture."+image_format)
        image.write_bytes(raw)
        meta = prepare(directory / "image", mode, image, image_format,
                       0x80010000 if image_format == "bin" else None,
                       0x80010000 if image_format == "bin" else None)
        for segment in meta["segments"]:
            if "file" in segment:
                blob = (directory / "image" / segment["file"]).read_bytes()
                memory.update({segment["address"]+i: b for i, b in enumerate(blob)})
    else:
        meta = prepare(directory / "image", mode)
    writes, reads = [], []

    def read(name, addr, beats=1, size=full, burst=1, resp=0, phase=1):
        t = dict(name=name, addr=addr, beats=beats, size=size, burst=burst, resp=resp,
                 id=len(reads)%(1 << id_bits), phase=phase, delay=0, expected=[])
        for low, high in addresses(t):
            aligned = low//lanes*lanes
            value = sum(memory.get(a, 0) << (8*(a-aligned)) for a in range(low, min(high, aligned+lanes))) if resp == 0 else 0
            t["expected"].append(value)
        reads.append(t)

    # These are disjoint from all writes, so phase 0 exercises independent AR/R
    # and AW/W/B without depending on a concurrent read/write race policy.
    for i, a in enumerate([0x80010000, 0x81000000, 0x81000020, 0x81FFFFF8, 0x88000000]*4):
        read("image-bss-unloaded-"+str(i), a, phase=0)

    def write(name, addr, beats=1, size=full, burst=1, resp=0, strobe=None):
        t = dict(name=name, addr=addr, beats=beats, size=size, burst=burst, resp=resp,
                 id=len(writes)%(1 << id_bits), delay=80 if not writes else 0, data=[], strobes=[])
        for low, high in addresses(t):
            aligned = low//lanes*lanes
            mask = sum(1 << (a-aligned) for a in range(low, min(high, aligned+lanes)))
            if strobe is not None:
                mask &= strobe
            value = rng.getrandbits(width)
            t["data"].append(value); t["strobes"].append(mask)
            if resp == 0:
                for lane in range(lanes):
                    if mask & (1 << lane):
                        memory[aligned+lane] = (value >> (8*lane)) & 255
        writes.append(t)

    # Distinct values on both sides of 256/512 MiB, plus last physical byte.
    for a in [0x80000000, 0x8FFFFFF8, 0x90000000, 0x9FFFFFF8, 0xA0000000, 0xBFFFFFF8]:
        write("high-address", a)
    write("zero-strobe", 0x80000000, strobe=0)
    write("partial-strobe", 0x90000000, strobe=0x55)
    write("highest-byte", 0xBFFFFFFF, size=0)
    write("incr-256", 0x83000000, beats=256)
    write("ends-at-4k", 0x83001000-4*lanes, beats=4)
    write("next-4k", 0x83001000, beats=4)
    write("fixed-16", 0x83002000, beats=16, burst=0)
    for beats in (2, 4, 8, 16):
        write("wrap-"+str(beats), 0x83003000+lanes*(beats-1), beats=beats, burst=2)
    for size in range(full+1):
        for lane in range(0, lanes, 1 << size):
            write("narrow-lane", 0x83004000+size*32+lane, size=size)
    write("unaligned-incr", 0x83005001, beats=4)
    write("unaligned-fixed", 0x83005101, beats=4, burst=0)
    # No-write-on-error is checked by subsequent legal reads of the same bytes.
    for name, addr, beats, size, burst, response in [
        ("below-window", 0x7FFFFFF8, 1, full, 1, 3),
        ("above-window", 0xC0000000, 1, full, 1, 3),
        ("overflow-32bit", 0xFFFFFFF8, 4, full, 1, 3),
        ("cross-window", 0xBFFFFFF8, 4, full, 1, 3),
        ("cross-4k", 0x83006FF8, 4, full, 1, 2),
        ("reserved-burst", 0x83008000, 1, full, 3, 2),
        ("oversize", 0x83009000, 1, full+1, 1, 2),
        ("illegal-wrap-length", 0x8300A000, 3, full, 2, 2),
        ("unaligned-wrap", 0x8300B001, 4, full, 2, 2),
        ("fixed-too-long", 0x8300C000, 17, full, 0, 2),
        ("injected-slverr", 0x84000000, 4, full, 1, 2),
    ]:
        write(name, addr, beats, size, burst, response)
    for i in range(128):
        # Unique cache-line regions; varies bursts, byte strobes and IDs.
        size = rng.randrange(full+1)
        write("random-"+str(i), 0x85000000+i*256, beats=rng.randrange(1, 17),
              size=size, strobe=rng.randrange(1 << lanes))
    # Build all expected reads after all write commits, including fixed/WRAP.
    for t in writes:
        read(t["name"], t["addr"], t["beats"], t["size"], t["burst"], t["resp"])
    for a in [0x83006FF8, 0x83007000, 0x83008000, 0x83009000, 0x8300A000, 0x8300B000, 0x8300C000]:
        read("error-no-write", a)
    read("last-byte", 0xBFFFFFFF, size=0)
    read("unaligned-last-byte", 0xBFFFFFFF, size=full)
    read("unaligned-4k-last-byte", 0x83000FFF, size=full)
    payload = dict(schema_version=1, width=width, id_bits=id_bits, mode=mode, image_format=image_format, image=meta,
                   injection=dict(start=0x84000000, end=0x84000FFF, response=2), writes=writes, reads=reads)
    (directory / "workload.json").write_text(json.dumps(payload, indent=2)+"\n")
    (directory / "aw.txt").write_text("".join(f"{t['delay']} {t['id']:x} {t['addr']:x} {t['beats']-1:x} {t['size']:x} {t['burst']:x}\n" for t in writes))
    (directory / "ar.txt").write_text("".join(f"{t['phase']} {t['delay']} {t['id']:x} {t['addr']:x} {t['beats']-1:x} {t['size']:x} {t['burst']:x}\n" for t in reads))
    (directory / "w.txt").write_text("".join(f"{40 if n==1 and i==0 else 0} {d:x} {s:x} {int(i==t['beats']-1)}\n"
        for n, t in enumerate(writes) for i, (d, s) in enumerate(zip(t["data"], t["strobes"]))))
    return payload


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("directory", type=Path)
    p.add_argument("--width", type=int, choices=(32,64,128), default=32)
    p.add_argument("--id-bits", type=int, choices=range(1,17), default=4)
    p.add_argument("--mode", choices=("PRELOAD","PROTOCOL_BOOT"), default="PRELOAD")
    p.add_argument("--format", choices=("bin","elf"), default="elf")
    a = p.parse_args()
    result = generate(a.directory, a.width, a.mode, a.format, a.id_bits)
    print(json.dumps({"writes": len(result["writes"]), "reads": len(result["reads"]), "image": result["image"]}))
