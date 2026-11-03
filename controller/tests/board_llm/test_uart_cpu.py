"""Actual T09 ROM -> UART pins -> final native DDR -> authenticated entry.

The immutable legal-tail T10 fixture is small enough for cycle simulation.
Full production pack is separately streamed by the native C-loader test.
"""
import hashlib
import json
import os
from pathlib import Path
import struct
import zlib
import cocotb
from cocotb.triggers import FallingEdge,Timer
from software.boot.uart_stream import frame,DATA,START,CRC,FORMAT
if cocotb.simulator.is_running():
    BIT_NS=int(os.environ['CE64_UART_BIT_NS'])


@cocotb.test()
async def authenticated_stream(dut):
    raw=bytearray();acks=[];checks=0
    async def receive():
        while True:
            await FallingEdge(dut.board_tx);await Timer(BIT_NS*3//2,unit='ns');value=0
            for i in range(8):
                value|=int(dut.board_tx.value)<<i;await Timer(BIT_NS,unit='ns')
            assert int(dut.board_tx.value)==1,'UART stop bit'
            raw.append(value)
            if len(raw)>=24:
                packet=raw[-24:]
                if struct.unpack_from('<I',packet)[0]==0x41353255:
                    assert zlib.crc32(packet[:20])==struct.unpack_from('<I',packet,20)[0],'ACK CRC'
                    acks.append(struct.unpack_from('<4I',packet,4))
    receiver=cocotb.start_soon(receive())
    try:
        for _ in range(10000):
            if b'T25 UART BOOT v1\n' in raw:break
            assert not int(dut.timed_out.value),'CPU time limit before banner'
            await Timer(10000,unit='ns')
        assert b'T25 UART BOOT v1\n' in raw,'Actual ROM ready';checks+=1
        assert int(dut.model_sealed.value)==0;checks+=1
        image=Path('stream.img').read_bytes();count=len(image)//512
        async def send(packet,sequence):
            previous=len(acks)
            for value in packet:
                dut.uart_input.value=0;await Timer(BIT_NS,unit='ns')
                for bit in range(8):dut.uart_input.value=(value>>bit)&1;await Timer(BIT_NS,unit='ns')
                dut.uart_input.value=1;await Timer(BIT_NS,unit='ns')
            for _ in range(50000):
                if len(acks)>previous:
                    assert acks[-1][0]==sequence
                    return acks[-1]
                assert not int(dut.timed_out.value),'CPU cycle envelope'
                await Timer(10000,unit='ns')
            raise AssertionError('No actual UART ACK '+str(sequence))
        bad=bytearray(frame(DATA,0,1,image[:512]));bad[40]^=1
        assert (await send(bad,1))[1]==CRC;checks+=1
        assert (await send(frame(START,0,1),1))[1]==FORMAT;checks+=1
        for lba in range(count):
            payload=image[512*lba:512*(lba+1)]
            assert await send(frame(DATA,lba,lba+1,payload),lba+1)==(lba+1,0,lba+1,zlib.crc32(payload));checks+=1
            if lba==2:
                writes=int(dut.ddr_write_bytes.value)
                assert await send(frame(DATA,lba,lba+1,payload),lba+1)==(lba+1,0,lba+1,zlib.crc32(payload))
                assert int(dut.ddr_write_bytes.value)==writes,'Duplicate cannot repeat writes';checks+=2
        assert int(dut.model_sealed.value)==1,'Only fully authenticated pack seals';checks+=1
        assert b'T25 TEST ENTRY\n' not in raw,'START required';checks+=1
        spans=json.loads(Path('expected-memory.json').read_text())
        for span in spans:
            data=bytearray()
            for offset in range(0,span['bytes'],4):
                dut.peek_address.value=span['address']+offset;await Timer(2,unit='ns')
                data.extend(int(dut.peek_value.value).to_bytes(4,'little'))
            assert hashlib.sha256(data[:span['bytes']]).hexdigest()==span['sha256'],span['name'];checks+=1
        assert await send(frame(START,0,count+1),count+1)==(count+1,0,count,0);checks+=1
        for _ in range(1000):
            if b'T25 TEST ENTRY\n' in raw:break
            await Timer(10000,unit='ns')
        assert b'T25 TEST ENTRY\n' in raw,'Actual DDR instruction fetch and entry';checks+=1
        model_lba=struct.unpack_from('<I',image,68)[0]
        pack=image[model_lba*512:]
        entries=struct.unpack_from('<I',pack,32)[0]
        payload_bytes=sum(struct.unpack_from('<Q',pack,192+256*i+168)[0]
            for i in range(entries) if struct.unpack_from('<I',pack,192+256*i+140)[0]==0)
        # Native counters count accepted strobed bytes, excluding padding/aliases.
        expected_written=struct.unpack_from('<I',image,24)[0]+entries*256+payload_bytes+8
        assert int(dut.ddr_write_bytes.value)==expected_written,(int(dut.ddr_write_bytes.value),expected_written);checks+=1
        assert int(dut.ddr_read_bytes.value)>=expected_written,'DDR readback plus numeric/entry fetch';checks+=1
        assert int(dut.launches.value)==0 and int(dut.retired.value)>1000;checks+=1
        Path('cpu-checks.json').write_text(json.dumps(dict(status='PASS',checks=checks,sectors=count,
            uart_divisor=BIT_NS//8,write_drain_cycles=1024,retired=int(dut.retired.value),
            final_memory_spans=len(spans),model_sealed=True,
            expected_written_bytes=expected_written,ddr_write_bytes=int(dut.ddr_write_bytes.value),ddr_read_bytes=int(dut.ddr_read_bytes.value),
            scope='Actual RISC-V UART authenticated small frozen T10 pack and DDR entry; no full-model inference/PHY claim'),indent=2)+'\n')
    finally:
        receiver.cancel();Path('uart.bin').write_bytes(raw)
