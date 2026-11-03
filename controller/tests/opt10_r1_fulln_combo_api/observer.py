"""Real RV32 single linear call; no stimulus of submission or computation."""
import json
import os
from pathlib import Path
import numpy as np
import cocotb
from cocotb.triggers import Timer
from common.checks import Checks
from scripts.opt10_r1_measurement_cocotb import close_observation,save_observer_output

@cocotb.test()
async def fulln_combo_cpu_api(dut):
 cfg=json.loads(Path(os.environ['NEXUSRV_CASE']).read_text());c=Checks();result={}
 try:
  while not int(dut.completed.value) and not int(dut.timed_out.value):await Timer(100000,unit='ns')
  c.equal(int(dut.completed.value),1,'completion','real CPU exit');c.equal(int(dut.exit_code.value),0,'completion','guest success')
  reports={}
  for line in Path('cpu-output.txt').read_text().splitlines():
   g,i,v=map(int,line.split());c.require((g,i) not in reports,'report','unique report');reports[g,i]=v
  c.equal(set(reports),{(1,i) for i in range(3)}|{(2,i) for i in range(9)}|{(3,i) for i in range(26)},'report','exact report closure')
  for key in ((1,0),(1,1),(1,2),(2,0),(2,3)):c.equal(reports[key],0,'status',str(key))
  c.equal(reports[2,4],2,'identity','one real quantize and one real linear submission')
  def u(g,i):return reports[g,i]|reports[g,i+1]<<32
  counts={name:u(3,2*i) for i,name in enumerate(('calls','completed','sfu_calls','linear_backend_cycles','quantize_backend_cycles','staging_bytes','staging_saved_bytes','output_copy_bytes','private_output_saved_bytes','direct_Aq_bytes','direct_Sa_bytes','Sa_copy_bytes','staging_ticks'))}
  k,n=cfg['K'],cfg['N']
  for name,want in dict(calls=1,completed=1,sfu_calls=1,staging_bytes=0,staging_saved_bytes=k*4,output_copy_bytes=0,private_output_saved_bytes=n*4,direct_Aq_bytes=k,direct_Sa_bytes=k//64*4,Sa_copy_bytes=0).items():c.equal(counts[name],want,'accounting',name)
  async def inspect():
   words=[]
   for i in range(n):
    dut.peek_address.value=cfg['Y']+4*i;await Timer(2,unit='ns');words.append(int(dut.peek_value.value))
   actual=np.array(words,dtype='<u4').view('<f4');want=np.fromfile(cfg['golden'],dtype='<f4');threshold=cfg['linear_thresholds']
   c.require(np.isfinite(actual).all(),'numeric','all output finite')
   err=np.abs(actual.astype('f8')-want.astype('f8'));nr=float(np.sqrt(np.mean(err**2))/max(np.sqrt(np.mean(want.astype('f8')**2)),1e-12))
   c.require(np.all(err<=threshold['atol']+threshold['rtol']*np.abs(want)),'numeric','frozen linear elementwise threshold');c.require(nr<=threshold['nrmse'],'numeric','frozen linear NRMSE')
   for name,address,expected in (('Aq',0xba1c0000,Path(cfg['expected_aq']).read_bytes()),('Sa',0xba1c5000,Path(cfg['expected_sa']).read_bytes())):
    captured=bytearray()
    for i in range(len(expected)//4):
     dut.peek_address.value=address+4*i;await Timer(2,unit='ns');captured.extend(int(dut.peek_value.value).to_bytes(4,'little'))
    c.require(bytes(captured)==expected,'quantize',name+' all original numeric-v1 integer/scale object bits')
   Path('output.bin').write_bytes(actual.tobytes());return dict(elements=n,max_abs=float(err.max()),nrmse=nr,output_bits=words,Aq_Sa_bitwise_reference=True)
  numeric,close=await close_observation(dut,inspect,deadline=cfg['max_cycles'],transport_state=lambda:(bool(int(dut.api_transport_drained.value)),int(dut.api_activity.value)))
  result=dict(shape=cfg['shape'],K=k,N=n,CPU_API_cycles=u(2,1),api_start_mcycle=u(2,5),api_end_mcycle=u(2,7),counts=counts,numeric=numeric,terminal_close=close,
   scope='ONE_REAL_RV32_M1_FULL_N_POSTLOAD_LINEAR_API_ROPE_NOT_EXECUTED_NOT_FULLGRAPH_OR_TTFT',GO=False)
 except BaseException as error:
  if c.first_failure is None:c.first_failure=dict(category='exception',detail=repr(error))
  raise
 finally:await save_observer_output(result,c,dict(run_id=cfg['run_id'],arm=cfg['arm']))
