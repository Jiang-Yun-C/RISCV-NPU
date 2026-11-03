"""Actual cached VexRiscv firmware + RTL bridge/guard + labeled endpoint double."""
import hashlib,json,os,sys
from pathlib import Path
import cocotb
from cocotb.triggers import Timer
from common.checks import Checks
from accel_check import score,check_transactions

@cocotb.test()
async def accel_control(dut):
    cfg=json.loads(Path(os.environ['NEXUSRV_CASE']).read_text());checks=Checks();result={}
    try:
        for key in ('fixture','golden'):
            checks.equal(hashlib.sha256(Path(cfg[key]).read_bytes()).hexdigest(),cfg[key+'_sha256'],'input_identity',key)
        fixture=json.loads(Path(cfg['fixture']).read_text());golden=json.loads(Path(cfg['golden']).read_text())
        for rec in fixture['images']:
            checks.equal(hashlib.sha256(Path(rec['path']).read_bytes()).hexdigest(),rec['sha256'],'input_identity',rec['path'])
        while not int(dut.completed.value) and not int(dut.timed_out.value):
            await Timer(10000,unit='ns')
            if cfg.get('negative')=='early-completion':
                checks.require(',EARLY,' not in Path('transactions.csv').read_text(),'visibility','owner released while backend write response pending')
        checks.require(bool(int(dut.completed.value)),'completion','cycle timeout without real CPU exit')
        checks.equal(int(dut.exit_code.value),0,'completion','firmware exit')
        await Timer(1000,unit='ns')
        if cfg.get('negative')=='early-completion':check_transactions(Path('.'),checks)
        metrics,count=score('.',golden,checks)
        checks.equal(count,int(dut.report_count.value),'output_set','passive report count')
        checks.require(int(dut.retired.value)>1000,'execution','real CPU instruction retirement')
        checks.equal(int(dut.owner.value),0,'ownership','final owner released')
        for addr in (0x80000000,0xb8000000,0xbc000000,0xb4000000):
            dut.peek_address.value=addr;await Timer(2,unit='ns')
            checks.equal(int(dut.peek_value.value),fixture['guard_values'][str(addr)],'protection',hex(addr))
        from guard_components import exercise
        await exercise(dut,checks)
        result={**metrics,'cycles':int(dut.cycles.value),'retired':int(dut.retired.value),'reports':count}
    except BaseException as e:
        if checks.first_failure is None:checks.first_failure={'category':'test_exception','detail':repr(e)}
        raise
    finally:
        sequence=hashlib.sha256(Path('transactions.csv').read_bytes()).hexdigest() if Path('transactions.csv').exists() else None
        Path('observations.json').write_text(json.dumps({'summary':result,'sequence_sha256':sequence,'scope':'real CPU, native adapter, firewall, T04 memory; transactional Coral substitute'},indent=2)+'\n')
        checks.save('checks.json',**{k:cfg[k] for k in ('case_id','run_id','seed','profile','fixture_sha256','golden_sha256')},
            sequence_sha256=sequence,result=result,runtime={'python':sys.version,'prefix':sys.prefix,'cocotb':cocotb.__version__})
