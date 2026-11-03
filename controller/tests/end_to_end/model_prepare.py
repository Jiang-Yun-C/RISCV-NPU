"""T19: immutable T11 block, independent reduced 14:2 graph, no DUT data."""
import json,sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/'scripts'),str(ROOT/'tests/reference')]
from evidence import sha256,write_json
from model_tools import numeric_v1 as num
from model_tools.verify_pack import verify
from fixture_io import load
NAMES=['embedding','input','norm1','q','k','v','qr','kr','attn','o','res1','norm2','gate','up','act','down','output','final_norm','logits','cache_k','cache_v']
def group(step,layer,name):return 1000+step*100+(layer+1)*22+NAMES.index(name)

class MiniOracle:
    """Same frozen tree/FP32 semantics; no reference C or backend imports."""
    def __init__(self,arrays):self.a=arrays;self.reset()
    def reset(self):self.k=[[] for _ in range(2)];self.v=[[] for _ in range(2)];self.length=0
    def forward(self,token):
        a=self.a;t={};jobs=[];past=self.length
        def emit(l,n,x):t[(l,n)]=np.asarray(x,dtype='<f4').reshape(-1).copy()
        def lin(x,key):
            aq,sa=num.quantize(x);y,dots=num.linear_quantized(aq,sa,a[key+'.q'][:,:x.shape[1]],a[key+'.s'],a.get(key+'.bias'))
            jobs.append(dict(key=key,x=x.copy(),aq=aq,sa=sa,y=y,dots=dots));return y
        x=num.dequantize(a['embed.q'][token:token+1],a['embed.s'][token:token+1])[:,:112];emit(-1,'embedding',x)
        def rotate(x):
            angle=np.float32(past)*a['inv'];angle=np.concatenate([angle,angle])[None,None]
            return x*np.cos(angle.astype('f8')).astype('f4')+np.concatenate([-x[:,:,4:],x[:,:,:4]],axis=-1)*np.sin(angle.astype('f8')).astype('f4')
        for l in range(2):
            stem=f'l{l}.';emit(l,'input',x);z=num.rmsnorm(x,a[stem+'norm1']);emit(l,'norm1',z)
            q=lin(z,stem+'q').reshape(1,14,8);k=lin(z,stem+'k').reshape(1,2,8);v=lin(z,stem+'v').reshape(1,2,8)
            for n,p in [('q',q),('k',k),('v',v)]:emit(l,n,p)
            q=rotate(q);k=rotate(k);emit(l,'qr',q);emit(l,'kr',k)
            self.k[l].append(k[0]);self.v[l].append(v[0]);ks=np.stack(self.k[l]);vs=np.stack(self.v[l])
            # Physical cache remains [T,2,D]; index each Q head's KV owner.
            attn=[]
            for h in range(14):
                scores=num.tree_sum(q[0,h]*ks[:,h//7])*np.float32(1/np.sqrt(np.float32(8)))
                e=np.exp((scores-scores.max()).astype('f8')).astype('f4');prob=e/num.tree_sum(e)
                attn.append(num.tree_sum(prob[:,None]*vs[:,h//7],axis=0))
            attn=np.asarray(attn,'f4').reshape(1,112);emit(l,'attn',attn)
            o=lin(attn,stem+'o');emit(l,'o',o);x=x+o;emit(l,'res1',x)
            z=num.rmsnorm(x,a[stem+'norm2']);emit(l,'norm2',z);gate=lin(z,stem+'gate');up=lin(z,stem+'up')
            emit(l,'gate',gate);emit(l,'up',up);e=np.exp(-np.abs(gate).astype('f8')).astype('f4');sig=np.where(gate>=0,np.float32(1)/(np.float32(1)+e),e/(np.float32(1)+e));act=(gate*sig)*up;emit(l,'act',act)
            down=lin(act,stem+'down');emit(l,'down',down);x=x+down;emit(l,'output',x)
        z=num.rmsnorm(x,a['norm']);emit(24,'final_norm',z);y=lin(z,'embed');emit(24,'logits',y)
        self.length+=1
        for l in range(2):emit(l,'cache_k',np.stack(self.k[l]));emit(l,'cache_v',np.stack(self.v[l]))
        return t,jobs

def prepare(out,config,profile):
    out=Path(out);out.mkdir(parents=True,exist_ok=False);regions=[];arrays={};addresses={};cursor=0x80000000
    published=json.loads((ROOT/'docs/spec/model-pack-v1-manifest.json').read_text())
    fm=ROOT/'tests/cocotb/fixtures/golden/manifest.json';manifest=load(fm)
    records=[];jobs=[];gold={};specs={};header=['#include "nx_reference.h"','static void fixture_weights(nx_weights *w) {','memset(w,0,sizeof(*w));']
    def add(key,a,address=None):
        nonlocal cursor
        a=np.ascontiguousarray(a);address=address if address is not None else cursor;cursor=(address+a.nbytes+63)//64*64
        p=out/(key.replace('.','-')+'.bin');p.write_bytes(a.tobytes());arrays[key]=a;addresses[key]=address
        regions.append(dict(name=key,address=address,bytes=a.nbytes,path=str(p.resolve()),sha256=sha256(p),kind='immutable_model',dtype=a.dtype.str,shape=list(a.shape)))
        return address
    def matrix(key,member,n=None,k=None):
        n,k=arrays[key+'.q'].shape if n is None else (n,k)
        b='0' if key+'.bias' not in addresses else '(const float *)%du'%addresses[key+'.bias']
        header.append('%s=(nx_matrix){(const int8_t *)%du,(const float *)%du,%s,%d,%d};'%(member,addresses[key+'.q'],addresses[key+'.s'],b,n,k))
    def expect(step,trace,opjobs):
        for (l,n),a in trace.items():
            g=group(step,l,n);key=str(g);gold[key]=a;specs[key]=dict(step=step,layer=l,stage=n,executor='CORAL_RVV_RTL' if n in ('q','k','v','o','gate','up','down','logits') else 'CPU_C_ON_VEXRISCV_RTL',shape=list(a.shape))
        for j in opjobs:
            physical=(j['x'].shape[1]+63)//64*64
            rec=dict(step=step,key=j['key'],n=j['y'].shape[1],k=physical,logical_k=j['x'].shape[1],w_address=addresses[j['key']+'.q'],sw_address=addresses[j['key']+'.s'])
            for key in ('x','aq','sa','y','dots'):
                value=j[key]
                if key in ('x','aq'):value=np.pad(value,((0,0),(0,physical-value.shape[1])))
                gold['job%d.%s'%(len(jobs),key)]=value
            jobs.append(rec)
    if profile=='block':
        pack=verify(ROOT/published['pack_path'],expected_sha256=published['sha256'])
        def physical(key,name,rows=None):
            e=pack.entries[name];a=pack.rows(name);a=a if rows is None else a[:rows];return add(key,a,e['soc_address'])
        physical('embed.q','model.embed_tokens.weight',1);physical('embed.s','model.embed_tokens.weight.scale',1);matrix('embed','w->embedding',151936,896)
        for key in ('q','k','v','o','gate','up','down'):
            stem='model.layers.0.'+('mlp.' if key in ('gate','up','down') else 'self_attn.')+key+'_proj.'
            for suf,name in [('.q','weight'),('.s','weight.scale')]:physical('l0.'+key+suf,stem+name)
            if key in ('q','k','v'):physical('l0.'+key+'.bias',stem+'bias')
            matrix('l0.'+key,'w->layer[0].'+key)
        for key,name,member in [('l0.norm1','model.layers.0.input_layernorm.weight','layer[0].norm1'),('l0.norm2','model.layers.0.post_attention_layernorm.weight','layer[0].norm2'),('norm','model.norm.weight','norm')]:physical(key,name);header.append('w->%s=(const float *)%du;'%(member,addresses[key]))
        rope=json.loads((ROOT/'configs/t11-reference.json').read_text())['canonical_rope'];p=ROOT/rope['path'];assert sha256(p)==rope['sha256']
        with np.load(p) as f:add('inv',f['inv_freq'])
        rec=next(c for c in manifest['cases'] if c['kind']=='block-kv-logits' and c['past']==0)
        with np.load(fm.parent/rec['path']) as f:
            trace={(int(k.split('.')[0][5:]),k.split('.')[1]):f[k].reshape(-1) for k in f.files if k.startswith('layer0.') or k=='layer-1.embedding'}
            trace[0,'cache_k']=f['cache'][0,0].reshape(-1);trace[0,'cache_v']=f['cache'][0,1].reshape(-1)
        for key in ('q','k','v','o','gate','up','down'):
            x=trace[0,{'q':'norm1','k':'norm1','v':'norm1','o':'attn','gate':'norm2','up':'norm2','down':'act'}[key]].reshape(1,-1);aq,sa=num.quantize(x)
            y,dots=num.linear_quantized(aq,sa,arrays['l0.'+key+'.q'],arrays['l0.'+key+'.s'],arrays.get('l0.'+key+'.bias'))
            assert np.array_equal(y.ravel(),trace[0,key]),'T11 operator identity'
            records.append(dict(key='l0.'+key,x=x,aq=aq,sa=sa,y=y,dots=dots))
        expect(0,trace,records);tokens=[0];layers=1;kv=128;capacity=640;vocab=151936;steps=1
        provenance=dict(kind='T11_EXACT_PUBLISHED_BLOCK',path=str((fm.parent/rec['path']).relative_to(ROOT)),sha256=rec['sha256'])
    else:
        rng=np.random.default_rng(20261008)
        for key,n,k in [('embed',129,112)]+[(f'l{l}.{name}',n,k) for l in range(2) for name,n,k in [('q',112,112),('k',16,112),('v',16,112),('o',112,112),('gate',128,112),('up',128,112),('down',112,128)]]:
            q,s=num.quantize(rng.normal(0,.035,(n,k)).astype('f4'));add(key+'.q',np.pad(q,((0,0),(0,(-k)%64))));add(key+'.s',s)
            if key.rsplit('.',1)[-1] in ('q','k','v'):add(key+'.bias',rng.normal(0,.01,n).astype('f4'))
            member='w->embedding' if key=='embed' else 'w->layer[%s].%s'%(key[1],key.split('.')[1]);matrix(key,member,n,k)
        for l in range(2):
            for n in ('norm1','norm2'):add(f'l{l}.{n}',rng.uniform(.9,1.1,112).astype('f4'));header.append('w->layer[%d].%s=(const float *)%du;'%(l,n,addresses[f'l{l}.{n}']))
        add('norm',np.ones(112,'f4'));header.append('w->norm=(const float *)%du;'%addresses['norm'])
        add('inv',(np.float32(1)/np.power(np.float32(1000000),np.arange(0,8,2,dtype='f4')/np.float32(8))).astype('f4'))
        tokens=[0,127] if profile=='smoke' else [0,127,126,17,128,1,64,7,0]
        oracle=MiniOracle(arrays)
        for step,token in enumerate(tokens):t,j=oracle.forward(token);expect(step,t,j)
        if profile!='smoke':
            oracle.reset()
            for step,token in enumerate([7,0],start=len(tokens)):t,j=oracle.forward(token);expect(step,t,j)
        layers=2;kv=16;capacity=9;vocab=129;steps=len(tokens)+(2 if profile!='smoke' else 0)
        provenance=dict(kind='INDEPENDENT_T11_NUMERIC_GRAPH_REDUCED_GEOMETRY',oracle_path='tests/end_to_end/model_prepare.py',oracle_sha256=sha256(__file__),seed=20261008)
    header.append('w->inv_freq=(const float *)%du;}'%addresses['inv'])
    header+=['#define FIXTURE_LAYERS %d'%layers,'#define FIXTURE_KV %d'%kv,'#define FIXTURE_CAPACITY %d'%capacity,'#define FIXTURE_VOCAB %d'%vocab,'#define FIXTURE_TOKENS %d'%len(tokens),'static const int32_t tokens[]={%s};'%','.join(map(str,tokens))]
    (out/'model_weights.h').write_text('\n'.join(header)+'\n')
    np.savez(out/'golden.npz',**gold)
    write_json(out/'golden.json',dict(specs=specs,jobs=jobs,steps=steps,provenance=provenance,arrays_sha256=sha256(out/'golden.npz'),thresholds_sha256=sha256(ROOT/'configs/t05-thresholds.json')))
    fixture=dict(profile=profile,test_mode='PRELOAD',layers=layers,kv=kv,capacity=capacity,vocab=vocab,tokens=tokens,steps=steps,regions=regions,guards=[0xac010000-16,0xac010000+4864*4,0xac100000-16,0xac100000+4864*4],pack_sha256=published['sha256'],t11_manifest_sha256=sha256(fm),provenance=provenance)
    for i,a in enumerate(fixture['guards']):
        p=out/f'guard{i}.bin';p.write_bytes(b'\xa5'*16);regions.append(dict(name=p.stem,address=a,bytes=16,path=str(p.resolve()),sha256=sha256(p),kind='guard'))
    write_json(out/'fixture.json',fixture);(out/'data.plan').write_text(''.join('B %x %x %s\n'%(r['address'],r['bytes'],r['path']) for r in regions));return fixture
