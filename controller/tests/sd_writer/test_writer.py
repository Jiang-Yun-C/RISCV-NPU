"""Actual T09 CPU, UART pins and SPI pins; SD is an independent digital card."""
import hashlib,json,struct,zlib,os
from pathlib import Path
from collections import deque
import cocotb
from cocotb.triggers import FallingEdge,Timer
from card import Card,crc7,crc16
BIT_NS=2000
class Checks:
 def equal(self,a,b,*why):assert a==b,(a,b,why)
 def require(self,a,*why):assert a,why
class WriterCard(Card):
 def __init__(self,dut):
  super().__init__(dut,Checks(),1);self.image=bytearray(Path('old.img').read_bytes()+bytes([0xa7])*1024);self.write_pending=None;self.write_data=None;self.reject=False;self.writes=[];self.action={'index':0,'fault':'none','fault_lba':-1};self.dut.host_miso.value=1
 def receive(self,v):
  if self.write_pending is not None:
   if self.write_data is None:
    if v==254:self.write_data=bytearray()
    return
   self.write_data.append(v)
   if len(self.write_data)<514:return
   data=self.write_data[:512];assert crc16(data)==int.from_bytes(self.write_data[512:],'big')
   if self.reject:self.output.extend([0x0d,255])
   else:
    p=self.write_pending*512;self.image[p:p+512]=data;self.writes.append(self.write_pending);self.output.extend([5,0,0,255])
   self.write_pending=None;self.write_data=None;return
  if not self.command and v&0xc0!=0x40:return
  self.command.append(v)
  if len(self.command)!=6:return
  p=bytes(self.command);self.command=[];assert p[5]==crc7(p[:5]);cmd=p[0]&63;arg=int.from_bytes(p[1:5],'big');self.commands.append({'cmd':cmd,'arg':arg});Path('live-commands.json').write_text(json.dumps(self.commands))
  if cmd==0:self.idle=True;reply=[1]
  elif cmd==8:reply=[1,0,0,1,0xaa]
  elif cmd==55:self.app=True;reply=[int(self.idle)]
  elif cmd==41:assert self.app;self.idle=False;self.app=False;reply=[0]
  elif cmd==58:reply=[0,0xc0,0xff,0x80,0]
  elif cmd in (9,10,17):
   data=bytes(range(3,19)) if cmd==10 else bytes([0x40])+bytes(15) if cmd==9 else self.image[arg*512:(arg+1)*512]
   assert len(data)==(512 if cmd==17 else 16);crc=crc16(data);reply=[0,255,254,*data,crc>>8,crc&255]
  elif cmd==24:self.write_pending=arg;self.write_data=None;reply=[0]
  else:raise AssertionError(('unexpected SD command',cmd,arg))
  self.output.extend([255]+reply)
@cocotb.test()
async def temporary_writer(dut):
 card=WriterCard(dut);rx=deque();capture=bytearray();checks=0;seq=0
 async def receive_uart():
  while True:
   await FallingEdge(dut.board_tx);await Timer(3000,unit='ns');v=0
   for i in range(8):v|=int(dut.board_tx.value)<<i;await Timer(BIT_NS,unit='ns')
   assert int(dut.board_tx.value)==1;rx.append(v);capture.append(v);Path('live-uart.bin').write_bytes(capture)
 async def take(n):
  data=bytearray()
  for _ in range(n):
   for tick in range(25000):
    if rx:break
    await Timer(1000,unit='ns')
   assert rx,'UART timeout';data.append(rx.popleft())
  return bytes(data)
 async def reply(want_seq,status):
  nonlocal checks
  h=await take(16);magic,s,rc,n=struct.unpack('<4I',h);assert (magic,s,rc)==(0x5253584e,want_seq,status),(magic,s,rc,want_seq,status);assert n<=512
  data=await take(n);crc=struct.unpack('<I',await take(4))[0];assert crc==zlib.crc32(h+data);checks+=1;return data
 async def request(cmd,arg=0,count=0,data=b'',status=0,bad_crc=False):
  nonlocal seq
  seq+=1;wire=struct.pack('<6I',0x5753584e,cmd,arg,count,seq,len(data))+data;wire+=struct.pack('<I',zlib.crc32(wire)^int(bad_crc))
  for byte in wire:
   dut.host_rx.value=0;await Timer(BIT_NS,unit='ns')
   for bit in range(8):dut.host_rx.value=(byte>>bit)&1;await Timer(BIT_NS,unit='ns')
   dut.host_rx.value=1;await Timer(BIT_NS,unit='ns')
  return await reply(seq,status)
 receiver=cocotb.start_soon(receive_uart());pins=cocotb.start_soon(card.run());dut.host_rx.value=1;dut.reset_n.value=0;await Timer(100,unit='ns');dut.reset_n.value=1
 try:
  assert await reply(0,0)==b''
  info=await request(1);assert info[:16]==bytes(range(3,19));assert not card.writes
  await request(1,status=8,bad_crc=True);await request(6,1,1,bytes(512),status=5);assert not card.writes
  old=Path('old.img').read_bytes();new=Path('new.img').read_bytes()
  restore=os.environ.get('SD_WRITER_RESTORE')=='1';old_count=len(old)//512;new_count=len(new)//512;source_model=5 if restore else 4;target_model=4 if restore else 5
  assert await request(3,0,old_count)==hashlib.sha256(old).digest();await request(4,0,new_count,bytes(16),status=5);await request(4,0,new_count,info[:16]);await request(5,source_model,8)
  assert card.writes==(list(range(4,12)) if restore else list(range(12,4,-1)))
  for lba in range(1,target_model):await request(6,lba,1,new[lba*512:(lba+1)*512])
  if restore:await request(9,12,1,bytes([0xa7])*512)
  await request(7,0,1,new[:512]);assert card.image[:len(new)]==new;assert card.image[len(new):]==bytes([0xa7])*(len(card.image)-len(new))
  assert await request(3,0,new_count)==hashlib.sha256(new).digest();await request(6,1,1,bytes(512),status=5)
  # A fresh actual CPU reset and independent card reset exercise CMD24 reject.
  card.image=bytearray(old+bytes([0xa7])*1024);card.reject=True;card.writes=[];dut.reset_n.value=0;await Timer(100,unit='ns');dut.reset_n.value=1
  await reply(0,0);info=await request(1);await request(3,0,old_count);await request(4,0,new_count,info[:16]);await request(5,source_model,8,status=6);await request(1,status=9);assert not card.writes
  Path('checks.json').write_text(json.dumps({'status':'PASS','checks':checks,'actual_CPU':True,'actual_UART_and_SPI_RTL':True,'card_model':'digital; CMD24 rejection, CRC7/16, busy release, full bytes and neighbor','production_medium_qualification':False},indent=2)+'\n')
 finally:
  receiver.cancel();pins.cancel();Path('uart.bin').write_bytes(capture);Path('commands.json').write_text(json.dumps(card.commands,indent=2))
