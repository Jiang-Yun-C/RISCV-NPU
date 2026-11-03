"""Real arithmetic/transport fault recovery, independent baseline oracle."""
import csv,hashlib,json,os
from pathlib import Path
import numpy as np
import cocotb
from cocotb.triggers import Timer
from common.checks import Checks

@cocotb.test()
async def opt10_r1(dut):
    cfg=json.loads(Path(os.environ['NEXUSRV_CASE']).read_text());c=Checks()
    try:
        for name in ('fixture','golden'):c.equal(hashlib.sha256(Path(cfg[name]).read_bytes()).hexdigest(),cfg[name+'_sha256'],'identity',name)
        while not int(dut.completed.value) and not int(dut.timed_out.value):await Timer(100000,unit='ns')
        c.require(bool(int(dut.completed.value)),'completion','actual CPU completed');c.equal(int(dut.exit_code.value),0,'completion','CPU exit');await Timer(1000,unit='ns')
        reports={}
        for line in Path('cpu-output.txt').read_text().splitlines():
            g,i,v=map(int,line.split());c.require((g,i) not in reports,'report','unique');reports[g,i]=v
        c.require(not any(g==255 for g,i in reports),'trap','no CPU trap')
        gold=json.loads(Path(cfg['golden']).read_text())['jobs'][0];want=np.float32(gold['expected'][0]);t=json.loads(Path(cfg['thresholds']).read_text())['operators']['linear']
        def numeric(bits):
            actual=np.array([bits],dtype='<u4').view('<f4')[0]
            c.require(np.isfinite(actual) and abs(float(actual)-float(want))<=t['atol']+t['rtol']*abs(float(want)),'numeric',dict(actual=float(actual),expected=float(want)))
        for i in range(4):c.equal(reports.get((1,i)),0,'setup',str(i))
        numeric(reports[1,4]);expected={(1,i) for i in range(5)}|{(2,0),(2,1)}
        for case in range(1):
            g=10+case;expected|={(g,i) for i in range(13)}
            c.require(reports.get((g,0),0)!=0,'fault','injected call rejected')
            for i in (1,2,4):c.equal(reports[g,i],0,'atomic','no completed bytes or stale lease')
            c.equal(reports[g,3],0xa5a5a5a5,'atomic','failed row never published')
            for i in (5,6,8,9):c.equal(reports[g,i],0,'recovery','reset/rebind/recover idle')
            numeric(reports[g,7]);c.require(reports[g,11]>reports[g,10],'epoch','recovered epoch advanced');c.equal(reports[g,12],1,'recovery','exactly one successful recovered call')
        c.equal(set(reports),expected,'report','complete exact report set')
        events=list(csv.reader(Path('inline-faults.csv').open()));injected=[int(x[2]) for x in events if x[0]=='INJECT'];c.equal(injected,[43],'injection','all actual states reached exactly once')
        c.require(sum(x[0]=='RESET' for x in events)>=2,'recovery','actual drained reset grants')
        c.equal(reports[2,0],0,'state','idle');c.equal(reports[2,1],0,'owner','released');c.equal(int(dut.backend_idle.value),1,'drain','native drained');c.equal(int(dut.ddr_fault.value),0,'quarantine','none')
    except BaseException as error:
        if c.first_failure is None:c.first_failure={'category':'exception','detail':repr(error)}
        raise
    finally:
        sequence=hashlib.sha256(Path('transactions.csv').read_bytes()).hexdigest() if Path('transactions.csv').exists() else None
        Path('observations.json').write_text(json.dumps(dict(sequence_sha256=sequence,scope='FORCED_CONTROL_RESPONSE_FAULTS_WITH_REAL_CPU_ARITHMETIC_NATIVE_NOT_MODEL'),indent=2)+'\n')
        c.save('checks.json',**{k:cfg[k] for k in ('case_id','run_id','seed','fixture_sha256')},sequence_sha256=sequence)
