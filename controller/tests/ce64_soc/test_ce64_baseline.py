"""Execute the exact full-duration baseline ROM through its first real sweep."""
import json,os,struct,zlib
from pathlib import Path
import cocotb
from cocotb.triggers import FallingEdge,Timer
BIT_NS=int(os.environ.get('CE64_UART_BIT_NS','1000'))
@cocotb.test()
async def baseline_prefix(dut):
    raw=bytearray();records=[];acks=[]
    async def receive():
        while True:
            await FallingEdge(dut.board_tx);await Timer(BIT_NS*3//2,unit='ns');value=0
            for i in range(8):value|=int(dut.board_tx.value)<<i;await Timer(BIT_NS,unit='ns')
            assert int(dut.board_tx.value)==1,'UART stop bit';raw.append(value)
            if len(raw)>=20:
                p=raw[-20:];magic,a,b,c,crc=struct.unpack('<5I',p)
                if magic in (0x324b4341,0x3245434e):
                    assert zlib.crc32(p[:16])==crc,'Actual UART CRC'
                    (acks if magic==0x324b4341 else records).append((a,b,c))
    receiver=cocotb.start_soon(receive())
    try:
        for _ in range(3000):
            if b'CE64 BOOT v2\n' in raw:break
            await Timer(10000,unit='ns')
        assert b'CE64 BOOT v2\n' in raw,'CPU bootstrap readiness'
        packet=struct.pack('<6I',0x324c4543,2,0,0,1,3);packet+=struct.pack('<I',zlib.crc32(packet))
        for value in packet:
            dut.uart_input.value=0;await Timer(BIT_NS,unit='ns')
            for i in range(8):dut.uart_input.value=value>>i&1;await Timer(BIT_NS,unit='ns')
            dut.uart_input.value=1;await Timer(BIT_NS,unit='ns')
        for _ in range(70000):
            traps=[r for r in records if r[0]==0 and r[1]>>16==255]
            if traps:raise AssertionError('Actual CPU trapped in baseline: '+str(traps))
            if (0,5<<16|3,1) in records:break
            await Timer(10000,unit='ns')
        assert acks==[(1,0,0)],'Actual CPU SEAL/profile3 ACK'
        assert (0,5<<16,0x40500000) in records,'Actual FPU result3.25'
        assert (0,5<<16|3,1) in records,'Actual cached/uncached sweep completed'
        assert int(dut.ddr_write_bytes.value)>=65536 and int(dut.ddr_read_bytes.value)>=65536,'Native DDR payload was exercised'
        assert int(dut.retired.value)>1000 and int(dut.launches.value)==0,'Real CPU; CE disabled'
        Path('baseline-prefix.json').write_text(json.dumps(dict(status='PASS',checks=7,actual_FPU_bits=0x40500000,actual_completed_sweeps=1,
            ddr_write_bytes=int(dut.ddr_write_bytes.value),ddr_read_bytes=int(dut.ddr_read_bytes.value),scope='Exact deployed3605s ROM prefix only; no shortened firmware or physical/hour qualification'))+'\n')
    finally:
        Path('baseline-uart.bin').write_bytes(raw);receiver.cancel()
