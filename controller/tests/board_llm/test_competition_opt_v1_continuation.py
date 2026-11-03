"""Continuation must retain the real sealed W and reject reset platforms."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
import io
from software.boot.competition_opt_v1_short import sha
from software.boot.competition_opt_v1_continuation import load_continuation, validate_live_snapshot
from scripts.pds.windows_opt04_cleanup import complete
from scripts.run_competition_opt_v1_short import read_response

ROOT = Path(__file__).resolve().parents[2]
PARENT = ROOT / 'evidence/OPT03/opt03-completion-20261018-v2'
BOARD = ROOT / 'evidence/OPT03_BOARD_REVIEW/opt03-candidate-20261018-v2'
GOLD = ROOT / 'evidence/OPT02_GOLDEN/opt02-short-golden-20261018-v1/golden.json'
LIMITS = ROOT / 'configs/t05-thresholds.json'
IDENTITY = json.loads((ROOT / 'evidence/OPT03/opt03-board-20261018-v1/B-identity.json').read_text())


class ContinuationChecks(unittest.TestCase):
    def test_continuous_receive_never_reconfigures_port(self):
        class Reader:
            def __init__(self):self.parts=iter([b'T25 LOGITS\n',b'0123abcd\nT25 RE',b'ADY\n'])
            @property
            def timeout(self):return .02
            @timeout.setter
            def timeout(self,value):raise AssertionError('Changing timeout resets Windows UART configuration')
            def read(self,size):return next(self.parts)
        raw=io.BytesIO()
        self.assertEqual(read_response(Reader(),raw,1),b'T25 LOGITS\n0123abcd\nT25 READY\n')
        self.assertEqual(raw.getvalue(),b'T25 LOGITS\n0123abcd\nT25 READY\n')

    def test_continuous_receive_deadline_is_bounded(self):
        class Clock:
            tick=0
            def monotonic(self):self.tick+=.01;return self.tick
        class Silent:
            def read(self,size):return b''
        with self.assertRaises(TimeoutError):read_response(Silent(),io.BytesIO(),.05,Clock())

    def receipt(self):
        files = dict(completion=PARENT/'manifest.json', board=BOARD/'manifest.json',
                     numeric=PARENT/'numeric.json', service=BOARD/'service.json',
                     raw=BOARD/'service.bin', boot=BOARD/'service.boot.bin')
        return dict(status='READY', mode='OPT03_W_TO_OPT04_SP_PRESSURE', authorization='使用opt04',
                    identity=IDENTITY, ledger_id='8dc211fb999b4c559057ab5114fd6da0',
                    golden_manifest_sha256=sha(GOLD), thresholds_sha256=sha(LIMITS),
                    files={k:dict(path=str(v),sha256=sha(v)) for k,v in files.items()})

    def load(self, receipt):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'continuation.json';path.write_text(json.dumps(receipt))
            return load_continuation(path, IDENTITY, GOLD, LIMITS)

    def test_real_sealed_W_rechecked(self):
        checked=self.load(self.receipt())
        self.assertEqual(checked['W']['metrics']['session'],3)
        self.assertEqual(checked['W']['output_ids'],[7426])
        self.assertEqual(checked['W']['numeric']['compared_elements'],158080)

    def test_changed_dependency_or_ledger_rejected(self):
        for change in ('hash','ledger','identity'):
            receipt=self.receipt()
            if change=='hash':receipt['files']['numeric']['sha256']='0'*64
            elif change=='ledger':receipt['ledger_id']='0'*32
            else:receipt['identity']=dict(IDENTITY,application_sha256='0'*64)
            with self.subTest(change=change), self.assertRaises(ValueError):self.load(receipt)

    def test_live_snapshot_rejects_reset_or_pressure(self):
        old=dict(profile=0,begin_ticks=10,end_ticks=20,words=[100]*64)
        good=copy.deepcopy(old);good['begin_ticks']=30
        validate_live_snapshot(good,old)
        for change in ('clock','pressure','traffic','passes'):
            current=copy.deepcopy(good)
            if change=='clock':current['begin_ticks']=1
            elif change=='pressure':current['profile']=2
            elif change=='traffic':current['words'][48]=0
            else:current['words'][12]=0
            with self.subTest(change=change), self.assertRaises(ValueError):validate_live_snapshot(current,old)

    def test_cleanup_accepts_memory_report_before_ready(self):
        raw=b'T25 TELEMETRY END\nT25 MEMORY committed_bytes=00000000215dc011 \nT25 READY\n'
        self.assertTrue(complete(raw,b'T25 TELEMETRY END\n'))
        self.assertFalse(complete(raw.replace(b'T25 READY\n',b''),b'T25 TELEMETRY END\n'))
        self.assertFalse(complete(b'T25 READY\n',b'T25 TELEMETRY END\n'))


if __name__=='__main__':unittest.main()
