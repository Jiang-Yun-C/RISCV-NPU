"""Short actual VCS/cocotb regression for scheduling and terminal observation."""
import json
from pathlib import Path
import cocotb
from cocotb.triggers import ReadOnly, RisingEdge, Timer
from common.checks import Checks
from scripts.opt10_r1_measurement_cocotb import (
    close_observation, inspect_writable, save_observer_output,
)


@cocotb.test()
async def observer_boundary(dut):
    while not int(dut.completed.value):
        await RisingEdge(dut.clk)
        await ReadOnly()
    assert int(dut.backend_idle.value) == 1
    assert int(dut.cpu_write_accepts.value) > int(dut.cpu_write_responses.value)
    # Reproduce the original service failure in an actual ReadOnly phase.
    try:
        dut.peek_address.value = 4
    except RuntimeError as error:
        Path('readonly-reproduced.txt').write_text(repr(error) + '\n')
    else:
        raise AssertionError('expected actual cocotb ReadOnly write rejection')

    async def inspect():
        words = []
        for i in range(80):
            dut.peek_address.value = i * 4
            await Timer(2, unit='ns')
            words.append(int(dut.peek_value.value))
        assert words == [(i * 4) ^ 0x12345678 for i in range(80)]
        return dict(words=len(words), inspected_until_cycle=int(dut.cycles.value))

    # A secondary partial peek failure must not suppress primary failure files.
    checks = Checks()
    checks.first_failure = dict(category='original_failure', detail='preserve me')
    async def broken_partial():
        dut.peek_address.value = 8
        raise RuntimeError('injected partial inspection failure')
    await save_observer_output(dict(stage='FAILED_PRIMARY'), checks,
        dict(case_id='short-failure-finally'), partial_inspect=broken_partial)
    saved = json.loads(Path('checks.json').read_text())
    observed = json.loads(Path('observations.json').read_text())
    assert saved['status'] == 'FAIL'
    assert saved['first_failure']['category'] == 'original_failure'
    assert 'injected partial inspection failure' in observed['partial_inspection_error']
    inspected, close = await close_observation(dut, inspect, deadline=128,
        transport_state=lambda: (int(dut.backend_idle.value) == 1 and int(dut.native_pending.value) == 0,
            int(dut.native_activity.value)))
    assert close['accepted'] == close['responses'] == 6
    assert close['cycle'] == 60
    assert close['stable_since_cycle'] == 56
    assert close['transport_activity'] == 3
    assert inspected['inspected_until_cycle'] >= 21
    Path('close.json').write_text(json.dumps(close, indent=2) + '\n')
    Path('inspection.json').write_text(json.dumps(inspected, indent=2) + '\n')

