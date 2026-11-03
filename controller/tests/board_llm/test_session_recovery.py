import copy
import hashlib
import unittest

from scripts.recover_t25_sessions import audit_capture


class RecoveryCapture(unittest.TestCase):
    def fixture(self):
        raw = b'T25 READY\nT25 ERROR fffffffc\nT25 READY\n'
        actions = [dict(name='sync', kind='sync', command='', status='PASS', start_byte=0, end_byte=10,
                        steps=[], metrics=None, output_ids=None),
                   dict(name='reject-513', kind='bounds-error', command=':ids 1 0', status='PASS',
                        start_byte=10, end_byte=len(raw), steps=[], metrics=None, output_ids=None)]
        capture = dict(status='PASS', raw_bytes=len(raw), raw_sha256=hashlib.sha256(raw).hexdigest(),
                       port_identity=dict(port='COM10', vid=0x10c4, pid=0xea60, serial='0001', baud=500000),
                       programming_performed=False, flash_modified=False, actions=actions)
        plan = dict(actions=[{k: actions[1][k] for k in ('name', 'kind', 'command')}])
        return plan, capture, raw

    def test_raw_negative_case(self):
        plan, capture, raw = self.fixture()
        self.assertEqual(list(audit_capture(plan, capture, raw)), ['sync', 'reject-513'])

    def test_wrong_hash_missing_action_range_and_forged_counters(self):
        plan, capture, raw = self.fixture()
        for change in ('hash', 'missing', 'range', 'counters', 'identity', 'error'):
            bad = copy.deepcopy(capture)
            changed_raw = raw
            if change == 'hash': bad['raw_sha256'] = '0' * 64
            if change == 'missing': bad['actions'].pop()
            if change == 'range': bad['actions'][1]['start_byte'] += 1
            if change == 'counters': bad['actions'][1]['steps'] = [[1, 0]]
            if change == 'identity': bad['port_identity']['serial'] = 'other'
            if change == 'error':
                changed_raw = raw.replace(b'fffffffc', b'ffffffff')
                bad['raw_sha256'] = hashlib.sha256(changed_raw).hexdigest()
            with self.subTest(change=change), self.assertRaises(ValueError):
                audit_capture(plan, bad, changed_raw)

    def test_reload_identity_and_order_from_real_client_parser(self):
        from tests.board_llm.test_service_commands import CommandCapture
        action = dict(name='reload', kind='reload', command=':reload')
        reply = ('T25 RELOAD\nT25 SD WAIT DDR\nT25 SD EXPECT APP app MODEL model\n'
                 'T25 SERVICE v1 CE64_CANDIDATE_UNQUALIFIED total=512 max_new=128\n'
                 'T25 MODEL model TOKENIZER tokenizer\nT25 LOAD ticks=0000000000000020\nT25 READY\n')
        code, capture, raw = CommandCapture().run_capture([action], [('', 'T25 READY\n'), (':reload', reply)])
        self.assertEqual(code, 0)
        plan = dict(actions=[action], application_sha256='app', model_sha256='model', tokenizer_sha256='tokenizer')
        self.assertIn('reload', audit_capture(plan, capture, raw))
        service = b'T25 SERVICE v1 CE64_CANDIDATE_UNQUALIFIED total=512 max_new=128\n'
        model = b'T25 MODEL model TOKENIZER tokenizer\n'
        for changed in (raw.replace(b'MODEL model TOKENIZER', b'MODEL other TOKENIZER'),
                        raw.replace(service + model, model + service)):
            bad = copy.deepcopy(capture)
            bad.update(raw_bytes=len(changed), raw_sha256=hashlib.sha256(changed).hexdigest())
            bad['actions'][-1]['end_byte'] = len(changed)
            with self.subTest(raw=changed), self.assertRaises(ValueError):
                audit_capture(plan, bad, changed)
