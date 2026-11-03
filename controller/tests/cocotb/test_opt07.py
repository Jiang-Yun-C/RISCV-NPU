"""Real production-compiled CPU SwiGLU. Observe MMIO; no result injection."""
import hashlib,json,os,sys
from pathlib import Path
import cocotb
from cocotb.triggers import Timer,with_timeout
from common.checks import Checks
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from tests.opt07.check import score

@cocotb.test()
async def opt07_swiglu(dut):
    cfg=json.loads(Path(os.environ['NEXUSRV_CASE']).read_text());c=Checks();result={}
    try:
        for k in ('fixture','golden'):
            c.equal(hashlib.sha256(Path(cfg[k]).read_bytes()).hexdigest(),cfg[k+'_sha256'],'input_identity',k)
        g=json.loads(Path(cfg['golden']).read_text())
        if cfg.get('negative')=='bad-golden':g['expected_bits'][0]=0x3f800000
        async def complete():
            while not int(dut.completed.value) and not int(dut.timed_out.value):await Timer(100000,unit='ns')
            c.require(bool(int(dut.completed.value)),'completion','cycle bound')
        await with_timeout(complete(),cfg['max_cycles']*10,'ns')
        c.equal(int(dut.exit_code.value),0x700,'completion','CPU exit')
        result=score('cpu-output.txt',g,c)
        c.require(int(dut.retired.value)>1000,'execution','real CPU instruction retirement')
        c.require(int(dut.axi_reads.value)>100,'axi','real AXI memory reads')
        c.require(int(dut.axi_writes.value)>100,'axi','real AXI stores/MMIO')
        c.equal(int(dut.protection_error.value),0,'memory_protection','store ranges')
    except BaseException as exc:
        if c.first_failure is None:c.first_failure=dict(category='exception',detail=repr(exc))
        raise
    finally:
        seq=hashlib.sha256(Path('cpu-output.txt').read_bytes()).hexdigest() if Path('cpu-output.txt').exists() else None
        Path('observations.json').write_text(json.dumps(dict(metrics=result,cycles=int(dut.cycles.value),retired=int(dut.retired.value),sequence_sha256=seq,scope=cfg['scope']),indent=2)+'\n')
        c.save('checks.json',case_id=cfg['case_id'],run_id=cfg['run_id'],seed=cfg['seed'],profile=cfg['profile'],fixture_sha256=cfg['fixture_sha256'],golden_sha256=cfg['golden_sha256'],sequence_sha256=seq,runtime=dict(python=sys.version,prefix=sys.prefix,cocotb=cocotb.__version__))
