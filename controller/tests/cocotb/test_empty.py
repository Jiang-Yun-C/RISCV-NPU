"""Intentional empty test: XML success must not satisfy independent checks."""
import cocotb
@cocotb.test()
async def empty(dut):
    pass
