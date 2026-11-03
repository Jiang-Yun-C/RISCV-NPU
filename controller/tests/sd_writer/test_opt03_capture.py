"""Collector control tests using explicitly scripted bytes, never board samples."""
import importlib.util,json,sys,time
from pathlib import Path
from types import SimpleNamespace
import pytest
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('opt03_service',ROOT/'scripts/pds/windows_opt03_service.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
FIX=ROOT/'evidence/OPT02/opt02-completion-20261018-v2/scripted-serial/B-normal'
def run(tmp_path,monkeypatch,fault=None):
 import serial
 import serial.tools.list_ports
 cap=json.loads((FIX/'B.json').read_text());raw=(FIX/'B.bin').read_bytes();segments={a['command']:raw[a['start_byte']:a['end_byte']] for a in cap['actions'][:5]};identity=json.loads((FIX/'identity.json').read_text())
 class Device:
  def __init__(self):self.pending=bytearray((FIX/'boot.bin').read_bytes() if fault!='boot-error' else b'T25 ERROR 1234\n');self.sent=[];self.closed=False
  def open(self):pass
  def close(self):self.closed=True
  def reset_input_buffer(self):pass
  def flush(self):pass
  @property
  def in_waiting(self):return len(self.pending)
  def read(self,n):d=bytes(self.pending[:n]);del self.pending[:n];return d
  def write(self,wire):self.sent.append(wire);self.pending.extend(segments[wire.decode().strip()]);return len(wire)
 dev=Device();monkeypatch.setattr(serial,'Serial',lambda *a,**k:dev);monkeypatch.setattr(serial.tools.list_ports,'comports',lambda:[SimpleNamespace(device='COM10',vid=0x10c4,pid=0xea60,serial_number='0001')])
 plan=tmp_path/'plan.json';plan.write_text(json.dumps(identity));arm=tmp_path/'arm.json';arm.write_text(json.dumps({'done':True,'image_sha256':('1' if identity['bitstream_sha256'][0]!='1' else '2')+identity['bitstream_sha256'][1:] if fault=='wrong-arm' else identity['bitstream_sha256'],'program_done_epoch':time.time()}));out=tmp_path/'capture.json';ledger=tmp_path/'ledger.json';lock=tmp_path/'serial.lock'
 argv=['capture','--dependency-dir',str(tmp_path),'--out',str(out),'--plan',str(plan),'--arm-file',str(arm),'--serial-lock',str(lock),'--ledger',str(ledger),'--deadline-epoch',str(time.time()+600)];monkeypatch.setattr(sys,'argv',argv);code=m.main();assert dev.closed and not lock.exists();return code,json.loads(out.read_text()),dev,ledger

def test_one_W_and_budget(tmp_path,monkeypatch):
 code,result,dev,ledger=run(tmp_path,monkeypatch);assert code==0 and result['status']=='PASS_TRANSPORT_NUMERIC_REVIEW_PENDING';assert dev.sent==[b':pressure off\n',b':telemetry\n',b':reset\n',b':verify 1 0\n'];assert [x['name'] for x in result['actions']]==['off','telemetry','reset','W'];b=json.loads(ledger.read_text());assert 0<=b['spent_seconds']<1200 and not b['active_capture'] and b['diagnostic_B']
@pytest.mark.parametrize('fault',['wrong-arm','boot-error'])
def test_bad_boot_stops_before_requests(tmp_path,monkeypatch,fault):
 code,result,dev,ledger=run(tmp_path,monkeypatch,fault);assert code==1 and result['status']=='FAIL' and not dev.sent and not ledger.exists()
