"""Execute the portable C driver against an independent wired-AND pin model.

These are host component tests, not cocotb, RTL, or physical-board evidence.
"""
import ctypes as C
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
Release = C.CFUNCTYPE(None, C.c_void_p, C.c_uint32)
Read = C.CFUNCTYPE(C.c_uint32, C.c_void_p)
Delay = C.CFUNCTYPE(None, C.c_void_p, C.c_uint32)


class Bus(C.Structure):
    _fields_ = [('context', C.c_void_p), ('release', Release), ('read', Read),
                ('delay_us', Delay), ('half_period_us', C.c_uint32),
                ('stretch_timeout_us', C.c_uint32)]


class Target:
    """I2C target decoding actual SDA/SCL edges, including ACK and STOP."""
    def __init__(self, data=b'\x12\x34', address=0x48, nack_byte=None,
                 stretch_us=0, timeout_at=None, scl_stuck=False,
                 sda_stuck=False, recover_after=None):
        self.data = bytes(data)
        self.address = address
        self.nack_byte = nack_byte
        self.stretch_us = stretch_us
        self.timeout_at = timeout_at
        self.scl_stuck = scl_stuck
        self.sda_stuck = sda_stuck
        self.recover_after = recover_after
        self.time = self.stretch_until = 0
        self.control = 3
        self.slave_low = False
        self.levels = self.physical()
        self.phase = 'idle'
        self.bits = self.value = self.index = 0
        self.address_pending = False
        self.starts = self.stops = self.rises = self.attempts = 0
        self.received = []
        self.master_acks = []
        self.edges = []
        self.drives = []
        self.callbacks = (Release(self.drive), Read(self.read), Delay(self.delay))
        self.bus = Bus(None, *self.callbacks, 5, 20)

    def physical(self):
        scl = bool(self.control & 1) and not self.scl_stuck and self.time >= self.stretch_until
        sda = bool(self.control & 2) and not self.slave_low and not self.sda_stuck
        return int(scl) | (int(sda) << 1)

    def refresh(self):
        old, new = self.levels, self.physical()
        self.levels = new
        if old == new:
            return
        self.edges.append((self.time, new))
        if old & 1 and new & 1:
            if old & 2 and not new & 2:
                self.starts += 1
                self.phase, self.bits, self.value = 'receive', 0, 0
                self.address_pending = True
            elif not old & 2 and new & 2:
                self.stops += 1
                self.phase = 'idle'
                self.slave_low = False
        elif not old & 1 and new & 1:
            self.rises += 1
            if self.recover_after and self.rises >= self.recover_after:
                self.sda_stuck = False
            if self.phase == 'receive':
                self.value = (self.value << 1) | bool(new & 2)
                self.bits += 1
                if self.bits == 8:
                    self.received.append(self.value)
                    self.ack = len(self.received) != self.nack_byte
                    if self.address_pending:
                        self.ack &= self.value >> 1 == self.address
                        self.next_phase = 'send' if self.value & 1 else 'receive'
                        self.index = 0
                        self.address_pending = False
                    else:
                        self.next_phase = 'receive'
                    if not self.ack:
                        self.next_phase = 'idle'
            elif self.phase == 'send':
                self.bits += 1
            elif self.phase == 'master_ack':
                self.master_acks.append(not bool(new & 2))
        elif old & 1 and not new & 1:
            if self.phase == 'receive' and self.bits == 8:
                self.phase = 'target_ack'
                self.slave_low = bool(self.ack)
            elif self.phase == 'target_ack':
                self.phase, self.bits, self.value = self.next_phase, 0, 0
                self.slave_low = self.phase == 'send' and not bool(self.byte() & 0x80)
            elif self.phase == 'send':
                if self.bits == 8:
                    self.phase = 'master_ack'
                    self.slave_low = False
                else:
                    self.slave_low = not bool(self.byte() & (0x80 >> self.bits))
            elif self.phase == 'master_ack':
                if self.master_acks[-1]:
                    self.index += 1
                    self.phase, self.bits = 'send', 0
                    self.slave_low = not bool(self.byte() & 0x80)
                else:
                    self.phase = 'idle'
                    self.slave_low = False
        # A target changes SDA only after a falling clock edge. Reflect that
        # level without inventing an extra controller transition.
        self.levels = self.physical()

    def byte(self):
        return self.data[self.index] if self.index < len(self.data) else 0xff

    def drive(self, _, mask):
        self.refresh()
        if mask & 1 and not self.control & 1:
            self.attempts += 1
            if self.attempts == self.timeout_at:
                self.scl_stuck = True
            self.stretch_until = self.time + self.stretch_us
        self.control = mask
        self.drives.append(mask)
        self.refresh()

    def read(self, _):
        self.refresh()
        return self.physical()

    def delay(self, _, microseconds):
        self.time += microseconds
        self.refresh()


class I2CTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        library = Path(cls.temporary.name) / 'i2c.so'
        subprocess.run(['/usr/bin/gcc', '-std=c11', '-O2', '-shared', '-fPIC',
                        '-Wall', '-Wextra', '-Werror', str(ROOT / 'firmware/application/i2c.c'),
                        '-o', str(library)], check=True, timeout=30)
        cls.lib = C.CDLL(str(library))
        cls.lib.nx_i2c_transfer.argtypes = [C.POINTER(Bus), C.c_uint8, C.c_void_p,
                                           C.c_size_t, C.c_void_p, C.c_size_t]
        cls.lib.nx_i2c_recover.argtypes = [C.POINTER(Bus)]

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def transfer(self, target, tx=b'', count=2, address=0x48):
        source = (C.c_uint8 * len(tx)).from_buffer_copy(tx)
        received = (C.c_uint8 * count)(*([0xa5] * count))
        rc = self.lib.nx_i2c_transfer(C.byref(target.bus), address,
                                     source if tx else None, len(tx),
                                     received if count else None, count)
        self.assertTrue(all(0 <= mask <= 3 for mask in target.drives))
        self.assertEqual(target.control, 3)
        return rc, bytes(received)

    def test_read_actual_bytes_and_final_nack(self):
        t = Target(b'\x00\xff\x80\x01')
        self.assertEqual(self.transfer(t, count=4), (0, t.data))
        self.assertEqual(t.received, [0x91])
        self.assertEqual(t.master_acks, [True, True, True, False])
        self.assertEqual((t.starts, t.stops), (1, 1))

    def test_write_and_repeated_start(self):
        t = Target()
        self.assertEqual(self.transfer(t, tx=b'\x03\x7f'), (0, b'\x12\x34'))
        self.assertEqual(t.received, [0x90, 0x03, 0x7f, 0x91])
        self.assertEqual((t.starts, t.stops), (2, 1))

    def test_write_only(self):
        t = Target()
        self.assertEqual(self.transfer(t, tx=b'\x01\xfe', count=0), (0, b''))
        self.assertEqual(t.received, [0x90, 0x01, 0xfe])
        self.assertEqual(t.master_acks, [])

    def test_one_byte_read(self):
        t = Target(b'\x67')
        self.assertEqual(self.transfer(t, count=1), (0, t.data))
        self.assertEqual(t.master_acks, [False])

    def test_clock_stretch_and_minimum_clock_intervals(self):
        t = Target(stretch_us=7)
        self.assertEqual(self.transfer(t), (0, t.data))
        clock = [(time, levels & 1) for time, levels in t.edges]
        changes = [clock[0]]
        for row in clock[1:]:
            if row[1] != changes[-1][1]:
                changes.append(row)
        for a, b in zip(changes, changes[1:]):
            self.assertGreaterEqual(b[0] - a[0], 5)

    def test_address_data_and_repeated_address_nack(self):
        for byte in (1, 2, 3):
            with self.subTest(byte=byte):
                t = Target(nack_byte=byte)
                self.assertEqual(self.transfer(t, tx=b'\x00'), (2, b'\xa5\xa5'))
                self.assertEqual(t.stops, 1)

    def test_disconnected_target_does_not_publish(self):
        t = Target(address=0x49)
        self.assertEqual(self.transfer(t), (2, b'\xa5\xa5'))

    def test_stuck_clock_is_bounded(self):
        t = Target(scl_stuck=True)
        self.assertEqual(self.transfer(t), (3, b'\xa5\xa5'))
        self.assertLessEqual(t.time, t.bus.stretch_timeout_us)

    def test_mid_read_timeout_does_not_publish_partial_buffer(self):
        t = Target(timeout_at=19)
        self.assertEqual(self.transfer(t), (3, b'\xa5\xa5'))
        self.assertEqual(t.master_acks, [True])
        self.assertLess(t.time, 1000)

    def test_stop_timeout_does_not_publish_complete_buffer(self):
        t = Target(timeout_at=28)  # address 9 clocks, data 18, STOP 1
        self.assertEqual(self.transfer(t), (3, b'\xa5\xa5'))
        self.assertEqual(t.master_acks, [True, False])

    def test_stuck_clock_recovery_requires_fault_removal(self):
        t = Target(scl_stuck=True)
        self.assertEqual(self.lib.nx_i2c_recover(C.byref(t.bus)), 3)
        self.assertEqual(t.control, 3)
        t.scl_stuck = False
        self.assertEqual(self.lib.nx_i2c_recover(C.byref(t.bus)), 0)
        self.assertEqual(self.transfer(t), (0, t.data))

    def test_stuck_data_requires_explicit_recovery(self):
        t = Target(sda_stuck=True)
        self.assertEqual(self.transfer(t), (4, b'\xa5\xa5'))
        self.assertEqual(t.rises, 0)
        self.assertEqual(self.lib.nx_i2c_recover(C.byref(t.bus)), 4)
        self.assertLessEqual(t.rises, 10)  # at most nine pulses plus STOP clock
        self.assertEqual(t.control, 3)

    def test_bus_clear_and_next_request(self):
        t = Target(sda_stuck=True, recover_after=9)
        self.assertEqual(self.lib.nx_i2c_recover(C.byref(t.bus)), 0)
        self.assertEqual(self.transfer(t), (0, t.data))

    def test_nack_then_next_request(self):
        t = Target(nack_byte=1)
        self.assertEqual(self.transfer(t)[0], 2)
        t.nack_byte = None
        self.assertEqual(self.transfer(t), (0, t.data))

    def test_maximum_read_and_write(self):
        data = bytes(range(256))
        t = Target(data)
        self.assertEqual(self.transfer(t, tx=data, count=256), (0, data))
        self.assertEqual(t.received, [0x90, *data, 0x91])
        self.assertEqual(t.master_acks, [True] * 255 + [False])

    def test_invalid_inputs_never_touch_bus(self):
        t = Target()
        buf = (C.c_uint8 * 257)()
        for addr, tx, nt, rx, nr in [(0, buf, 1, None, 0), (0x78, buf, 1, None, 0),
                                     (0x48, None, 0, None, 0), (0x48, None, 1, None, 0),
                                     (0x48, None, 0, None, 1), (0x48, buf, 257, None, 0),
                                     (0x48, None, 0, buf, 257)]:
            self.assertEqual(self.lib.nx_i2c_transfer(C.byref(t.bus), addr, tx, nt, rx, nr), 1)
        for period, timeout in [(0, 20), (4, 20), (5, 0), (5, 1000001)]:
            t.bus.half_period_us, t.bus.stretch_timeout_us = period, timeout
            self.assertEqual(self.lib.nx_i2c_transfer(C.byref(t.bus), 0x48, buf, 1, None, 0), 1)
        self.assertEqual(t.drives, [])


if __name__ == '__main__':
    unittest.main()
