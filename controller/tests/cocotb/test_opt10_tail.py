import json,os,sys,hashlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import cocotb
from cocotb.triggers import Timer
from common.checks import Checks
from tests.opt10.tails import score
@cocotb.test()
async def opt10_tail(dut):
    cfg=json.loads(Path(os.environ['NEXUSRV_CASE']).read_text());c=Checks();result={}
    try:
        for key in ('fixture','golden'):c.equal(hashlib.sha256(Path(cfg[key]).read_bytes()).hexdigest(),cfg[key+'_sha256'],'input_identity',key)
        while not int(dut.completed.value) and not int(dut.timed_out.value):await Timer(100000,unit='ns')
        c.require(bool(int(dut.completed.value)),'completion','bounded tail completion');c.equal(int(dut.exit_code.value),0,'completion','CPU exit')
        await Timer(1000,unit='ns');result=score('.',c)
        c.equal(int(dut.owner.value),0,'ownership','final release');c.equal(int(dut.backend_idle.value),1,'visibility','final drain')
        c.equal(int(dut.ddr_fault.value),0,'native_protocol','no quarantine');c.require(int(dut.native_protocol_checks.value)>0,'native_protocol','native address checks')
    except BaseException as e:
        if c.first_failure is None:c.first_failure={'category':'exception','detail':repr(e)}
        raise
    finally:
        digest=hashlib.sha256(Path('transactions.csv').read_bytes()).hexdigest()
        Path('observations.json').write_text(json.dumps(dict(result=result,sequence_sha256=digest),indent=2)+'\n')
        c.save('checks.json',**{k:cfg[k] for k in ('case_id','run_id','seed','profile','fixture_sha256','golden_sha256')},result=result,sequence_sha256=digest,runtime=dict(python=sys.version,prefix=sys.prefix,cocotb=cocotb.__version__))
