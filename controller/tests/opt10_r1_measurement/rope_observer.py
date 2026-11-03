"""Actual RV32 old/new RoPE API brackets and complete post-inspection close."""
import json
import os
from pathlib import Path
import cocotb
from cocotb.triggers import Timer
from common.checks import Checks
from scripts.opt10_r1_measurement_cocotb import close_observation, save_observer_output


@cocotb.test()
async def rope_store(dut):
    config=json.loads(Path(os.environ['NEXUSRV_CASE']).read_text())
    checks=Checks();result={}
    try:
        while not int(dut.completed.value) and not int(dut.timed_out.value):
            await Timer(100000,unit='ns')
        checks.equal(int(dut.completed.value),1,'completion','real CPU finished')
        checks.equal(int(dut.exit_code.value),0,'completion','CPU exit')
        reports={}
        for line in Path('cpu-output.txt').read_text().splitlines():
            group,index,value=map(int,line.split())
            checks.require((group,index) not in reports,'report','unique')
            reports[group,index]=value
        checks.equal(set(reports),{(g,i) for g in range(10,26) for i in range(4)},'report','exact complete CPU reports')
        metrics=[]
        async def inspect():
            for i,case in enumerate(config['cases']):
                values=[]
                for variant in range(2):
                    words=[]
                    address=0xac000000+i*0x10000+variant*0x4000
                    for j in range(case['heads']*64):
                        dut.peek_address.value=address+4*j
                        await Timer(2,unit='ns')
                        words.append(int(dut.peek_value.value))
                    values.append(words)
                checks.equal(values[0],values[1],'numeric','old/new complete binary32 output including signed zero')
                for repeat in range(2):
                    group=10+i*4+repeat*2
                    for g in (group,group+1):
                        checks.equal(reports[g,0],0,'status','RoPE success')
                        checks.equal(reports[g,3],1,'cache','coefficient cache published')
                    cycles=[reports[g,1]|reports[g,2]<<32 for g in (group,group+1)]
                    metrics.append(dict(**case,cache_phase=('cold','hit')[repeat],old_api_cycles=cycles[0],new_api_cycles=cycles[1],saving_cycles=cycles[0]-cycles[1]))
            return dict(compared_complete_pairs=len(metrics))
        _,close=await close_observation(dut,inspect,deadline=config['max_cycles'],
            transport_state=lambda:(bool(int(dut.backend_idle.value)) and bool(int(dut.rope_native_drained.value))
                and not int(dut.rope_native_pending.value) and not int(dut.rope_upstream_pending.value),
                int(dut.cpu_write_accepts.value)+int(dut.cpu_write_responses.value)))
        result=dict(metrics=metrics,terminal_close=close,scope='FOUR_REAL_RV32_ROPE_CALL_PAIRS_NOT_FULLGRAPH_OR_TTFT',GO=False)
    except BaseException as error:
        if checks.first_failure is None:checks.first_failure=dict(category='exception',detail=repr(error))
        raise
    finally:
        # This finalizer advances no simulation time after a successful close.
        await save_observer_output(result,checks,dict(run_id=config['run_id']))
