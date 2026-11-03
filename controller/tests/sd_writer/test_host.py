"""Wire protocol checks only; these are not physical SD receipts."""
import importlib.util,io,struct,zlib
from pathlib import Path
import pytest
p=Path(__file__).resolve().parents[2]/'scripts/pds/windows_sd_writer.py'
spec=importlib.util.spec_from_file_location('sd_writer_host',p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class Serial:
 def __init__(self,reply):self.rx=bytearray(reply);self.tx=b''
 def read(self,n):x=bytes(self.rx[:min(n,3)]);del self.rx[:len(x)];return x
 def write(self,x):self.tx+=x;return len(x)
 def flush(self):pass
def response(seq=1,status=0,payload=b'card',corrupt=False):
 h=struct.pack('<4I',0x5253584e,seq,status,len(payload))+payload
 return h+struct.pack('<I',zlib.crc32(h)^int(corrupt))
def link(dev):return m.Link(dev,io.BytesIO(),[],m.time.time()+100)
def test_frame_and_partial_reads():
 d=Serial(response());l=link(d);assert l.request(2,17,1)==b'card';h=d.tx[:-4];assert struct.unpack('<6I',h)==(0x5753584e,2,17,1,1,0);assert zlib.crc32(h)==struct.unpack('<I',d.tx[-4:])[0];assert l.record[0]['status']=='PASS'
@pytest.mark.parametrize('wire',[response(seq=7),response(status=6),response(corrupt=True)])
def test_bad_response_stops(wire):
 l=link(Serial(wire))
 with pytest.raises(ValueError):l.request(5,10104,1048304)
 assert l.record[-1]['status']=='RUNNING'
def test_reservation_precedes_transmit():
 d=Serial(response());l=link(d);l.deadline=m.time.time()-1
 with pytest.raises(TimeoutError):l.request(4,0,1058409,bytes(16))
 assert not d.tx and not l.record
