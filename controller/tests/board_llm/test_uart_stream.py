import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import zlib
sys.path[:0]=[str(Path(__file__).resolve().parents[2]),str(Path(__file__).parent)]
from software.boot.uart_stream import Sender,frame,decode_ack,audit_image,DATA,START,RESET,CRC,SEQUENCE,FORMAT,TIMEOUT
from software.boot.sd_image import build
from uart_test_support import ROOT,build_native,launch,PipeLink,stop

ERRORS={'E_MAGIC':5,'E_VERSION':6,'E_ENDIAN':7,'E_LAYOUT':8,'E_CHECKSUM':9,'E_BOUNDS':10,'E_OVERFLOW':11,
        'E_ALIGNMENT':12,'E_RESERVED':13,'E_SHAPE':14,'E_ALIAS':15,'E_DUPLICATE':16,'E_OVERLAP':17,'E_NUMERIC':18,'E_METADATA':19}


def trusted(app,models):
    def array(name,hashes):
        return '#define NX_TRUSTED_'+name.upper()+' '+str(len(hashes))+'\nstatic const uint8_t nx_trusted_'+name+'[][32]={' + ','.join('{'+','.join('0x'+h[i:i+2] for i in range(0,64,2))+'}' for h in hashes)+'};\n'
    dots=[]
    for p in models:
        raw=p.read_bytes();offset=struct.unpack_from('<Q',raw,192+160)[0];dots.append(sum(struct.unpack('64b',raw[offset:offset+64])))
    return '#include <stdint.h>\n'+array('apps',[hashlib.sha256(app).hexdigest()])+array('models',[hashlib.sha256(p.read_bytes()).hexdigest() for p in models])+'static const int32_t nx_trusted_dot[]={'+','.join(map(str,dots))+'};\n'


class UartStream(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.folder=Path(cls.temp.name)
        cls.fixtures=ROOT/'tests/cocotb/fixtures/model_pack';cls.cases=json.loads((cls.fixtures/'manifest.json').read_text())['cases']
        cls.app=bytes(range(32));cls.app_file=cls.folder/'app.bin';cls.app_file.write_bytes(cls.app)
        cls.good=[cls.fixtures/c['pack']['file'] for c in cls.cases if not c.get('expected_error')]
        cls.binary=build_native(cls.folder/'all',trusted(cls.app,cls.good))
        cls.one=build_native(cls.folder/'one',trusted(cls.app,cls.good[:1]))
        cls.records=[]
    @classmethod
    def tearDownClass(cls):
        if os.environ.get('T25_UART_CHECKS'):
            Path(os.environ['T25_UART_CHECKS']).write_text(json.dumps(cls.records,indent=2)+'\n')
        cls.temp.cleanup()
    def image(self,name,model=None,app=None):
        path=self.folder/(name+'.img')
        build(app or self.app_file,model or self.good[0],path,validate=False)
        return path,audit_image(path)
    def execute(self,path,summary,binary=None,drop=None,inject=None,expect=0):
        process=launch(binary or self.binary,len(self.app));link=PipeLink(process,drop)
        sender=Sender(link,.15,.3,4)
        try:
            if inject:inject(sender)
            if expect:
                with self.assertRaises((RuntimeError,TimeoutError)):sender.transfer(path,summary)
            else:
                result=sender.transfer(path,summary);self.assertEqual(result['status'],'PASS')
            process.stdin.close();process.wait(timeout=5)
            report=json.loads(process.stderr.read());self.assertEqual(report['error'],expect)
            self.assertEqual(report['sealed'],0 if expect else 1);self.assertEqual(report['entry'],0 if expect else 0xb4000000)
            if not expect:
                self.assertEqual(report['app_memory_matches'],1);self.assertEqual(report['verified_memory_spans'],report['entries'])
            if drop:self.assertTrue(link.dropped);self.assertGreaterEqual(sender.retransmissions,1)
            self.records.append(dict(case=path.stem,report=report,retransmissions=sender.retransmissions))
            return report
        finally:stop(process)
    def test_all_legal_and_invalid_packs(self):
        for case in self.cases:
            with self.subTest(case=case['case_id']):
                path,summary=self.image(case['case_id'],self.fixtures/case['pack']['file'])
                self.execute(path,summary,expect=ERRORS.get(case.get('expected_error'),0))
    def test_crc_sequence_and_early_start(self):
        path,summary=self.image('frame-rejections');payload=path.read_bytes()[:512]
        def inject(sender):
            bad=bytearray(frame(DATA,0,1,payload));bad[40]^=1;sender._write(bad)
            self.assertEqual(sender._ack(1,2)[0],CRC)
            sender._write(frame(DATA,0,9,payload));self.assertEqual(sender._ack(9,2)[0],SEQUENCE)
            sender._write(frame(START,0,1));self.assertEqual(sender._ack(1,2)[0],FORMAT)
        self.execute(path,summary,inject=inject)
    def test_lost_middle_and_final_ack(self):
        for sequence in (1,audit_image(self.image('drop-probe')[0])['sectors']):
            with self.subTest(sequence=sequence):
                path,summary=self.image('lost-ack-'+str(sequence));self.execute(path,summary,drop=sequence)
    def test_partial_frame_timeout_then_retry(self):
        path,summary=self.image('partial-frame')
        def inject(sender):
            sender._write(frame(DATA,0,1,path.read_bytes()[:512])[:70])
            self.assertEqual(sender._ack(1,3)[0],TIMEOUT)
        self.execute(path,summary,inject=inject)
    def test_untrusted_application_and_model(self):
        app=self.folder/'untrusted-app';app.write_bytes(b'X'+self.app[1:])
        path,summary=self.image('untrusted-app',app=app);self.execute(path,summary,expect=9)
        path,summary=self.image('untrusted-model',self.good[1]);self.execute(path,summary,binary=self.one,expect=9)
    def test_reset_control(self):
        process=launch(self.binary,len(self.app));sender=Sender(PipeLink(process),.15,.3,4)
        try:
            sender._write(frame(RESET,0,0));self.assertEqual(sender._ack(0,2),(0,0,0))
            process.wait(timeout=5);self.assertEqual(process.returncode,91,'Actual loader invoked platform reset callback')
            self.records.append(dict(case='reset-control',reset_callback=True))
        finally:stop(process)
    def test_lost_start_ack_is_not_retried(self):
        path,summary=self.image('lost-start-ack');process=launch(self.binary,len(self.app))
        link=PipeLink(process,summary['sectors']+1);sender=Sender(link,.15,.3,4)
        try:
            with self.assertRaises(TimeoutError):sender.transfer(path,summary)
            process.stdin.close();process.wait(timeout=5);report=json.loads(process.stderr.read())
            self.assertTrue(link.dropped);self.assertEqual(report['error'],0);self.assertEqual(report['entry'],0xb4000000)
            self.assertEqual(sender.retransmissions,0);self.assertEqual(sender.tx_bytes,536*(summary['sectors']+1))
            self.records.append(dict(case='lost-start-ack',report=report,start_attempts=1))
        finally:stop(process)
    def test_host_rejects_bad_source_and_ack(self):
        path,_=self.image('bad-source');raw=bytearray(path.read_bytes());raw[-512]^=1;path.write_bytes(raw)
        with self.assertRaises(ValueError):audit_image(path)
        with self.assertRaises(ValueError):decode_ack(bytes(24))
    def test_board_rejects_relocated_application_or_entry(self):
        for label,offset,value in [('base',28,0xb4001000),('entry',32,0xb4000004),('size',24,8388609)]:
            with self.subTest(field=label):
                path,summary=self.image('bad-app-'+label);raw=bytearray(path.read_bytes())
                struct.pack_into('<I',raw,offset,value);struct.pack_into('<I',raw,508,zlib.crc32(raw[:508]));path.write_bytes(raw)
                with self.assertRaises(ValueError):audit_image(path)
                # Bypass host audit deliberately to test board-side enforcement.
                summary['sha256']=hashlib.sha256(raw).hexdigest();self.execute(path,summary,expect=10)


if __name__=='__main__':unittest.main()
