"""Full frozen golden through a scripted serial peer; no hardware qualification."""
import argparse
import copy
import json
import os
import shutil
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from scripts import run_competition_opt_v1_short as runner
from software.boot.competition_opt_v1_short import calls, check_capture, compare, sha

ROOT=Path(__file__).resolve().parents[2]
GOLD=ROOT/'evidence/OPT02_GOLDEN/opt02-short-golden-20261018-v1/golden.json'
LIMITS=ROOT/'configs/t05-thresholds.json'


def write(path, value):
    path.write_text(json.dumps(value,indent=2)+'\n')


def dump(golden):
    def words(values):
        a=values.reshape(-1).view('<u4')
        return '\n'.join(' '.join(f'{int(x):08x}' for x in a[i:i+8]) for i in range(0,len(a),8))+'\n'
    data='T25 LOGITS\n'+words(golden['logits'][-1])
    kv=golden['kv']
    for layer in range(24):
        for value in range(2):
            data+=f'T25 KV {layer:08x} {value:08x} {kv.shape[2]:08x}\n'+words(kv[layer,value])
    return data+'T25 DUMP END\n'


class Clock:
    def __init__(self):self.now=0
    def monotonic(self):return self.now
    def time(self):return 1000+self.now
    def sleep(self,seconds):self.now+=seconds


class Peer:
    """The peer replays reference bytes, never claims DUT numerical execution."""
    def __init__(self,variant,clock,scenario='normal'):
        self.variant,self.clock,self.scenario=variant,clock,scenario
        self.buffer=bytearray();self.commands=[];self.case=None;self.session=0
        self.tick=[0]*8;self.count=[30*n for n in (1,49,168,48,24,24,48,1)]
        self.pressure=False;self.pressure_completed=False;self.closed=False;self.timeout=.1
        self.golden={k:dict(np.load(GOLD.parent/(k+'.npz'),allow_pickle=False)) for k in ('W','S','P')}
        self.dumps={k:dump(v) for k,v in self.golden.items()}
    def open(self):pass
    def close(self):self.closed=True
    @property
    def in_waiting(self):return len(self.buffer)
    def read(self,n):
        if not self.buffer:self.clock.now+=self.timeout;return b''
        self.clock.now+=.001
        value=bytes(self.buffer[:n]);del self.buffer[:n];return value
    def snapshot(self):
        w=[0]*64;w[:3]=[0x34364543,2,0x307];w[6]=8;w[8]=1
        if self.pressure_completed and self.scenario!='no-pass':w[12]=1;w[56]=33554432;w[58]=33554432
        ticks=int(self.clock.now*125000000)
        text=f'T25 TELEMETRY BEGIN begin_ticks={ticks:016x} end_ticks={ticks+10:016x} status_after=0000000000000307 profile={2 if self.pressure else 0:016x}\n'
        text+=''.join(f'T25 TELEMETRY WORD {i:08x} {v:08x}\n' for i,v in enumerate(w))
        return text+'T25 TELEMETRY END\nT25 MEMORY committed_bytes=0000000000000001\n'
    def response(self,value):
        if value=='':return 'T25 READY\n'
        if value==':pressure off':
            if self.pressure and self.scenario=='stuck-off':return ''
            if self.pressure:self.pressure_completed=True
            self.pressure=False
            return 'T25 PRESSURE OFF DRAINED\nT25 READY\n'
        if value==':pressure on':
            self.pressure=True
            if self.scenario=='on-timeout':return ''
            return 'T25 PRESSURE ON\nT25 READY\n'
        if value==':telemetry':return self.snapshot()+'T25 READY\n'
        if value==':reset':self.session+=1;return 'T25 RESET\nT25 READY\n'
        if value==':dump':
            data=self.dumps[self.case]
            if self.scenario=='bad-logits' and self.case=='S':
                data=data.replace('T25 LOGITS\n','T25 LOGITS\n7fc00000 ',1)
            return data+'T25 READY\n'
        case='S' if value.startswith(':ids 3') else 'P' if value.count(' ')==7 else 'W'
        self.case=case;self.session+=1
        if self.scenario=='request-timeout' and case=='S':return ''
        g=self.golden[case];prompt=g['input_ids'].size;generated=g['output_ids'].size;f=prompt+generated-1
        ce,counts=calls(prompt,generated,self.variant,value.startswith(':verify'))
        lines=[]
        for i in range(f):
            lines.append(f'T25 STEP {min(i+1,prompt):08x} {max(0,i-prompt+2):08x}\n')
            if value.startswith(':verify'):lines.append(self.dumps['W'])
        output=g['output_ids'].tolist()
        if self.scenario=='early-eos' and case=='S':output=output[:1]
        lines.append('T25 IDS '+' '.join(f'{int(x):08x}' for x in output)+'\n')
        m=dict(session=self.session,stop=2,prompt=prompt,generated=len(output),kv=f,
               tokenizer_ticks=0,prefill_ticks=90000000,decode_ticks=20000000 if generated>1 else 0,
               total_ticks=125000000,first_token_ticks=95000000 if generated>1 else 125000001,
               stack_peak_bytes=34000,cpu_calls=0,ce_calls=ce,fallback_calls=0,dispatch_ticks=50000000)
        lines.append('T25 METRICS '+''.join(f'{k}={v:016x} ' for k,v in m.items())+'\n')
        if self.scenario=='missing-metrics' and case=='S':lines=[x for x in lines if not x.startswith('T25 METRICS')]
        for i,n in enumerate(counts):self.count[i]+=n;self.tick[i]+=n*100
        lines.append('T25 PROFILE CUMULATIVE '+''.join(f'{i:08x} ticks={self.tick[i]:016x} calls={self.count[i]:016x} ' for i in range(8))+'\nT25 READY\n')
        return ''.join(lines)
    def write(self,wire):
        value=wire.decode().strip();self.commands.append(value)
        self.buffer.extend(self.response(value).encode())
        return len(wire)


class TransportChecks(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        plan=json.loads((ROOT/'configs/competition-opt-v1-short.json').read_text(encoding='utf-8'))
        plan['status']='EXECUTABLE_OPT02_VALIDATED';write(self.root/'plan.json',plan)
        self.identity={k:'0'*64 for k in ('application_sha256','loader_rom_sha256','bitstream_sha256')}
        self.identity.update({k:plan[k] for k in ('model_sha256','tokenizer_sha256','route','clock_hz','native_write_drain_cycles','synthetic_pressure_gap_cycles')})
        write(self.root/'identity.json',self.identity)
        boot=(f"T25 SD EXPECT APP {self.identity['application_sha256']} MODEL {self.identity['model_sha256']}\n"
              f"T25 MODEL {self.identity['model_sha256']} TOKENIZER {self.identity['tokenizer_sha256']}\n"
              'T25 SERVICE v1 CE64_CANDIDATE_UNQUALIFIED total=512 max_new=128\nT25 READY\n')
        (self.root/'boot.bin').write_text(boot)
        write(self.root/'ready.json',dict(status='PASS',task_status='DONE',plan_sha256=sha(self.root/'plan.json'),
              golden_manifest_sha256=sha(GOLD),overall_started_epoch=1000,
              variant_applications={'A':'0'*64,'B':'0'*64}))
    def tearDown(self):self.temp.cleanup()
    def run_capture(self,variant='B',scenario='normal',spent=0,lock=False):
        clock=Clock();peer=Peer(variant,clock,scenario)
        write(self.root/'platform.json',dict(status='PASS',variant=variant,identity=self.identity,
              current_service_confirmed=True,boot_capture_sha256=sha(self.root/'boot.bin')))
        if spent:write(self.root/'ledger.json',dict(ledger_id='1'*32,limit_seconds=1200,spent_seconds=spent,variants=[],pressure_attempted=False))
        if lock:(self.root/'serial.lock').write_text('occupied')
        args=argparse.Namespace(out=str(self.root/(variant+'.json')),plan=str(self.root/'plan.json'),readiness=str(self.root/'ready.json'),
              identity=str(self.root/'identity.json'),boot_capture=str(self.root/'boot.bin'),platform_receipt=str(self.root/'platform.json'),
              golden=str(GOLD),thresholds=str(LIMITS),ledger=str(self.root/'ledger.json'),serial_lock=str(self.root/'serial.lock'),port='COM10',variant=variant)
        port=argparse.Namespace(device='COM10',vid=0x10c4,pid=0xea60,serial_number='0001')
        with patch('serial.Serial',return_value=peer),patch('serial.tools.list_ports.comports',return_value=[port]):
            code=runner.capture(args,clock=clock)
        result=json.loads(Path(args.out).read_text(encoding='utf-8'))
        if os.environ.get('OPT02_TRANSPORT_EVIDENCE_DIR'):
            dest=Path(os.environ['OPT02_TRANSPORT_EVIDENCE_DIR'])/(variant+'-'+scenario+('-budget' if spent else '')+('-locked' if lock else ''))
            dest.mkdir(parents=True,exist_ok=False)
            for path in self.root.iterdir():
                if path.is_file() and path.suffix in ('.json','.bin'):shutil.copy2(path,dest/path.name)
            write(dest/'scope.json',dict(scope='SCRIPTED_SERIAL_REPLAYS_FULL_PRODUCTION_GOLDEN',board_measurement=False,commands=peer.commands))
        return code,result,peer,clock,args
    def test_complete_a_b_and_independent_compare(self):
        outputs=[]
        for variant in ('A','B'):
            code,result,peer,clock,args=self.run_capture(variant)
            self.assertEqual(code,0,result.get('failure'));self.assertTrue(peer.closed)
            outputs.append(check_capture(args.out,GOLD,LIMITS,self.identity))
        self.assertEqual(outputs[1]['pressure_status'],'PASS')
        self.assertEqual(compare(*outputs)['status'],'PASS')
    def test_no_pass_is_inconclusive_without_extension(self):
        code,result,peer,clock,args=self.run_capture(scenario='no-pass')
        self.assertEqual(code,0,result.get('failure'))
        self.assertEqual(check_capture(args.out,GOLD,LIMITS,self.identity)['pressure_status'],'INCONCLUSIVE_NO_NEW_COMPLETE_PASS')
        self.assertEqual(peer.commands.count(':pressure on'),1);self.assertLess(clock.now,125)
    def test_pressure_budget_reserved_before_on(self):
        code,result,peer,clock,args=self.run_capture(spent=800)
        self.assertEqual(code,0,result.get('failure'));self.assertNotIn(':pressure on',peer.commands)
        self.assertEqual(check_capture(args.out,GOLD,LIMITS,self.identity)['pressure_status'],'NOT_RUN_BUDGET')
    def test_timeout_stops_requests_and_drains(self):
        code,result,peer,clock,args=self.run_capture(scenario='request-timeout')
        self.assertEqual(code,1);self.assertEqual(result['pressure_status'],'OFF_DRAINED_AFTER_FAILURE')
        self.assertNotIn(':ids 1 0 255 1023 0 255 1023',peer.commands)
        self.assertLess(clock.now,306);self.assertTrue(peer.closed)
    def test_lost_on_ack_attempts_off(self):
        code,result,peer,clock,args=self.run_capture(scenario='on-timeout')
        self.assertEqual(code,1);self.assertEqual(result['pressure_status'],'OFF_DRAINED_AFTER_FAILURE')
        self.assertEqual(peer.commands[-1],':pressure off');self.assertNotIn(':ids 1 0',peer.commands)
    def test_stuck_off_marks_unknown_and_closes(self):
        code,result,peer,clock,args=self.run_capture(scenario='stuck-off')
        self.assertEqual(code,1);self.assertEqual(result['pressure_status'],'UNKNOWN_AFTER_FAILURE')
        self.assertTrue(peer.closed);self.assertLess(clock.now,132)
    def test_missing_early_eos_and_bad_numeric_stop(self):
        for scenario in ('missing-metrics','early-eos','bad-logits'):
            with self.subTest(scenario=scenario):
                # Each failed attempt gets its own fresh ledger and capture.
                self.tearDown();self.setUp()
                code,result,peer,clock,args=self.run_capture(scenario=scenario)
                self.assertEqual(code,1);self.assertNotIn(':pressure on',peer.commands)
                with self.assertRaises(ValueError):check_capture(args.out,GOLD,LIMITS,self.identity)
    def test_serial_ownership_is_exclusive(self):
        code,result,peer,clock,args=self.run_capture(lock=True)
        self.assertEqual(code,1);self.assertEqual(peer.commands,[])
        self.assertTrue((self.root/'serial.lock').exists())
    def test_wrong_identity_rejected_before_serial(self):
        ready=json.loads((self.root/'ready.json').read_text(encoding='utf-8'));ready['variant_applications']['B']='f'*64;write(self.root/'ready.json',ready)
        with self.assertRaises(ValueError):self.run_capture()


if __name__=='__main__':unittest.main()
