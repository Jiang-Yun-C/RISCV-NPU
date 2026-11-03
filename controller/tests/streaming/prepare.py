"""Pinned T10 payloads into their frozen SoC addresses; independent expected data."""
import hashlib,json,struct,sys
from pathlib import Path
import numpy as np
from elftools.elf.elffile import ELFFile
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/'tests/models')]
from model_tools.verify_pack import verify,PackError
from prepare_image import parse_elf
ABI=0x53543134

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def request(**kw):
    names='abi size session_lo session_hi sequence_lo sequence_hi opcode m n k source destination scales bias aq sa output_stride row_bytes source_stride destination_stride'.split()
    values=dict.fromkeys(names,0);values.update(abi=ABI,size=96,session_lo=1,sequence_lo=1);values.update(kw)
    return [values[k] for k in names]+[0]*4

def prepare(elf,out,profile):
    out=Path(out);out.mkdir(parents=True)
    fixture_root=ROOT/'tests/cocotb/fixtures/model_pack'
    manifest=json.loads((fixture_root/'manifest.json').read_text());good={c['case_id']:c for c in manifest['cases'] if c['expected_error'] is None}
    negatives=[]
    for c in manifest['cases']:
        path=fixture_root/c['pack']['file']
        if sha(path)!=c['pack']['sha256']:raise ValueError('fixture pack identity')
        if c['expected_error']:
            try:verify(path)
            except PackError as e:
                if e.code!=c['expected_error']:raise
                negatives.append(dict(case=c['case_id'],error=e.code,pack_sha256=sha(path),backend_submissions=0))
            else:raise ValueError('bad pack accepted')
    (out/'pack-rejections.json').write_text(json.dumps(negatives,indent=2)+'\n')
    with Path(elf).open('rb') as f:
        symbols={s.name:int(s['st_value']) for s in ELFFile(f).get_section_by_name('.symtab').iter_symbols() if s.name}
    entry,segs,_=parse_elf(Path(elf).read_bytes(),base=0,capacity=0x18000)
    mem=bytearray(0x18000)
    for s in segs:
        if not (s.address+s.memory_size<=8192 or 0x10000<=s.address<s.address+s.memory_size<=0x17000):raise ValueError('TCM segment overlaps stack')
        mem[s.address:s.address+len(s.data)]=s.data
    mem[0x17000-16:0x18000]=bytes([0xa5])*4112
    tcm=mem[:8192]+mem[0x10000:0x18000]
    (out/'load.hex').write_text(''.join(f'{int.from_bytes(tcm[i:i+16],"little"):032x}\n' for i in range(0,len(tcm),16)))
    regions=[];jobs=[];plan=[];output_cursor=0xac100000
    def region(name,address,data,kind):
        path=out/(name+'.bin');path.write_bytes(bytes(data));rec=dict(name=name,address=address,bytes=len(data),path=str(path.resolve()),sha256=sha(path),kind=kind)
        regions.append(rec);plan.append(f'B {address:x} {len(data):x} {path.resolve()}\n');return address
    def add_copy(name,src,rows,width,srcstride,dststride,data,**extra):
        nonlocal output_cursor
        dst=output_cursor;span=(rows-1)*dststride+width
        region(name+'-sentinel',dst-16,bytes([0xa5])*(span+48),'output')
        expected=out/(name+'-expected.bin');expected.write_bytes(bytes(data))
        jobs.append(dict(name=name,request=request(opcode=1,n=rows,source=src,destination=dst,row_bytes=width,source_stride=srcstride,destination_stride=dststride),
            expected_path=str(expected.resolve()),expected_sha256=sha(expected),rows=rows,row_bytes=width,source_stride=srcstride,destination_stride=dststride,
            checksum=sum(data)&0xffffffff,logical_read=rows*width,logical_write=rows*width,status=0,**extra))
        output_cursor=(dst+span+4095)//4096*4096+4096
    selected=[{'pack':'legal-rvv','pack-tail':'legal-tail','pack-down':'legal-down'}.get(profile,'legal-down')]
    for fid in selected:
        c=good[fid];pack=verify(fixture_root/c['pack']['file'],expected_sha256=c['pack']['sha256']);raw=pack.path.read_bytes()
        # Packs overlap the same production weights base; each simulation loads one
        # pack at its real address, while further packs get their own batch process.
        for e in pack.entries.values():
            if e['alias_of'] is not None or e['region']!=1:continue
            payload=raw[e['offset']:e['offset']+e['length']]
            key=fid+'-'+e['name'].replace('.','-').replace('/','-')
            region(key,e['soc_address'],payload,'input')
            width=((e['shape'][1]+63)//64)*64 if e['kind']==1 else e['length']
            rows=e['shape'][0] if e['kind']==1 else 1
            if profile in ('short','errors'):
                rows=1;width=min(width,256);payload=payload[:width]
            stride=(width+15)//16*16
            add_copy(key,e['soc_address'],rows,width,stride,stride,payload,pack=fid,tensor=e['name'],pack_sha256=c['pack']['sha256'],file_offset=e['offset'],layout_id=e['layout_id'])
        # Real row-tail calculation; package Aq/Sa are not host-generated substitutes.
        aq=np.load(fixture_root/c['arrays']['aq']['file'],allow_pickle=False)
        sa=np.load(fixture_root/c['arrays']['sa']['file'],allow_pickle=False)
        for key in ('aq','sa','y'):
            if sha(fixture_root/c['arrays'][key]['file'])!=c['arrays'][key]['sha256']:raise ValueError('array identity')
        a=region(fid+'-aq',0xac000000,aq.tobytes(),'input');s=region(fid+'-sa',0xac008000,sa.tobytes(),'input')
        if profile=='capacity':
            aq=np.repeat(aq,4,axis=0);sa=np.repeat(sa,4,axis=0)
            # Four exact producer rows exercise the maximum 20672-byte staging.
            regions[:]=[r for r in regions if r['name'] not in (fid+'-aq',fid+'-sa')]
            plan[:]=[line for line in plan if not line.endswith(str((out/(fid+'-aq.bin')).resolve())+'\n') and not line.endswith(str((out/(fid+'-sa.bin')).resolve())+'\n')]
            a=region(fid+'-aq',0xac000000,aq.tobytes(),'input');s=region(fid+'-sa',0xac008000,sa.tobytes(),'input')
        w=pack.entries['model.embed_tokens.weight'];sc=pack.entries['model.embed_tokens.weight.scale'];bias=pack.entries['fixture.bias']
        m,k=aq.shape;n=w['shape'][0] if profile not in ('short','errors') else 1;stride=n*4+16
        dst=output_cursor;region(fid+'-y-sentinel',dst-16,bytes([0xa5])*(m*stride+48),'output')
        y=np.load(fixture_root/c['arrays']['y']['file'],allow_pickle=False)[:,:n]
        if profile=='capacity':y=np.repeat(y,4,axis=0)
        yp=out/(fid+'-y.npy');np.save(yp,y)
        jobs.append(dict(name=fid+'-linear',request=request(opcode=2,m=m,n=n,k=k,source=w['soc_address'],destination=dst,scales=sc['soc_address'],bias=bias['soc_address'],aq=a,sa=s,output_stride=stride),
            expected_path=str(yp.resolve()),expected_sha256=sha(yp),m=m,n=n,k=k,output_stride=stride,rows=n,status=0,
            logical_read=m*k+m*(k//64)*4+n*k+n*(k//64)*4+n*4 if k!=65 else 0,logical_write=m*n*4 if k!=65 else 0,pack=fid,pack_sha256=c['pack']['sha256']))
        if k==65:jobs[-1].update(status=-3,rows=0)
        output_cursor=(dst+m*stride+4096+15)//16*16
    src=region('boundary-input',0xa7ffcff0,bytes((i*37+11)&255 for i in range(4099 if profile in ('short','errors') else 8197)),'input')
    data=Path(regions[-1]['path']).read_bytes();add_copy('boundary-tail',src,1,len(data),8208,8208,data)
    # High shared-I/O address ending just before the protected boundary.
    src2=region('high-input',0xbbffffe0,bytes(range(32)),'input');add_copy('high-address',src2,1,32,32,32,bytes(range(32)))
    if profile=='errors':
        base=next(j for j in jobs if j['name']=='boundary-tail')
        for name,index,value,status in [('misaligned',10,src+1,-5),('high-wrap',10,0xfffffff0,-4),('cross-window',10,0xa7fffff0,-4),('private-output',11,0xb4000000,-4),('overlap',11,src,-4),('unknown-op',6,3,-3),('k65',6,2,-3)]:
            r=base['request'].copy();r[index]=value
            if name=='k65':r[7]=1;r[9]=65
            jobs.append(dict(name=name,request=r,status=status,logical_read=0,logical_write=0,rows=0))
        for name,resp,where in [('read-slverr',2,'read'),('read-decerr',3,'read'),('write-slverr',2,'write'),('write-decerr',3,'write'),('long-pause',0,'pause')]:
            r=base['request'].copy()
            jobs.append(dict(name=name,request=r,status='IO_FAULT' if resp else 'TIMEOUT',inject=resp,inject_where=where,rows=0))
        # Same buffers after recovery, with no reset of the AXI responder/guard.
        jobs.append({**base,'name':'recovered-boundary'})
    for i,j in enumerate(jobs,1):j['request'][4]=i
    (out/'load.plan').write_text(''.join(plan))
    golden=dict(producer='T10',numeric_version=manifest['numeric_version'],thresholds_sha256=sha(ROOT/'configs/t05-thresholds.json'),thresholds=json.loads((ROOT/'configs/t05-thresholds.json').read_text())['operators']['linear'],jobs=jobs)
    (out/'golden.json').write_text(json.dumps(golden,indent=2)+'\n')
    fixture=dict(schema_version=1,profile=profile,entry=entry,regions=regions,elf_sha256=sha(elf),symbols=symbols,
                 fixture_manifest_sha256=sha(fixture_root/'manifest.json'),pack_rejections=negatives,
                 scope='REAL_CORAL_RVV_COMPONENT; native subordinate submission; no CPU execution claim',test_mode='PRELOAD',
                 activation_derivation='repeat four pinned T10 M1 rows, including golden' if profile=='capacity' else 'exact pinned T10 Aq/Sa',
                 files={p.name:sha(p) for p in out.iterdir() if p.is_file()})
    (out/'fixture.json').write_text(json.dumps(fixture,indent=2)+'\n');return fixture
