import hashlib,json,os,sys
from pathlib import Path
import cocotb
from cocotb.triggers import Timer
from common.checks import Checks
@cocotb.test()
async def opt08_copy(dut):
    cfg=json.loads(Path(os.environ['NEXUSRV_CASE']).read_text());c=Checks();result={}
    try:
        for k in ('fixture','golden'):c.equal(hashlib.sha256(Path(cfg[k]).read_bytes()).hexdigest(),cfg[k+'_sha256'],'input_identity',k)
        golden=json.loads(Path(cfg['golden']).read_text())
        while not int(dut.completed.value) and not int(dut.timed_out.value):await Timer(100000,unit='ns')
        c.require(bool(int(dut.completed.value)),'completion','bounded actual CPU exit');c.equal(int(dut.exit_code.value),0x800,'completion','firmware exit')
        records={}
        for line in Path('cpu-output.txt').read_text().splitlines():
            g,i,v=map(int,line.split());c.require((g,i) not in records,'output_set','unique complete record');records[g,i]=v
        expected_keys={(0,i) for i in range(5)}|{(1+(i>>16),i&65535) for i in range(151936)}
        c.equal(set(records),expected_keys,'output_set','exact complete vocabulary inventory')
        c.equal(records[0,2],151936,'data','full vocabulary');c.equal(records[0,3],golden['hash'],'data','all copied words independent hash');c.equal(records[0,4],0,'data','firmware complete readback')
        elapsed=records[0,0]+(records[0,1]<<32);c.require(elapsed>0,'timing','actual mcycle copy cost')
        h=2166136261
        for i in range(151936):
            actual=records[1+(i>>16),i&65535];expected=0x3f000000+(i*13&0x7fffff)
            c.equal(actual,expected,'data','actual CPU load of copied logits word');h=((h^actual)*16777619)&0xffffffff
        c.equal(h,golden['hash'],'data','independent full output hash');c.require(int(dut.retired.value)>1000,'execution','real CPU retirement');c.equal(int(dut.protection_error.value),0,'protection','store ranges')
        result=dict(copy_cycles=elapsed,bytes=607744,elements=151936,scope='REAL_CPU_FULL_MEMCPY_T04_BEHAVIORAL_AXI_NO_NATIVE_DDR_TIMING')
    except BaseException as e:
        if c.first_failure is None:c.first_failure=dict(category='exception',detail=repr(e))
        raise
    finally:
        Path('observations.json').write_text(json.dumps(result,indent=2)+'\n')
        c.save('checks.json',**{k:cfg[k] for k in ('case_id','run_id','seed','profile','fixture_sha256','golden_sha256')},runtime=dict(prefix=sys.prefix,cocotb=cocotb.__version__,python=sys.version))
