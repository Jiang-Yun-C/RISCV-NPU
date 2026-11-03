"""U251 authenticated-image transport. Host transfers bytes; board owns parsing,
hash verification, final DDR placement, seal, tokenizer and model execution.
Only stdlib is needed for audit/tests; physical serial requires pyserial.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys
import time
import zlib

MAGIC=0x31353255
ACK=0x41353255
DATA,START,RESET=1,2,3
CRC,SEQUENCE,FORMAT,TIMEOUT,STATE=range(256,261)


def frame(command,lba,sequence,payload=b''):
    if command==DATA and len(payload)!=512:raise ValueError('DATA requires one full 512-byte sector')
    if command not in (DATA,START,RESET):raise ValueError('unknown command')
    if command!=DATA and (lba or payload):raise ValueError('control fields must be zero')
    body=struct.pack('<5I',MAGIC,command,lba,sequence,len(payload))+payload.ljust(512,b'\0')
    return body+struct.pack('<I',zlib.crc32(body))


def decode_ack(raw):
    if len(raw)!=24 or zlib.crc32(raw[:20])!=struct.unpack_from('<I',raw,20)[0]:raise ValueError('ACK length/CRC')
    magic,seq,status,next_lba,value,_=struct.unpack('<6I',raw)
    if magic!=ACK:raise ValueError('ACK magic')
    return seq,status,next_lba,value


def audit_image(path,identity=None):
    """Bounded independent container audit, including payload and padding."""
    path=Path(path);whole=hashlib.sha256()
    with path.open('rb') as source:
        header=source.read(512);whole.update(header)
        if len(header)!=512 or header[:8]!=b'NXSDV1\0\0':raise ValueError('stream container magic')
        version,size,count,app_lba,app_bytes,base,entry=struct.unpack_from('<7I',header,8)
        model_lba,model_bytes=struct.unpack_from('<2I',header,68)
        if version!=1 or size!=512 or zlib.crc32(header[:508])!=struct.unpack_from('<I',header,508)[0] or any(header[108:508]):raise ValueError('header format/CRC')
        if base!=0xb4000000 or entry!=base or not 0<app_bytes<=8388608 or not model_bytes:raise ValueError('application entry/size')
        if app_lba!=1 or model_lba!=1+(app_bytes+511)//512 or count!=model_lba+(model_bytes+511)//512 or count>=2**32-1 or path.stat().st_size!=count*512:raise ValueError('stream spans/truncation')
        for name,n,expected in [('application',app_bytes,header[36:68]),('model',model_bytes,header[76:108])]:
            digest=hashlib.sha256();left=n
            while left:
                data=source.read(min(left,1<<20))
                if not data:raise ValueError('truncated '+name)
                whole.update(data);digest.update(data);left-=len(data)
            pad=source.read((-n)%512);whole.update(pad)
            if digest.digest()!=expected or len(pad)!=(-n)%512 or any(pad):raise ValueError(name+' hash/padding')
    result=dict(bytes=count*512,sectors=count,sha256=whole.hexdigest(),
        application_sha256=header[36:68].hex(),model_sha256=header[76:108].hex())
    if identity is not None:
        if identity.get('transport')!='uart':raise ValueError('identity is not a UART candidate')
        for expected,key in [('sd_image_sha256','sha256'),('application_sha256','application_sha256'),('model_sha256','model_sha256')]:
            if identity.get(expected)!=result[key]:raise ValueError('candidate identity mismatch: '+key)
    return result


class Sender:
    def __init__(self,device,frame_timeout=120,final_timeout=1800,retries=3,raw=None,journal=None):
        self.device=device;self.frame_timeout=frame_timeout;self.final_timeout=final_timeout;self.retries=retries
        self.buffer=bytearray();self.raw=raw;self.journal=journal;self.tx_hash=hashlib.sha256()
        self.tx_bytes=0;self.acknowledged=0;self.retransmissions=0;self.start_sent=False

    def _read(self):
        data=self.device.read(max(1,min(getattr(self.device,'in_waiting',1),4096)))
        if data:
            if self.raw:self.raw.write(data);self.raw.flush()
            self.buffer.extend(data)

    def wait_text(self,marker,seconds):
        until=time.monotonic()+seconds
        while time.monotonic()<until:
            at=self.buffer.find(marker)
            if at>=0:
                prefix=bytes(self.buffer[:at+len(marker)]);del self.buffer[:at+len(marker)];return prefix
            self._read()
        raise TimeoutError('Missing '+repr(marker))

    def _write(self,data):
        left=memoryview(data)
        while left:
            n=self.device.write(left)
            if not n:raise IOError('short UART write')
            self.tx_hash.update(left[:n]);self.tx_bytes+=n;left=left[n:]
        self.device.flush()

    def _ack(self,sequence,seconds):
        until=time.monotonic()+seconds;magic=struct.pack('<I',ACK)
        while time.monotonic()<until:
            at=self.buffer.find(magic)
            if at>=0 and len(self.buffer)>=at+24:
                data=bytes(self.buffer[at:at+24]);del self.buffer[:at+24]
                try:seq,status,next_lba,value=decode_ack(data)
                except ValueError:continue
                if seq==sequence or seq==0 and status in (CRC,TIMEOUT):return status,next_lba,value
                if seq>sequence:raise RuntimeError('ACK from a future sequence')
            self._read()
        raise TimeoutError('UART ACK sequence '+str(sequence))

    def sector(self,lba,payload,final=False):
        sequence=lba+1;packet=frame(DATA,lba,sequence,payload)
        for attempt in range(self.retries+1):
            self._write(packet)
            try:status,next_lba,value=self._ack(sequence,self.final_timeout if final else self.frame_timeout)
            except TimeoutError:
                if attempt==self.retries:raise
                self.retransmissions+=1;continue
            if status in (CRC,TIMEOUT):
                if attempt==self.retries:raise RuntimeError('Repeated frame rejection '+str(status))
                self.retransmissions+=1;continue
            if status or next_lba!=lba+1 or value!=zlib.crc32(payload):raise RuntimeError('Board rejected/changed sector '+str((sequence,status,next_lba,value)))
            self.acknowledged+=1
            if self.journal:
                self.journal.write(json.dumps(dict(sequence=sequence,lba=lba,crc32=value,attempt=attempt))+'\n')
            return

    def transfer(self,path,summary):
        digest=hashlib.sha256();start=time.monotonic()
        with Path(path).open('rb') as source:
            for lba in range(summary['sectors']):
                payload=source.read(512)
                if len(payload)!=512:raise ValueError('source changed/truncated')
                self.sector(lba,payload,lba==summary['sectors']-1);digest.update(payload)
                if lba and lba%4096==0:print('UART_SECTORS='+str(lba+1)+'/'+str(summary['sectors']),flush=True)
            if source.read(1) or digest.hexdigest()!=summary['sha256']:raise ValueError('source changed during transfer; START withheld')
        # Never retry START blindly: its ACK could be lost after the CPU jumps.
        self.start_sent=True;self._write(frame(START,0,summary['sectors']+1))
        status,next_lba,value=self._ack(summary['sectors']+1,self.frame_timeout)
        if status or next_lba!=summary['sectors'] or value:raise RuntimeError('START rejected')
        return dict(status='PASS',scope='UART authenticated loading and START only; generation unqualified',
            sectors=self.acknowledged,retransmissions=self.retransmissions,tx_bytes=self.tx_bytes,
            tx_sha256=self.tx_hash.hexdigest(),elapsed_s=time.monotonic()-start,start_acknowledged=True)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--image',type=Path,required=True)
    p.add_argument('--identity',type=Path,required=True);p.add_argument('--dry-run',action='store_true')
    p.add_argument('--receipt-dir',type=Path);p.add_argument('--port',default='COM10');p.add_argument('--baud',type=int,default=500000)
    p.add_argument('--reload',action='store_true',help='Ask an already-running T25 service for a real platform reset before uploading')
    p.add_argument('--serial-deps',type=Path,help='Existing host pyserial dependency directory, if not installed globally')
    p.add_argument('--ready-timeout',type=float,default=1800);p.add_argument('--frame-timeout',type=float,default=120)
    p.add_argument('--final-timeout',type=float,default=1800);p.add_argument('--retries',type=int,default=3)
    a=p.parse_args();identity=json.loads(a.identity.read_text());summary=audit_image(a.image,identity)
    if a.dry_run:print(json.dumps(dict(status='PASS',scope='File audit only; no serial access',**summary),indent=2));return 0
    if not a.receipt_dir:p.error('--receipt-dir required for physical transport')
    if a.baud!=500000 or a.retries<0 or min(a.frame_timeout,a.final_timeout,a.ready_timeout)<=0:p.error('invalid UART limits')
    a.receipt_dir.mkdir(parents=True,exist_ok=False)
    result=dict(status='FAIL',physical_qualification=False,flash_modified=False,source=summary,port=a.port,baud=a.baud,
        application_manifest_sha256=hashlib.sha256(a.identity.read_bytes()).hexdigest(),reload_requested=a.reload)
    try:
        if a.serial_deps:sys.path.insert(0,str(a.serial_deps))
        import serial
        from serial.tools import list_ports
        ports=[x for x in list_ports.comports() if x.device==a.port and x.vid==0x10c4 and x.pid==0xea60 and x.serial_number=='0001']
        if len(ports)!=1:raise RuntimeError('Exact CP2102 10c4:ea60 serial0001 target missing')
        dev=serial.Serial(None,a.baud,timeout=.05,write_timeout=5,rtscts=False,dsrdtr=False)
        dev.dtr=False;dev.rts=False;dev.port=a.port;dev.open()
        with dev, (a.receipt_dir/'rx.bin').open('xb') as raw, (a.receipt_dir/'acks.jsonl').open('x') as journal:
            sender=Sender(dev,a.frame_timeout,a.final_timeout,a.retries,raw,journal)
            if a.reload:sender._write(b':reload\n')
            sender.wait_text(b'T25 UART BOOT v1\n',a.ready_timeout)
            result.update(sender.transfer(a.image,summary))
            result['service_banner']=sender.wait_text(b'T25 READY\n',180).decode('utf-8',errors='replace')
    except Exception as exc:
        result.update(status='FAIL',error=str(exc))
    (a.receipt_dir/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2));return 0 if result['status']=='PASS' else 1


if __name__=='__main__':raise SystemExit(main())
