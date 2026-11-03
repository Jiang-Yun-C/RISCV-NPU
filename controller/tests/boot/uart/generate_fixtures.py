"""Generate immutable wire/error fixtures; expected byte writes come from inputs."""
import json
import sys
import zlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'software/boot')]
from evidence import sha256,write_json
from uart_protocol import *

SIGNATURES={'A':0xa1700001,'B':0xb1700002}

def generate(directory,apps,profile):
    directory=Path(directory);directory.mkdir(parents=True)
    images={name:(Path(path).read_bytes()) for name,path in apps.items()}
    actions=[]
    def add(name,wire,status,next_seq,writes=(),run=None,ack_seq=None):
        seq=int.from_bytes(wire[8:12],'little') if len(wire)>=12 else 0
        actions.append(dict(name=name,wire_hex=wire.hex(),ack=[seq if ack_seq is None else ack_seq,status,next_seq],
                            writes=list(writes),run=run,text=f'APP {run} PASS\nBOOT RETURN\n' if run else None))
    def begin(name,crc=None):
        image=images[name]
        return packet(BEGIN,0,BASE,len(image),BASE,zlib.crc32(image) if crc is None else crc)
    def load(name,prefix='',crc=None):
        image=images[name];checksum=zlib.crc32(image) if crc is None else crc
        add(prefix+'begin-'+name,begin(name,crc),OK,1)
        seq=1
        for offset in range(0,len(image),MAX_CHUNK):
            chunk=image[offset:offset+MAX_CHUNK]
            add(prefix+f'data-{name}-{seq}',packet(DATA,seq,BASE+offset,len(chunk),payload=chunk),OK,seq+1,
                [(BASE+offset+i,v) for i,v in enumerate(chunk)])
            seq+=1
        return packet(RUN,seq,BASE,len(image),BASE,checksum),seq
    if profile=='control':
        for name,address,length,target in [('rom',0x10000,64,0x10000),('stack',0xb7fefff0,64,0xb7fefff0),
                                          ('wrap',0xfffffff0,64,0xfffffff0),('entry-outside',BASE,64,BASE+64),
                                          ('entry-unaligned',BASE,64,BASE+1),('empty',BASE,0,BASE),
                                          ('image-oversize',BASE,65537,BASE)]:
            add('reject-'+name,packet(BEGIN,0,address,length,target),RANGE,0)
        add('partial-header-timeout',begin('A')[:24],TIMEOUT,0,ack_seq=0)
        add('begin-before-faults',begin('A'),OK,1)
        add('run-incomplete',packet(RUN,1,BASE,len(images['A']),BASE,zlib.crc32(images['A'])),INCOMPLETE,1)
        chunk=images['A'][:MAX_CHUNK];first=packet(DATA,1,BASE,len(chunk),payload=chunk)
        corrupt=bytearray(first);corrupt[-1]^=1
        add('bad-crc',bytes(corrupt),CRC,1)
        add('wrong-sequence',packet(DATA,3,BASE,len(chunk),payload=chunk),SEQUENCE,1)
        add('data-outside',packet(DATA,1,0x10000,len(chunk),payload=chunk),RANGE,1)
        add('data-zero-length',packet(DATA,1,BASE,0),RANGE,1)
        add('first-good',first,OK,2,[(BASE+i,v) for i,v in enumerate(chunk)])
        add('duplicate-ack-retry',first,DUP,2)
        changed=bytes([chunk[0]^1])+chunk[1:]
        add('duplicate-different-content',packet(DATA,1,BASE,len(changed),payload=changed),SEQUENCE,2)
        wire=packet(DATA,2,BASE+MAX_CHUNK,MAX_CHUNK,payload=images['A'][MAX_CHUNK:MAX_CHUNK*2])
        add('interrupted-data-timeout',wire[:-20],TIMEOUT,0)
        add('resume-aborted-session',wire,INCOMPLETE,0)
        oversized=packet(DATA,1,BASE,257,payload=b'\0'*257)
        add('oversize-packet',oversized[:28],FORMAT,0)
        run,seq=load('A','restart-')
        add('run-illegal-entry',packet(RUN,seq,BASE,len(images['A']),BASE+4,zlib.crc32(images['A'])),RANGE,seq)
        add('run-A',run,OK,seq,run='A')
        run,seq=load('B','image-crc-',zlib.crc32(images['B'])^1)
        add('reject-image-crc',run,IMAGE_CRC,seq)
        run,seq=load('B','redownload-')
        add('run-B',run,OK,seq,run='B')
    else:
        name='B' if profile=='preload' else 'A'
        run,seq=load(name)
        # Smoke and preload also prove rejection without any app execution.
        add('reject-run-entry',packet(RUN,seq,BASE,len(images[name]),BASE+4,zlib.crc32(images[name])),RANGE,seq)
        add('run-'+name,run,OK,seq,run=name)
    final_name='A' if profile=='smoke' else 'B'
    initial=images['A'] if profile=='preload' else b''
    final=images[final_name]
    fixture=dict(schema_version=1,producer='T17',profile=profile,test_mode='PRELOAD' if profile=='preload' else 'PROTOCOL_BOOT',
                 format_version=1,endianness='little',dtype='uint8',shape=[len(final)],stride_bytes=[1],
                 group_size='not_applicable',layout_id='RV32_RAW_CONTIGUOUS',logical_view='physical application bytes',
                 model_identity='not_applicable',comparison='bit_exact',generator_sha256=sha256(__file__),
                 checker_sha256=sha256(ROOT/'tests/boot/uart/scoreboard.py'),
                 images={n:dict(file=Path(p).name,sha256=sha256(p),bytes=len(images[n]),soc_address=BASE,entry=BASE)
                         for n,p in apps.items()},actions=actions)
    golden=dict(initial_hex=(initial+bytes(65536-len(initial))).hex(),final_hex=(final+bytes(65536-len(final))).hex(),
                images={n:dict(hex=b.hex(),signature=SIGNATURES[n]) for n,b in images.items()},
                boot_text='BOOT PRELOAD\nAPP A PASS\nBOOT RETURN\n' if profile=='preload' else 'BOOT PROTOCOL_BOOT\n',
                signatures=[SIGNATURES['A']] if profile=='smoke' else list(SIGNATURES.values()))
    write_json(directory/'fixture.json',fixture);write_json(directory/'golden.json',golden)
    return directory
