"""Environment-only cocotb: CPU owns every native submission and result read."""
import hashlib,json,os,sys
from pathlib import Path
import cocotb
from cocotb.triggers import Timer
from common.checks import Checks
from scoreboard import score

@cocotb.test()
async def soc_accel(dut):
    cfg=json.loads(Path(os.environ['NEXUSRV_CASE']).read_text());c=Checks();result={}
    try:
        for key in ('fixture','golden'):c.equal(hashlib.sha256(Path(cfg[key]).read_bytes()).hexdigest(),cfg[key+'_sha256'],'input_identity',key)
        fixture=json.loads(Path(cfg['fixture']).read_text());golden=json.loads(Path(cfg['golden']).read_text())
        while not int(dut.completed.value) and not int(dut.timed_out.value):await Timer(100000,unit='ns')
        c.require(bool(int(dut.completed.value)),'completion','bounded wait for real CPU exit')
        c.equal(int(dut.exit_code.value),0,'completion','real firmware exit')
        await Timer(1000,unit='ns')
        result,c=score('.',fixture,golden,Path(cfg['fixture']).parent,c,cfg.get('negative'))
        c.require(int(dut.retired.value)>1000,'execution','actual VexRiscv instruction retirement')
        c.equal(int(dut.owner.value),0,'ownership','final owner release');c.equal(int(dut.backend_idle.value),1,'visibility','actual final bus drain')
        for address in fixture['guards']:
            for offset in (0,4,8,12):
                dut.peek_address.value=address+offset;await Timer(2,unit='ns');c.equal(int(dut.peek_value.value),0xa5a5a5a5,'protection','actual shared guard')
        result.update(cycles=int(dut.cycles.value),retired=int(dut.retired.value),scope='REAL_VEXRISCV_CORAL_RVV_AXI_SHARED_SPARSE_DDR',test_mode='PRELOAD')
    except BaseException as error:
        if c.first_failure is None:c.first_failure={'category':'test_exception','detail':repr(error)}
        raise
    finally:
        sequence=hashlib.sha256(Path('transactions.csv').read_bytes()).hexdigest() if Path('transactions.csv').exists() else None
        Path('observations.json').write_text(json.dumps(dict(result=result,sequence_sha256=sequence),indent=2)+'\n')
        c.save('checks.json',**{k:cfg[k] for k in ('case_id','run_id','seed','profile','fixture_sha256','golden_sha256')},sequence_sha256=sequence,result=result,runtime=dict(python=sys.version,prefix=sys.prefix,cocotb=cocotb.__version__))
