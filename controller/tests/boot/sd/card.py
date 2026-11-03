"""SDHC SPI mode card; drives only MISO, observes CS/SCK/MOSI pins."""
from collections import deque
from pathlib import Path
import random
from cocotb.triggers import RisingEdge,FallingEdge,Timer
from cocotb.utils import get_sim_time

def crc7(data):
    c=0
    for byte in data:
        for bit in range(7,-1,-1):
            feedback=((c>>6)^(byte>>bit))&1;c=(c<<1)&127
            if feedback:c^=9
    return (c<<1)|1

def crc16(data):
    c=0
    for byte in data:
        c^=byte<<8
        for _ in range(8):c=((c<<1)^ (0x1021 if c&0x8000 else 0))&65535
    return c

class Card:
    def __init__(self,dut,checks,seed):
        self.dut=dut;self.checks=checks;self.rng=random.Random(seed^0x53)
        self.trace=[];self.commands=[];self.action=None;self.output=deque();self.command=[]
        self.current=255;self.bit=0;self.tx=0;self.rx=0;self.idle=True;self.app=False;self.acmd=0;self.high_clocks=0
    def insert(self,action):
        self.action=action;self.image=Path(action['image']).read_bytes();self.output.clear();self.command=[]
        self.current=255;self.bit=0;self.tx=0;self.rx=0;self.idle=True;self.app=False;self.acmd=0;self.high_clocks=0
        self.dut.host_miso.value=1
    def receive(self,v):
        if self.command or v&0xc0==0x40:
            self.command.append(v)
            if len(self.command)!=6:return
            p=bytes(self.command);self.command=[];cmd=p[0]&63;arg=int.from_bytes(p[1:5],'big')
            self.checks.equal(p[-1],crc7(p[:5]),'protocol','command CRC7')
            self.commands.append(dict(cycle=int(get_sim_time(unit='ns'))//10,index=self.action['index'],cmd=cmd,arg=arg))
            if self.action['fault']=='init-timeout':return
            delay=[255]*self.rng.randint(1,7)
            if cmd==0:
                self.checks.require(self.high_clocks>=74 and arg==0,'protocol','power-up clocks and CMD0')
                self.idle=True;reply=[1]
            elif cmd==8:
                self.checks.equal(arg,0x1aa,'protocol','SD v2 voltage/pattern');reply=[1,0,0,1,0xaa]
            elif cmd==55:self.app=True;reply=[int(self.idle)]
            elif cmd==41:
                self.checks.require(self.app and arg==0x40000000,'protocol','CMD55/ACMD41 HCS')
                self.app=False;self.acmd+=1;self.idle=self.acmd<2;reply=[int(self.idle)]
            elif cmd==58:
                self.checks.require(not self.idle,'protocol','CMD58 after initialization');reply=[0,0xc0,0xff,0x80,0]
            elif cmd==17:
                self.checks.require(not self.idle,'protocol','CMD17 only after initialization')
                reply=[0]+[255]*self.rng.randint(1,12)
                if arg==self.action['fault_lba'] and self.action['fault'] in ('token-timeout','bad-block'):
                    if self.action['fault']=='bad-block':reply+=[4]
                elif (arg+1)*512>len(self.image):pass
                else:
                    data=self.image[arg*512:(arg+1)*512];crc=crc16(data)
                    if arg==self.action['fault_lba'] and self.action['fault']=='crc':crc^=1
                    reply+=[254,*data,crc>>8,crc&255]
            else:
                self.checks.require(False,'protocol','unexpected command '+str(cmd));reply=[4]
            self.output.extend(delay+reply)
    async def run(self):
        while True:
            await RisingEdge(self.dut.spi_sck)
            cs=int(self.dut.spi_cs.value);mosi=int(self.dut.spi_mosi.value);miso=int(self.dut.spi_miso.value)
            if cs:self.high_clocks+=1
            self.tx=(self.tx<<1)|mosi;self.rx=(self.rx<<1)|miso;self.bit+=1
            if self.bit==8:
                self.trace.append([int(get_sim_time(unit='ns'))//10,cs,self.tx,self.rx])
                if not cs:self.receive(self.tx)
                else:self.command=[];self.output.clear()
                self.current=self.output.popleft() if self.output else 255
                self.bit=0;self.tx=0;self.rx=0
            await FallingEdge(self.dut.spi_sck)
            self.dut.host_miso.value=(self.current>>(7-self.bit))&1
