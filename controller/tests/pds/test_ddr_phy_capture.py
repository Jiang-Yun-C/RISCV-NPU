"""Exercise passive capture/boot isolation and raw replay without board access."""
import json
import contextlib
import io
from pathlib import Path
import struct
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import zlib

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts/pds'))
import windows_ddr_uart
import analyze_ddr_phy

def frame(seq,cycles,beats):
    words=[0]*64
    words[:10]=[0x31503244,seq,0x1130,0,beats,beats,beats,beats,cycles,0]
    payload=struct.pack('<64I',*words)
    return payload+struct.pack('<I',zlib.crc32(payload)&0xffffffff)

class CaptureTest(unittest.TestCase):
    def capture(self,out,chunks,guard=True,extra=()):
        class Serial:
            def __init__(self,*args,**kwargs): self.closed=False
            def open(self):
                assert not self.dtr and not self.rts
            def reset_input_buffer(self): pass
            @property
            def in_waiting(self): return len(chunks[0]) if chunks else 0
            def read(self,count): return chunks.pop(0) if chunks else b''
            def write(self,data): raise AssertionError('Passive capture transmitted')
            def close(self): self.closed=True
        ports=types.ModuleType('serial.tools.list_ports')
        ports.comports=lambda:[types.SimpleNamespace(vid=0x10c4,pid=0xea60,device='COM10',serial_number='0001',description='mock CP2102')]
        serial=types.ModuleType('serial'); serial.Serial=Serial
        serial_tools=types.ModuleType('serial.tools'); serial_tools.list_ports=ports
        clock=[0.0]
        def now(): clock[0]+=0.05; return clock[0]
        args=['capture','--dependency-dir','unused','--protocol','d2p1','--port','COM10',
              '--seconds','2','--after-first-frame','0.35','--out',str(out)]
        if guard: args+=['--await-boot']
        args+=list(extra)
        with patch.dict(sys.modules,{'serial':serial,'serial.tools':serial_tools,'serial.tools.list_ports':ports}), \
             patch.object(sys,'argv',args),patch.object(windows_ddr_uart.time,'monotonic',now):
            rc=windows_ddr_uart.main()
        return rc,json.loads(out.read_text())

    def test_boot_excludes_previous_image_and_raw_replay_matches(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory); cap=p/'capture.json'
            rc,c=self.capture(cap,[frame(400,9000,100),frame(0,0,0),frame(1,1000,16),frame(2,2000,32)])
            self.assertEqual(rc,0)
            self.assertEqual(c['preboot_valid_frames'],1)
            self.assertEqual([f['sequence'] for f in c['frames']],[0,1,2])
            self.assertFalse(c['writes_performed'])
            program=p/'program.json'; inputs=p/'inputs.json'; out=p/'summary.json'
            program.write_text(json.dumps({'status':'PASS','done_bit':True,'svf_sha256':'mock'}))
            inputs.write_text(json.dumps({'program_svf_sha256':'mock'}))
            argv=['analyze',str(cap),str(program),str(inputs),'--out',str(out)]
            with patch.object(sys,'argv',argv): analyze_ddr_phy.main()
            self.assertEqual(json.loads(out.read_text())['status'],'PASS_OBSERVED_SHORT_RW')
            # Raw alteration must be rejected before any qualification status.
            cap.with_suffix('.bin').write_bytes(b'corrupt')
            with patch.object(sys,'argv',argv),self.assertRaises(ValueError): analyze_ddr_phy.main()

    def test_missing_boot_cannot_use_existing_frames(self):
        with tempfile.TemporaryDirectory() as directory:
            rc,c=self.capture(Path(directory)/'capture.json',[frame(800,1000,100)])
            self.assertEqual(rc,1)
            self.assertEqual(c['status'],'NO_VALIDATED_DDR_TELEMETRY')
            self.assertEqual(c['valid_frames'],0)
            self.assertEqual(c['preboot_valid_frames'],1)

    def test_graceful_stop_keeps_exact_raw_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory);stop=p/'capture.stop';stop.touch()
            raw=frame(0,0,0)
            rc,c=self.capture(p/'capture.json',[raw,frame(1,1000,16)],extra=['--stop-file',str(stop)])
            self.assertEqual(rc,0)
            self.assertTrue(c['stopped_by_request'])
            self.assertEqual((p/'capture.bin').read_bytes(),raw)
            self.assertEqual(c['valid_frames'],1)

    def test_training_failure_progress_does_not_depend_on_workload_change(self):
        def no_init(raw):
            words=list(struct.unpack('<64I',raw[:256]));words[2]&=~4096
            words[2]|=8<<24
            payload=struct.pack('<64I',*words)
            return payload+struct.pack('<I',zlib.crc32(payload))
        with tempfile.TemporaryDirectory() as directory:
            output=io.StringIO()
            with contextlib.redirect_stdout(output):
                rc,c=self.capture(Path(directory)/'capture.json',[no_init(frame(0,0,0))],
                    extra=['--init-timeout','0.1','--progress'])
            self.assertEqual(rc,0)
            self.assertTrue(c['stopped_on_init_timeout'])
            event=next(json.loads(line) for line in output.getvalue().splitlines()
                       if json.loads(line).get('event')=='WORKLOAD_PROGRESS')
            self.assertFalse(event['init_done'])
            self.assertEqual(event['training_retries'],8)

    def test_corrupt_reset_stops_capture_and_preserves_crc_valid_raw(self):
        words=[0]*64
        words[0]=0x31443244;words[47]=512;words[49]=0x10002
        payload=struct.pack('<64I',*words)
        raw=payload+struct.pack('<I',zlib.crc32(payload))
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)/'capture.json'
            with contextlib.redirect_stdout(io.StringIO()):
                rc,c=self.capture(output,[raw],extra=['--protocol','d2d1','--stop-on-test-failure'])
            self.assertEqual(rc,0)  # Capture success is independent of qualification.
            self.assertTrue(c['stopped_on_corrupt_reset_snapshot'])
            self.assertEqual(c['valid_frames'],1)
            self.assertEqual(c['crc_failures'],0)
            self.assertEqual(c['frames'][0]['verified_passes'],512)
            self.assertEqual(output.with_suffix('.bin').read_bytes(),raw)

if __name__=='__main__': unittest.main()
