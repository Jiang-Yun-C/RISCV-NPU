"""Independent Torch CPU checker. Does not import the NumPy numeric oracle.

FP64 integer GEMM is exact for every 64-element dot here (< 2**20).
FP32 recovery is separately replayed; model/tokenizer identity is checked by runner.
"""
import argparse
import json
from pathlib import Path
import sys
import numpy as np
import torch
from safetensors import safe_open

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
from evidence import sha256, write_json

torch.set_num_threads(1)
torch.use_deterministic_algorithms(True)
THRESHOLDS=json.loads((ROOT/'configs/t05-thresholds.json').read_text())


def tensor(x):
    return torch.from_numpy(np.array(x,copy=True))


def quant(x):
    if x.ndim!=2 or min(x.shape)<=0 or not torch.isfinite(x).all(): raise ValueError('invalid quant input')
    r,k=x.shape; g=(k+63)//64
    blocks=torch.nn.functional.pad(x,(0,g*64-k)).reshape(r,g,64)
    peak=blocks.abs().amax(-1)
    scale=(peak/127).clamp_min(torch.finfo(torch.float32).tiny)
    scale[peak==0]=0
    divisor=scale.clone(); divisor[divisor==0]=1
    q=torch.round(blocks/divisor[...,None]).clamp(-127,127).to(torch.int8)
    return q.reshape(r,-1)[:,:k],scale


def linear(aq,sa,wq,sw,bias=None):
    out=torch.zeros((aq.shape[0],wq.shape[0]),dtype=torch.float32); ints=[]
    for g in range(sa.shape[1]):
        d=aq[:,g*64:(g+1)*64].double()@wq[:,g*64:(g+1)*64].double().T
        assert torch.equal(d,d.round()) and d.abs().max()<=64*127*127
        ints.append(d.to(torch.int32))
        restored=d.float()*sa[:,g,None]
        out=out+restored*sw[None,:,g]
    if bias is not None: out=out+bias
    return out,torch.stack(ints)


def metric(actual,expected,limit):
    a=np.asarray(actual,dtype=np.float64); b=np.asarray(expected,dtype=np.float64)
    if a.shape!=b.shape or a.size==0 or not np.isfinite(a).all() or not np.isfinite(b).all():
        raise ValueError('invalid shape/nonfinite comparison')
    delta=np.abs(a-b); rms=float(np.sqrt(np.mean(delta*delta)))
    nrmse=rms/max(float(np.sqrt(np.mean(b*b))),1e-12)
    violations=int(np.count_nonzero(delta>limit['atol']+limit['rtol']*np.abs(b)))
    result={'max_abs':float(delta.max()),'max_relative':float((delta/np.maximum(np.abs(b),1e-12)).max()),
            'rmse':rms,'nrmse':nrmse,'elementwise_violations':violations}
    if violations or nrmse>limit['nrmse']: raise AssertionError(json.dumps(result))
    return result


def exact(a,b):
    assert np.asarray(a).dtype==np.asarray(b).dtype and np.asarray(a).shape==np.asarray(b).shape and np.array_equal(a,b),'integer/dtype mismatch'


def small_check(path):
    with np.load(path,allow_pickle=False) as s:
        # Scalar Python round and unbounded ints, independent of either GEMM.
        for fp,q,sc in [('x','aq','sa'),('w','wq','sw')]:
            for row in range(s[fp].shape[0]):
                for g in range(s[sc].shape[1]):
                    vals=s[fp][row,g*64:(g+1)*64]
                    peak=max(abs(float(v)) for v in vals)
                    scale=np.float32(0 if peak==0 else max(np.float32(peak)/np.float32(127),np.finfo(np.float32).tiny))
                    assert scale.tobytes()==s[sc][row,g].tobytes(),'scalar scale mismatch'
                    for i,v in enumerate(vals):
                        q=0 if scale==0 else max(-127,min(127,round(float(np.float32(v/scale)))))
                        assert q==int(s[qname(fp)][row,g*64+i]),'scalar quant mismatch'
        d=np.zeros(s['dots'].shape,dtype=np.int32)
        for g in range(d.shape[0]):
            for m in range(d.shape[1]):
                for n in range(d.shape[2]):
                    d[g,m,n]=sum(int(s['aq'][m,i])*int(s['wq'][n,i]) for i in range(g*64,min((g+1)*64,s['aq'].shape[1])))
        exact(d,s['dots'])
        expected,td=linear(*[tensor(s[k]) for k in ['aq','sa','wq','sw','bias']])
        exact(td.numpy(),d)
        return metric(s['y'],expected.numpy(),THRESHOLDS['operators']['linear'])


def qname(name): return 'aq' if name=='x' else 'wq'


def norm(x,gamma): return (x*torch.rsqrt((x*x).mean(-1,keepdim=True)+1e-6))*gamma


def strict_sum(x,dim=-1,keepdim=False):
    dim %= x.ndim
    y=x.movedim(dim,-1); n=y.shape[-1]; size=2**((n-1).bit_length())
    y=torch.nn.functional.pad(y,(0,size-n))
    while y.shape[-1]>1:
        pairs=y.reshape(*y.shape[:-1],-1,2)
        y=pairs[...,0]+pairs[...,1]
    y=y.squeeze(-1)
    return y.unsqueeze(dim) if keepdim else y


def strict_norm(x,gamma):
    return (x*(1/torch.sqrt(strict_sum(x*x,keepdim=True)/x.shape[-1]+1e-6)))*gamma


def strict_attention(q,k,v):
    q=q.permute(1,0,2); k=k.repeat_interleave(7,dim=1).permute(1,0,2); v=v.repeat_interleave(7,dim=1).permute(1,0,2)
    scores=strict_sum(q[:,:,None,:]*k[:,None,:,:])*.125
    mask=torch.arange(k.shape[1])[None,:]<=torch.arange(q.shape[1])[:,None]
    scores=scores.masked_fill(~mask[None,...],float('-inf'))
    e=(scores-scores.amax(-1,keepdim=True)).exp(); prob=e/strict_sum(e,keepdim=True)
    return strict_sum(prob[:,:,:,None]*v[:,None,:,:],dim=2).permute(1,0,2).reshape(-1,896)


def strict_swiglu(gate,up):
    e=(-gate.abs()).exp(); sigmoid=torch.where(gate>=0,1/(1+e),e/(1+e))
    return (gate*sigmoid)*up


def rotate(x,positions,inv=None):
    if inv is None: inv=1/(torch.tensor(1e6)**(torch.arange(0,64,2).float()/64))
    angle=positions.float()[:,None]*inv[None,:]
    angle=torch.cat((angle,angle),dim=-1)[:,None,:]
    return x*angle.cos()+torch.cat((-x[...,32:],x[...,:32]),-1)*angle.sin()


def attn(q,k,v,past=0):
    kr=k.repeat_interleave(7,dim=1).permute(1,0,2)
    vr=v.repeat_interleave(7,dim=1).permute(1,0,2)
    scores=(q.permute(1,0,2)@kr.transpose(1,2))*.125
    mask=torch.arange(k.shape[0])[None,:]<=past+torch.arange(q.shape[0])[:,None]
    prob=torch.softmax(scores.masked_fill(~mask[None,...],float('-inf')),-1)
    return (prob@vr).permute(1,0,2).reshape(-1,896),prob,scores


def check(out,report):
    idx=json.loads((out/'index.json').read_text())
    assert idx['numeric_version']=='w8a8-g64-fp32-v1'
    assert idx['thresholds_sha256']==sha256(ROOT/'configs/t05-thresholds.json')
    assert idx['model_lock_sha256']==sha256(ROOT/'docs/spec/application-v2-model-lock.json')
    actual={str(p.relative_to(out)) for p in out.rglob('*') if p.is_file() and p.name!='index.json'}
    assert actual==set(idx['files']),'missing/extra vector files'
    for name,meta in idx['files'].items():
        assert (out/name).stat().st_size==meta['bytes'] and sha256(out/name)==meta['sha256'],name
    results={'small':small_check(out/'small.npz'),'linear':[],'operators':{},'cumulative':{},'integer_elements_checked':0,'quantized_weight_elements_checked':0}
    def compare(name,a,b,kind,category='operators'):
        try: results[category][name]=metric(a,b,THRESHOLDS[category][kind])
        except (ValueError,AssertionError) as e: raise AssertionError(name+': '+str(e)) from e
    lock=json.loads((ROOT/'docs/spec/application-v2-model-lock.json').read_text())
    with safe_open(ROOT/lock['local_path']/'model.safetensors',framework='numpy') as ckpt:
        for key,w in idx['weights'].items():
            q=np.load(out/w['q'],mmap_mode='r'); s=np.load(out/w['scale'],mmap_mode='r')
            assert q.dtype==np.int8 and s.dtype==np.float32 and list(q.shape)==w['shape']
            source=ckpt.get_slice(w['tensor'])
            for lo in range(0,q.shape[0],256):
                tq,ts=quant(tensor(source[lo:min(q.shape[0],lo+256),:]))
                exact(q[lo:lo+256],tq.numpy()); exact(s[lo:lo+256].view(np.uint32),ts.numpy().view(np.uint32))
                results['quantized_weight_elements_checked']+=int(tq.numel())
            if w['bias']:
                exact(np.load(out/w['bias']),ckpt.get_tensor(w['tensor'].replace('.weight','.bias')))
        for case in idx['cases']:
            c=out/case['path']; w=idx['weights'][case['weight']]
            x=tensor(np.load(c/'x.npy')); aq,sa=quant(x)
            exact(aq.numpy(),np.load(c/'aq.npy')); exact(sa.numpy().view(np.uint32),np.load(c/'sa.npy').view(np.uint32))
            q=np.load(out/w['q'],mmap_mode='r'); s=np.load(out/w['scale'],mmap_mode='r')
            b=np.load(out/w['bias']) if w['bias'] else None
            yd=np.load(c/'y.npy',mmap_mode='r'); dd=np.load(c/'dots.npy',mmap_mode='r')
            m,k,n=case['shape_MKN']; assert x.shape==(m,k) and yd.shape==(m,n) and dd.shape==((k+63)//64,m,n)
            expected=np.empty(yd.shape,dtype=np.float32)
            for lo in range(0,n,256):
                yy,d=linear(aq,sa,tensor(q[lo:lo+256]),tensor(s[lo:lo+256]),None if b is None else tensor(b[lo:lo+256]))
                exact(d.numpy(),dd[:,:,lo:lo+256]); expected[:,lo:lo+256]=yy.numpy()
                results['integer_elements_checked']+=int(d.numel())
            results['linear'].append({'case':case['path'],**metric(yd,expected,THRESHOLDS['operators']['linear'])})
            print('checked',case['path'],flush=True)
        assert {(c['weight'],c['shape_MKN'][0]) for c in idx['cases']}=={(k,m) for k in idx['weights'] for m in [1,4,8]}
        assert len(idx['cases'])==24 and idx['blocks']==['block-m1.npz','block-m4.npz','block-m8.npz']
        for name in ['input_layernorm.weight','post_attention_layernorm.weight']:
            exact(np.load(out/(name+'.npy')),ckpt.get_tensor('model.layers.0.'+name))
        exact(np.load(out/'final_norm.npy'),ckpt.get_tensor('model.norm.weight'))
    packed={}
    for key,w in idx['weights'].items():
        if key!='head': packed[key]=[tensor(np.load(out/w['q'])),tensor(np.load(out/w['scale'])),None if not w['bias'] else tensor(np.load(out/w['bias']))]
    def lin(x,key):
        aq,sa=quant(x); return linear(aq,sa,*packed[key])[0]
    gamma1=tensor(np.load(out/'input_layernorm.weight.npy')); gamma2=tensor(np.load(out/'post_attention_layernorm.weight.npy'))
    with np.load(out/'rope-positions.npz') as r: canonical_inv=tensor(r['inv_freq'])
    with np.load(out/'embedding.npz') as e:
        wh=idx['weights']['head']; ids=e['ids']
        exact(e['q'],np.load(out/wh['q'],mmap_mode='r')[ids]); exact(e['scale'],np.load(out/wh['scale'],mmap_mode='r')[ids])
        y=tensor(e['q']).float()*tensor(e['scale']).repeat_interleave(64,dim=1)
        compare('embedding',e['y'],y.numpy(),'embedding')
        embedding=e['y'].copy()
    for filename in idx['blocks']:
        with np.load(out/filename) as f:
            t={k:tensor(f[k]) for k in f.files}; tag=filename[:-4]; m=t['input'].shape[0]
            exact(f['input'],embedding[:m])
            # Isolated operator comparisons use identical captured inputs.
            compare(tag+'-norm1',norm(t['input'],gamma1).numpy(),f['norm1'],'rmsnorm')
            for key in ['q','k','v']:
                compare(tag+'-'+key,lin(t['norm1'],key).reshape(t[key].shape).numpy(),f[key],'linear')
            compare(tag+'-rope',rotate(t['q'],torch.arange(m)).numpy(),f['qr'],'rope')
            aa,pp,ss=attn(t['qr'],t['cache_k'],t['cache_v'])
            compare(tag+'-qk',ss.numpy(),f['scores'],'attention')
            compare(tag+'-attention',aa.numpy(),f['attn'],'attention')
            causal=torch.arange(m)[None,:]<=torch.arange(m)[:,None]
            isolated_prob=torch.softmax(t['scores'].masked_fill(~causal[None,...],float('-inf')),-1)
            compare(tag+'-softmax',isolated_prob.numpy(),f['prob'],'softmax')
            isolated_pv=(t['prob']@t['cache_v'].repeat_interleave(7,dim=1).permute(1,0,2)).permute(1,0,2).reshape(m,896)
            compare(tag+'-pv',isolated_pv.numpy(),f['attn'],'attention')
            compare(tag+'-o',lin(t['attn'],'o').numpy(),f['o'],'linear')
            compare(tag+'-res1',(t['input']+t['o']).numpy(),f['res1'],'residual')
            compare(tag+'-norm2',norm(t['res1'],gamma2).numpy(),f['norm2'],'rmsnorm')
            for key in ['gate','up']: compare(tag+'-'+key,lin(t['norm2'],key).numpy(),f[key],'linear')
            compare(tag+'-swiglu',(torch.nn.functional.silu(t['gate'])*t['up']).numpy(),f['act'],'swiglu')
            compare(tag+'-down',lin(t['act'],'down').numpy(),f['down'],'linear')
            compare(tag+'-res2',(t['res1']+t['down']).numpy(),f['output'],'residual')
            compare(tag+'-finalnorm',norm(t['output'],tensor(np.load(out/'final_norm.npy'))).numpy(),f['final_norm'],'rmsnorm')
            # End-to-end independent layer arithmetic, with its own dynamic quantization.
            z=strict_norm(t['input'],gamma1)
            q=rotate(lin(z,'q').reshape(m,14,64),torch.arange(m),canonical_inv)
            k=rotate(lin(z,'k').reshape(m,2,64),torch.arange(m),canonical_inv); v=lin(z,'v').reshape(m,2,64)
            z=t['input']+lin(strict_attention(q,k,v),'o'); u=strict_norm(z,gamma2)
            y=z+lin(strict_swiglu(lin(u,'gate'),lin(u,'up')),'down')
            compare(tag,y.numpy(),f['output'],'block','cumulative')
            compare(tag+'-K',k.numpy(),f['cache_k'],'kv','cumulative'); compare(tag+'-V',v.numpy(),f['cache_v'],'kv','cumulative')
    with np.load(out/'cache-chunks.npz') as c, np.load(out/'block-m8.npz') as b:
        for name in ['output','cache_k','cache_v']: compare('chunk-'+name,c[name],b[name],'block' if name=='output' else 'kv','cumulative')
    with np.load(out/'rope-positions.npz') as r:
        inv=1/(torch.tensor(1e6)**(torch.arange(0,64,2).float()/64))
        assert torch.allclose(inv,tensor(r['inv_freq']),atol=0,rtol=2e-7)
        compare('rope-absolute-positions',rotate(tensor(r['x']),tensor(r['positions']),tensor(r['inv_freq'])).numpy(),r['y'],'rope')
    results['cumulative_engine']='independent Torch CPU with canonical adjacent-pair FP32 reductions, sqrt reciprocal and stable sigmoid'
    results['status']='PASS'; results['scope']='24 full linear cases, isolated vector ops, layer 0 cumulative and cached chunks; no full-model quality/backend/RTL claim'
    write_json(report,results)


if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('vectors',type=Path); p.add_argument('--report',required=True,type=Path); a=p.parse_args()
    check(a.vectors,a.report)
