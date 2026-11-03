#!/usr/bin/env python3
"""Download a raw RV32 image through the NXU1 stop-and-wait UART protocol."""
import argparse
from pathlib import Path
import struct
import time
from uart_protocol import BEGIN,DATA,RUN,OK,DUP,CRC,BASE,download_packets,response

def read_ack(port,timeout):
    deadline=time.monotonic()+timeout;prefix=bytearray()
    while time.monotonic()<deadline:
        b=port.read(1)
        if not b:continue
        prefix.extend(b);prefix=prefix[-4:]
        if prefix==b'NXAK':
            rest=bytearray()
            while len(rest)<16 and time.monotonic()<deadline:rest.extend(port.read(16-len(rest)))
            if len(rest)!=16:raise TimeoutError('truncated UART ACK')
            return response(bytes(prefix+rest))
    raise TimeoutError('UART ACK timeout')

def download(port,image,address=BASE,entry=BASE,retries=3,timeout=2):
    packets=list(download_packets(image,address,entry))
    for wire in packets:
        command,seq=struct.unpack_from('<2I',wire,4)
        # RUN ACK loss may occur after execution has begun. Never replay an
        # uncertain jump; DATA retries alone use the duplicate acknowledgement.
        attempts=1 if command==RUN else retries+1
        last_error=None
        for attempt in range(attempts):
            port.write(wire);port.flush()
            try:
                deadline=time.monotonic()+timeout
                while True:
                    actual_seq,status,next_seq=read_ack(port,max(0,deadline-time.monotonic()))
                    if actual_seq==seq:break
                    if time.monotonic()>=deadline:raise TimeoutError('no ACK for current sequence')
                expected_next=1 if command==BEGIN else seq+1 if command==DATA else seq
                if status in (OK,DUP) and next_seq==expected_next and (status!=DUP or command==DATA):break
                if status==CRC and command!=RUN:
                    last_error=ValueError('packet CRC rejected');continue
                raise ValueError(f'UART rejected sequence {seq}: status={status}, next={next_seq}')
            except (TimeoutError,ValueError) as error:
                last_error=error
                if isinstance(error,ValueError) and 'UART rejected' in str(error):raise
        else:raise last_error or TimeoutError('UART retries exhausted')
    return dict(bytes=len(image),packets=len(packets),entry=entry)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('image',type=Path);p.add_argument('--port',required=True)
    p.add_argument('--baud',type=int,default=115200);p.add_argument('--address',type=lambda s:int(s,0),default=BASE)
    p.add_argument('--entry',type=lambda s:int(s,0),default=BASE);p.add_argument('--timeout',type=float,default=2)
    p.add_argument('--retries',type=int,default=3);args=p.parse_args()
    if args.timeout<=0 or args.retries<0:p.error('timeout must be positive; retries nonnegative')
    image=args.image.read_bytes();list(download_packets(image,args.address,args.entry))
    import serial
    with serial.Serial(args.port,args.baud,timeout=min(args.timeout,0.1),write_timeout=args.timeout) as port:
        print(download(port,image,args.address,args.entry,args.retries,args.timeout))

if __name__=='__main__':main()
