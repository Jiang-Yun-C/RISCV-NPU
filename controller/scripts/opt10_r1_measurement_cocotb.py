"""Cocotb scheduling adapter; new runners opt in explicitly before freezing."""
from pathlib import Path
import json
from cocotb.triggers import ReadOnly, RisingEdge, Timer
from scripts.opt10_r1_measurement import TerminalSample, close_after_inspection


async def inspect_writable(inspect):
    # Guest completion can be observed in ReadOnly. Advance out of that phase
    # before assigning any passive peek address; this is outside API timing.
    await Timer(1, unit='ns')
    return await inspect()


async def close_observation(dut, inspect, *, transport_state, deadline, stable_cycles=4):
    """transport_state supplies (fully_drained, monotonic_channel_activity).

    It must include DMA/native accepted requests and held responses. Its own raw
    ledger remains a separate integration obligation; backend_idle is not enough.
    """
    async def advance():
        await RisingEdge(dut.clk)
        await ReadOnly()

    async def inspect_then_settle():
        value = await inspect_writable(inspect)
        await advance()
        return value

    def sample():
        drained, activity = transport_state()
        return TerminalSample(int(dut.cycles.value), int(dut.cpu_write_accepts.value),
            int(dut.cpu_write_responses.value), bool(drained),
            bool(int(dut.timed_out.value)), int(activity))

    return await close_after_inspection(inspect_then_settle, sample, advance,
        deadline=deadline, stable_cycles=stable_cycles)


async def save_observer_output(result, checks, metadata, *, partial_inspect=None):
    """Best-effort partial inspection cannot suppress required failure outputs."""
    try:
        if partial_inspect is not None:
            result['partial_inspection'] = await inspect_writable(partial_inspect)
    except BaseException as error:
        result['partial_inspection_error'] = repr(error)
        if checks.first_failure is None:
            checks.first_failure = dict(category='partial_inspection', detail=repr(error))
    finally:
        try:
            Path('observations.json').write_text(json.dumps(result, indent=2) + '\n')
        finally:
            checks.save('checks.json', **metadata)
