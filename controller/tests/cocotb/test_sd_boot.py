"""Real CPU SD boot; card inputs are supplied solely on MISO pins."""
import json
import os
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'tests/boot/sd')]
import cocotb
from cocotb.triggers import Timer,with_timeout
from cocotb.utils import get_sim_time
from common.checks import Checks,digest
from evidence import sha256
from card import Card
from scoreboard import score

@cocotb.test()
async def sd_boot(dut):
    cfg=json.loads(Path(os.environ['NEXUSRV_CASE']).read_text());checks=Checks();task=None;actions=[];result={}
    fixture=json.loads(Path(cfg['fixture']).read_text());golden=json.loads(Path(cfg['golden']).read_text())
    card=Card(dut,checks,cfg['seed'])
    try:
        for key in ('fixture','golden'):checks.equal(sha256(cfg[key]),cfg[key+'_sha256'],'input_identity',key)
        await Timer(200,unit='ns');checks.equal(Path('initial.bin').read_bytes(),bytes(golden['initial_bytes']),'initial_memory','no application/model preload')
        task=cocotb.start_soon(card.run())
        async def scenario():
            for i,a in enumerate(fixture['actions']):
                checks.equal(sha256(a['image']),a['image_sha256'],'input_identity','SD card image '+a['name'])
                start=int(get_sim_time(unit='ns'))//10
                card.insert(a)
                dut.ddr_block.value=int(a['fault']=='ddr-timeout')
                dut.card_generation.value=i+1
                polls=0
                while int(dut.boot_done.value)!=i+1:
                    checks.equal(int(dut.fault_code.value),0,'execution','CPU trap-free boot')
                    await Timer(10000,unit='ns')
                    polls+=1
                    if polls%1000==0:
                        dut._log.info('SD progress attempt=%d cycles=%d retired=%d pc=%08x spi_busy=%d commands=%d',i,int(get_sim_time(unit='ns'))//10,int(dut.retired.value),int(dut.trace_pc.value),int(dut.spi.busy.value),len(card.commands))
                checks.equal(int(dut.boot_error.value),a['expected_error'],'rejection','expected boot status '+a['name'])
                checks.equal(int(dut.model_ready.value),int(a['expected_error']==0),'seal','model publication '+a['name'])
                if a['expected_error']==0:
                    target=(a['selftest']&0xffffffff)^(1 if cfg.get('negative')=='bad-golden' else 0)
                    checks.equal(int(dut.selftest.value),target,'selftest','dot of first loaded group')
                dut.capture_id.value=i;dut.capture.value=1;await Timer(100,unit='ns')
                checks.equal(int(dut.captured.value),1,'completion','capture final RAM')
                dut.capture.value=0;await Timer(100,unit='ns')
                actions.append(dict(index=i,name=a['name'],start=start,end=int(get_sim_time(unit='ns'))//10))
        await with_timeout(scenario(),cfg['max_cycles']*10,'ns')
        checks.require(int(dut.retired.value)>1000,'execution','real cached RV32 retirement')
        checks.equal(int(dut.timed_out.value),0,'completion','cycle bound')
        Path('spi-trace.json').write_text(json.dumps(dict(bytes=card.trace,commands=card.commands,actions=actions))+'\n')
        summary=score(Path.cwd(),fixture,golden,cfg,checks)
        result=dict(cycles=int(get_sim_time(unit='ns'))//10,retired=int(dut.retired.value),mode='PROTOCOL_BOOT',attempts=len(actions),**summary)
    except BaseException as error:
        if checks.first_failure is None:checks.first_failure=dict(category='completion' if 'Timeout' in type(error).__name__ else 'test_exception',detail=repr(error))
        raise
    finally:
        if task:task.cancel()
        Path('spi-trace.json').write_text(json.dumps(dict(bytes=card.trace,commands=card.commands,actions=actions))+'\n')
        Path('observations.json').write_text(json.dumps(dict(result=result,actions=actions))+'\n')
        checks.save('checks.json',case_id=cfg['case_id'],run_id=cfg['run_id'],seed=cfg['seed'],profile=cfg['profile'],
          fixture_sha256=cfg['fixture_sha256'],golden_sha256=cfg['golden_sha256'],result=result,
          sequence_sha256=digest([card.trace,card.commands,actions]),
          runtime=dict(python=sys.version,executable=sys.executable,prefix=sys.prefix,cocotb=cocotb.__version__))
