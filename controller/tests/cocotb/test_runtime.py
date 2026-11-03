"""T12: real CPU + T04 memory, independent text/numeric/control scoreboard."""
import hashlib
import json
import os
from pathlib import Path
import sys
import cocotb
from cocotb.triggers import Timer
from common.checks import Checks,digest
from check import records,score

@cocotb.test()
async def runtime_execution(dut):
    cfg=json.loads(Path(os.environ['NEXUSRV_CASE']).read_text());checks=Checks();result={}
    try:
        for k in ('fixture','golden'):
            checks.equal(hashlib.sha256(Path(cfg[k]).read_bytes()).hexdigest(),cfg[k+'_sha256'],'input_identity',k)
        fixture=json.loads(Path(cfg['fixture']).read_text());golden=json.loads(Path(cfg['golden']).read_text())
        for rec in fixture['images']:
            checks.equal(hashlib.sha256(Path(rec['path']).read_bytes()).hexdigest(),rec['sha256'],'input_identity',rec['path'])
        if cfg.get('negative')=='bad-golden':golden['texts'][1]['ids'][0]^=1
        while not int(dut.completed.value) and not int(dut.timed_out.value):
            await Timer(10000,unit='ns')
        checks.require(bool(int(dut.completed.value)),'completion','simulation cycle timeout without CPU exit')
        checks.equal(int(dut.exit_code.value),0x1200,'completion','firmware exit')
        await Timer(1000,unit='ns')
        observed=records('cpu-output.txt')
        checks.equal(len(observed),int(dut.report_count.value),'output_set','passive AXI report count')
        checks,metrics=score(observed,golden,cfg['profile'],checks)
        checks.require(int(dut.retired.value)>1000,'execution','real RTL instruction retirement')
        checks.require(int(dut.axi_reads.value)>1000 and int(dut.axi_writes.value)>1000 and int(dut.protocol_checks.value)>1000,'axi','real memory transactions and passive protocol checks')
        checks.equal(int(dut.protection_error.value),0,'memory_protection','all stores inside approved regions; weights/tokenizer/stack guard protected')
        async def peek(address):
            dut.peek_address.value=address;await Timer(2,unit='ns');return int(dut.peek_value.value)
        for addr in fixture['guard_addresses']:
            checks.equal(await peek(addr),0xa5a5a5a5,'memory_protection',hex(addr))
        # Sentinel scan measures the stack used by this actual RV32 binary.
        first=0xb8000000
        for addr in range(0xb7ff0000,0xb8000000,4):
            if await peek(addr)!=0xa5a5a5a5:first=addr;break
        peak=0xb8000000-first
        checks.require(0<peak<65536-16,'memory_protection','measured stack peak within 64KiB guard')
        result={'cycles':int(dut.cycles.value),'retired':int(dut.retired.value),
                'axi_reads':int(dut.axi_reads.value),'axi_writes':int(dut.axi_writes.value),
                'stack_peak_bytes':peak,'metrics':metrics,'reports':len(observed),'backend':'CPU_C',
                'hardware_calls':0,'control_fixture':'CONTROL_ONLY' if cfg['profile']=='control' else 'ONE_LAYER_W8_REAL_KERNELS'}
    except BaseException as e:
        if checks.first_failure is None:checks.first_failure={'category':'test_exception','detail':repr(e)}
        raise
    finally:
        sequence=hashlib.sha256(Path('cpu-output.txt').read_bytes()).hexdigest() if Path('cpu-output.txt').exists() else None
        Path('observations.json').write_text(json.dumps({'summary':result,'sequence_sha256':sequence,'scope':'CPU-produced AXI MMIO records; initial 10000-cycle VCD window'},indent=2)+'\n')
        checks.save('checks.json',case_id=cfg['case_id'],run_id=cfg['run_id'],seed=cfg['seed'],profile=cfg['profile'],
                    fixture_sha256=cfg['fixture_sha256'],golden_sha256=cfg['golden_sha256'],sequence_sha256=sequence,
                    runtime={'python':sys.version,'executable':sys.executable,'prefix':sys.prefix,'cocotb':cocotb.__version__},result=result)
