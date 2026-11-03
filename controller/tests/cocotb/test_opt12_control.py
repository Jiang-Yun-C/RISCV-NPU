import json,os
from pathlib import Path
import numpy as np
import cocotb
from cocotb.triggers import Timer
from common.checks import Checks
@cocotb.test()
async def control(d):
 c=Checks();scratch={};out={};cfg=json.loads(Path(os.environ['NEXUSRV_CASE']).read_text())
 desc=[0]*32
 for i,v in {0:0x34364543,1:1,2:128,4:1,5:1,8:0x4c4e3135,9:96,10:1,12:1,14:3,15:1,16:1,17:65,18:0xac100000,19:0xac200000,24:5}.items():desc[i]=v
 x=np.arange(65,dtype='f4');x[0]=.5
 try:
  await Timer(16,unit='ns');d.platform_reset_n.value=1;await Timer(8,unit='ns');d.descriptor.value=sum(v<<(i*32) for i,v in enumerate(desc));d.submit.value=1;await Timer(8,unit='ns');d.submit.value=0
  for cycle in range(100000):
   d.dma_result_valid.value=0
   if int(d.ram_en.value):d.ram_q.value=scratch.get(int(d.ram_address.value),0)
   if int(d.dma_valid.value):
    addr=int(d.dma_address.value);size=int(d.dma_size.value);length=int(d.dma_len.value)+1
    if int(d.dma_write.value):out[addr]=int(d.dma_data.value)
    else:
     off=int(d.dma_scratch.value)
     for i in range(length):
      v=int(x.view('u4')[(addr-0xac100000)//4+i]);a=off+i*4;slot=a//16;shift=(a%16)*8
      scratch[slot]=(scratch.get(slot,0)&~(0xffffffff<<shift))|(v<<shift)
    await Timer(8,unit='ns');d.dma_result_valid.value=1
   if int(d.dut.state.value) in (25,26,27):
    print('DEBUG',cycle,'state',int(d.dut.state.value),'pass',int(getattr(d.dut,'pass').value),'base',int(d.dut.base_index.value),'count',int(d.dut.summary_count.value),'fp',str(d.dut.group_fp.value),'sum',str(d.dut.final_sum.value))
   if int(d.completion_valid.value):break
   await Timer(8,unit='ns')
  from tests.opt12.fixture import tree
  expected=int(np.asarray(tree(x)).view('u4'))
  c.equal(out.get(0xac200000),expected,'sum','K65')
 finally:
  c.save('checks.json',case_id=cfg['case_id'],fixture_sha256=cfg['fixture_sha256'])
  Path('observations.json').write_text(json.dumps({'output':out})+'\n')
