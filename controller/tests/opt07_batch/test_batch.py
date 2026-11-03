"""Supplementary 24x4864 run; same VexRiscv RTL and T04 AXI environment."""
import hashlib,json,os,sys
from pathlib import Path
import cocotb
from cocotb.triggers import Timer,with_timeout
from common.checks import Checks
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from tests.opt07.check import score
from tests.runtime.check import records

@cocotb.test()
async def opt07_batch(dut):
    cfg=json.loads(Path(os.environ['NEXUSRV_CASE']).read_text());c=Checks();results=[]
    try:
        for k in ('fixture','golden'):
            c.equal(hashlib.sha256(Path(cfg[k]).read_bytes()).hexdigest(),cfg[k+'_sha256'],'input_identity',k)
        gold=json.loads(Path(cfg['golden']).read_text())
        async def complete():
            while not int(dut.completed.value) and not int(dut.timed_out.value):await Timer(1000000,unit='ns')
            c.require(bool(int(dut.completed.value)),'completion','bounded 24-layer run')
        await with_timeout(complete(),cfg['max_cycles']*10,'ns')
        c.equal(int(dut.exit_code.value),0x700,'completion','actual CPU exit')
        observed=records('cpu-output.txt');used=0
        for layer,g in enumerate(gold['layers']):
            selected={(a-layer*100,i):v for (a,i),v in observed.items() if 100+layer*100<=a<200+layer*100}
            local=Path('layer%02d.txt'%layer);local.write_text(''.join(f'{a} {i} {v}\n' for (a,i),v in selected.items()))
            result=score(local,g,c);results.append(result);used+=len(selected)
        c.equal(used,len(observed),'output_set','all 24 layers consumed')
        c.require(int(dut.retired.value)>100000,'execution','real CPU retirement')
        c.require(int(dut.axi_reads.value)>10000 and int(dut.axi_writes.value)>10000,'axi','real T04 transactions')
        c.equal(int(dut.protection_error.value),0,'memory_protection','all stores in approved regions')
    except BaseException as exc:
        if c.first_failure is None:c.first_failure=dict(category='exception',detail=repr(exc))
        raise
    finally:
        seq=hashlib.sha256(Path('cpu-output.txt').read_bytes()).hexdigest() if Path('cpu-output.txt').exists() else None
        Path('observations.json').write_text(json.dumps(dict(layers=results,cycles=int(dut.cycles.value),retired=int(dut.retired.value),sequence_sha256=seq,scope=cfg['scope']),indent=2)+'\n')
        c.save('checks.json',case_id=cfg['case_id'],run_id=cfg['run_id'],seed=cfg['seed'],profile='batch24',fixture_sha256=cfg['fixture_sha256'],golden_sha256=cfg['golden_sha256'],sequence_sha256=seq,runtime=dict(python=sys.version,prefix=sys.prefix,cocotb=cocotb.__version__))
