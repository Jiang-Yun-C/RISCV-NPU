"""Expected bad-first-Sw failure, with original CPU API and full transport close."""
import json,os
from pathlib import Path
import cocotb
from cocotb.triggers import Timer
from common.checks import Checks
from scripts.opt10_r1_measurement_cocotb import close_observation,save_observer_output

@cocotb.test()
async def bad_sw_cpu_api(dut):
 cfg=json.loads(Path(os.environ['NEXUSRV_CASE']).read_text());c=Checks();result={}
 try:
  while not int(dut.completed.value) and not int(dut.timed_out.value):await Timer(100000,unit='ns')
  c.equal(int(dut.completed.value),1,'completion','real CPU error return');c.equal(int(dut.exit_code.value),4,'completion','unchanged firmware reports API error exit')
  reports={}
  for line in Path('cpu-output.txt').read_text().splitlines():
   g,i,v=map(int,line.split());c.require((g,i) not in reports,'report','unique');reports[g,i]=v
  c.equal(set(reports),{(1,i) for i in range(3)}|{(2,i) for i in range(9)}|{(3,i) for i in range(26)},'report','exact original firmware reports')
  for i in range(3):c.equal(reports[1,i],0,'status','successful original init/bind/configure')
  c.equal(reports[2,0],0xfffffffc,'status','original backend returns NX_STATE after failed device result')
  u=lambda g,i:reports[g,i]|reports[g,i+1]<<32
  c.equal(u(3,0),1,'accounting','one attempted linear API');c.equal(u(3,2),0,'accounting','no successful linear completion');c.equal(u(3,4),1,'accounting','real quantization completed')
  c.equal(u(3,16),0,'publication','no private output publication');c.equal(u(3,14),0,'publication','no CPU Y copy')
  async def inspect():return None
  _,close=await close_observation(dut,inspect,deadline=cfg['max_cycles'],transport_state=lambda:(bool(int(dut.api_transport_drained.value)),int(dut.api_activity.value)))
  result=dict(expected_fault='FIRST_Q_SW_QUIET_NAN',actual_API_status=-4,CPU_API_cycles=u(2,1),api_start_mcycle=u(2,5),api_end_mcycle=u(2,7),terminal_close=close,
   no_successful_API_completion=True,no_private_Y_publication=True,scope='ONE_REAL_RV32_BAD_SW_API_EXPECTED_FAILURE_NOT_NORMAL_NUMERIC_PASS',GO=False)
 except BaseException as error:
  if c.first_failure is None:c.first_failure=dict(category='exception',detail=repr(error))
  raise
 finally:await save_observer_output(result,c,dict(run_id=cfg['run_id'],arm=cfg['arm'],expected_fault=True))
