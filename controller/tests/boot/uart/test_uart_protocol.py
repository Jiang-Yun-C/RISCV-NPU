import ctypes
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib

ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'software/boot'),str(ROOT/'tests/cocotb'),str(ROOT/'tests/boot/uart')]
from uart_protocol import *
from common.checks import Checks
from scoreboard import observe
from waveform import decode
from download_uart import download
from generate_fixtures import generate

class ProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();p=Path(cls.tmp.name)
        (p/'check.c').write_text('#include "protocol.h"\nint valid(uint32_t a,uint32_t n,uint32_t e){return nx_image_range(a,n,e);}\nuint32_t checksum(const uint8_t *p,uint32_t n){uint32_t c=~0u;for(uint32_t i=0;i<n;i++)c=nx_crc_byte(c,p[i]);return ~c;}\n')
        subprocess.run(['/usr/bin/gcc','-shared','-fPIC','-Wall','-Werror','-I',str(ROOT/'firmware/boot/uart_loader'),str(p/'check.c'),'-o',str(p/'check.so')],check=True,capture_output=True)
        cls.lib=ctypes.CDLL(str(p/'check.so'));cls.lib.checksum.restype=ctypes.c_uint32
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def test_crc_independent_known_and_packet(self):
        for b in (b'',b'123456789',bytes(range(256)),packet(DATA,1,BASE,3,payload=b'abc')):
            self.assertEqual(self.lib.checksum(b,len(b)),zlib.crc32(b))
        self.assertEqual(self.lib.checksum(b'123456789',9),0xcbf43926)
    def test_c_host_ranges_boundaries(self):
        for a,n,e in [(BASE,4,BASE),(LIMIT-4,4,LIMIT-4),(BASE,65536,BASE+65532),
                      (BASE,0,BASE),(BASE,3,BASE),(BASE,65537,BASE),(BASE+1,4,BASE+1),
                      (BASE,16,BASE+1),(BASE,16,BASE+16),(BASE,16,BASE-4),(LIMIT-4,8,LIMIT-4),
                      (0xfffffff0,64,0xfffffff0),(0x10000,64,0x10000),(0xb8000000,4,0xb8000000)]:
            with self.subTest(a=a,n=n,e=e):self.assertEqual(bool(self.lib.valid(a,n,e)),image_range(a,n,e))
    def test_download_chunk_and_tail(self):
        image=bytes(range(256))*8+b'end!';packets=list(download_packets(image))
        self.assertEqual(len(packets),11)
        chunks=[]
        for i,p in enumerate(packets[1:-1],1):
            fields=struct.unpack_from('<6I',p,4)
            self.assertEqual(fields[0:3],(DATA,i,BASE+len(b''.join(chunks))))
            self.assertEqual(zlib.crc32(p[:-4]),struct.unpack_from('<I',p,len(p)-4)[0]);chunks.append(p[28:-4])
        self.assertEqual(b''.join(chunks),image)
    def test_invalid_image_and_payload(self):
        for args in [(b'',BASE,BASE),(b'1234',0x10000,0x10000),(b'1234',BASE,BASE+4)]:
            with self.assertRaises(ValueError):list(download_packets(*args))
        with self.assertRaises(ValueError):packet(DATA,1,BASE,2,payload=b'a')
    def test_ack_crc_and_shape(self):
        raw=struct.pack('<4s3I',b'NXAK',2,DUP,3);wire=raw+struct.pack('<I',zlib.crc32(raw))
        self.assertEqual(response(wire),(2,DUP,3))
        for bad in (wire[:-1],bytes([wire[0]^1])+wire[1:],wire[:-1]+bytes([wire[-1]^1])):
            with self.assertRaises(ValueError):response(bad)
    def test_uart_vcd_decoder_all_bytes(self):
        bit=64*10000;edges=[(0,1)];t=10000;level=1
        for byte in range(256):
            for value in [0,*[(byte>>i)&1 for i in range(8)],1]:
                if value!=level:edges.append((t,value));level=value
                t+=bit
            t+=bit
        self.assertEqual(decode(edges,64),list(range(256)))
    def test_uart_waveform_missing_edges_rejected(self):
        with self.assertRaises(ValueError):decode([(0,1),(134035000,0),(140485000,0)],64)
    def test_frozen_fixtures_rebuild(self):
        frozen=ROOT/'tests/cocotb/fixtures/uart_boot'
        apps={n:frozen/f'app-{n}.bin' for n in ('A','B')}
        with tempfile.TemporaryDirectory() as tmp:
            for profile in ('smoke','control','preload'):
                out=generate(Path(tmp)/profile,apps,profile)
                for name in ('fixture.json','golden.json'):
                    self.assertEqual((out/name).read_bytes(),(frozen/profile/name).read_bytes())
    def test_host_retry_lost_ack_and_duplicate(self):
        class Port:
            def __init__(self):self.wires=[];self.pending=b'';self.lost=False
            def write(self,wire):
                self.wires.append(wire);cmd,seq=struct.unpack_from('<2I',wire,4)
                if cmd==DATA and not self.lost:self.lost=True;return
                status=DUP if cmd==DATA else OK
                nxt=1 if cmd==BEGIN else seq+1 if cmd==DATA else seq
                raw=struct.pack('<4s3I',b'NXAK',seq,status,nxt)
                self.pending=b'boot text\n'+raw+struct.pack('<I',zlib.crc32(raw))
            def flush(self):pass
            def read(self,n):b=self.pending[:n];self.pending=self.pending[n:];return b
        p=Port();result=download(p,b'code',timeout=0.005)
        self.assertEqual(result['bytes'],4)
        self.assertEqual(len(p.wires),4)
        self.assertEqual(p.wires[1],p.wires[2])
    def test_host_does_not_repeat_uncertain_run(self):
        class Port:
            def __init__(self):self.wires=[];self.pending=b''
            def write(self,wire):
                self.wires.append(wire);cmd,seq=struct.unpack_from('<2I',wire,4)
                if cmd==RUN:return
                raw=struct.pack('<4s3I',b'NXAK',seq,OK,1 if cmd==BEGIN else seq+1)
                self.pending=raw+struct.pack('<I',zlib.crc32(raw))
            def flush(self):pass
            def read(self,n):b=self.pending[:n];self.pending=self.pending[n:];return b
        p=Port()
        with self.assertRaises(TimeoutError):download(p,b'code',timeout=0.005)
        self.assertEqual(sum(struct.unpack_from('<I',w,4)[0]==RUN for w in p.wires),1)
    def test_monitor_detects_illegal_and_missing_response(self):
        good='1,DA,3019898880,0,0\n2,DW,65,1,1\n3,DB,0,0,0\n'
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'trace.csv';p.write_text('cycle,kind,a,b,c\n'+good)
            self.assertEqual(observe(p,Checks())['loaded'][0][1:],(BASE,65))
            for bad in [good.replace('3019898880','65536'),good.replace('65,1,1','65,2,1'),
                        good.replace('3,DB,0,0,0\n',''),good.replace('3,DB,0','3,DB,2')]:
                p.write_text('cycle,kind,a,b,c\n'+bad)
                with self.assertRaises(AssertionError):observe(p,Checks())

if __name__=='__main__':unittest.main()
