import itertools
import json
from pathlib import Path
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles,Timer
from cocotbext.axi import AxiBus,AxiMaster,AxiResp


@cocotb.test()
async def sd_local_devices(dut):
    dut.reset_n.value=1
    await Timer(2,unit='ns')
    bus=AxiMaster(AxiBus.from_prefix(dut,'s'),dut.clk,reset=dut.reset_n,reset_active_level=False)
    # cocotbext initializes inactive payloads to X. This router computes READY
    # from the offered address; give idle payloads defined values before clocks.
    for name in ('awaddr','awid','awlen','awsize','awburst','wdata','wstrb','wlast',
                 'araddr','arid','arlen','arsize','arburst'):
        getattr(dut,'s_'+name).value=0
    await Timer(2,unit='ns')
    dut.reset_n.value=0
    await Timer(2,unit='ns')
    cocotb.start_soon(Clock(dut.clk,8,unit='ns').start(start_high=False))
    bus.read_if.r_channel.set_pause_generator(itertools.cycle([1,1,1,0]))
    bus.write_if.b_channel.set_pause_generator(itertools.cycle([1,1,0]))
    await ClockCycles(dut.clk,8)
    dut._log.info('RESET BUS '+str({n:str(getattr(dut,'s_'+n).value) for n in ('awaddr','awvalid','awready','wvalid','wready','araddr','arvalid','arready','bvalid','rvalid')}))
    dut.reset_n.value=1;await ClockCycles(dut.clk,8)
    checks=0

    async def read(a,expected,resp=AxiResp.OKAY):
        nonlocal checks
        r=await bus.read(a,4,size=2,arid=0)
        assert r.resp==resp,(hex(a),r.resp,resp)
        assert int.from_bytes(r.data,'little')==expected,(hex(a),r.data,expected)
        checks+=2

    async def write(a,v):
        nonlocal checks
        r=await bus.write(a,v.to_bytes(4,'little'),size=2,awid=0)
        assert r.resp==AxiResp.OKAY,(hex(a),r.resp)
        checks+=1

    assert int(dut.model_sealed.value)==0;checks+=1
    await read(0x10002024,1)
    await read(0x10002034,1)
    await read(0x10002018,0)
    # A diagnostic UART seal does not authorize the SD model guard.
    await write(0x100000e0,0x5345414c)
    assert int(dut.model_sealed.value)==0;checks+=1
    for a,v in [(0x20000,0x1234abcd),(0x2fffc,0xaabbccdd),(0x20010,0x5555aaaa)]:
        await write(a,v);await read(a,v)
    for off,value in [(0x18,1),(0x1c,3),(0x20,1),(0x28,0xffc32),(0x2c,467)]:
        await write(0x10002000+off,value);await read(0x10002000+off,value)
    assert int(dut.model_sealed.value)==1;checks+=1
    # Actual mode-0 pins are looped back, rather than supplying RX data via MMIO.
    await write(0x10002004,1)
    await write(0x10002010,0)
    assert int(dut.sd_cs_n.value)==0;checks+=1
    for value in (0xa5,0,0xff,0x3c):
        await write(0x10002008,value)
        await ClockCycles(dut.clk,80)
        await read(0x10002000,0)
        await read(0x1000200c,value)
    await write(0x10002010,1)
    assert int(dut.sd_cs_n.value)==1;checks+=1
    await read(0x10002044,0,AxiResp.DECERR)
    await write(0x10002018,0)
    assert int(dut.model_sealed.value)==0;checks+=1
    await read(0x20000,0x1234abcd)
    dut.reset_n.value=0;await ClockCycles(dut.clk,8);dut.reset_n.value=1;await ClockCycles(dut.clk,8)
    await read(0x10002018,0)
    assert int(dut.model_sealed.value)==0;checks+=1
    Path('local-checks.json').write_text(json.dumps(dict(status='PASS',checks=checks,
        scope='Actual T25 local RTL, SPI pins, RAM routing, held AXI responses and SD-only seal; no physical board')))
