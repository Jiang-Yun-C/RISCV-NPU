"""Bounded real CPU/Coral performance prefix; deliberately no completion claim."""
import json
from pathlib import Path
import cocotb
from cocotb.triggers import Timer
@cocotb.test()
async def bounded_window(dut):
    while not int(dut.timed_out.value):await Timer(100000,unit='ns')
    assert int(dut.cycles.value)>=3000000
    assert int(dut.launches.value)>=1
    Path('window.json').write_text(json.dumps(dict(scope='PERFORMANCE_PREFIX_ONLY',cycles=int(dut.cycles.value),launches=int(dut.launches.value),completed=int(dut.completed.value))))
