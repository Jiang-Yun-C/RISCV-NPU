"""Observe terminal CPU B retirement after exit MMIO acceptance."""
from cocotb.triggers import Timer

async def terminal_writes_drained(dut):
    stable=0
    while not int(dut.timed_out.value):
        if int(dut.cpu_write_accepts.value)==int(dut.cpu_write_responses.value) and int(dut.backend_idle.value):
            stable+=1
            if stable==2:return True
        else:stable=0
        await Timer(16,unit='ns')
    return False
