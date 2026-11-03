"""Independent NumPy numeric-v1 graph; Torch exact group dots only.

No C runtime imports or candidate values. Each FP32 integer group GEMM is exact:
every partial sum is bounded by 64*127**2 < 2**20. TF32 is disabled.
"""
import json
import hashlib
import os
from pathlib import Path
import numpy as np
os.environ['CUBLAS_WORKSPACE_CONFIG']=':4096:8'
import torch
from model_tools import numeric_v1 as num
from model_tools.verify_pack import verify
ROOT=Path(__file__).resolve().parents[2]

class Oracle:
    def __init__(self,device='cuda'):
        torch.set_num_threads(4);torch.backends.cuda.matmul.allow_tf32=False
        torch.use_deterministic_algorithms(True)
        self.device=device
        m=json.loads((ROOT/'docs/spec/model-pack-v1-manifest.json').read_text())
        self.pack=verify(ROOT/m['pack_path'],expected_sha256=m['sha256'])
        self.arrays={};self.w={};self.sc={}
        for name,e in self.pack.entries.items():
            if e['kind']==4 or name.startswith('lm_head'):continue
            a=self.pack.rows(name);self.arrays[name]=a
            if e['kind']==1:
                n,k=a.shape
                self.w[name]=torch.tensor(a.copy(),device=device,dtype=torch.float32).reshape(n,k//64,64).permute(1,2,0).contiguous()
                self.sc[name]=torch.tensor(self.pack.rows(name+'.scale').copy(),device=device)
        spec=json.loads((ROOT/'configs/t11-reference.json').read_text())['canonical_rope']
        path=ROOT/spec['path'];assert hashlib.sha256(path.read_bytes()).hexdigest()==spec['sha256']
        with np.load(path) as f:self.inv=f['inv_freq'].copy()
        self.reset()
    def reset(self):self.k=[None]*24;self.v=[None]*24;self.length=0
    def linear(self,x,name,details=False):
        aq,sa=num.quantize(x);m,k=aq.shape
        a=torch.tensor(aq,device=self.device,dtype=torch.float32).reshape(m,k//64,64).permute(1,0,2).contiguous()
        d=torch.bmm(a,self.w[name]);sc=torch.tensor(sa,device=self.device)
        out=torch.zeros((m,self.w[name].shape[-1]),device=self.device,dtype=torch.float32)
        for g in range(k//64):out=out+(d[g]*sc[:,g,None])*self.sc[name][None,:,g]
        b=self.arrays.get(name.replace('.weight','.bias'))
        if b is not None:out=out+torch.tensor(b.copy(),device=self.device)
        y=out.cpu().numpy()
        if not np.isfinite(y).all():raise ValueError('oracle nonfinite')
        return (y,aq,sa,d.cpu().numpy().astype(np.int32)) if details else y
    def rotate(self,x,past):
        angles=np.arange(past,past+len(x),dtype=np.float32)[:,None]*self.inv
        a=np.concatenate([angles,angles],axis=1)[:,None,:]
        return x*np.cos(a.astype(np.float64)).astype(np.float32)+np.concatenate([-x[:,:,32:],x[:,:,:32]],axis=-1)*np.sin(a.astype(np.float64)).astype(np.float32)
    def attention(self,q,k,v,past):
        scores=num.attention_scores(q,k)
        mask=np.arange(len(k))[None,:]<=past+np.arange(len(q))[:,None]
        scores=np.where(mask[None],scores,np.float32(-np.inf))
        shifted=scores-np.max(scores,axis=-1,keepdims=True)
        e=np.exp(shifted.astype(np.float64)).astype(np.float32)
        prob=e/num.tree_sum(e,keepdims=True)
        return num.tree_sum(prob[:,:,:,None]*np.repeat(v,7,axis=1).transpose(1,0,2)[:,None],axis=2).transpose(1,0,2).reshape(len(q),896)
    def swiglu(self,gate,up):
        e=np.exp(-np.abs(gate).astype(np.float64)).astype(np.float32)
        sig=np.where(gate>=0,np.float32(1)/(np.float32(1)+e),e/(np.float32(1)+e))
        return (gate*sig)*up
    def forward(self,ids,logits=True,trace=None):
        a=self.arrays;past=self.length;m=len(ids)
        q=a['model.embed_tokens.weight'][ids];sc=a['model.embed_tokens.weight.scale'][ids]
        x=num.dequantize(q,sc)
        def emit(l,name,x):
            if trace:trace(l,name,x.reshape(m,-1).copy())
        emit(-1,'embedding',x)
        for l in range(24):
            stem=f'model.layers.{l}.'
            def lin(x,key):return self.linear(x,stem+('self_attn.' if key in ('q','k','v','o') else 'mlp.')+key+'_proj.weight')
            emit(l,'input',x)
            z=num.rmsnorm(x,a[stem+'input_layernorm.weight']);emit(l,'norm1',z)
            q=lin(z,'q').reshape(m,14,64);k=lin(z,'k').reshape(m,2,64);v=lin(z,'v').reshape(m,2,64)
            for name,t in [('q',q),('k',k),('v',v)]:emit(l,name,t)
            q=self.rotate(q,past);k=self.rotate(k,past);emit(l,'qr',q);emit(l,'kr',k)
            self.k[l]=k if past==0 else np.concatenate([self.k[l],k]);self.v[l]=v if past==0 else np.concatenate([self.v[l],v])
            attn=self.attention(q,self.k[l],self.v[l],past);emit(l,'attn',attn)
            o=lin(attn,'o');emit(l,'o',o);x=num.residual(x,o);emit(l,'res1',x)
            z=num.rmsnorm(x,a[stem+'post_attention_layernorm.weight']);emit(l,'norm2',z)
            gate=lin(z,'gate');up=lin(z,'up');emit(l,'gate',gate);emit(l,'up',up)
            act=self.swiglu(gate,up);emit(l,'act',act)
            down=lin(act,'down');emit(l,'down',down);x=num.residual(x,down);emit(l,'output',x)
        self.length+=m
        if logits:
            x=num.rmsnorm(x,a['model.norm.weight']);emit(24,'final_norm',x)
            y=self.linear(x,'model.embed_tokens.weight');emit(24,'logits',y);return y
    def cache(self):return np.stack([np.stack([k.reshape(self.length,128),v.reshape(self.length,128)]) for k,v in zip(self.k,self.v)])
