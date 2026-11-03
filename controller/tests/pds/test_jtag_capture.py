"""Ensure diagnostic payload capture cannot bypass native ID/DONE checks."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'scripts/pds'))
import windows_cmsis_jtag as programming
import windows_cram_reset as clearing


class FakeJtag:
    instances = []
    bad_id = False
    done = True

    def __init__(self, dependencies, hz):
        self.idcode = 0x10603899
        self.hz = hz
        self.packets = self.shifted = 0
        self.opcode = None
        self.scans = []
        self.instructions = []
        self.idle_counts = []
        self.instances.append(self)

    def set_frequency(self, hz): self.hz = hz
    def goto(self, state): pass
    def idle(self, count, state='IDLE'): self.idle_counts.append(count)
    def instruction(self, opcode): self.instructions.append(opcode)
    def close(self): pass

    def register(self, opcode): return 0x1ffca0 if self.done else 0x180c80

    def scan(self, kind, nbits, data, capture=True):
        self.scans.append((kind, nbits, capture, hashlib.sha256(data).hexdigest()))
        if kind == 'IR': self.opcode = int.from_bytes(data, 'little')
        if kind == 'DR' and nbits == 32:
            value = (0x10603898 if self.bad_id else self.idcode) if self.opcode == 0x283 else self.register(self.opcode)
            return value.to_bytes(4,'little')
        return b'\0'*((nbits+7)//8) if capture else b''


class CaptureGuard(unittest.TestCase):
    def invoke(self, capture=False, bad_id=False, done=True):
        FakeJtag.instances = []
        FakeJtag.bad_id = bad_id
        FakeJtag.done = done
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            payload = 'A5'*125001
            svf = folder/'cram.svf'
            svf.write_text('TRST OFF; ENDIR IDLE; ENDDR IDLE; STATE RESET; STATE IDLE; '
                'FREQUENCY 1E5 HZ; SIR 10 TDI (283); '
                'SDR 32 TDI (00000000) TDO (00603899) MASK (0FFFFFFF); '
                'SIR 10 TDI (28A); RUNTEST IDLE 100 TCK; SIR 10 TDI (28B); '
                'RUNTEST IDLE 500000 TCK; SDR 1000008 TDI ('+payload+'); '
                'RUNTEST RESET 100 TCK; RUNTEST IDLE 10000 TCK; SIR 10 TDI (28D); '
                'SIR 10 TDI (159); SDR 32 TDI (00000000) TDO (00001000) MASK (00001000);')
            out = folder/'result.json'
            args = ['programming','--dependency-dir',temporary,'--out',str(out),'--svf',str(svf),
                    '--hz','100000','--snapshot-after-payload']
            if capture: args.append('--capture-payload')
            with patch.object(programming,'Jtag',FakeJtag), patch.object(sys,'argv',args), contextlib.redirect_stdout(io.StringIO()):
                code = programming.main()
            return code, json.loads(out.read_text()), FakeJtag.instances[0].scans

    def test_default_payload_remains_uncaptured(self):
        code, result, scans = self.invoke()
        self.assertEqual(code,0)
        self.assertFalse(result['payload_tdo_capture_enabled'])
        self.assertEqual(next(x for x in scans if x[1]==1000008)[2],False)
        self.assertTrue(result['done_bit'])

    def test_capture_preserves_payload_and_native_checks(self):
        plain = self.invoke()
        captured = self.invoke(capture=True)
        self.assertEqual(captured[0],0)
        self.assertEqual(captured[1]['tdo_checks'],plain[1]['tdo_checks'])
        expected = hashlib.sha256(b'\xa5'*125001).hexdigest()
        self.assertEqual(next(x for x in captured[2] if x[1]==1000008)[2:],(True,expected))
        self.assertEqual([x[:2]+x[3:] for x in plain[2]], [x[:2]+x[3:] for x in captured[2]])
        self.assertFalse(captured[1]['flash_modified'])

    def test_wrong_id_is_rejected_with_capture(self):
        code, result, scans = self.invoke(capture=True,bad_id=True)
        self.assertEqual(code,1)
        self.assertIn('TDO comparison failed',result['error'])
        self.assertFalse(any(x[1]==1000008 for x in scans))

    def test_missing_done_is_rejected_with_capture(self):
        code, result, scans = self.invoke(capture=True,done=False)
        self.assertEqual(code,1)
        self.assertEqual(result['status'],'FAIL')
        self.assertEqual(result['tdo_checks'][-1]['actual'],'0x180c80')
        self.assertFalse(result['configuration_snapshots'][0]['done_bit'])

    def invoke_clear(self, done):
        FakeJtag.instances=[]
        FakeJtag.done=done
        with tempfile.TemporaryDirectory() as temporary:
            output=Path(temporary)/'clear.json'
            with patch.object(clearing,'Jtag',FakeJtag), patch.object(sys,'argv',
                ['clearing','--dependency-dir',temporary,'--out',str(output)]), contextlib.redirect_stdout(io.StringIO()):
                code=clearing.main()
            return code,json.loads(output.read_text()),FakeJtag.instances[0]

    def test_clear_uses_only_jrst_and_leaves_no_image(self):
        code,result,j=self.invoke_clear(done=False)
        self.assertEqual(code,0)
        self.assertEqual(j.instructions,[0x28a])
        self.assertEqual(j.idle_counts,[500000])
        self.assertEqual(j.hz,100000)
        self.assertFalse(result['flash_modified'])
        self.assertFalse(result['configuration_frames_written'])

    def test_clear_rejects_done_still_asserted(self):
        code,result,j=self.invoke_clear(done=True)
        self.assertEqual(code,1)
        self.assertEqual(result['status'],'FAIL_DONE_STILL_ASSERTED')


if __name__=='__main__': unittest.main()
