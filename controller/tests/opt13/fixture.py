"""Frozen two-block 14:2 GQA oracle; independent per-token arithmetic."""
from pathlib import Path
import json
import numpy as np
from model_tools.numeric_v1 import quantize,linear_quantized,tree_sum
H,F,V,L,D,KV=28,32,32,2,2,4
class Oracle:
    def __init__(self):
        rng=np.random.default_rng(20261019)
        self.qe=rng.integers(-8,9,(V,64),dtype='i1');self.se=rng.uniform(.01,.03,(V,1)).astype('f4')
        self.q=rng.integers(-8,9,(L,7,F,64),dtype='i1');self.sc=rng.uniform(.005,.015,(L,7,F,1)).astype('f4')
        self.bias=rng.uniform(-.01,.01,(L,3,F)).astype('f4')
        self.n1=rng.uniform(.9,1.1,(L,H)).astype('f4');self.n2=rng.uniform(.9,1.1,(L,H)).astype('f4')
        self.norm=rng.uniform(.9,1.1,H).astype('f4');self.inv=np.ones(D//2,'f4');self.reset()
    def reset(self):self.k=np.empty((L,0,KV),'f4');self.v=self.k.copy()
    @staticmethod
    def norm_fn(x,w):return ((x*(np.float32(1)/np.sqrt(tree_sum(x*x)/np.float32(len(x))+np.float32(1e-6))))*w).astype('f4')
    @staticmethod
    def linear(x,q,sc,b=None):
        aq,sa=quantize(x[None]);return linear_quantized(aq,sa,q[:,:len(x)],sc,b)[0][0]
    def forward(self,id,head=True):
        pos=self.k.shape[1];x=self.qe[id,:H].astype('f4')*self.se[id,0]
        self.k=np.concatenate((self.k,np.empty((L,1,KV),'f4')),axis=1);self.v=np.concatenate((self.v,np.empty((L,1,KV),'f4')),axis=1)
        def rotate(a):
            angle=np.float32(pos)*self.inv;co=np.cos(angle.astype('f8')).astype('f4');si=np.sin(angle.astype('f8')).astype('f4')
            a=a.reshape(-1,D);u=a[:,:D//2];v=a[:,D//2:]
            return np.concatenate((u*co+(-v)*si,v*co+u*si),axis=1).reshape(-1)
        for l in range(L):
            ns=[H,KV,KV,H,F,F,H]
            def lin(a,j):return self.linear(a,self.q[l,j,:ns[j]],self.sc[l,j,:ns[j]],self.bias[l,j,:ns[j]] if j<3 else None)
            z=self.norm_fn(x,self.n1[l]);q=rotate(lin(z,0)).reshape(14,D)
            self.k[l,pos]=rotate(lin(z,1));self.v[l,pos]=lin(z,2);attn=np.empty((14,D),'f4')
            for h in range(14):
                kh=h//7;k=self.k[l,:,kh*D:(kh+1)*D];v=self.v[l,:,kh*D:(kh+1)*D]
                scores=tree_sum(q[h]*k,axis=1)*np.float32(1/np.sqrt(np.float32(D)))
                e=np.exp((scores-np.max(scores)).astype('f8')).astype('f4');p=e/tree_sum(e)
                for i in range(D):attn[h,i]=tree_sum(p*v[:,i])
            x=x+lin(attn.reshape(H),3);z=self.norm_fn(x,self.n2[l]);gate=lin(z,4);up=lin(z,5)
            e=np.exp(-np.abs(gate).astype('f8')).astype('f4');sig=np.where(gate>=0,np.float32(1)/(np.float32(1)+e),e/(np.float32(1)+e))
            x=x+lin((gate*sig)*up,6)
        return self.linear(self.norm_fn(x,self.norm),self.qe,self.se) if head else None
    def cache(self):return np.stack((self.k,self.v),axis=1)
    def header(self,path):
        def decl(name,a):
            values=[str(int(x)) for x in a.ravel()] if a.dtype==np.int8 else [float(x).hex()+'f' for x in a.ravel()]
            return 'static const '+('int8_t' if a.dtype==np.int8 else 'float')+' '+name+''.join(f'[{i}]' for i in a.shape)+'={'+','.join(values)+'};\n'
        Path(path).write_text('#include <stdint.h>\n'+''.join(decl(n,a) for n,a in [('qe',self.qe),('se',self.se),('wq',self.q),('sw',self.sc),('bias',self.bias),('n1',self.n1),('n2',self.n2),('norm',self.norm),('inv',self.inv)]))
def generate(folder):
    folder=Path(folder);folder.mkdir(parents=True);o=Oracle();o.header(folder/'inputs.h');cases=[]
    for rows in (1,4):
        for n in (1,3,4,5,7,8,9):cases.append(dict(rows=rows,n=n,prefix=0))
        cases.append(dict(rows=rows,n=9,prefix=3))
    for i,c in enumerate(cases):
        o.reset();ids=[(j+1)%V for j in range(c['n'])];y=None
        for id in ids:y=o.forward(id)
        first=int(np.argmax(y));last=o.forward(first)
        c.update(index=i,ids=ids,output=[first,int(np.argmax(last))],logits=last.tolist(),kv=o.cache().reshape(-1).tolist())
    (folder/'golden.json').write_text(json.dumps(dict(cases=cases,geometry=dict(H=H,F=F,V=V,L=L,D=D,KV=KV),atol=2e-5,rtol=2e-4),indent=2)+'\n')
    return folder
