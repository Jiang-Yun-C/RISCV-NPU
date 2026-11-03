import hashlib,json,os,sys
from pathlib import Path
import cocotb
from cocotb.triggers import Timer,with_timeout
from common.checks import Checks
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from tests.opt13.score import score
@cocotb.test()
async def opt13_runtime(dut):
    cfg=json.loads(Path(os.environ['NEXUSRV_CASE']).read_text());c=Checks();metrics={}
    try:
        for k in ('fixture','golden'):c.equal(hashlib.sha256(Path(cfg[k]).read_bytes()).hexdigest(),cfg[k+'_sha256'],'input_identity',k)
        g=json.loads(Path(cfg['golden']).read_text())
        if cfg.get('negative')=='bad-golden':g['cases'][0]['logits'][0]+=100
        async def done():
            while not int(dut.completed.value) and not int(dut.timed_out.value):await Timer(100000,unit='ns')
            c.require(bool(int(dut.completed.value)),'completion','bounded real CPU completion')
        await with_timeout(done(),cfg['max_cycles']*10+100000,'ns')
        c.equal(int(dut.exit_code.value),0x1300,'completion','firmware exit')
        await Timer(1000,unit='ns');metrics=score('cpu-output.txt',g,c)
        c.require(int(dut.retired.value)>1000,'execution','real instructions')
        c.require(int(dut.axi_reads.value)>100 and int(dut.axi_writes.value)>100,'axi','actual AXI loads/stores')
        c.equal(int(dut.protection_error.value),0,'memory_protection','no stores outside arenas')
    except BaseException as e:
        if c.first_failure is None:c.first_failure=dict(category='exception',detail=repr(e))
        raise
    finally:
        sequence=hashlib.sha256(Path('cpu-output.txt').read_bytes()).hexdigest() if Path('cpu-output.txt').exists() else None
        Path('observations.json').write_text(json.dumps(dict(metrics=metrics,cycles=int(dut.cycles.value),retired=int(dut.retired.value),sequence_sha256=sequence),indent=2)+'\n')
        c.save('checks.json',**{k:cfg[k] for k in ('case_id','run_id','seed','profile','fixture_sha256','golden_sha256')},sequence_sha256=sequence,runtime=dict(python=sys.version,prefix=sys.prefix,cocotb=cocotb.__version__))
