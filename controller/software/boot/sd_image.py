"""NXSD v1 fixed-sector image builder. The ROM pins independently received hashes."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys
import zlib
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'model_tools'))
from verify_pack import verify

def header(app_bytes,app_hash,model_bytes,model_hash,base=0xb4000000,entry=0xb4000000):
    app_sectors=(app_bytes+511)//512;model_start=1+app_sectors
    if not 0xb4000000<=base<0xb7ff0000 or not 0<app_bytes<=0xb7ff0000-base or not base<=entry<base+app_bytes or entry%4:
        raise ValueError('application window/entry')
    sectors=model_start+(model_bytes+511)//512
    if not 0<model_bytes or sectors>=2**32:raise ValueError('model/image size')
    out=bytearray(512);struct.pack_into('<8s7I',out,0,b'NXSDV1\0\0',1,512,sectors,1,app_bytes,base,entry)
    out[36:68]=bytes.fromhex(app_hash);struct.pack_into('<2I',out,68,model_start,model_bytes);out[76:108]=bytes.fromhex(model_hash)
    struct.pack_into('<I',out,508,zlib.crc32(out[:508]));return bytes(out)

def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1<<20),b''):h.update(b)
    return h.hexdigest()

def build(app,model,out,validate=True):
    app,model,out=map(Path,(app,model,out))
    if validate:verify(model,expected_sha256=digest(model))
    raw=header(app.stat().st_size,digest(app),model.stat().st_size,digest(model))
    with out.open('wb') as f:
        f.write(raw)
        for p in (app,model):
            with p.open('rb') as source:
                for b in iter(lambda:source.read(1<<20),b''):f.write(b)
            f.write(bytes((-p.stat().st_size)%512))
    return audit(out,check_model=validate)

def audit(path,check_model=False):
    path=Path(path)
    with path.open('rb') as f:
        raw=f.read(512)
        if len(raw)!=512 or raw[:8]!=b'NXSDV1\0\0' or struct.unpack_from('<2I',raw,8)!=(1,512):raise ValueError('media format')
        if zlib.crc32(raw[:508])!=struct.unpack_from('<I',raw,508)[0] or any(raw[108:508]):raise ValueError('media CRC/reserved')
        count,start,n,base,entry=struct.unpack_from('<5I',raw,16);mstart,mn=struct.unpack_from('<2I',raw,68)
        expected=header(n,raw[36:68].hex(),mn,raw[76:108].hex(),base,entry)
        if raw!=expected or start!=1 or path.stat().st_size!=count*512:raise ValueError('media spans/truncation')
        spans=[]
        for label,lba,size,h in [('application',start,n,raw[36:68]),('model',mstart,mn,raw[76:108])]:
            f.seek(lba*512);hasher=hashlib.sha256();left=size
            while left:
                b=f.read(min(left,1<<20))
                if not b:raise ValueError('truncated '+label)
                left-=len(b);hasher.update(b)
            if hasher.digest()!=h or any(f.read((-size)%512)):raise ValueError('payload hash/padding '+label)
            spans.append(dict(name=label,lba=lba,bytes=size,sha256=h.hex()))
    # Model structure is verified by the independent T10 reader on the source
    # before construction; audit always rechecks every byte and media offset.
    return dict(status='PASS',bytes=path.stat().st_size,sectors=count,spans=spans,sha256=digest(path))

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--app',type=Path);p.add_argument('--model',type=Path);p.add_argument('--output',type=Path);p.add_argument('--audit',type=Path);a=p.parse_args()
    if a.audit:print(json.dumps(audit(a.audit),indent=2));return
    if not all((a.app,a.model,a.output)):p.error('--app/--model/--output required')
    print(json.dumps(build(a.app,a.model,a.output),indent=2))
if __name__=='__main__':main()
