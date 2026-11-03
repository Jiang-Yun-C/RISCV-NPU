"""Environment-only test of real CPU -> production adapter/driver -> CE/guard/native."""
import hashlib,json,os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import cocotb
from cocotb.triggers import Timer
from common.checks import Checks
from tests.opt08.score import score
@cocotb.test()
async def opt08(dut):
    cfg=json.loads(Path(os.environ['NEXUSRV_CASE']).read_text());c=Checks();result={}
    try:
        for key in ('fixture','golden'):c.equal(hashlib.sha256(Path(cfg[key]).read_bytes()).hexdigest(),cfg[key+'_sha256'],'input_identity',key)
        fixture=json.loads(Path(cfg['fixture']).read_text());golden=json.loads(Path(cfg['golden']).read_text())
        while not int(dut.completed.value) and not int(dut.timed_out.value):await Timer(100000,unit='ns')
        c.require(bool(int(dut.completed.value)),'completion','bounded CPU completion');c.equal(int(dut.exit_code.value),0,'completion','firmware exit')
        await Timer(1000,unit='ns')
        while int(dut.cpu_write_accepts.value)!=int(dut.cpu_write_responses.value) and not int(dut.timed_out.value):await Timer(8,unit='ns')
        c.equal(int(dut.cpu_write_accepts.value),int(dut.cpu_write_responses.value),'axi','all CPU B responses consumed')
        result=score('.',fixture,golden,c,cfg.get('negative'))
        c.require(int(dut.retired.value)>1000,'execution','real VexRiscv retirement')
        c.equal(int(dut.owner.value),0,'ownership','final release');c.equal(int(dut.backend_idle.value),1,'visibility','actual final drain');c.equal(int(dut.ddr_fault.value),0,'native_protocol','no native quarantine')
        c.require(int(dut.native_protocol_checks.value)>0,'native_protocol','independent native column/ID checks')
        result.update(cycles_total=int(dut.cycles.value),retired=int(dut.retired.value),native_protocol_checks=int(dut.native_protocol_checks.value),scope='REAL_CPU_CE64_GUARD_NATIVE_DIGITAL',write_drain_cycles=1024)
    except BaseException as error:
        if c.first_failure is None:c.first_failure={'category':'test_exception','detail':repr(error)}
        raise
    finally:
        sequence=hashlib.sha256(Path('transactions.csv').read_bytes()).hexdigest() if Path('transactions.csv').exists() else None
        Path('observations.json').write_text(json.dumps(dict(result=result,sequence_sha256=sequence),indent=2)+'\n')
        c.save('checks.json',**{k:cfg[k] for k in ('case_id','run_id','seed','profile','fixture_sha256','golden_sha256')},sequence_sha256=sequence,result=result,runtime=dict(python=sys.version,prefix=sys.prefix,cocotb=cocotb.__version__))
