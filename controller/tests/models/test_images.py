"""Loader rejection tests use malformed external images, not just happy paths."""
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "axi"))
from make_workload import elf_fixture
from prepare_image import parse_elf, prepare, check_range


class Images(unittest.TestCase):
    def reject(self, mutate, match):
        data = bytearray(elf_fixture())
        mutate(data)
        with self.assertRaisesRegex(ValueError, match):
            parse_elf(data)

    def test_elf_segments_endian_entry_bss(self):
        entry, segments, flags = parse_elf(elf_fixture())
        self.assertEqual(entry, 0x80010000)
        self.assertEqual(int.from_bytes(segments[0].data[:4], "little"), 0x12345678)
        self.assertEqual((len(segments[1].data), segments[1].memory_size), (32, 16*1024*1024))
        self.assertEqual(flags, 0)

    def test_wrong_class(self):
        self.reject(lambda d: d.__setitem__(4, 2), "ELF32")

    def test_big_endian(self):
        self.reject(lambda d: d.__setitem__(5, 2), "little-endian")

    def test_wrong_machine(self):
        self.reject(lambda d: struct.pack_into("<H", d, 18, 62), "RISC-V")

    def test_dynamic_executable(self):
        self.reject(lambda d: struct.pack_into("<H", d, 16, 3), "executable")

    def test_truncated_headers(self):
        self.reject(lambda d: struct.pack_into("<I", d, 28, 0xFFFFFFF0), "truncated")

    def test_truncated_data(self):
        self.reject(lambda d: struct.pack_into("<I", d, 56, 0xFFFFFF00), "truncated")

    def test_filesz_exceeds_memsz(self):
        self.reject(lambda d: struct.pack_into("<I", d, 68, 33), "segment")

    def test_address_overflow(self):
        self.reject(lambda d: struct.pack_into("<II", d, 60, 0xFFFFFF00, 0xFFFFFF00), "outside")

    def test_overlap(self):
        self.reject(lambda d: struct.pack_into("<II", d, 92, 0x80010000, 0x80010000), "overlapping")

    def test_virtual_physical_mismatch(self):
        self.reject(lambda d: struct.pack_into("<I", d, 64, 0x80020000), "must match")

    def test_bad_alignment(self):
        self.reject(lambda d: struct.pack_into("<I", d, 80, 3), "alignment")

    def test_entry_bss(self):
        self.reject(lambda d: struct.pack_into("<I", d, 24, 0x81000020), "entry")

    def test_entry_nonexecuting_segment(self):
        self.reject(lambda d: struct.pack_into("<I", d, 24, 0x81000000), "entry")

    def test_entry_alignment(self):
        self.reject(lambda d: struct.pack_into("<I", d, 24, 0x80010001), "entry")

    def test_interpreter(self):
        self.reject(lambda d: struct.pack_into("<I", d, 84, 3), "interpreter")

    def test_last_byte_and_past_end(self):
        check_range(0xBFFFFFFF, 1)
        for addr, size in ((0xBFFFFFFF,2), (0x80000000,0x40000001), (0x7FFFFFFF,1), (0x100000000,1), (0x80000000,-1)):
            with self.subTest(addr=addr, size=size), self.assertRaises(ValueError): check_range(addr,size)

    def test_modes_bin_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp); image = p / "code.bin"; image.write_bytes(b"\x78\x56\x34\x12")
            meta = prepare(p/"bin", "PRELOAD", image, "bin", 0xBFFFFFFC, 0xBFFFFFFC)
            self.assertEqual(meta["entry"], 0xBFFFFFFC)
            with self.assertRaises(FileExistsError): prepare(p/"bin", "PRELOAD", image, "bin", 0xBFFFFFFC, 0xBFFFFFFC)
            with self.assertRaisesRegex(ValueError, "forbids"): prepare(p/"bad", "PROTOCOL_BOOT", image, "bin", 0x80000000, 0x80000000)
            self.assertFalse((p/"bad").exists())
            meta = prepare(p/"boot", "PROTOCOL_BOOT")
            self.assertIsNone(meta["entry"])
            self.assertEqual((p/"boot/load.plan").read_bytes(), b"")
            with self.assertRaisesRegex(ValueError,"explicit"): prepare(p/"bad", "PRELOAD", image, "bin")
            with self.assertRaisesRegex(ValueError,"entry"): prepare(p/"bad", "PRELOAD", image, "bin", 0x80000000, 0x80000004)

    def test_sparse_bss_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp); image=p/"code.elf"; image.write_bytes(elf_fixture())
            meta=prepare(p/"out", "PRELOAD", image, "elf")
            self.assertEqual(sum(s["file_bytes"] for s in meta["segments"]), 64)
            self.assertIn("Z 81000020 ffffe0", (p/"out/load.plan").read_text())
            self.assertLess(sum(f.stat().st_size for f in (p/"out").iterdir()), 4096)


if __name__ == "__main__":
    unittest.main()
