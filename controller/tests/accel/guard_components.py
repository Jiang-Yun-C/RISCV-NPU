"""Explicit component test, not firmware/backend execution evidence."""
from cocotb.triggers import Timer,RisingEdge,FallingEdge

async def exercise(dut,checks):
    bus=dut.probe_up
    fields=['awready','wready','bvalid','bresp','bid','arready','rvalid','rresp','rid','rdata','rlast']
    for name in ('awvalid','awaddr','awid','awlen','awsize','awburst','wvalid','wdata','wstrb','wlast','bready',
                 'arvalid','araddr','arid','arlen','arsize','arburst','rready'):getattr(bus,name).value=0
    await FallingEdge(dut.clk)
    async def step():
        await Timer(1,unit='ns');v={n:int(getattr(bus,n).value) for n in fields}
        await RisingEdge(dut.clk);await FallingEdge(dut.clk);return v
    await step();dut.probe_reset_n.value=1;await step()
    async def write(address,values,response=0,wfirst=False,isolate_partial=False):
        bus.awaddr.value=address;bus.awlen.value=len(values)-1;bus.awsize.value=2;bus.awburst.value=1;bus.awid.value=37
        bus.bready.value=1;index=0;aw_done=False;w_done=False;partial=False
        for tick in range(400):
            # Independent AW/W valid arrival; no assumptions about slave ready.
            bus.awvalid.value=not aw_done and (not wfirst or tick>=5)
            bus.wvalid.value=index<len(values) and (wfirst or tick>=5)
            if index<len(values):
                lane=(address+4*index)&15;bus.wdata.value=values[index]<<(8*lane);bus.wstrb.value=15<<lane;bus.wlast.value=index==len(values)-1
            v=await step()
            if not aw_done and (not wfirst or tick>=5) and v['awready']:aw_done=True;partial=True
            if index<len(values) and (wfirst or tick>=5) and v['wready']:index+=1;partial=True
            if isolate_partial and partial:dut.probe_isolate.value=1
            if v['bvalid']:
                checks.equal(v['bresp'],response,'component_axi','write response')
                checks.equal(v['bid'],37,'component_axi','write ID');checks.equal(index,len(values),'component_axi','all W beats consumed')
                bus.awvalid.value=0;bus.wvalid.value=0;await step()
                checks.equal(int(dut.probe_idle.value),1,'component_isolation','fully drained after B')
                dut.probe_isolate.value=0;await step();return
        checks.require(False,'component_axi','write timeout')
    async def read(address,count,response=0):
        bus.araddr.value=address;bus.arlen.value=count-1;bus.arsize.value=2;bus.arburst.value=1;bus.arid.value=18;bus.arvalid.value=1
        accepted=False;result=[]
        for tick in range(400):
            ready=tick%3!=0;bus.rready.value=ready;v=await step()
            if not accepted and v['arready']:accepted=True;bus.arvalid.value=0
            if v['rvalid'] and ready:
                checks.equal(v['rresp'],response,'component_axi','read response');checks.equal(v['rid'],18,'component_axi','read ID')
                lane=(address+4*len(result))&15;result.append((v['rdata']>>(8*lane))&0xffffffff)
                checks.equal(v['rlast'],int(len(result)==count),'component_axi','exact RLAST')
                if v['rlast']:return result
        checks.require(False,'component_axi','read timeout')
    values=[0x76543210+i for i in range(4)]
    for address in (0xa8000000,0xac000ff0,0xba000000):
        await write(address,values,wfirst=True);checks.equal(await read(address,4),values,'component_data',hex(address))
    # Accepted AW must retain W/B state across isolation; early W must also drain.
    await write(0xba000040,[0xabc],isolate_partial=True)
    await write(0xba000080,[0xdef],response=3,wfirst=True,isolate_partial=True)
    checks.equal(await read(0xba000040,1),[0xabc],'component_isolation','accepted write survives isolate')
    checks.equal(await read(0xba000080,1),[0],'component_isolation','unissued write rejected after early W isolation')
    for address in (0x80000000,0xb4000000,0xb8000000,0xbc000000,0x20000000,0xfffffff0,0xabfffffc):
        await write(address,values,response=3)
    for address in (0xb4000000,0xb8000000,0xbc000000,0x20000000,0xfffffff0,0xabfffffc):
        checks.equal(await read(address,4,response=3),[0]*4,'component_protection','denied read returns no memory')
    checks.equal(await read(0x80000000,4),[0]*4,'component_protection','sealed weights readable')
    checks.equal(int(dut.probe_error.value),1,'component_protection','sticky protection error')
    dut.probe_clear.value=1;await step();dut.probe_clear.value=0;await step()
    checks.equal(int(dut.probe_error.value),0,'component_isolation','clear only after drain')
    dut.probe_isolate.value=1;bus.araddr.value=0x80000000;bus.arlen.value=0;bus.arvalid.value=1
    for _ in range(5):checks.equal((await step())['arready'],0,'component_isolation','new reads stopped while isolated')
    dut.probe_isolate.value=0
    checks.equal(await read(0x80000000,1),[0],'component_isolation','new read resumes after release')
