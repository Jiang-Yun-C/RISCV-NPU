"""Independent frozen numeric oracle over actual RV32 scheduler output."""
import hashlib
import json
import os
from pathlib import Path
import numpy as np
import cocotb
from cocotb.triggers import Timer
from common.checks import Checks


@cocotb.test()
async def opt10_r1(dut):
    cfg=json.loads(Path(os.environ['NEXUSRV_CASE']).read_text());c=Checks();metrics=[]
    try:
        for name in ('fixture','golden'):
            c.equal(hashlib.sha256(Path(cfg[name]).read_bytes()).hexdigest(),cfg[name+'_sha256'],'identity',name)
        while not int(dut.completed.value) and not int(dut.timed_out.value):await Timer(100000,unit='ns')
        c.require(bool(int(dut.completed.value)),'completion','bounded real CPU completion')
        c.equal(int(dut.exit_code.value),0,'completion','CPU exit')
        await Timer(1000,unit='ns')
        reports={}
        for line in Path('cpu-output.txt').read_text().splitlines():
            g,i,v=map(int,line.split());c.require((g,i) not in reports,'report','unique');reports[g,i]=v
        c.require(not any(g==255 for g,i in reports),'execution','no traps')
        for i in range(3):c.equal(reports.get((1,i)),0,'setup',str(i))
        golden=json.loads(Path(cfg['golden']).read_text())
        thresholds=json.loads(Path(cfg['thresholds']).read_text())
        expected={(1,i) for i in range(3)}|{(2,0),(2,1)}
        for i,j in enumerate(golden['jobs']):
            g=10+i
            for field in range(5):expected.add((g,field))
            c.equal(reports.get((g,0)),0,'status',j['name'])
            c.equal(reports.get((g,2)),j['rows'],'producer','exact per-row SFU calls')
            c.equal(reports.get((g,3)),j['rows']+(1 if j['mode']==0 else 0),'sequence','producer and consumers')
            c.equal(reports.get((g,4)),int(j['mode']==0),'lease','published only for quantized linear')
            c.require(reports.get((g,1),0)>0,'timing','real API cycles')
            ev=np.asarray(j['expected'],dtype='f4');av=[]
            for z in range(ev.size):
                expected.add((100+i+(z>>16),z&65535));c.require((100+i+(z>>16),z&65535) in reports,'numeric','complete output')
                av.append(reports[100+i+(z>>16),z&65535])
            av=np.array(av,dtype='u4').view('f4')
            t=thresholds['operators'][j['operator']];error=np.abs(av.astype('f8')-ev.astype('f8'))
            for z in range(ev.size):c.require(np.isfinite(av[z]) and error[z]<=t['atol']+t['rtol']*abs(float(ev[z])),'numeric',dict(case=j['name'],index=z,actual=float(av[z]),expected=float(ev[z])))
            nrmse=float(np.sqrt(np.mean(error**2))/max(np.sqrt(np.mean(ev.astype('f8')**2)),1e-12))
            c.require(nrmse<=t['nrmse'],'numeric','frozen NRMSE')
            metrics.append(dict(case=j['name'],api_cycles=reports[g,1],sfu_calls=reports[g,2],max_abs=float(error.max()),nrmse=nrmse))
        c.equal(set(reports),expected,'report','exact complete report set')
        c.equal(reports[2,0],0,'state','idle');c.equal(reports[2,1],0,'owner','released')
        c.equal(int(dut.owner.value),0,'owner','hardware release')
        c.equal(int(dut.backend_idle.value),1,'drain','native idle')
        c.equal(int(dut.ddr_fault.value),0,'fault','no quarantine')
        c.require(int(dut.retired.value)>1000,'execution','real CPU retired instructions')
    except BaseException as error:
        if c.first_failure is None:c.first_failure={'category':'test_exception','detail':repr(error)}
        raise
    finally:
        sequence=hashlib.sha256(Path('transactions.csv').read_bytes()).hexdigest() if Path('transactions.csv').exists() else None
        Path('observations.json').write_text(json.dumps(dict(metrics=metrics,sequence_sha256=sequence),indent=2)+'\n')
        c.save('checks.json',**{k:cfg[k] for k in ('case_id','run_id','seed','fixture_sha256')},sequence_sha256=sequence)
