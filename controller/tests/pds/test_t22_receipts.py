"""Prevent configuration-only or altered telemetry receipts closing T22."""
import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'scripts'))
from qualify_t22 import SBIT_HASH, SVF_HASH, assess, verify_native_replay, verify_timing_boundary
from ddr_data_protocol import Decoder


class T22ReplayReceipts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        packets = []
        for i in range(5):
            words = [0]*64
            words[:11] = [0x31443244, i, 0x113c, 0, 1000+i*100,
                          1000+i*100, 100+i*10, 100+i*10,
                          0x0fffff80, 0x0fffff80, 0]
            words[45] = i*25000000
            words[47:51] = [i+1, 3, 0x10001, 0]
            payload = struct.pack('<64I', *words)
            packets.append(payload+struct.pack('<I', zlib.crc32(payload)))
        self.raw = b''.join(packets)
        frames = Decoder().feed(self.raw)
        for i, frame in enumerate(frames):
            frame['host_elapsed_s'] = i*.2
        self.capture = {'protocol':'d2d1', 'frames':frames, 'valid_frames':5,
                        'port':'COM10', 'writes_performed':False,
                        'matching_ports':[{'serial_number':'0001'}],
                        'raw_sha256':hashlib.sha256(self.raw).hexdigest()}
        self.board = {'status':'PASS', 'idcode':'0x10603899', 'done_bit':True,
                      'flash_modified':False, 'svf_sha256':SVF_HASH}
        self.inputs = {'program_svf_sha256':SVF_HASH, 'sbit_sha256':SBIT_HASH,
                       'test_window_bytes':1073741824, 'expected_core_clock_hz':125000000,
                       'capacity_counter_schema':0x10001}
        self.summary = assess(self.capture, self.raw, self.board, self.inputs)
        self.manifest = {'status':'PASS', 'board_replay':self.summary['status']}
        self.save()

    def save(self):
        for name, value in (('uart.json',self.capture), ('board.json',self.board),
                            ('program-inputs.json',self.inputs),
                            ('functional-summary.json',self.summary)):
            (self.path/name).write_text(json.dumps(value))
        (self.path/'uart.bin').write_bytes(self.raw)

    def test_complete_raw_receipt_passes(self):
        self.assertTrue(verify_native_replay(self.path, self.manifest)[0])

    def test_jtag_only_pass_is_rejected(self):
        (self.path/'uart.bin').unlink()
        self.assertFalse(verify_native_replay(self.path, {'status':'PASS'})[0])

    def test_changed_raw_is_rejected(self):
        raw = bytearray(self.raw)
        raw[20] ^= 1
        (self.path/'uart.bin').write_bytes(raw)
        self.assertFalse(verify_native_replay(self.path, self.manifest)[0])

    def test_invented_summary_counter_is_rejected(self):
        self.summary['window']['verified_pass_delta'] += 1
        self.save()
        self.assertFalse(verify_native_replay(self.path, self.manifest)[0])

    def test_wrong_frozen_image_is_rejected(self):
        self.inputs['sbit_sha256'] = 'another-image'
        self.save()
        self.assertFalse(verify_native_replay(self.path, self.manifest)[0])

    def test_wrong_board_uart_is_rejected(self):
        self.capture['port'] = 'COM9'
        self.save()
        self.assertFalse(verify_native_replay(self.path, self.manifest)[0])

    def test_reused_programming_requires_current_readiness(self):
        self.manifest['programming_reused'] = True
        self.assertFalse(verify_native_replay(self.path, self.manifest)[0])

    def test_failed_parent_manifest_cannot_pass(self):
        self.manifest['status'] = 'FAIL'
        self.assertFalse(verify_native_replay(self.path, self.manifest)[0])

    def test_documented_phy_gap_does_not_claim_final_signoff(self):
        timing = {'report_execution':'PASS', 'full_phy_timing_qualification':False,
                  'open_items':['External DDR timing budget'],
                  'unconstrained_inputs':['mem_dq[0]'], 'unconstrained_outputs':[]}
        self.assertTrue(verify_timing_boundary(timing))
        self.assertFalse(timing['full_phy_timing_qualification'])
        timing['full_phy_timing_qualification'] = True
        self.assertFalse(verify_timing_boundary(timing))

    def test_undocumented_phy_gap_cannot_close_platform_handoff(self):
        timing = {'report_execution':'PASS', 'full_phy_timing_qualification':False,
                  'open_items':[], 'unconstrained_inputs':['mem_dq[0]'],
                  'unconstrained_outputs':[]}
        self.assertFalse(verify_timing_boundary(timing))


if __name__=='__main__':
    unittest.main()
