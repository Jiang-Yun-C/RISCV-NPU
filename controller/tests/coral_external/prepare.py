#!/usr/bin/env python3
"""Project the frozen T05 vectors into a T07 probe image, with checked ELF bounds."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys
import numpy as np
from elftools.elf.elffile import ELFFile
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tests/models'))
from prepare_image import parse_elf

def digest(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def prepare(elf, vectors, output, family, m, row=0, rows=None, audit=1, restore=1):
    index=json.loads((vectors/'index.json').read_text())
    assert index['numeric_version']=='w8a8-g64-fp32-v1'
    assert index['thresholds_sha256']==digest(ROOT/'configs/t05-thresholds.json')
    assert index['model_lock_sha256']==digest(ROOT/'docs/spec/application-v2-model-lock.json')
    used={}
    def load(name):
        p=vectors/name; h=digest(p)
        expected=index['files'][name]
        assert h==(expected['sha256'] if isinstance(expected,dict) else expected),name
        used[name]=h
        return np.load(p,allow_pickle=False,mmap_mode='r')
    wi=index['weights'][family]
    w=load(wi['q']); sw=load(wi['scale']); n,k=w.shape
    rows=n-row if rows is None else rows
    assert 0<=row<row+rows<=n and m in (1,4)
    aq=load(f'{family}-m{m}/aq.npy'); sa=load(f'{family}-m{m}/sa.npy')
    dots=load(f'{family}-m{m}/dots.npy')[:,:,row:row+rows].transpose(2,0,1)
    y=load(f'{family}-m{m}/y.npy')[:,row:row+rows]
    bias=load(wi['bias'])[row:row+rows] if wi['bias'] else None
    entry,segs,flags=parse_elf(elf.read_bytes(),base=0,capacity=0x18000)
    assert not flags&1 and entry%4==0
    mem=bytearray(0x18000)
    for s in segs:
        assert (0<=s.address<s.address+s.memory_size<=8192 or 0x10000<=s.address<s.address+s.memory_size<=0x18000)
        mem[s.address:s.address+len(s.data)]=s.data
    with elf.open('rb') as f:
        symbols={s.name:dict(address=int(s['st_value']),size=int(s['st_size'])) for s in ELFFile(f).get_section_by_name('.symtab').iter_symbols() if s.name}
    output.mkdir(parents=True,exist_ok=False)
    regions={}; plan=[]
    def region(name,addr,blob,access):
        blob=bytes(blob); p=output/(name+'.bin');p.write_bytes(blob)
        regions[name]=dict(address=addr,size=len(blob),file=p.name,sha256=digest(p),access=access)
        plan.append(f'B {addr:x} {len(blob):x} {p.resolve()}\n')
    region('weights',0x80000000,w[row:row+rows].tobytes()+bytes(16),'read')
    region('scales',0x82000000,sw[row:row+rows].tobytes(),'read')
    if bias is not None: region('bias',0x83000000,bias.tobytes(),'read')
    region('output',0xa0000000,bytes([0xa5])*y.nbytes,'write')
    region('dots',0xa1000000,bytes([0xa5])*dots.nbytes,'write')
    def put(name,blob):
        s=symbols[name];addr=s['address'];assert len(blob)<=s['size'] and 0x10000<=addr<addr+s['size']<=0x18000
        mem[addr:addr+len(blob)]=blob
    put('activations',aq.tobytes());put('activation_scales',sa.tobytes())
    put('config',struct.pack('<10I',rows,k,m,regions['weights']['address'],regions['scales']['address'],
        regions['bias']['address'] if bias is not None else 0,regions['output']['address'],regions['dots']['address'],audit,restore))
    tcm=mem[:8192]+mem[0x10000:0x18000]
    (output/'load.hex').write_text(''.join(f'{int.from_bytes(tcm[i:i+16],"little"):032x}\n' for i in range(0,len(tcm),16)))
    (output/'load.plan').write_text(''.join(plan))
    np.save(output/'expected-dots.npy',dots);np.save(output/'expected-y.npy',y)
    meta=dict(schema_version=1,family=family,m=m,n=rows,k=k,groups=(k+63)//64,row_offset=row,full_n=n,
        entry=entry,audit=bool(audit),restore=bool(restore),regions=regions,symbols=symbols,
        numeric_version=index['numeric_version'],thresholds_sha256=index['thresholds_sha256'],
        model_lock_sha256=index['model_lock_sha256'],vector_index_sha256=digest(vectors/'index.json'),
        vector_files=used,elf_sha256=digest(elf),segments=[dict(address=s.address,file_bytes=len(s.data),memory_bytes=s.memory_size) for s in segs],
        files={p.name:digest(p) for p in output.iterdir() if p.is_file()})
    (output/'image.json').write_text(json.dumps(meta,indent=2)+'\n')
    return meta

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('elf',type=Path);p.add_argument('vectors',type=Path);p.add_argument('output',type=Path)
    p.add_argument('--family',required=True);p.add_argument('--m',type=int,default=1);p.add_argument('--row',type=int,default=0)
    p.add_argument('--rows',type=int);p.add_argument('--audit',type=int,default=1);p.add_argument('--restore',type=int,default=1)
    a=p.parse_args();r=prepare(a.elf,a.vectors,a.output,a.family,a.m,a.row,a.rows,a.audit,a.restore)
    print(json.dumps({k:r[k] for k in ('family','m','n','k','row_offset')}))
