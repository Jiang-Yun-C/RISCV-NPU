#!/usr/bin/env python3
"""Validate physical RV32 images before emitting a compact binary/zero load plan."""
import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import struct

BASE = 0x80000000
SIZE = 0x40000000


@dataclass
class Segment:
    address: int
    data: bytes
    memory_size: int
    flags: int = 0


def check_range(address, size, base=BASE, capacity=SIZE):
    if not (0 <= base < 2**32 and 0 < capacity <= 2**32-base
            and base <= address < base+capacity and 0 < size <= base+capacity-address):
        raise ValueError("image outside physical memory window or integer overflow")


def parse_elf(data, base=BASE, capacity=SIZE):
    if len(data) < 52 or data[:7] != b"\x7fELF\x01\x01\x01":
        raise ValueError("require ELF32 little-endian version 1")
    (kind, machine, version, entry, phoff, _, flags, ehsize, phsize, phnum,
     _, _, _) = struct.unpack_from("<HHIIIIIHHHHHH", data, 16)
    if kind != 2 or machine != 243 or version != 1 or ehsize != 52 or phsize != 32 or not phnum:
        raise ValueError("require executable RISC-V ELF32 with program headers")
    if phoff < 52 or phoff + phnum*32 > len(data):
        raise ValueError("truncated program header table")
    segments = []
    for i in range(phnum):
        ptype, offset, virtual, physical, filesz, memsz, perms, align = struct.unpack_from("<8I", data, phoff+32*i)
        if ptype in (2, 3):
            raise ValueError("dynamic/interpreter images are not supported")
        if ptype != 1:
            continue
        if filesz > memsz or offset+filesz > len(data):
            raise ValueError("invalid/truncated ELF segment")
        if align > 1 and ((align & (align-1)) or (virtual-offset) % align):
            raise ValueError("invalid ELF segment alignment")
        if virtual != physical:
            raise ValueError("virtual and physical addresses must match (no MMU/relocation)")
        if not memsz:
            continue
        check_range(physical, memsz, base, capacity)
        if any(physical < s.address+s.memory_size and s.address < physical+memsz for s in segments):
            raise ValueError("overlapping ELF segments")
        segments.append(Segment(physical, data[offset:offset+filesz], memsz, perms))
    if entry % 2 or not any(s.flags & 1 and s.address <= entry < s.address+len(s.data) for s in segments):
        raise ValueError("entry must be aligned and in file-backed executable bytes")
    return entry, segments, flags


def prepare(output, mode, source=None, image_format=None, address=None, entry=None, base=BASE, capacity=SIZE):
    if mode not in ("PRELOAD", "PROTOCOL_BOOT"):
        raise ValueError("invalid load mode")
    if mode == "PROTOCOL_BOOT" and source is not None:
        raise ValueError("PROTOCOL_BOOT forbids external application preload")
    segments, elf_flags = [], None
    source_id = None
    if source is not None:
        source = Path(source)
        data = source.read_bytes()
        source_id = {"path": str(source.resolve()), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
        if image_format == "elf":
            if address is not None or entry is not None:
                raise ValueError("ELF address and entry come from checked program headers")
            entry, segments, elf_flags = parse_elf(data, base, capacity)
        elif image_format == "bin":
            if address is None or entry is None:
                raise ValueError("BIN requires explicit base and entry")
            check_range(address, len(data), base, capacity)
            if entry % 2 or not address <= entry < address+len(data):
                raise ValueError("BIN entry outside image or unaligned")
            segments = [Segment(address, data, len(data), 5)]
        else:
            raise ValueError("explicit bin/elf format required")
    elif mode == "PRELOAD" or any(v is not None for v in (address, entry, image_format)):
        raise ValueError("PRELOAD requires an image; empty PROTOCOL_BOOT requires no image options")
    output = Path(output).resolve()
    if any(c.isspace() for c in str(output)):
        raise ValueError("SV load-plan directory cannot contain whitespace")
    output.mkdir(parents=True, exist_ok=False)
    lines, records = [], []
    for i, s in enumerate(segments):
        record = {"address": s.address, "file_bytes": len(s.data), "memory_bytes": s.memory_size, "flags": s.flags}
        if s.data:
            path = output / f"segment-{i}.bin"
            path.write_bytes(s.data)
            lines.append(f"B {s.address:x} {len(s.data):x} {path}\n")
            record.update(file=path.name, sha256=hashlib.sha256(s.data).hexdigest())
        if s.memory_size > len(s.data):
            lines.append(f"Z {s.address+len(s.data):x} {s.memory_size-len(s.data):x}\n")
        records.append(record)
    (output / "load.plan").write_text("".join(lines))
    manifest = {"schema_version": 1, "mode": mode, "format": image_format, "source": source_id,
                "base": base, "capacity": capacity, "entry": entry, "elf_flags": elf_flags,
                "unloaded_byte": 0, "segments": records}
    (output / "image.json").write_text(json.dumps(manifest, indent=2)+"\n")
    return manifest


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--mode", choices=("PRELOAD", "PROTOCOL_BOOT"), required=True)
    p.add_argument("--image", type=Path)
    p.add_argument("--format", choices=("bin", "elf"))
    p.add_argument("--base", type=lambda s: int(s, 0))
    p.add_argument("--entry", type=lambda s: int(s, 0))
    args = p.parse_args()
    try:
        result = prepare(args.output, args.mode, args.image, args.format, args.base, args.entry)
    except (ValueError, OSError) as error:
        p.exit(1, f"IMAGE_REJECT: {error}\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
