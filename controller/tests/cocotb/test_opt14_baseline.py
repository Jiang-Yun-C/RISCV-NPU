import hashlib,json,os,sys
from pathlib import Path
import cocotb
from cocotb.triggers import Timer
from common.checks import Checks
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tests.opt14.score import score

@cocotb.test()
async def opt14_baseline(dut):
    cfg=json.loads(Path(os.environ['NEXUSRV_CASE']).read_text());c=Checks();result={}
    try:
        for key in ('fixture','golden'):
            c.equal(hashlib.sha256(Path(cfg[key]).read_bytes()).hexdigest(),cfg[key+'_sha256'],'input_identity',key)
        while not int(dut.completed.value) and not int(dut.timed_out.value):
            await Timer(100000,unit='ns')
        c.require(bool(int(dut.completed.value)),'completion','bounded real CPU exit')
        c.equal(int(dut.exit_code.value),0x800,'completion','firmware exit')
        result=score('cpu-output.txt',json.loads(Path(cfg['golden']).read_text()),c)
        c.require(int(dut.retired.value)>1000,'execution','real CPU retirement')
        c.equal(int(dut.protection_error.value),0,'protection','CPU write ranges')
    except BaseException as error:
        if c.first_failure is None:c.first_failure=dict(category='exception',detail=repr(error))
        raise
    finally:
        Path('observations.json').write_text(json.dumps(result,indent=2)+'\n')
        c.save('checks.json',**{k:cfg[k] for k in ('case_id','run_id','seed','profile','fixture_sha256','golden_sha256')},
               runtime=dict(prefix=sys.prefix,cocotb=cocotb.__version__,python=sys.version))
