"""Pin-level UART host and independent open-drain virtual I2C sensor."""
import struct
import cocotb
from cocotb.triggers import Timer, RisingEdge, FallingEdge

BIT_NS=320
class UART:
    def __init__(self,dut,checks):self.dut=dut;self.checks=checks;self.buffer=bytearray();self.lines=[];self.received=[]
    async def receive(self):
        while True:
            await FallingEdge(self.dut.uart_tx);await Timer(BIT_NS//2,unit='ns')
            self.checks.equal(int(self.dut.uart_tx.value),0,'uart','TX start bit')
            n=0
            for i in range(8):
                await Timer(BIT_NS,unit='ns');n |= int(self.dut.uart_tx.value)<<i
            await Timer(BIT_NS,unit='ns');self.checks.equal(int(self.dut.uart_tx.value),1,'uart','TX stop bit')
            self.received.append(n)
            if n==10:self.lines.append(self.buffer.decode('utf-8'));self.buffer.clear()
            else:self.buffer.append(n)
    async def send(self,data):
        for n in data:
            for bit in [0,*[(n>>i)&1 for i in range(8)],1]:
                self.dut.host_rx.value=bit;await Timer(BIT_NS,unit='ns')
        self.dut.host_rx.value=1
    async def line(self):
        while not self.lines:
            if int(self.dut.timed_out.value):raise AssertionError('simulation cycle limit')
            await Timer(1000,unit='ns')
        return self.lines.pop(0)

class Sensor:
    def __init__(self,dut,row,checks):self.dut=dut;self.row=row;self.checks=checks;self.events=[];self.sampled_at=None
    async def stop(self):
        while True:
            await RisingEdge(self.dut.i2c_sda)
            if int(self.dut.i2c_scl.value):break
        self.events.append(['stop',int(self.dut.cycles.value)])
    async def serve(self):
        d=self.dut;d.sensor_sda.value=1;d.sensor_scl.value=1
        while True:
            await FallingEdge(d.i2c_sda)
            if int(d.i2c_scl.value):break
        fault=self.row.get('fault');self.events.append(['start',int(d.cycles.value)])
        if fault=='timeout':
            await FallingEdge(d.i2c_scl);d.sensor_scl.value=0
            await Timer(100000000,unit='ns');return
        address=0
        for _ in range(8):
            await RisingEdge(d.i2c_scl);address=(address<<1)|int(d.i2c_sda.value)
            await FallingEdge(d.i2c_scl)
        self.checks.equal(address,0x91,'i2c','7-bit sensor address 0x48/read')
        self.events.append(['address',address])
        d.sensor_sda.value=int(fault=='nack')
        await RisingEdge(d.i2c_scl);await FallingEdge(d.i2c_scl);d.sensor_sda.value=1
        if fault=='nack':self.events.append(['nack']);await self.stop();return
        temperature=self.row['state']['temperature'];light=self.row['state']['light'];epoch=self.row['epoch']
        if fault=='sensor-low':temperature=-41
        if fault=='sensor-high':temperature=126
        if fault=='light-range':light=100001
        if fault=='epoch-change':epoch+=1
        sampled_at=int(d.cycles.value)
        if fault=='stale':sampled_at=(sampled_at-1000001)&0xffffffff
        if fault=='future':sampled_at=(sampled_at+1000000)&0xffffffff
        self.sampled_at=sampled_at
        data=struct.pack('<iIII',temperature,light,epoch,sampled_at)
        self.events.append(['packet',data.hex()])
        for i,n in enumerate(data):
            for b in range(7,-1,-1):
                d.sensor_sda.value=(n>>b)&1;await RisingEdge(d.i2c_scl);await FallingEdge(d.i2c_scl)
            d.sensor_sda.value=1;await RisingEdge(d.i2c_scl)
            self.checks.equal(int(d.i2c_sda.value),int(i==15),'i2c','master ACK each byte, final NACK')
            await FallingEdge(d.i2c_scl)
        d.sensor_sda.value=1;self.events.append(['complete',16]);await self.stop()
