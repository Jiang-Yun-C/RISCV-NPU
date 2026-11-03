"""Actual DMA/fault/native short proof; CPU and production owner are not modeled."""
import json
from pathlib import Path
import cocotb
from cocotb.triggers import FallingEdge,RisingEdge,ReadOnly,Timer
from common.checks import Checks
from scripts.opt10_r1_measurement_cocotb import close_observation,save_observer_output
from service_case import peek_words,transport_state


@cocotb.test()
async def service_adapter_short(dut):
    checks=Checks();events=[]
    async def tick():
        await RisingEdge(dut.clk);await ReadOnly()
        assert not int(dut.timed_out.value),'original2048 short deadline'
    async def wait(predicate,label):
        for _ in range(2048):
            await tick()
            if predicate():return
        raise AssertionError(label)
    async def command(write):
        await FallingEdge(dut.clk)
        dut.owner.value=1;dut.command_write.value=int(write);dut.command_address.value=0x80001000
        dut.command_valid.value=1
        for _ in range(2048):
            await RisingEdge(dut.clk)
            accepted=int(dut.command_ready.value)
            await ReadOnly()
            if accepted:break
            assert not int(dut.timed_out.value)
        else:raise AssertionError('command accepted')
        await FallingEdge(dut.clk);dut.command_valid.value=0
    async def consume():
        await wait(lambda:int(dut.result_valid.value)==1,'DMA result')
        checks.equal(int(dut.result_resp.value),0,'numeric','actual DMA response')
        await FallingEdge(dut.clk);dut.result_ready.value=1
        await tick();await FallingEdge(dut.clk);dut.result_ready.value=0
    await FallingEdge(dut.reset)
    await command(True)
    await wait(lambda:int(dut.held_b_valid.value)==1,'held B')
    assert int(dut.backend_idle.value)==1 and not transport_state(dut)[0]
    assert not int(dut.native_pending.value) and int(dut.upstream_pending.value)
    held_cycle=int(dut.cycles.value)
    await FallingEdge(dut.clk);dut.reset_request.value=1
    await tick();await FallingEdge(dut.clk);dut.reset_request.value=0
    for _ in range(8):
        await tick();assert int(dut.epoch.value)==0 and not int(dut.reset_grant.value)
    events.append(dict(case='real_soft_reset_waits_for_held_B',cycle=held_cycle,epoch=0))
    await FallingEdge(dut.clk);dut.allow_b.value=1
    await consume()
    await wait(lambda:int(dut.epoch.value)==1,'first drain-authorized epoch')
    await command(False)
    await FallingEdge(dut.clk);dut.allow_r.value=0
    await wait(lambda:int(dut.held_r_valid.value)==1,'held read response')
    assert not transport_state(dut)[0] and int(dut.upstream_pending.value)
    for _ in range(6):await tick()
    await FallingEdge(dut.clk);dut.allow_r.value=1
    await consume()
    checks.equal(int(dut.observed_scratch.value),0x00112233445566778899aabbccddeeff,'numeric','actual native write/readback after epoch1')
    events.append(dict(case='actual_held_R_then_numerical_warm_read',cycle=int(dut.cycles.value),epoch=1))
    await command(False)
    await FallingEdge(dut.clk);dut.run_timeout.value=1
    await tick();await FallingEdge(dut.clk);dut.run_timeout.value=0
    await consume()
    assert int(dut.faulted.value) and int(dut.stop_new.value) and not int(dut.command_ready.value)
    await FallingEdge(dut.clk);dut.reset_request.value=1
    await tick();await FallingEdge(dut.clk);dut.reset_request.value=0
    await wait(lambda:int(dut.epoch.value)==2,'fault recovery epoch')
    await command(False);await consume()
    checks.equal(int(dut.observed_scratch.value),0x00112233445566778899aabbccddeeff,'numeric','actual warm read after timeout/soft reset')
    await FallingEdge(dut.clk);dut.owner.value=0
    # Acceptance of only W must hold closure even while original paired-CW
    # counters remain zero; AW-only/held B then remains outstanding as well.
    dut.cpu_fixture_wvalid.value=1
    await tick();await FallingEdge(dut.clk);dut.cpu_fixture_wvalid.value=0
    assert int(dut.cpu_write_accepts.value)==int(dut.cpu_write_responses.value)==0
    assert not transport_state(dut)[0]
    dut.cpu_fixture_awvalid.value=1
    await tick();await FallingEdge(dut.clk);dut.cpu_fixture_awvalid.value=0
    for _ in range(6):
        await tick();assert not transport_state(dut)[0]
    await FallingEdge(dut.clk);dut.cpu_fixture_bvalid.value=1
    await tick();await FallingEdge(dut.clk);dut.cpu_fixture_bvalid.value=0
    await tick()
    # Reproduce the original scheduler error using the actual production peek helper.
    try:dut.service_stack_peek_address.value=4
    except RuntimeError as error:Path('readonly-negative.txt').write_text(repr(error)+'\n')
    else:raise AssertionError('ReadOnly write negative did not reproduce')
    negative=Checks();negative.first_failure=dict(category='primary_service_failure',detail='preserve original')
    async def broken_partial():
        await peek_words(dut,'service_stack_peek_address','service_stack_peek_value',[4,8])
        raise RuntimeError('secondary peek failure')
    await save_observer_output(dict(stage='FAILED_PRIMARY'),negative,dict(case_id='finally-negative'),partial_inspect=broken_partial)
    Path('negative-observations.json').write_bytes(Path('observations.json').read_bytes())
    Path('negative-checks.json').write_bytes(Path('checks.json').read_bytes())
    assert json.loads(Path('negative-checks.json').read_text())['first_failure']['category']=='primary_service_failure'
    assert 'secondary peek failure' in json.loads(Path('negative-observations.json').read_text())['partial_inspection_error']
    async def inspect():
        values=await peek_words(dut,'service_stack_peek_address','service_stack_peek_value',range(0,128,4))
        assert values==[a^0x12345678 for a in range(0,128,4)]
        dut.late_store.value=1
        await Timer(16,unit='ns')
        return dict(words=len(values),inspection_end_cycle=int(dut.cycles.value))
    inspected,close=await close_observation(dut,inspect,transport_state=lambda:transport_state(dut),deadline=2048,stable_cycles=4)
    assert close['accepted']==close['responses']==2
    result=dict(status='PASS',stage='COMPLETE_OBSERVER',terminal_close=close,inspection=inspected,
        component_events=events,actual_epoch=int(dut.epoch.value),actual_DMA_read_bytes=int(dut.read_bytes.value),
        actual_DMA_write_bytes=int(dut.write_bytes.value),original_native_write_drain_cycles=1024,
        production_CPU_service_qualification=False,production_owner_publication_qualification=False)
    Path('close.json').write_text(json.dumps(close,indent=2)+'\n')
    await save_observer_output(result,checks,dict(case_id='actual-dma-native-short'))
