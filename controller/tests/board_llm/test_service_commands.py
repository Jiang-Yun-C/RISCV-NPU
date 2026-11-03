import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch


class CommandCapture(unittest.TestCase):
    def test_diagnostics_require_snapshot_and_physical_drain_ack(self):
        actions=[dict(name='on',kind='pressure-on',command=':pressure on'),
            dict(name='sample',kind='telemetry',command=':telemetry'),
            dict(name='off',kind='pressure-off',command=':pressure off')]
        replies=[('','T25 READY\n'),(':pressure on','T25 PRESSURE ON\nT25 READY\n'),
            (':telemetry','T25 TELEMETRY END\nT25 MEMORY committed_bytes=0000000000000040\nT25 READY\n'),
            (':pressure off','T25 PRESSURE OFF DRAINED\nT25 READY\n')]
        code,result,raw=self.run_capture(actions,replies)
        self.assertEqual(code,0);self.assertIn(b'OFF DRAINED',raw)
        for action,reply in [(actions[1],'T25 TELEMETRY END\nT25 READY\n'),
                (actions[2],'T25 PRESSURE OFF\nT25 READY\n')]:
            code,result,raw=self.run_capture([action],[('','T25 READY\n'),(action['command'],reply)])
            self.assertEqual(code,1)

    def run_capture(self,actions,replies):
        fixture=self
        class Port:
            def __init__(self,*args,**kwargs):self.pending=b'';self.sent=[]
            def open(self):pass
            def close(self):pass
            def reset_input_buffer(self):pass
            def flush(self):pass
            @property
            def in_waiting(self):return min(37,len(self.pending))
            def read(self,n):
                result=self.pending[:n];self.pending=self.pending[n:];return result
            def write(self,data):
                fixture.assertFalse(self.pending)
                expected,reply=replies[len(self.sent)];fixture.assertEqual(data,(expected+'\n').encode())
                self.sent.append(data);self.pending=reply.encode('utf-8');return len(data)
        port=types.SimpleNamespace(device='COM10',vid=0x10c4,pid=0xea60,serial_number='0001')
        serial=types.ModuleType('serial');serial.Serial=Port
        serial_tools=types.ModuleType('serial.tools');serial_tools.list_ports=types.SimpleNamespace(comports=lambda:[port])
        path=Path(__file__).resolve().parents[2]/'scripts/pds/windows_t25_commands.py'
        spec=importlib.util.spec_from_file_location('t25_commands_under_test',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary);plan=directory/'plan.json';out=directory/'capture.json'
            plan.write_text(json.dumps(dict(application_sha256='app',model_sha256='model',tokenizer_sha256='tokenizer',plaintext_command='你好',actions=actions)))
            with patch.dict(sys.modules,{'serial':serial,'serial.tools':serial_tools}),patch.object(sys,'argv',
                    ['capture','--dependency-dir',str(directory),'--plan',str(plan),'--out',str(out)]):
                code=module.main()
            return code,json.loads(out.read_text()),out.with_suffix('.bin').read_bytes()

    def test_utf8_zero_outputs_dump_reset_and_real_reload(self):
        actions=[dict(name='reset',kind='reset',command=':reset'),dict(name='zero',kind='request',command=':ids 1 0',forward_steps=2),
            dict(name='dump',kind='dump',command=':dump'),dict(name='bounds',kind='bounds-error',command=':ids 1 0'),
            dict(name='reload',kind='reload',command=':reload')]
        reload='T25 RELOAD\nT25 SD WAIT DDR\nT25 SD EXPECT APP app MODEL model\nT25 SERVICE v1 CE64_CANDIDATE_UNQUALIFIED total=512 max_new=128\nT25 MODEL model TOKENIZER tokenizer\nT25 LOAD ticks=0000000000000020\nT25 READY\n'
        replies=[('','T25 READY\n'),(':reset','T25 RESET\nT25 READY\n'),(':ids 1 0',
            'T25 STEP 00000001 00000000\nT25 STEP 00000002 00000000\nT25 IDS \nT25 TEXT 中文\nT25 METRICS generated=0000000000000000\nT25 READY\n'),
            (':dump','T25 LOGITS\n3f800000\nT25 DUMP END\nT25 READY\n'),(':ids 1 0','T25 ERROR fffffffc\nT25 READY\n'),(':reload',reload)]
        code,result,raw=self.run_capture(actions,replies)
        self.assertEqual(code,0);self.assertEqual(result['actions'][2]['output_ids'],[])
        self.assertIn('中文'.encode(),raw);self.assertEqual(result['actions'][-1]['load_ticks'],32)
        for previous,current in zip(result['actions'],result['actions'][1:]):self.assertEqual(previous['end_byte'],current['start_byte'])

    def test_unexpected_error_or_missing_reload_identity_fails(self):
        for action,reply in [(dict(name='request',kind='request',command=':ids 1 0',forward_steps=1),'T25 ERROR fffffffc\nT25 READY\n'),
            (dict(name='reload',kind='reload',command=':reload'),'T25 RELOAD\nT25 READY\n')]:
            with self.subTest(kind=action['kind']):
                code,result,raw=self.run_capture([action],[('','T25 READY\n'),(action['command'],reply)])
                self.assertEqual(code,1);self.assertEqual(result['status'],'FAIL');self.assertTrue(raw)

    def test_plaintext_is_sent_as_utf8_with_board_outputs_captured(self):
        action=dict(name='text',kind='text',command='你好',forward_steps=1)
        reply='T25 STEP 00000001 00000001\nT25 IDS 00000001\nT25 TEXT 你好\nT25 METRICS generated=0000000000000001\nT25 READY\n'
        code,result,raw=self.run_capture([action],[('','T25 READY\n'),('你好',reply)])
        self.assertEqual(code,0);self.assertEqual(result['actions'][1]['output_ids'],[1]);self.assertIn('你好'.encode(),raw)
        action['command']=':reload'
        code,result,raw=self.run_capture([action],[('','T25 READY\n')])
        self.assertEqual(code,1)
