"""No preload: card model drives only MISO; real CPU authenticates and enters DDR."""
import hashlib
import json
import os
from pathlib import Path
import struct
import cocotb
from cocotb.triggers import FallingEdge,Timer
if cocotb.simulator.is_running():
    from card import Card
    BIT_NS=int(os.environ['CE64_UART_BIT_NS'])


class PinChecks:
    count=0
    def equal(self,a,b,category,detail):
        assert a==b,(category,detail,a,b);self.count+=1
    def require(self,value,category,detail):
        assert value,(category,detail);self.count+=1


@cocotb.test()
async def authenticated_sd(dut):
    checks=PinChecks();raw=bytearray();card=Card(dut,checks,1)
    card.insert(dict(image=str(Path('sd.img').resolve()),index=0,fault='none',fault_lba=-1))
    async def receive():
        while True:
            await FallingEdge(dut.board_tx);await Timer(BIT_NS*3//2,unit='ns');v=0
            for i in range(8):
                v|=int(dut.board_tx.value)<<i;await Timer(BIT_NS,unit='ns')
            assert int(dut.board_tx.value)==1,'UART stop bit';raw.append(v)
    receiver=cocotb.start_soon(receive());pins=cocotb.start_soon(card.run())
    try:
        await Timer(100,unit='ns')
        checks.equal(int(dut.model_sealed.value),0,'seal','initial unsealed')
        for _ in range(160000):
            if b'T25 TEST ENTRY\n' in raw:break
            assert b'T25 SD ERROR' not in raw,bytes(raw)
            assert not int(dut.timed_out.value),'actual CPU cycle envelope'
            await Timer(10000,unit='ns')
        checks.require(b'T25 TEST ENTRY\n' in raw,'entry','real DDR instruction fetch')
        checks.equal(int(dut.model_sealed.value),1,'seal','authenticated SD only')
        image=Path('sd.img').read_bytes();model_lba=struct.unpack_from('<I',image,68)[0]
        pack=image[model_lba*512:];entries=struct.unpack_from('<I',pack,32)[0]
        expected_written=40+struct.unpack_from('<I',image,24)[0]+entries*256+8+sum(
            struct.unpack_from('<Q',pack,192+256*i+168)[0] for i in range(entries)
            if struct.unpack_from('<I',pack,192+256*i+140)[0]==0)
        checks.equal(int(dut.ddr_write_bytes.value),expected_written,'DDR','exact accepted payload bytes')
        checks.require(int(dut.ddr_read_bytes.value)>=expected_written,'DDR','actual writeback reads')
        # Independently derive per-region byte counts from card input. Read the
        # actual production ROM's published counters through the native memory.
        counts=[0,0,struct.unpack_from('<I',image,24)[0],entries*256]
        for i in range(entries):
            e=192+256*i
            if struct.unpack_from('<I',pack,e+140)[0]==0:
                counts[struct.unpack_from('<I',pack,e+176)[0]-1]+=struct.unpack_from('<Q',pack,e+168)[0]
        for i,expected in enumerate([0x4d323544]+counts):
            dut.peek_address.value=0xba080010+4*i;await Timer(2,unit='ns')
            checks.equal(int(dut.peek_value.value),expected,'memory-accounting','published successful readback count')
        for span in json.loads(Path('expected-memory.json').read_text()):
            data=bytearray()
            for offset in range(0,span['bytes'],4):
                dut.peek_address.value=span['address']+offset;await Timer(2,unit='ns')
                data.extend(int(dut.peek_value.value).to_bytes(4,'little'))
            checks.equal(hashlib.sha256(data[:span['bytes']]).hexdigest(),span['sha256'],'memory',span['name'])
        commands=[x['cmd'] for x in card.commands]
        checks.require(all(x in commands for x in [0,8,55,41,58,17]),'SPI','SDHC initialization and reads')
        checks.equal([x['arg'] for x in card.commands if x['cmd']==17],list(range(len(image)//512)),'SPI','block addressed sequential complete image')
        checks.equal(int(dut.launches.value),0,'scope','loader performs no model inference')
        Path('cpu-checks.json').write_text(json.dumps(dict(status='PASS',checks=checks.count,
            sectors=len(image)//512,write_drain_cycles=1024,retired=int(dut.retired.value),
            expected_written_bytes=expected_written,ddr_write_bytes=int(dut.ddr_write_bytes.value),
            ddr_read_bytes=int(dut.ddr_read_bytes.value),
            scope='Actual T09 CPU + SPI MISO-only card + SD shell + native DDR small pack; no physical card/PHY/full-model claim'),indent=2)+'\n')
    finally:
        receiver.cancel();pins.cancel();Path('uart.bin').write_bytes(raw)
        Path('spi-commands.json').write_text(json.dumps(card.commands)+'\n')
