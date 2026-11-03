import hashlib,json,os,sys
from pathlib import Path
import cocotb
from cocotb.triggers import Timer
from common.checks import Checks
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from tests.opt10.base_score import score
@cocotb.test()
async def opt13_pack_wave(dut):
 cfg=json.loads(Path(os.environ['NEXUSRV_CASE']).read_text());c=Checks();result={}
 try:
  for k in ('fixture','golden'):c.equal(hashlib.sha256(Path(cfg[k]).read_bytes()).hexdigest(),cfg[k+'_sha256'],'input_identity',k)
  while not int(dut.completed.value) and not int(dut.timed_out.value):await Timer(100000,unit='ns')
  c.require(bool(int(dut.completed.value)),'completion','bounded real CPU completion');c.equal(int(dut.exit_code.value),0,'completion','CPU exit')
  await Timer(1000,unit='ns')
  while int(dut.cpu_write_accepts.value)!=int(dut.cpu_write_responses.value):await Timer(8,unit='ns')
  f=json.loads(Path(cfg['fixture']).read_text());g=json.loads(Path(cfg['golden']).read_text());result,c=score('.',f,g,Path(cfg['fixture']).parent,c)
  c.equal(int(dut.owner.value),0,'ownership','released');c.equal(int(dut.backend_idle.value),1,'visibility','native drained');c.equal(int(dut.m4_wave_writes.value),8,'wave_pack','eight actual packed writes observed')
  c.require(int(dut.retired.value)>1000,'execution','real CPU execution')
 except BaseException as e:
  if c.first_failure is None:c.first_failure=dict(category='exception',detail=repr(e))
  raise
 finally:
  Path('observations.json').write_text(json.dumps(dict(result=result,sequence_sha256=hashlib.sha256(Path('transactions.csv').read_bytes()).hexdigest() if Path('transactions.csv').exists() else None),indent=2)+'\n')
  c.save('checks.json',**{k:cfg[k] for k in ('case_id','run_id','seed','profile','fixture_sha256','golden_sha256')},runtime=dict(python=sys.version,prefix=sys.prefix,cocotb=cocotb.__version__))
