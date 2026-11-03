"""T16 immutable PRELOAD fixture and independent T05/T11 oracle."""
import hashlib,json,struct,sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/'tests/linear')]
from model_tools.verify_pack import verify
from prepare_linear import oracle

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def tensor(address,bytes_,dtype,shape):
    rank=len(shape);stride=[];item=1 if dtype==1 else 4
    for x in reversed(shape):stride.insert(0,item);item*=x
    return dict(address=address,allocation_bytes=bytes_,dtype=dtype,rank=rank,shape=shape+[0]*(4-rank),stride_bytes=stride+[0]*(4-rank),layout_id=1)
def c_tensor(t):
    if not t:return '{0}'
    return '{.address=%du,.allocation_bytes=%du,.dtype=%d,.rank=%d,.shape={%s},.stride_bytes={%s},.layout_id=1}'%(t['address'],t['allocation_bytes'],t['dtype'],t['rank'],','.join(map(str,t['shape'])),','.join(map(str,t['stride_bytes'])))
def prepare(out,config,profile):
    out=Path(out);out.mkdir(parents=True,exist_ok=False)
    published=json.loads((ROOT/'docs/spec/model-pack-v1-manifest.json').read_text());pack=verify(ROOT/published['pack_path'],expected_sha256=published['sha256'])
    vectors=ROOT/config['input_t05']/'artifacts/vectors';idx=json.loads((vectors/'index.json').read_text())
    jobs=[];regions=[];unique=set();source_address=0xb4100000
    def region(name,address,data,kind):
        if (address,len(data)) in unique:return
        unique.add((address,len(data)));p=out/(name+'.bin');p.write_bytes(data)
        regions.append(dict(name=name,address=address,bytes=len(data),path=str(p.resolve()),sha256=sha(p),kind=kind))
    def array(folder,key):
        p=folder/(key+'.npy');rec=idx['files'][str(p.relative_to(vectors))];expected=rec['sha256'] if isinstance(rec,dict) else rec
        if sha(p)!=expected:raise ValueError('T05 array hash')
        return np.load(p,allow_pickle=False)
    def add(family,m,n,mode=0,source='T05',name=None):
        nonlocal source_address
        name=name or '%s-m%d-n%d-mode%d'%(family,m,n,mode)
        tensor_name='lm_head.weight' if family=='head' else 'model.layers.0.%s.%s_proj.weight'%('mlp' if family in ('gate','up','down') else 'self_attn',family)
        w=pack.rows(tensor_name,0,n);sw=pack.rows(tensor_name+'.scale',0,n);bn=tensor_name[:-6]+'bias';bias=pack.rows(bn,0,n) if bn in pack.entries else None
        a={}
        for key in ('x','aq','sa','y'):a[key]=array(vectors/('%s-m%d'%(family,m)),key)
        if source=='T11':
            manifest=json.loads((ROOT/'tests/cocotb/fixtures/golden/manifest.json').read_text());rec=next(c for c in manifest['cases'] if c['kind']=='linear');p=ROOT/'tests/cocotb/fixtures/golden'/rec['path']
            if sha(p)!=rec['sha256']:raise ValueError('T11 fixture hash')
            with np.load(p,allow_pickle=False) as f:a={k:f[k] for k in ('x','aq','sa','y')}
        k=w.shape[1];g=k//64;scale=np.max(np.abs(a['x'].reshape(m,g,64)),axis=2)/np.float32(127)
        scale=np.where((scale!=0)&(scale<np.float32(2**-126)),np.float32(2**-126),scale).astype('<f4')
        with np.errstate(divide='ignore',invalid='ignore'):quant=np.rint(np.where(scale[:,:,None]!=0,a['x'].reshape(m,g,64)/scale[:,:,None],0)).clip(-127,127).astype('i1').reshape(m,k)
        if not np.array_equal(quant,a['aq']) or not np.array_equal(scale,a['sa']):raise ValueError('independent quantization vs producer')
        expected=oracle(quant,scale,w,sw,bias)
        if not np.array_equal(expected['y'],a['y'][:,:n]):raise ValueError('independent output vs '+source)
        addresses=[]
        for suffix,data in [('',w),('.scale',sw),('bias',bias)]:
            if data is None:addresses.append(0);continue
            key=bn if suffix=='bias' else tensor_name+suffix;entry=pack.entries[key];address=entry['soc_address']
            region(key.replace('.','-')+'-n'+str(n),address,data.tobytes(),'immutable_model');addresses.append(address)
        region(name+'-input-source',source_address,a['x'].tobytes(),'cpu_private_input')
        wa,sca,ba=addresses
        j=dict(a=tensor(0xac010000,m*k*4,2,[m,k]),wq=tensor(wa,n*k,1,[n,k]),sw=tensor(sca,n*g*4,2,[n,g]),bias=tensor(ba,n*4,2,[n]) if ba else {},y=tensor(0xac100000,m*n*4,2,[m,n]),group_size=64)
        gp=out/(name+'.npz');np.savez(gp,aq=quant,sa=scale,y=expected['y'])
        # Only sentinel initialization, never golden output preload.
        jobs.append(dict(name=name,job=j,input_source=source_address,mode=mode,status=-11 if mode in (3,4) else -7 if mode==5 else -8 if mode in (6,7) else 0,
            timeout=500000 if mode==5 else 900000000 if profile=='head' else 8000000,expected_path=str(gp.resolve()),expected_sha256=sha(gp),source=source,pack_sha256=pack.summary['sha256'],tensor=tensor_name))
        source_address=(source_address+m*k*4+63)//64*64
    if profile=='head':add('head',1,151936)
    elif profile=='smoke':add('q',1,4);add('k',4,4);add('v',8,4)
    else:
        for fam,m in [('q',1),('k',4),('v',8),('o',1),('gate',1),('up',1),('down',1)]:add(fam,m,16)
        add('q',4,16,source='T11',name='t11-q-m4')
        for mode in (1,2,3,4,5,6,7):
            add('q',1,4,mode);add('q',1,4,name='recovery-after-mode%d'%mode)
        add('q',1,129,name='n129-tail')
    (out/'data.plan').write_text(''.join('B %x %x %s\n'%(r['address'],r['bytes'],r['path']) for r in regions))
    # Place guards immediately around shared buffers. CPU initializes Y itself.
    guards=[0xac010000-16,0xac010000+8*4864*4,0xac000000-16,0xac000000+8*4864,0xac00a000-16,0xac00a000+8*76*4,0xac100000-16,0xac100000+max(j['job']['y']['allocation_bytes'] for j in jobs)]
    for i,address in enumerate(guards):region('guard%d'%i,address,b'\xa5'*16,'guard')
    (out/'data.plan').write_text(''.join('B %x %x %s\n'%(r['address'],r['bytes'],r['path']) for r in regions))
    threshold=json.loads((ROOT/'configs/t05-thresholds.json').read_text())['operators']['linear']
    golden=dict(producer='INDEPENDENT_ORACLE_PINNED_T05_T11',jobs=jobs,thresholds=threshold,thresholds_sha256=sha(ROOT/'configs/t05-thresholds.json'))
    (out/'golden.json').write_text(json.dumps(golden,indent=2)+'\n')
    fixture=dict(profile=profile,test_mode='PRELOAD',numeric_version='w8a8-g64-fp32-v1',group_size=64,layout_id=4097,logical_layout=1,dtype='W8A8/F32',endianness='little',regions=regions,guards=guards,pack_sha256=published['sha256'],seal='Verified T10 immutable model payload; bridge and guard reject model writes',generator_sha256=sha(__file__))
    (out/'fixture.json').write_text(json.dumps(fixture,indent=2)+'\n')
    header='#include "linear_api.h"\nstruct fixture_job { nx_linear job; uint32_t input_source,mode; uint64_t timeout; };\n#define FIXTURE_JOBS %d\nstatic const struct fixture_job fixture_jobs[]={\n'%len(jobs)
    for row in jobs:
        j=row['job'];header+='{.job={'+','.join('.%s=%s'%(k,c_tensor(j[k])) for k in ('a','wq','sw','bias','y'))+',.group_size=64},.input_source=%du,.mode=%d,.timeout=%du},\n'%(row['input_source'],row['mode'],row['timeout'])
    (out/'fixture_jobs.h').write_text(header+'};\n')
    return fixture
