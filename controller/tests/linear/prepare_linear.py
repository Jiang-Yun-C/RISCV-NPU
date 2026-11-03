"""Consume pinned T10 physical payloads and T05/T11 logical inputs.

The oracle is independent integer arithmetic followed by explicit binary32
steps. No production numeric, firmware, or runtime implementation is imported.
"""
import hashlib,json,struct,sys
from pathlib import Path
import numpy as np
from elftools.elf.elffile import ELFFile
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/'tests/models')]
from model_tools.verify_pack import verify
from prepare_image import parse_elf
ABI=0x4c4e3135
_packs={}
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def oracle(a,sa,w,sw,bias):
    m,k=a.shape;n=w.shape[0];g=(k+63)//64
    dots=np.empty((g,m,n),dtype='<i4');p=np.empty((g,m,n),dtype='<f4');v=np.empty_like(p);partial=np.empty_like(p)
    y=np.zeros((m,n),dtype='<f4')
    for group in range(g):
        lo=group*64;hi=min(k,lo+64)
        dots[group]=a[:,lo:hi].astype('i8')@w[:,lo:hi].astype('i8').T
        p[group]=dots[group].astype('f4')*sa[:,group,None]
        v[group]=p[group]*sw[None,:,group]
        y=np.add(y,v[group],dtype='f4');partial[group]=y
    if bias is not None:y=np.add(y,bias[None,:],dtype='f4')
    return dict(dots=dots,p=p,v=v,partial=partial,y=y)
def request(m,n,k,w,sw,b,aq,sa,y,stride,audit):
    return [ABI,96,1,0,1,0,2,m,n,k,w,y,sw,b,aq,sa,stride,0,0,0,audit,0,0,0]
def prepare(elf,out,profile,config):
    out=Path(out);out.mkdir(parents=True)
    with Path(elf).open('rb') as f:symbols={s.name:int(s['st_value']) for s in ELFFile(f).get_section_by_name('.symtab').iter_symbols() if s.name}
    entry,segs,_=parse_elf(Path(elf).read_bytes(),base=0,capacity=0x18000);mem=bytearray(0x18000)
    for s in segs:
        if not (s.address+s.memory_size<=8192 or 0x10000<=s.address<s.address+s.memory_size<=0x16ff0):raise ValueError('TCM segment/guard overlap')
        mem[s.address:s.address+len(s.data)]=s.data
    mem[0x16ff0:0x18000]=bytes([0xa5])*4112;tcm=mem[:8192]+mem[0x10000:0x18000]
    (out/'load.hex').write_text(''.join(f'{int.from_bytes(tcm[i:i+16],"little"):032x}\n' for i in range(0,len(tcm),16)))
    regions=[];jobs=[];plan=[];sources=[];cursor=0xac100ff0;inputs=0xac000000;audit_cursor=0xba000ff0
    def region(name,address,data,kind):
        data=bytes(data);path=out/(name+'.bin');path.write_bytes(data)
        regions.append(dict(name=name,address=address,bytes=len(data),path=str(path.resolve()),sha256=sha(path),kind=kind))
        plan.append(f'B {address:x} {len(data):x} {path.resolve()}\n');return address
    def add(name,aq,sa,w,sw,bias,addresses=None,audit=True,producer=None):
        nonlocal cursor,inputs,audit_cursor
        m,k=aq.shape;n=w.shape[0];g=(k+63)//64;pk=g*64
        if addresses is None:
            wa=region(name+'-w',0x80000000+sum(r['bytes']+64 for r in regions if r['kind']=='weight')//64*64,np.pad(w,((0,0),(0,pk-k))).tobytes(),'weight')
            sca=(wa+n*pk+63)//64*64;region(name+'-sw',sca,sw.tobytes(),'weight')
            ba=(sca+n*g*4+63)//64*64 if bias is not None else 0
            if ba:region(name+'-b',ba,bias.tobytes(),'weight')
        else:wa,sca,ba=addresses
        aa=region(name+'-aq',inputs,np.pad(aq,((0,0),(0,pk-k))).tobytes(),'input');inputs=(inputs+m*pk+63)//64*64
        asa=region(name+'-sa',inputs,sa.tobytes(),'input');inputs=(inputs+m*g*4+63)//64*64
        stride=n*4+16;yaddr=cursor;size=(m-1)*stride+n*4
        region(name+'-output',yaddr-16,bytes([0xa5])*(size+48),'output');cursor=(yaddr+size+4095)//4096*4096+4096
        au=audit_cursor if audit else 0
        if au:region(name+'-audit',au-16,bytes([0xa5])*(m*n*g*16+48),'audit');audit_cursor=(au+m*n*g*16+4095)//4096*4096+4096
        expected=oracle(aq,sa,w,sw,bias);gp=out/(name+'-expected.npz');np.savez(gp,**expected)
        tile_count=(m+3)//4
        jobs.append(dict(name=name,request=request(m,n,k,wa,sca,ba,aa,asa,yaddr,stride,au),expected_path=str(gp.resolve()),expected_sha256=sha(gp),m=m,n=n,k=k,output_stride=stride,rows=n*tile_count,status=0,
            logical_read=m*(pk+g*4)+tile_count*n*(k+g*4+(4 if bias is not None else 0)),logical_write=m*n*4+(m*n*g*16 if au else 0),producer=producer,audit=bool(au)))
        if producer and 'y' in producer:
            pinned=np.load(ROOT/producer['y'],allow_pickle=False)[:,producer.get('row_start',0):producer.get('row_start',0)+n]
            if pinned.shape!=expected['y'].shape or not np.array_equal(pinned,expected['y']):raise ValueError('independent oracle differs from pinned producer Y')
    def fullpack():
        p=json.loads((ROOT/'docs/spec/model-pack-v1-manifest.json').read_text());path=ROOT/p['pack_path']
        if str(path) not in _packs:_packs[str(path)]=verify(path,expected_sha256=p['sha256'])
        return _packs[str(path)]
    def physical(pack,name,lo=0,hi=None):
        e=pack.entries[name]
        width=e['length']//e['shape'][0];hi=e['shape'][0] if hi is None else hi
        with pack.path.open('rb') as f:f.seek(e['offset']+lo*width);data=f.read((hi-lo)*width)
        address=e['soc_address']+lo*width
        region(name.replace('.','-'),address,data,'weight')
        return address
    if profile in config.get('profiles',{}):
        spec=config['profiles'][profile];pack=fullpack();family,m=spec['family'],spec['m']
        tensor=('lm_head.weight' if family=='head' else f'model.layers.0.{"mlp" if family in ("gate","up","down") else "self_attn"}.{family}_proj.weight')
        lo=spec['row_start'];hi=lo+spec['rows']
        wa=physical(pack,tensor,lo,hi);sca=physical(pack,tensor+'.scale',lo,hi);bn=tensor[:-6]+'bias';ba=physical(pack,bn,lo,hi) if bn in pack.entries else 0
        w=pack.rows(tensor,lo,hi);sw=pack.rows(tensor+'.scale',lo,hi);bias=pack.rows(bn,lo,hi) if ba else None
        vectors=ROOT/config['input_t05']/'artifacts/vectors';idx=json.loads((vectors/'index.json').read_text())
        folder=vectors/f'{family}-m{m}';aq=np.load(folder/'aq.npy',allow_pickle=False);sa=np.load(folder/'sa.npy',allow_pickle=False)
        for p in (folder/'aq.npy',folder/'sa.npy',folder/'y.npy'):
            record=idx['files'][str(p.relative_to(vectors))]
            if sha(p)!=(record['sha256'] if isinstance(record,dict) else record):raise ValueError('T05 input identity')
        producer=dict(task='T05/T10',pack_sha256=pack.summary['sha256'],tensor=tensor,file_offset=pack.entries[tensor]['offset']+lo*((pack.entries[tensor]['shape'][1]+63)//64)*64,soc_address=wa,physical_layout=4097,logical_layout=1,row_start=lo,y=str((folder/'y.npy').relative_to(ROOT)))
        add(profile,aq,sa,w,sw,bias,(wa,sca,ba),audit=spec['audit'],producer=producer);sources.append(producer)
    elif profile=='t11':
        pack=fullpack();manifest=json.loads((ROOT/'tests/cocotb/fixtures/golden/manifest.json').read_text());rec=next(c for c in manifest['cases'] if c['kind']=='linear');p=ROOT/'tests/cocotb/fixtures/golden'/rec['path']
        if sha(p)!=rec['sha256']:raise ValueError('T11 fixture identity')
        with np.load(p,allow_pickle=False) as f:
            name=rec['weight'];wa=physical(pack,name);sca=physical(pack,name+'.scale');bn=name[:-6]+'bias';ba=physical(pack,bn)
            add('t11-q',f['aq'],f['sa'],pack.rows(name),pack.rows(name+'.scale'),pack.rows(bn),(wa,sca,ba),producer=dict(task='T11',fixture_sha256=rec['sha256']))
            with np.load(jobs[-1]['expected_path'],allow_pickle=False) as got:
                if not np.array_equal(f['dots'],got['dots']) or not np.array_equal(f['y'],got['y']):raise ValueError('T11 independent oracle')
    elif profile=='packs':
        manifest=json.loads((ROOT/'tests/cocotb/fixtures/model_pack/manifest.json').read_text());base=ROOT/'tests/cocotb/fixtures/model_pack'
        # Separate packs use relocated temporary views; full real-shape runs
        # above consume the unchanged production SoC addresses.
        for rec in manifest['cases']:
            if rec['case_id'] not in ('legal-rvv','legal-tail','legal-down'):continue
            pack=verify(base/rec['pack']['file'],expected_sha256=rec['pack']['sha256']);a={}
            for key in ('aq','sa','y','dots'):
                p=base/rec['arrays'][key]['file']
                if sha(p)!=rec['arrays'][key]['sha256']:raise ValueError('T10 fixture array identity')
                a[key]=np.load(p,allow_pickle=False)
            add(rec['case_id'],a['aq'],a['sa'],pack.rows('model.embed_tokens.weight'),pack.rows('model.embed_tokens.weight.scale'),pack.rows('fixture.bias'),producer=dict(task='T10',pack_sha256=pack.summary['sha256'],adaptation='byte-identical payload relocated for simultaneous small packs'))
            with np.load(jobs[-1]['expected_path'],allow_pickle=False) as got:
                if not np.array_equal(got['dots'],a['dots']) or not np.array_equal(got['y'],a['y']):raise ValueError('T10 oracle')
    else:
        rng=np.random.default_rng(20261005)
        m,n,k=8,129,65;aq=rng.integers(-127,128,(m,k),dtype=np.int8);w=rng.integers(-127,128,(n,k),dtype=np.int8)
        aq[0]=127;aq[1]=-127;aq[2]=0;w[0]=127;w[1]=-127;w[2]=0
        sa=np.full((m,2),0.015625,dtype='<f4');sw=np.full((n,2),0.03125,dtype='<f4');sa[2]=0;sw[2]=0
        add('extreme-tail-m8',aq,sa,w,sw,np.linspace(-1,1,n,dtype='f4'),producer=dict(task='T15_BOUNDARY',seed=20261005))
        a3=rng.integers(-127,128,(5,127),dtype=np.int8);w3=rng.integers(-127,128,(17,127),dtype=np.int8)
        add('m5-k127-no-bias',a3,np.full((5,2),.0078125,dtype='f4'),w3,np.full((17,2),.015625,dtype='f4'),None,producer=dict(task='T15_BOUNDARY',seed=20261005))
        if profile=='errors':
            basejob=jobs[0]
            for name,index,value,status in [('unknown-op',6,99,-3),('m-zero',7,0,-1),('k-too-large',9,4865,-3),('misaligned',10,0x80000001,-5),('output-protected',11,0xb4000000,-4),('overlap',11,basejob['request'][14],-4),('reserved',21,1,-1),('version',0,0,-2),('sequence',4,0,-10)]:
                r=basejob['request'].copy();r[index]=value;jobs.append(dict(name=name,request=r,status=status,rows=0,logical_read=0,logical_write=0))
            for name,resp,where in [('read-slverr',2,'read'),('write-decerr',3,'write')]:
                jobs.append(dict(name=name,request=basejob['request'].copy(),status='IO_FAULT',inject=resp,inject_where=where,rows=0))
            jobs.append({**basejob,'name':'recovered-tail'})
            for name,kind in [('aq-minus128','aq'),('sa-negative','sa'),('sa-subnormal','subnormal'),('sa-zero-nonzero','zero'),('w-minus128','w'),('sw-negative','sw')]:
                a4=np.ones((1,65),dtype='i1');w4=np.ones((1,65),dtype='i1');s4=np.ones((1,2),dtype='f4');ws4=np.ones((1,2),dtype='f4')
                if kind=='aq':a4[0,0]=-128
                if kind=='sa':s4[0,0]=-1
                if kind=='subnormal':s4[0,0]=np.nextafter(np.float32(0),np.float32(1))
                if kind=='zero':s4[0,0]=0
                if kind=='w':w4[0,0]=-128
                if kind=='sw':ws4[0,0]=-1
                add(name,a4,s4,w4,ws4,None,audit=False);jobs[-1].update(status=-9,rows=0,logical_read=None,logical_write=0)
    for i,j in enumerate(jobs,1):
        if j['name']!='sequence':j['request'][4]=i
    (out/'load.plan').write_text(''.join(plan));threshold=json.loads((ROOT/'configs/t05-thresholds.json').read_text())['operators']['linear']
    golden=dict(producer='INDEPENDENT_T15_ORACLE_AND_PINNED_T05_T10_T11',numeric_version='w8a8-g64-fp32-v1',thresholds_sha256=sha(ROOT/'configs/t05-thresholds.json'),thresholds=threshold,jobs=jobs)
    (out/'golden.json').write_text(json.dumps(golden,indent=2)+'\n')
    fixture=dict(schema_version=1,profile=profile,entry=entry,regions=regions,elf_sha256=sha(elf),symbols=symbols,sources=sources,
        scope='REAL_CORAL_RVV_LINEAR_COMPONENT; native subordinate submission; VexRiscv control remains T16',test_mode='PRELOAD',group_size=64,numeric_version='w8a8-g64-fp32-v1',endianness='little',
        generator_sha256=sha(__file__),checker_sha256=sha(ROOT/'tests/linear/linear_check.py'),files={p.name:sha(p) for p in out.iterdir() if p.is_file()})
    (out/'fixture.json').write_text(json.dumps(fixture,indent=2)+'\n');return fixture
