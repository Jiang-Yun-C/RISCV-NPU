"""Fake transport only; collection uses the shipped live parser and export adapter."""
import base64
import contextlib
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from software.competition_semantics import collect, evaluate
from tests.competition_semantics.make_fixture import raw_result


class FakeBridge:
    def __init__(self, run, *, disconnect_at=None, corrupt_at=None):
        self.run = run;self.writes = [];self.queue = [];self.seq = 0;self.attempt = 0
        self.disconnect_at = disconnect_at;self.corrupt_at = corrupt_at;self.closed = False
        self.dataset, self.commands, self.contract, _ = evaluate.cases_and_commands()

    def connect(self, port, owner, baud):
        self.owner = owner

    def emit(self, raw):
        data = raw.encode('utf8')
        for start in range(0, len(data), 19):
            part = data[start:start+19];self.seq += 1
            self.queue.append({'seq':self.seq,'data':base64.b64encode(part).decode(),
                               'received_ns':str(time.monotonic_ns())})

    def write(self, command, owner):
        self.writes.append(command)
        if command == '':
            self.emit('T25 CAPABILITIES stream=1 text_max=1 identity=1\nT25 READY\n')
        elif command == ':identity':
            # An extra READY from initial synchronization must not be mistaken
            # for this identity query's acknowledgment.
            self.emit('T25 READY\nT25 MODEL ' + self.contract['model'] + ' TOKENIZER ' + self.contract['tokenizer'] + '\nT25 READY\n')
        else:
            if self.attempt:
                previous = self.dataset['cases'][self.attempt-1]['id']
                assert (self.run.parent/'exports'/f'{previous}.json').is_file()
                assert (self.run.parent/'exports'/f'{previous}.chunks.jsonl').is_file()
                manifest = evaluate.load(self.run)
                assert manifest['records'][self.attempt-1]['attempt_status'] == 'completed'
            case = self.dataset['cases'][self.attempt]
            assert command == self.commands[case['id']]
            self.attempt += 1
            raw = raw_result(evaluate.encode(case['program']))
            if self.attempt == self.corrupt_at:raw = raw.replace('generated=0000000000000002','generated=0000000000000003')
            if self.attempt == self.disconnect_at:raw = raw[:len(raw)//2]
            self.emit(raw)
        return {'clock':'python.time.monotonic_ns','write_start':str(time.monotonic_ns()-1000000),
                'write_return':str(time.monotonic_ns()),'flush_end':str(time.monotonic_ns()),'bytes':len(command.encode())+1}

    def read(self, after, owner, wait=0):
        chunks, self.queue = self.queue[:7], self.queue[7:]
        connected = not (self.attempt == self.disconnect_at and not self.queue)
        return {'chunks':chunks,'connected':connected,'error':None,'pending':bool(self.queue)}

    def disconnect(self):
        self.closed = True


class BatchCaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='t27-capture-test-')
        self.run = evaluate.make_plan(Path(self.temp.name)/'run')

    def tearDown(self):
        self.temp.cleanup()

    def test_all_24_saved_before_next_request_without_history_eviction(self):
        bridge = FakeBridge(self.run)
        result = collect.collect(self.run, 'FAKE_ONLY', bridge=bridge, source='fixture', wait_seconds=10)
        self.assertEqual(result['capture']['status'], 'all_attempts_saved')
        self.assertEqual(len(result['records']), 24)
        self.assertTrue(all(row['attempt_status']=='completed' for row in result['records']))
        self.assertEqual(len(list((self.run.parent/'exports').glob('*.json'))), 24)
        self.assertEqual(len(list((self.run.parent/'exports').glob('*.chunks.jsonl'))), 24)
        self.assertTrue(bridge.closed)
        report = evaluate.score_run(self.run)
        self.assertEqual(report['protocol']['accepted'], 24)
        self.assertEqual(report['diagnostic_semantic_agreement']['passed'], 24)
        self.assertIsNone(report['declared_live_model_semantics']['accuracy_including_missing_and_failed'])
        self.assertEqual(report['physical_evidence']['actuator_operations_by_this_tool'], 0)
        with self.assertRaises(ValueError):collect.load_plan(self.run)

    def test_disconnect_saves_partial_attempt_and_preserves_all_denominators(self):
        result = collect.collect(self.run, 'FAKE_ONLY', bridge=FakeBridge(self.run, disconnect_at=2),
                                 source='fixture', wait_seconds=10)
        self.assertEqual(result['capture']['status'], 'stopped')
        self.assertEqual([r['attempt_status'] for r in result['records'][:3]], ['completed','disconnected','pending'])
        partial = evaluate.load(self.run.parent/result['records'][1]['export'])
        self.assertFalse(partial['complete']);self.assertTrue(partial['rawChunks'])
        report = evaluate.score_run(self.run)
        self.assertEqual(report['required_cases'],24)
        self.assertEqual(report['protocol']['accepted'],1)
        self.assertEqual(report['missing_exports'],22)

    def test_protocol_error_is_saved_and_prevents_next_command(self):
        bridge = FakeBridge(self.run, corrupt_at=1)
        result = collect.collect(self.run, 'FAKE_ONLY', bridge=bridge, source='fixture', wait_seconds=10)
        self.assertEqual(result['records'][0]['attempt_status'],'failed')
        self.assertEqual(bridge.attempt,1)
        self.assertEqual(sum(row['attempt_status']=='pending' for row in result['records']),23)
        self.assertFalse(result['records'][0]['capture']['protocol_accepted'])

    def test_default_plan_is_read_only_and_tampered_case_is_rejected(self):
        with patch.object(collect, 'SerialBridge', side_effect=AssertionError('must not open serial')):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):self.assertEqual(collect.main(['--run',str(self.run)]),0)
            self.assertEqual(json.loads(output.getvalue())['cases'],24)
        self.assertFalse((self.run.parent/'capture.lock').exists())
        lines = (self.run.parent/'requests.jsonl').read_text().splitlines()
        row = json.loads(lines[0]);row['command'] = ':text 1 changed';lines[0] = evaluate.encode(row)
        (self.run.parent/'requests.jsonl').write_text('\n'.join(lines)+'\n')
        with self.assertRaises(ValueError):collect.load_plan(self.run)


if __name__ == '__main__':unittest.main()
