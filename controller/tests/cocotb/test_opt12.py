import hashlib,json,os,sys
from pathlib import Path
import cocotb
from cocotb.triggers import Timer
from tests.opt12.checks import Checks
from tests.opt12.score import score

@cocotb.test()
async def opt12(d):
    cfg=json.loads(Path(os.environ['NEXUSRV_CASE']).read_text());c=Checks();result={}
    try:
        p=Path(cfg['fixture']);c.equal(hashlib.sha256(p.read_bytes()).hexdigest(),cfg['fixture_sha256'],'identity','fixture')
        fixture=json.loads(p.read_text())
        while not int(d.completed.value) and not int(d.timed_out.value):await Timer(100000,unit='ns')
        c.require(int(d.completed.value)==1,'completion','bounded CPU completion');c.equal(int(d.exit_code.value),0,'completion','real firmware exit')
        await Timer(1000,unit='ns')
        while int(d.cpu_write_accepts.value)!=int(d.cpu_write_responses.value) and not int(d.timed_out.value):await Timer(8,unit='ns')
        c.equal(int(d.cpu_write_accepts.value),int(d.cpu_write_responses.value),'protocol','CPU B drained')
        result=score('.',fixture,c,cfg.get('negative'))
        c.require(int(d.retired.value)>1000,'execution','actual VexRiscv retirement');c.equal(int(d.owner.value),0,'ownership','final release');c.equal(int(d.backend_idle.value),1,'drain','final backend idle')
        c.equal(int(d.ddr_fault.value),0,'protocol','no native quarantine');c.require(int(d.native_protocol_checks.value)>0,'native','independent native checks')
    except BaseException as e:
        if c.first_failure is None:c.first_failure={'category':'exception','detail':repr(e)}
        raise
    finally:
        seq=hashlib.sha256(Path('transactions.csv').read_bytes()).hexdigest() if Path('transactions.csv').exists() else None
        Path('observations.json').write_text(json.dumps(dict(result=result,sequence_sha256=seq),indent=2)+'\n')
        c.save('checks.json',case_id=cfg['case_id'],run_id=cfg['run_id'],seed=cfg['seed'],fixture_sha256=cfg['fixture_sha256'],runtime=dict(prefix=sys.prefix,cocotb=cocotb.__version__))
