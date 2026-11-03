"""Acceptance boundaries for native125MHz short-window telemetry."""
import hashlib
from pathlib import Path
import struct
import sys
import unittest
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts/pds'))
from analyze_ddr_capacity import assess
from ddr_capacity_protocol import Decoder
from ddr_data_protocol import Decoder as DataDecoder


def packet(sequence, cycles, passes, maximum=0x3f80):
    # Locked/init, window and masks verified; native low PLL bits were cleared.
    flags = 0x1000 | 0x100 | 0x20 | 0x10 | 0x6
    payload = struct.pack('<13IQ', 0x31513244, sequence, flags, 0,
                          1000 + passes * 100, 1000 + passes * 100,
                          100 + passes * 10, 100 + passes * 10,
                          maximum, maximum, passes, 0, 0, cycles)
    return payload + struct.pack('<I', zlib.crc32(payload))


class NativeCapacityAcceptance(unittest.TestCase):
    def test_crc_valid_reset_ghost_counter_or_data_is_rejected(self):
        for index,value in ((47,512),(33,0x08000000)):
            capture,raw,board,inputs=self.data_fixture(schema=0x10002)
            words=[0]*64;words[0]=0x31443244;words[49]=0x10002;words[index]=value
            payload=struct.pack('<64I',*words)
            raw=payload+struct.pack('<I',zlib.crc32(payload))+raw[260:]
            capture['frames']=DataDecoder().feed(raw)
            for i,f in enumerate(capture['frames']):f['host_elapsed_s']=i*.2
            capture['raw_sha256']=hashlib.sha256(raw).hexdigest()
            inputs['capacity_counter_schema']=0x10002
            result=assess(capture,raw,board,inputs)
            self.assertEqual(result['status'],'FAIL_EVIDENCE')
            self.assertFalse(next(c['pass'] for c in result['checks']
                                  if c['name']=='literal_reset_snapshot_purity'))

    def fixture(self, prefix=b'', window=65536):
        raw = prefix + b''.join(packet(i, i * 25000000, i + 1) for i in range(3))
        frames = Decoder().feed(raw)[-3:]
        for i, frame in enumerate(frames):
            frame['host_elapsed_s'] = i * .2
        capture = {'frames': frames, 'valid_frames': 3, 'port': 'COM10',
                   'writes_performed': False, 'matching_ports': [{'serial_number': '0001'}],
                   'raw_sha256': hashlib.sha256(raw).hexdigest()}
        board = {'idcode': '0x10603899', 'status': 'PASS', 'done_bit': True,
                 'flash_modified': False, 'svf_sha256': 'actual-image'}
        inputs = {'program_svf_sha256': 'actual-image', 'test_window_bytes': window,
                  'expected_core_clock_hz': 125000000}
        return capture, raw, board, inputs

    def test_short_window_never_claims_physical_capacity(self):
        result = assess(*self.fixture())
        self.assertEqual(result['status'], 'PASS_SHORT_WINDOW_AND_BYTE_MASK_OBSERVATION_ONLY')
        self.assertIsNone(result['measured_capacity_bytes'])
        self.assertEqual(result['verified_test_window_bytes'], 65536)

    def test_short_addresses_cannot_claim_one_gib(self):
        result = assess(*self.fixture(window=1073741824))
        self.assertEqual(result['status'], 'FAIL_FULL_RANGE_ADDRESS_OBSERVATION')
        self.assertIsNone(result['measured_capacity_bytes'])

    def test_wrong_image_cannot_qualify(self):
        capture, raw, board, inputs = self.fixture()
        board['svf_sha256'] = 'different-image'
        self.assertEqual(assess(capture, raw, board, inputs)['status'], 'FAIL_EVIDENCE')

    def test_prior_image_frames_are_excluded_only_with_boot_guard(self):
        prefix = packet(400, 1000000000, 100) + packet(401, 1025000000, 101)
        capture, raw, board, inputs = self.fixture(prefix)
        self.assertEqual(assess(capture, raw, board, inputs)['status'], 'FAIL_EVIDENCE')
        capture.update(await_boot=True, preboot_valid_frames=2)
        self.assertTrue(assess(capture, raw, board, inputs)['status'].startswith('PASS_SHORT'))

    def test_altered_raw_cannot_qualify(self):
        capture, raw, board, inputs = self.fixture()
        damaged = bytearray(raw)
        damaged[20] ^= 1
        self.assertEqual(assess(capture, bytes(damaged), board, inputs)['status'], 'FAIL_EVIDENCE')

    def test_wrong_nominal_clock_is_rejected(self):
        capture, raw, board, inputs = self.fixture()
        inputs['expected_core_clock_hz'] = 93750000
        self.assertEqual(assess(capture, raw, board, inputs)['status'], 'FAIL_CORE_CLOCK_ESTIMATE')

    def data_fixture(self, schema=0x10001, project_flags=3):
        capture, _, board, inputs = self.fixture(window=1073741824)
        packets=[]
        for i in range(3):
            words=[0]*64
            # Native GPLL/PHYPLL bits are set even without completed data tests.
            words[:11]=[0x31443244,i,0x113c,0,1000+i*100,1000+i*100,
                        100+i*10,100+i*10,0x0fffff80,0x0fffff80,0]
            words[45]=i*25000000
            words[47:51]=[i+1,project_flags,schema,0]
            payload=struct.pack('<64I',*words)
            packets.append(payload+struct.pack('<I',zlib.crc32(payload)))
        raw=b''.join(packets)
        frames=DataDecoder().feed(raw)
        for i, frame in enumerate(frames):frame['host_elapsed_s']=i*.2
        capture.update(protocol='d2d1',frames=frames,raw_sha256=hashlib.sha256(raw).hexdigest())
        inputs['capacity_counter_schema']=0x10001
        return capture,raw,board,inputs

    def test_diagnostic_without_explicit_counters_cannot_qualify(self):
        self.assertEqual(assess(*self.data_fixture(schema=0))['status'],'FAIL_EVIDENCE')

    def test_adapter_counter_schema_requires_matching_input_identity(self):
        capture,raw,board,inputs=self.data_fixture(schema=0x10002)
        self.assertEqual(assess(capture,raw,board,inputs)['status'],'FAIL_EVIDENCE')
        inputs['capacity_counter_schema']=0x10002
        result=assess(capture,raw,board,inputs)
        self.assertEqual(result['status'],'PASS_FULL_CAPACITY_AND_BYTE_MASK_OBSERVATION_ONLY')
        self.assertIn('T23 AXI adapter',result['scope'])

    def test_only_first_zero_cycle_reset_can_have_legacy_schema(self):
        for active_count in (0,1):
            capture,raw,board,inputs=self.data_fixture(schema=0x10002)
            # A reset report contains only magic/schema; retaining live address
            # fields would itself be a corrupt reset report.
            words=[0]*64
            words[0]=0x31443244
            words[4]=active_count
            words[49]=0x10001
            payload=struct.pack('<64I',*words)
            raw=payload+struct.pack('<I',zlib.crc32(payload))+raw[260:]
            capture['frames']=DataDecoder().feed(raw)
            for i,f in enumerate(capture['frames']):f['host_elapsed_s']=i*.2
            capture['raw_sha256']=hashlib.sha256(raw).hexdigest()
            inputs['capacity_counter_schema']=0x10002
            result=assess(capture,raw,board,inputs)
            self.assertEqual(result['status'],'FAIL_EVIDENCE' if active_count else 'PASS_FULL_CAPACITY_AND_BYTE_MASK_OBSERVATION_ONLY')

    def test_native_pll_bits_do_not_imply_completed_mask_test(self):
        self.assertEqual(assess(*self.data_fixture(project_flags=0))['status'],
                         'NO_COMPLETED_CAPACITY_MASK_PASS')

    def test_explicit_full_range_counters_qualify_observation_only(self):
        result=assess(*self.data_fixture())
        self.assertEqual(result['status'],'PASS_FULL_CAPACITY_AND_BYTE_MASK_OBSERVATION_ONLY')
        self.assertEqual(result['measured_capacity_bytes'],1073741824)
        self.assertFalse(result['formal_platform_qualification'])

    def hour_fixture(self, omit_frame=False, retry=False):
        capture, _, board, inputs = self.data_fixture()
        packets = []
        times = []
        for i in range(14401):
            if omit_frame and i == 7200:
                continue
            words = [0] * 64
            words[:4] = [0x31443244, i + 31, 0x1130, 0]
            # Start near overflow and cross it during this continuous window.
            words[4:8] = [(0xfff00000 + i * 300000) & 0xffffffff,
                          (0xfff80000 + i * 200000) & 0xffffffff,
                          i * 18000, i * 12000]
            words[8:10] = [0x0fffff80, 0x0fffff80]
            cycles = i * 31250000
            words[45:47] = [cycles & 0xffffffff, cycles >> 32]
            words[47:51] = [1 + i // 80, 3, 0x10001, 0]
            if retry and i >= 7200:
                words[2] |= 1 << 24
            payload = struct.pack('<64I', *words)
            packets.append(payload + struct.pack('<I', zlib.crc32(payload)))
            times.append(i * .25)
        raw = b''.join(packets)
        frames = DataDecoder().feed(raw)
        for frame, time_s in zip(frames, times):
            frame['host_elapsed_s'] = time_s
        capture.update(frames=frames, valid_frames=len(frames),
                       raw_sha256=hashlib.sha256(raw).hexdigest())
        return capture, raw, board, inputs

    def test_continuous_hour_qualifies_and_unwraps_traffic_counters(self):
        result = assess(*self.hour_fixture())
        self.assertEqual(result['status'], 'PASS_FULL_CAPACITY_MASK_AND_ONE_HOUR_STRESS')
        self.assertEqual(result['window']['counter_deltas']['write_beats'], 14400 * 300000)
        self.assertEqual(result['window']['counter_deltas']['read_beats'], 14400 * 200000)
        self.assertFalse(result['formal_platform_qualification'])

    def test_missing_frame_prevents_one_hour_qualification(self):
        result = assess(*self.hour_fixture(omit_frame=True))
        self.assertEqual(result['status'], 'PASS_FULL_CAPACITY_AND_BYTE_MASK_OBSERVATION_ONLY')
        self.assertFalse(result['one_hour_zero_error_observation'])
        self.assertEqual(result['window']['dropped_frames'], 1)

    def test_training_retry_during_hour_is_rejected(self):
        result = assess(*self.hour_fixture(retry=True))
        self.assertEqual(result['status'], 'FAIL_TRAINING_RESET_DURING_VERIFIED_WINDOW')


if __name__ == '__main__':
    unittest.main()
