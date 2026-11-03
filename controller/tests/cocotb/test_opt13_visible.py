import hashlib,json,os,sys
from pathlib import Path
import cocotb
from cocotb.triggers import Timer,with_timeout
from common.checks import Checks

def score(path,g,c):
 r={}
 for line in Path(path).read_text().splitlines():
  a,b,v=map(int,line.split());c.require((a,b) not in r,'output_set','unique report');r[a,b]=v
 for (group,i),v in r.items():
  if group==200:c.equal(v,1,'contract','stream/model contract')
 c.equal(len([1 for group,i in r if group==200]),r[300,0],'output_set','all contract checks')
 results=[]
 for i in range(4):
  group=600+i
  def ticks(j):return r[group,j]+(r[group,j+1]<<32)
  for j,v in enumerate(g['output_ids']):c.equal(r[group,16+j],v,'token','independent model output')
  text=[r[500+i,j] for j in range(r[group,18])];c.equal(text,g['text_bytes'],'text','official tokenizer UTF8 bytes')
  c.require(ticks(0)>0 and ticks(2)>=ticks(0) and ticks(4)>0 and ticks(6)>0 and ticks(8)>0 and ticks(10)>0,'timing','complete readable TEXT follows first token')
  if i%2:c.require(ticks(14)>0,'timing','prefix preparation separately recorded')
  results.append(dict(rows=1 if i<2 else 4,prefix=3 if i%2 else 0,prompt=9,first_token_cycles=ticks(0),first_text_cycles=ticks(2),prefill_cycles=ticks(4),decode_cycles=ticks(6),decoder_cycles=ticks(8),callback_cycles=ticks(10),total_request_cycles=ticks(12),prefix_prepare_cycles=ticks(14),text_bytes=text))
 return results
@cocotb.test()
async def opt13_visible(dut):
 cfg=json.loads(Path(os.environ['NEXUSRV_CASE']).read_text());c=Checks();metrics=[]
 try:
  for k in ('fixture','golden'):c.equal(hashlib.sha256(Path(cfg[k]).read_bytes()).hexdigest(),cfg[k+'_sha256'],'input_identity',k)
  async def done():
   while not int(dut.completed.value) and not int(dut.timed_out.value):await Timer(100000,unit='ns')
   c.require(bool(int(dut.completed.value)),'completion','bounded completion')
  await with_timeout(done(),cfg['max_cycles']*10+100000,'ns');c.equal(int(dut.exit_code.value),0x1300,'completion','CPU exit');await Timer(1000,unit='ns')
  metrics=score('cpu-output.txt',json.loads(Path(cfg['golden']).read_text()),c)
  c.require(int(dut.retired.value)>1000,'execution','actual CPU retirement');c.require(int(dut.axi_reads.value)>100 and int(dut.axi_writes.value)>100,'axi','real AXI');c.equal(int(dut.protection_error.value),0,'memory_protection','no arena faults')
 except BaseException as e:
  if c.first_failure is None:c.first_failure=dict(category='exception',detail=repr(e))
  raise
 finally:
  Path('observations.json').write_text(json.dumps(dict(metrics=metrics,cycles=int(dut.cycles.value),sequence_sha256=hashlib.sha256(Path('cpu-output.txt').read_bytes()).hexdigest() if Path('cpu-output.txt').exists() else None),indent=2)+'\n')
  c.save('checks.json',**{k:cfg[k] for k in ('case_id','run_id','seed','profile','fixture_sha256','golden_sha256')},runtime=dict(python=sys.version,prefix=sys.prefix,cocotb=cocotb.__version__))
