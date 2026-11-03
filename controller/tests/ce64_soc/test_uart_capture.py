"""Capture acquisition boundary and fail-closed physical serial checks."""
import importlib.util,struct,tempfile,unittest,zlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('capture',ROOT/'scripts/pds/windows_ce64_uart.py')
capture=importlib.util.module_from_spec(spec);spec.loader.exec_module(capture)
def packet(item,value):
    body=struct.pack('<4I',0x3245434e,0,128<<16|item,value)
    return body+struct.pack('<I',zlib.crc32(body))
class Device:
    def __init__(self,data):self.data=data
    @property
    def in_waiting(self):return len(self.data)
    def read(self,n):data,self.data=self.data[:n],self.data[n:];return data
class CaptureChecks(unittest.TestCase):
    def run_link(self,data,action):
        with tempfile.TemporaryDirectory() as tmp:
            link=capture.Link(Device(data),Path(tmp)/'uart.json')
            try:action(link)
            finally:link.close()
    def test_initial_fragment_then_complete_epoch(self):
        words=[0]*64;words[:4]=[0x34364543,2,0,0]
        data=b''.join(packet(i,0) for i in range(37,64))+b''.join(packet(i,v) for i,v in enumerate(words))
        def check(link):
            link.pump();self.assertEqual(link.initial_telemetry_fragment_words,27)
            self.assertEqual([s['words'] for s in link.snapshots],[words])
            self.assertEqual(link.record_count,91)
        self.run_link(data,check)
    def test_missing_word_after_epoch_start_rejected(self):
        def check(link):
            with self.assertRaisesRegex(RuntimeError,'Missing/reordered'):link.pump()
        self.run_link(packet(0,0x34364543)+packet(2,0),check)
    def test_bad_crc_in_initial_fragment_rejected(self):
        data=bytearray(packet(37,0));data[-1]^=1
        def check(link):
            with self.assertRaisesRegex(RuntimeError,'CRC failure'):link.pump()
        self.run_link(bytes(data),check)
    def test_native_quarantine_health_rejected(self):
        words=[0]*64;words[:4]=[0x34364543,2,64,0]
        def check(link):
            with self.assertRaisesRegex(RuntimeError,'native/BIST/PHY fault'):link.pump()
        self.run_link(b''.join(packet(i,v) for i,v in enumerate(words)),check)
    def test_paired_readback_wrong_DDR_crc_rejected(self):
        payload=bytes(range(256))*2
        def ack(sequence,value):
            body=struct.pack('<4I',0x324b4341,sequence,0,value)
            return body+struct.pack('<I',zlib.crc32(body))
        class PairedDevice(Device):
            def write(self,data):return len(data)
            def flush(self):pass
        with tempfile.TemporaryDirectory() as tmp:
            # Both serial CRCs are correct; the independently returned DDR
            # payload CRC is wrong. A valid write ACK cannot hide that fault.
            dev=PairedDevice(ack(7,0)+ack(8,zlib.crc32(payload)^1))
            link=capture.Link(dev,Path(tmp)/'uart.json')
            try:
                with self.assertRaisesRegex(RuntimeError,'readback ACK or CRC mismatch'):
                    link.write_readback(0xa8002000,payload,7)
            finally:link.close()
    def test_unexpected_normal_timeout_rejected_before_hour(self):
        body=struct.pack('<4I',0x3245434e,0,11<<16,(-7)&0xffffffff)
        data=body+struct.pack('<I',zlib.crc32(body))
        def check(link):
            link.expected_control_status={11:0}
            with self.assertRaisesRegex(RuntimeError,'Frozen control status mismatch'):link.pump()
        self.run_link(data,check)
if __name__=='__main__':unittest.main()
