import copy
from pathlib import Path
import struct
import sys
import unittest
import zlib
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts/pds'))
from ddr_data_protocol import Decoder
from bandwidth import physical_workloads,WORKLOADS

class RawPhysicalWorkloads(unittest.TestCase):
    def fixture(self):
        packets=[];write=2**32;read=2**33
        for mode in range(1,7):
            for point in range(3):
                seq=(mode-1)*3+point
                if mode!=1:write+=128
                if mode!=2:read+=256
                words=[0]*64
                words[:4]=[0x31443244,seq,0x1130,0]
                cycles=seq*625000000
                words[45:51]=[cycles&0xffffffff,cycles>>32,1,3,0x10002,0]
                words[51:58]=[write&0xffffffff,write>>32,read&0xffffffff,read>>32,mode,point*625000000,0]
                payload=struct.pack('<64I',*words)
                packets.append(payload+struct.pack('<I',zlib.crc32(payload)))
        raw=b''.join(packets);frames=Decoder().feed(raw)
        for i,f in enumerate(frames):f['host_elapsed_s']=i*5.
        return {'frames':frames,'await_boot':True},raw
    def test_original_bytes_and_high_counters_produce_all_workloads(self):
        result=physical_workloads(*self.fixture())
        self.assertEqual(set(result),set(WORKLOADS.values()))
        self.assertEqual(result['sequential_read']['result']['payload_bytes'],512)
        self.assertEqual(result['sequential_write']['result']['payload_bytes'],256)
    def test_summary_tampering_without_uart_change_rejected(self):
        capture,raw=self.fixture();capture['frames'][1]['read_payload_bytes']+=1
        with self.assertRaises(ValueError):physical_workloads(capture,raw)
    def test_corrupt_uart_and_missing_workload_rejected(self):
        capture,raw=self.fixture();corrupt=bytearray(raw);corrupt[100]^=1
        with self.assertRaises(ValueError):physical_workloads(capture,bytes(corrupt))
        with self.assertRaises(ValueError):physical_workloads({'frames':capture['frames'][:-3],'await_boot':True},raw[:-780])
    def test_legacy_bist_is_not_adapter_bandwidth(self):
        capture,raw=self.fixture();payload=bytearray(raw[:256]);struct.pack_into('<I',payload,49*4,0x10001)
        altered=bytes(payload)+struct.pack('<I',zlib.crc32(payload))+raw[260:]
        capture['frames'][0]=dict(Decoder().feed(altered[:260])[0],host_elapsed_s=0.)
        with self.assertRaises(ValueError):physical_workloads(capture,altered)
    def test_phy_snapshot_retains_lane_and_high_bits(self):
        capture,raw=self.fixture();words=list(struct.unpack('<64I',raw[:256]))
        words[58]=0x12345678;words[59]=0x03002001
        words[60]=0x80000000;words[61]=0x00010000
        words[62]=(1<<31)|(7<<25)|(9<<21)|(5<<17);words[63]=0xabcdef01
        payload=struct.pack('<64I',*words);frame=payload+struct.pack('<I',zlib.crc32(payload))
        f=Decoder().feed(frame)[0]
        self.assertTrue(f['first_phy_fault_valid']);self.assertEqual(f['first_phy_retry'],7)
        self.assertEqual(f['first_phy_wrlvl_lane_mask'],5)
        self.assertEqual(f['first_phy_rdel_lane_mask'],1)
        self.assertEqual(f['first_phy_calib']>>30,9)
