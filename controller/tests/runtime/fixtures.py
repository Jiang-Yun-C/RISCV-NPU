#!/usr/bin/env python3
"""Generate independent text/control/small-network and sealed T11 tile fixtures."""
import hashlib
import json
from pathlib import Path
import sys
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/'scripts'),str(Path(__file__).parent)]
from evidence import sha256,write_json
from model_tools import numeric_v1 as num
from tokenizer_reference import official,cases

def generate(dest):
    dest=Path(dest);dest.mkdir(parents=True,exist_ok=True)
    reference,hf=official();texts=cases()
    messages=[{'role':'system','content':'你是控制助手。'},{'role':'user','content':'如果温度高于28度，打开风扇。'}]
    template=hf.apply_chat_template(messages,tokenize=False,add_generation_prompt=True)
    texts.append(template)
    records=[];header=['/* Input bytes only; no expected output is linked into firmware. */',f'#define TEXT_CASES {len(texts)}']
    for i,text in enumerate(texts):
        b=text.encode();header.append(f'static const unsigned char text_{i}[]={{'+','.join(map(str,[*b,0]))+'};')
        ids=reference.encode(text,add_special_tokens=False).ids
        records.append({'text':text,'hex':b.hex(),'ids':ids,'decode':reference.decode(ids,skip_special_tokens=False)})
    header.append('static const unsigned char *text_cases[]={'+','.join(f'text_{i}' for i in range(len(texts)))+'};')
    header.append('static const unsigned text_sizes[]={'+','.join(str(len(t.encode())) for t in texts)+'};')
    overhead=len(hf.apply_chat_template([{'role':'user','content':'1'}],tokenize=True,add_generation_prompt=True))-1
    boundary='1'*(512-overhead)
    assert len(hf.apply_chat_template([{'role':'user','content':boundary}],tokenize=True,add_generation_prompt=True))==512
    assert len(hf.apply_chat_template([{'role':'user','content':boundary+'1'}],tokenize=True,add_generation_prompt=True))==513
    header.append('static const char text_boundary[]='+json.dumps(boundary)+';')
    (dest/'text_inputs.h').write_text('\n'.join(header)+'\n')
    gold={'schema_version':1,'texts':records,'template':template,
          'template_ids':hf.apply_chat_template(messages,tokenize=True,add_generation_prompt=True),
          'control':{str(i):int(i in (2,5)) for i in range(1,31)},
          'thresholds_sha256':sha256(ROOT/'configs/t05-thresholds.json')}
    # Model is deliberately reduced only for control/port verification. Full
    # model numerical/quality evidence remains T11 and full CPU commands use it.
    rng=np.random.default_rng(120912);data=bytearray();meta={};arrays={}
    def add(name,a):
        a=np.ascontiguousarray(a);data.extend(bytes((-len(data))%16));off=len(data);data.extend(a.tobytes())
        arrays[name]=a;meta[name]={'offset':off,'shape':list(a.shape),'dtype':str(a.dtype)}
        return off
    for name,n,k in [(name,64,64) for name in ('embed','q','k','v','o','gate','up','down')]:
        q,sc=num.quantize(rng.normal(0,.03,(n,k)).astype('f4'))
        add(name+'.q',q);add(name+'.s',sc)
        if name in ('q','k','v'):add(name+'.bias',rng.normal(0,.01,n).astype('f4'))
    for name in ('norm1','norm2','norm'):add(name,np.ones(64,'f4')+rng.normal(0,.02,64).astype('f4'))
    rope=json.loads((ROOT/'configs/t11-reference.json').read_text())['canonical_rope']
    assert sha256(ROOT/rope['path'])==rope['sha256']
    with np.load(ROOT/rope['path']) as f:inv=f['inv_freq'].copy()
    add('inv',inv)
    small={'config':{'hidden':64,'intermediate':64,'vocab':64,'layers':1,'q_heads':1,'kv_heads':1},'steps':[],'ids':[1,7,19]}
    kcache=[];vcache=[]
    def linear(x,name):return num.linear_quantized(*num.quantize(x),arrays[name+'.q'],arrays[name+'.s'],arrays.get(name+'.bias'))[0]
    def rotate(x,past):
        angle=np.float32(past)*inv;co=np.cos(angle.astype('f8')).astype('f4');si=np.sin(angle.astype('f8')).astype('f4')
        a=x[..., :32].copy();b=x[...,32:].copy();return np.concatenate((a*co+(-b)*si,b*co+a*si),axis=-1)
    for past,token in enumerate(small['ids']):
        x=num.dequantize(arrays['embed.q'][token:token+1],arrays['embed.s'][token:token+1]);z=num.rmsnorm(x,arrays['norm1'])
        q=rotate(linear(z,'q').reshape(1,64),past);k=rotate(linear(z,'k').reshape(1,64),past);v=linear(z,'v').reshape(1,64)
        kcache.append(k);vcache.append(v);ks=np.stack(kcache);vs=np.stack(vcache)
        scores=num.tree_sum(q[:,None,:]*ks.transpose(1,0,2))*np.float32(.125)
        exp=np.exp((scores-scores.max(axis=-1,keepdims=True)).astype('f8')).astype('f4');prob=exp/num.tree_sum(exp,keepdims=True)
        attn=num.tree_sum(prob[:,:,None]*vs.transpose(1,0,2),axis=1).reshape(1,64)
        x=x+linear(attn,'o');z=num.rmsnorm(x,arrays['norm2']);gate=linear(z,'gate');up=linear(z,'up')
        e=np.exp(-np.abs(gate.astype('f8'))).astype('f4');sig=np.where(gate>=0,np.float32(1)/(np.float32(1)+e),e/(np.float32(1)+e))
        x=x+linear((gate*sig)*up,'down');y=linear(num.rmsnorm(x,arrays['norm']),'embed')
        small['steps'].append({'logits':y.ravel().tolist(),'k':k.ravel().tolist(),'v':v.ravel().tolist(),'argmax':int(y.argmax())})
    (dest/'small.bin').write_bytes(data);write_json(dest/'small-layout.json',meta)
    h=['static void load_small(nx_weights *w,const unsigned char *base) {','memset(w,0,sizeof(*w));']
    for name in ('embed','q','k','v','o','gate','up','down'):
        member='w->embedding' if name=='embed' else 'w->layer[0].'+name
        n,k=meta[name+'.q']['shape'];b='NULL' if name+'.bias' not in meta else f'(const float *)(base+{meta[name+".bias"]["offset"]})'
        h.append(f'{member}=(nx_matrix){{(const int8_t *)(base+{meta[name+".q"]["offset"]}),(const float *)(base+{meta[name+".s"]["offset"]}),{b},{n},{k}}};')
    for name,member in [('norm1','layer[0].norm1'),('norm2','layer[0].norm2'),('norm','norm'),('inv','inv_freq')]:h.append(f'w->{member}=(const float *)(base+{meta[name]["offset"]});')
    h.append('}');(dest/'small_weights.h').write_text('\n'.join(h)+'\n');gold['small']=small
    # Consume an actual T11 golden tile, without re-deriving its expected answer.
    m=json.loads((ROOT/'tests/cocotb/fixtures/golden/manifest.json').read_text())
    rec=next(c for c in m['cases'] if 'linear-q' in c['path']);path=ROOT/'tests/cocotb/fixtures/golden'/rec['path']
    assert sha256(path)==rec['sha256'],'T11 fixture identity'
    with np.load(path) as f:fx={k:f[k] for k in f.files}
    pack=json.loads((ROOT/'docs/spec/model-pack-v1-manifest.json').read_text());entries={e['name']:e for e in pack['directory']}
    data=bytearray();meta={};arrays={}
    add('x',fx['x'][0:1]);stem='model.layers.0.self_attn.q_proj.weight'
    with (ROOT/pack['pack_path']).open('rb') as stream:
        for suffix,key,shape,dt in [('', 'q',(4,896),'i1'),('.scale','s',(4,14),'<f4')]:
            e=entries[stem+suffix];stream.seek(e['offset']);add(key,np.frombuffer(stream.read(int(np.prod(shape))*np.dtype(dt).itemsize),dtype=dt).reshape(shape).copy())
        e=entries[stem.replace('weight','bias')];stream.seek(e['offset']);add('bias',np.frombuffer(stream.read(16),dtype='<f4').copy())
    (dest/'t11-tile.bin').write_bytes(data)
    h=[f'#define TILE_{k.upper()} {v["offset"]}u' for k,v in meta.items()]
    (dest/'t11_tile.h').write_text('\n'.join(h)+'\n')
    gold['t11_tile']={'y':fx['y'][0,:4].tolist(),'norm':num.rmsnorm(fx['x'][0:1],np.ones(896,'f4')).ravel().tolist(),'dots':fx['dots'][:,0,:4].ravel().tolist(),
                     'aq':fx['aq'][0].tolist(),'sa_bits':fx['sa'][0].view('u4').tolist(),
                     'fixture_path':str(path.relative_to(ROOT)),'fixture_sha256':sha256(path),
                     'pack_sha256':pack['sha256']}
    write_json(dest/'golden.json',gold)
    write_json(dest/'manifest.json',{'producer':'T12','test_mode':'PRELOAD','endianness':'little',
        'numeric_version':'w8a8-g64-fp32-v1','layout':'contiguous, 16B aligned, explicit JSON offsets',
        'files':{p.name:sha256(p) for p in dest.iterdir() if p.is_file() and p.name!='manifest.json'},
        'generator_sha256':sha256(__file__),'official_tokenizer':'original model lock, never adapted serializer'})
    return gold

if __name__=='__main__':generate(sys.argv[1])
