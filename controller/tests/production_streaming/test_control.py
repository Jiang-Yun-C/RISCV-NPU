"""Byte-fragmented cancel decoder uses the complete 64-bit request identity."""
import ctypes as C
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class Decoder(C.Structure):
    _fields_ = [('line', C.c_char * 64), ('used', C.c_uint), ('overflow', C.c_uint)]


class ControlDecoderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='t27-control-')
        path = Path(cls.tmp.name) / 'control.so'
        subprocess.run(['gcc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                        '-Wno-misleading-indentation', '-shared', '-fPIC',
                        str(ROOT / 'firmware/runtime/port/control.c'), '-o', str(path)], check=True)
        cls.lib = C.CDLL(str(path))
        cls.lib.nxc_feed.argtypes = [C.POINTER(Decoder), C.c_ubyte, C.c_uint64, C.POINTER(C.c_uint64)]
        cls.lib.nxc_feed.restype = C.c_int

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def feed(self, data, session=0xfedcba9876543210, state=None):
        state = state if state is not None else Decoder()
        target = C.c_uint64();events = []
        for byte in data:
            event = self.lib.nxc_feed(C.byref(state), byte, session, C.byref(target))
            if event:events.append((event, target.value))
        return events, state

    def test_complete_identity_lf_boundary_and_stale_request(self):
        command = b':cancel fedcba9876543210'
        events, state = self.feed(command)
        self.assertEqual(events, [])
        self.assertEqual(self.feed(b'\r\n', state=state)[0], [(1, 0xfedcba9876543210)])
        self.assertEqual(self.feed(command + b'\n', session=0xfedcba9876543211)[0], [(2, 0xfedcba9876543210)])

    def test_bad_and_oversized_lines_never_cancel_and_next_line_recovers(self):
        good = b':cancel fedcba9876543210\n'
        for bad in (b'x' * 100, b':cancel 0000000000000000', b':cancel FEDCBA9876543210',
                    b':cancel fedcba9876543210\x00', b':cancel fedcba9876543210x',
                    '取消'.encode(), b':cancel fedcba987654321'):
            with self.subTest(bad=bad):
                events, _ = self.feed(bad + b'\n' + good)
                self.assertEqual(events, [(3, 0), (1, 0xfedcba9876543210)])


if __name__ == '__main__':
    unittest.main()
