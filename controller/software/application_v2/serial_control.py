#!/usr/bin/env python3
"""Desktop full-model terminal -> T20 UART executor. No language rules."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import select
import sys
import termios
import time
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/'tests/runtime')]
from software.runtime.run_cpu import PortableModel,build
from tokenizer_reference import CTokenizer
from software.application_v2.compiler import compile_request

def frame(request_id,epoch,text,intent):
    a=text.encode('utf-8');b=intent.encode('utf-8')
    if not 0<request_id<0xffffffff or not 0<=epoch<=0xffffffff or len(a)>4096 or len(b)>4096 or '\x00' in text or '\x00' in intent:raise ValueError('UART frame bounds')
    return f'{request_id} {epoch} {len(a)} {len(b)}\n'.encode()+a+b'\n'+b+b'\n'

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--snapshot',type=Path,required=True,help='JSON {epoch,state:{temperature,light,led,pwm}} from acquisition side')
    p.add_argument('--text');p.add_argument('--request-id',type=int,default=1);p.add_argument('--port');p.add_argument('--baud',type=int,default=115200);p.add_argument('--dry-run',action='store_true');p.add_argument('--log',type=Path,required=True)
    a=p.parse_args()
    if not a.dry_run and not a.port:p.error('--port or --dry-run required')
    library=ROOT/'build/t20-terminal/libnxr.so';cmd=build(library);tokenizer=ROOT/'build/runtime-cpu/tokenizer/tokenizer.nxt'
    if not tokenizer.exists():
        from model_tools.export_tokenizer import export
        export(tokenizer.parent)
    model=PortableModel(library);tok=CTokenizer(library,tokenizer);fd=None
    if not a.dry_run:
        fd=os.open(a.port,os.O_RDWR|os.O_NOCTTY|os.O_NONBLOCK);attrs=termios.tcgetattr(fd)
        attrs[0]=0;attrs[1]=0;attrs[2]=termios.CS8|termios.CREAD|termios.CLOCAL;attrs[3]=0
        attrs[4]=attrs[5]=getattr(termios,'B'+str(a.baud));attrs[6][termios.VMIN]=0;attrs[6][termios.VTIME]=0;termios.tcsetattr(fd,termios.TCSANOW,attrs)
    try:
        texts=[a.text] if a.text is not None else (line.rstrip('\n') for line in sys.stdin)
        for request_id,text in enumerate(texts,a.request_id):
            snap=json.loads(a.snapshot.read_text())
            generated=compile_request(model,tok,text,snap['state'])
            if generated['stop']!='eos':raise ValueError('model generation did not reach EOS; no device request sent')
            packet=frame(request_id,snap['epoch'],text,generated['text']);response=None
            if a.dry_run:sys.stdout.buffer.write(packet);sys.stdout.buffer.flush()
            else:
                pending=memoryview(packet);deadline=time.monotonic()+120;buf=bytearray()
                while pending:
                    if time.monotonic()>deadline:raise TimeoutError('UART write')
                    if select.select([], [fd], [],1)[1]:pending=pending[os.write(fd,pending):]
                while response is None:
                    if time.monotonic()>deadline:raise TimeoutError('UART response')
                    if select.select([fd],[],[],1)[0]:buf.extend(os.read(fd,4096))
                    while b'\n' in buf:
                        line,_,rest=buf.partition(b'\n');buf=bytearray(rest);print(line.decode('utf-8'))
                        if line.startswith(b'{'):
                            row=json.loads(line)
                            if row.get('id')==request_id:response=row
            record=dict(id=request_id,text=text,snapshot=snap,model=generated,output_sha256=hashlib.sha256(generated['text'].encode()).hexdigest(),
                frame_sha256=hashlib.sha256(packet).hexdigest(),library_sha256=hashlib.sha256(library.read_bytes()).hexdigest(),build_argv=cmd,response=response,
                model_pack_sha256=json.loads((ROOT/'docs/spec/model-pack-v1-manifest.json').read_text())['sha256'],
                compiler_sha256=hashlib.sha256((ROOT/'software/application_v2/compiler.py').read_bytes()).hexdigest(),
                scope='desktop full W8 C model; UART recorded-intent executor; physical port is an explicit caller choice')
            with a.log.open('a') as log:log.write(json.dumps(record,ensure_ascii=False)+'\n')
    finally:
        if fd is not None:os.close(fd)
if __name__=='__main__':main()
