#!/usr/bin/env python3
"""Independent host oracle and AXI handshake/completion checker for T06."""
import argparse
from collections import deque
import csv
import hashlib
import json
from pathlib import Path
import re


def require(ok, msg):
    if not ok: raise ValueError(msg)


def read_hex(path, count):
    lines=path.read_text().splitlines()
    require(len(lines)==count and all(re.fullmatch('[0-9a-fA-F]{32}',s) for s in lines),'bad memory dump')
    return b''.join(int(s,16).to_bytes(16,'little') for s in lines)


def check(case, image, disassembly, log):
    spec=json.loads((image/'image.json').read_text())
    initial=read_hex(image/'load.hex',2560)
    require(hashlib.sha256(initial).hexdigest()==spec['image_sha256'],'image hash')
    final=read_hex(case/'dtcm.hex',2048)
    for name,s in spec['expected'].items():
        a=s['address']-0x10000
        require(final[a:a+s['size']].hex()==s['hex'],'wrong output: '+name)
    asm=disassembly.read_text()
    needed={'vector':['vle8.v','vwadd.vv','vwmul.vv','vwredsum.vs','vse16.v'],
            'upstream_rvv':['vle8.v','vwadd.vv','vse16.v'], 'float':['fadd.s']}[spec['kind']]
    require(all(op in asm for op in needed),'missing compute instructions in ELF disassembly')
    output=log.read_text()
    marker=re.search(r'T06_EXECUTED seed=(\d+) entry=([0-9a-f]+) cycles=(\d+) halted=1 fault=0',output)
    require(marker is not None and 'Fatal:' not in output and 'Error' not in output,'missing clean execution marker')
    require(int(marker[2],16)==spec['entry'] and int(marker[3])>0,'bad execution identity')
    aw,w,ar=deque(),deque(),deque()
    counts={k:0 for k in ['aw','w','b','ar','r']}
    loaded=[]; readback=[]; dump=[]; prior=None; halted_seen=False
    with (case/'bus.csv').open() as f:
        for row in csv.DictReader(f):
            def hx(k):
                require(re.fullmatch('[0-9a-fA-F]+',row[k]) is not None,'unknown active field '+k)
                return int(row[k],16)
            def hs(ch): return row[ch+'valid']=='1' and row[ch+'ready']=='1'
            if prior:
                require(int(row['cycle'])==int(prior['cycle'])+1,'trace cycle gap')
                for ch,fields in [('b',['bidresp']),('r',['ridresp','rdata','rlast']),
                                  ('aw',['awaddr']),('w',['wdata','wstrb']),('ar',['araddr'])]:
                    if prior[ch+'valid']=='1' and prior[ch+'ready']=='0':
                        require(row[ch+'valid']=='1' and all(row[k]==prior[k] for k in fields),'unstable '+ch)
            if hs('aw'): aw.append((hx('awaddr'),int(row['phase']))); counts['aw']+=1
            if hs('w'): w.append((hx('wdata'),hx('wstrb'))); counts['w']+=1
            if hs('b'):
                require(aw and w and hx('bidresp')==12,'unexpected write response')
                addr,phase=aw.popleft(); data,strb=w.popleft(); counts['b']+=1
                if addr<0x18000: loaded.append((addr,data,strb))
                else:
                    require((addr==0x30004 and data==spec['entry']<<32 and strb==0xf0) or
                            (addr==0x30000 and data==0 and strb==0xf),'incorrect control write')
            if hs('ar'): ar.append((hx('araddr'),int(row['phase']))); counts['ar']+=1
            if hs('r'):
                require(ar and hx('ridresp')==20 and row['rlast']=='1','unexpected read response')
                addr,phase=ar.popleft(); data=hx('rdata'); counts['r']+=1
                if phase==1 and addr<0x18000:readback.append((addr,data))
                if phase==3 and addr<0x18000:dump.append((addr,data))
                if addr==0x30004: require((data>>32)&0xffffffff==spec['entry'],'wrong CSR entry')
                if addr==0x30008: require((data>>64)&0xffffffff==1,'wrong CSR halt status')
            if int(row['phase'])>=2:
                require(row['fault']=='0','fault in execution trace')
                halted_seen |= row['halted']=='1'
            prior=row
    addresses=[i*16 if i<512 else 0x10000+(i-512)*16 for i in range(2560)]
    words=[int.from_bytes(initial[i:i+16],'little') for i in range(0,len(initial),16)]
    require(loaded==[(a,d,0xffff) for a,d in zip(addresses,words)],'AXI upload mismatch')
    require(readback==list(zip(addresses,words)),'AXI image readback mismatch')
    require(dump==[(0x10000+i,int.from_bytes(final[i:i+16],'little')) for i in range(0,len(final),16)],'dump differs from bus reads')
    require(counts=={'aw':2562,'w':2562,'b':2562,'ar':4610,'r':4610},'incomplete/extra bus transactions')
    require(not aw and not w and not ar and halted_seen,'unfinished bus or no halt')
    vcd=(case/'coral.vcd').read_text()
    require('$enddefinitions' in vcd and ' halted ' in vcd and ' fault ' in vcd and '#0' in vcd,'missing waveform signals')
    result={'status':'PASS','kind':spec['kind'],'seed':int(marker[1]),'execution_cycles':int(marker[3]),
            'halted':True,'fault':False,'counts':counts,'checked_outputs':list(spec['expected']),
            'required_instructions':needed,'dtcm_sha256':hashlib.sha256(final).hexdigest(),
            'qualification':'TCM_PROGRAM_EXECUTION_ONLY_NO_EXTERNAL_MEMORY_OR_BOARD_PERFORMANCE'}
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('case',type=Path);p.add_argument('image',type=Path)
    p.add_argument('disassembly',type=Path);p.add_argument('log',type=Path);a=p.parse_args()
    result=check(a.case,a.image,a.disassembly,a.log)
    (a.case/'check.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
