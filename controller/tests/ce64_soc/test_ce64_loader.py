"""Real CPU, actual UART pins and local ROM/SRAM; no preload or Y calculation."""
import json,os,struct,zlib
from pathlib import Path
import cocotb
from cocotb.triggers import FallingEdge,Timer
BIT_NS=int(os.environ.get('CE64_UART_BIT_NS','1000'))
@cocotb.test()
async def loader(dut):
    raw=bytearray();acks=[];records=[];checks=0
    async def receive():
        while True:
            await FallingEdge(dut.board_tx);await Timer(BIT_NS*3//2,unit='ns');value=0
            for i in range(8):
                value|=int(dut.board_tx.value)<<i;await Timer(BIT_NS,unit='ns')
            assert int(dut.board_tx.value)==1,'UART stop bit'
            raw.append(value)
            if len(raw)>=20:
                p=raw[-20:];magic,sequence,status,data,crc=struct.unpack('<5I',p)
                if magic in (0x324b4341,0x3245434e):
                    assert zlib.crc32(p[:16])==crc,'Actual serial record CRC'
                    if magic==0x324b4341:acks.append((sequence,status,data))
                    else:records.append((sequence,status,data))
    receiver=cocotb.start_soon(receive())
    try:
        for _ in range(3000):
            if b'CE64 BOOT v2\n' in raw:break
            await Timer(10000,unit='ns')
        assert b'CE64 BOOT v2\n' in raw,'Actual CPU loader ready';checks+=1
        assert len(records)==64,'Complete actual board telemetry serial window';checks+=1
        async def frame(command,address,sequence,payload=b'',length=0,corrupt=False):
            data=struct.pack('<6I',0x324c4543,command,address,len(payload) if command==1 else length,sequence,0)+payload
            data+=struct.pack('<I',zlib.crc32(data)^(1 if corrupt else 0))
            count=len(acks)
            for value in data:
                dut.uart_input.value=0;await Timer(BIT_NS,unit='ns')
                for i in range(8):dut.uart_input.value=value>>i&1;await Timer(BIT_NS,unit='ns')
                dut.uart_input.value=1;await Timer(BIT_NS,unit='ns')
            for _ in range(1000):
                if len(acks)>count:return acks[-1]
                await Timer(10000,unit='ns')
            raise AssertionError('Missing real CPU UART ACK')
        payload=bytes((i*37+11)&255 for i in range(512));address=0xa8002000
        assert await frame(1,address,1,payload,corrupt=True)==(1,2,0);checks+=1
        assert int(dut.ddr_write_bytes.value)==0;checks+=1
        assert await frame(1,address,1,payload)==(1,0,0);checks+=1
        assert int(dut.ddr_write_bytes.value)==512;checks+=1
        assert await frame(1,address,1,payload)==(1,0,0);checks+=1
        assert int(dut.ddr_write_bytes.value)==512,'Duplicate cannot replay CPU stores';checks+=1
        assert await frame(1,0xbc000000,2,payload)==(2,3,0);checks+=1
        assert int(dut.ddr_write_bytes.value)==512;checks+=1
        assert await frame(3,address,2,length=512)==(2,0,zlib.crc32(payload));checks+=1
        assert int(dut.ddr_read_bytes.value)==512,'CRC uses actual CPU native DDR reads';checks+=1
        # Exercise the exact paired host upload at native1024 and the frozen
        # 64-byte UART FIFO: only the 28-byte CRC request queues after stores.
        pair_payload=bytes((i*29+7)&255 for i in range(512));pair_address=address+512
        write=struct.pack('<6I',0x324c4543,1,pair_address,512,3,0)+pair_payload
        read=struct.pack('<6I',0x324c4543,3,pair_address,512,4,0)
        paired=write+struct.pack('<I',zlib.crc32(write))+read+struct.pack('<I',zlib.crc32(read))
        count=len(acks)
        for value in paired:
            dut.uart_input.value=0;await Timer(BIT_NS,unit='ns')
            for i in range(8):dut.uart_input.value=value>>i&1;await Timer(BIT_NS,unit='ns')
            dut.uart_input.value=1;await Timer(BIT_NS,unit='ns')
        for _ in range(1000):
            if len(acks)>=count+2:break
            await Timer(10000,unit='ns')
        assert acks[count:]==[(3,0,0),(4,0,zlib.crc32(pair_payload))];checks+=1
        assert int(dut.ddr_write_bytes.value)==1024 and int(dut.ddr_read_bytes.value)==1024;checks+=1
        assert await frame(4,0,5)==(5,0,0);checks+=1
        await Timer(10000,unit='ns')
        assert int(dut.platform_reset_request.value)==1;checks+=1
        assert int(dut.retired.value)>1000 and int(dut.launches.value)==0;checks+=1
        Path('loader-checks.json').write_text(json.dumps({'status':'PASS','checks':checks,'acks':acks,'telemetry_records':len(records),
            'retired':int(dut.retired.value),'write_drain_cycles':1024,'scope':'Real CPU/UART/native DDR digital loader only; board calibration/reset still required'},indent=2)+'\n')
    finally:
        receiver.cancel();Path('uart.bin').write_bytes(raw)
