"""Independent NumPy two-block oracle. Never imports the candidate runtime."""
import json
from pathlib import Path
import numpy as np

def tree(a):
    a=np.asarray(a,dtype='f4').copy();n=1
    while n<a.size:n*=2
    a=np.pad(a,(0,n-a.size))
    while len(a)>1:a=a[::2]+a[1::2]
    return a[0]

class Oracle:
    def __init__(self,seed=20261019):
        rng=np.random.default_rng(seed)
        self.qe=rng.integers(-8,9,(32,64),dtype=np.int8)
        self.se=rng.uniform(.01,.03,32).astype('f4')
        self.q=rng.integers(-8,9,(2,7,16,64),dtype=np.int8)
        self.s=rng.uniform(.01,.03,(2,7,16)).astype('f4')
        self.bias=rng.uniform(-.01,.01,(2,3,16)).astype('f4')
        self.n1=rng.uniform(.9,1.1,(2,8)).astype('f4');self.n2=rng.uniform(.9,1.1,(2,8)).astype('f4')
        self.norm=rng.uniform(.9,1.1,8).astype('f4');self.inv=np.array([1,.01],dtype='f4')
        self.reset()
    def reset(self):self.k=np.empty((2,0,4),'f4');self.v=self.k.copy()
    @staticmethod
    def rms(x,w):return (x*(np.float32(1)/np.sqrt(tree(x*x)/np.float32(len(x))+np.float32(1e-6))))*w
    @staticmethod
    def linear(x,q,s,b=None):
        peak=np.max(np.abs(x));scale=np.float32(0) if peak==0 else np.maximum(peak/np.float32(127),np.finfo('f4').tiny)
        aq=np.zeros(len(x),dtype='i1') if scale==0 else np.clip(np.rint(x/scale),-127,127).astype('i1')
        d=np.sum(q[:,:len(x)].astype('i4')*aq.astype('i4'),axis=1,dtype='i4')
        y=(d.astype('f4')*scale)*s
        return y if b is None else y+b
    def forward(self,id,head=True):
        pos=self.k.shape[1];x=self.qe[id,:8].astype('f4')*self.se[id]
        self.k=np.concatenate((self.k,np.empty((2,1,4),'f4')),axis=1)
        self.v=np.concatenate((self.v,np.empty((2,1,4),'f4')),axis=1)
        def rotate(a):
            angle=np.float32(pos)*self.inv;co=np.cos(angle.astype('f8')).astype('f4');si=np.sin(angle.astype('f8')).astype('f4')
            a=a.reshape(-1,4);first=a[:,:2];last=a[:,2:]
            return np.concatenate((first*co+(-last)*si,last*co+first*si),axis=1).reshape(-1)
        for l in range(2):
            ns=[8,4,4,8,16,16,8]
            def linear(a,j):return self.linear(a,self.q[l,j,:ns[j]],self.s[l,j,:ns[j]],self.bias[l,j,:ns[j]] if j<3 else None)
            z=self.rms(x,self.n1[l]);q=rotate(linear(z,0)).reshape(2,4)
            self.k[l,pos]=rotate(linear(z,1));self.v[l,pos]=linear(z,2)
            attn=np.empty((2,4),'f4')
            for h in range(2):
                scores=np.array([tree(q[h]*k)*np.float32(.5) for k in self.k[l]],dtype='f4')
                e=np.exp((scores-np.max(scores)).astype('f8')).astype('f4');p=e/tree(e)
                for i in range(4):attn[h,i]=tree(p*self.v[l,:,i])
            x=x+linear(attn.reshape(8),3);z=self.rms(x,self.n2[l]);gate=linear(z,4);up=linear(z,5)
            e=np.exp(-np.abs(gate).astype('f8')).astype('f4');sig=np.where(gate>=0,np.float32(1)/(np.float32(1)+e),e/(np.float32(1)+e))
            x=x+linear((gate*sig)*up,6)
        return self.linear(self.rms(x,self.norm),self.qe,self.se) if head else None
    def header(self,path):
        def decl(name,a):
            a=np.asarray(a);shape=''.join(f'[{n}]' for n in a.shape)
            values=[str(int(x)) for x in a.ravel()] if a.dtype==np.int8 else [float(x).hex()+'f' for x in a.ravel()]
            # Flat initializers are legal for nested arrays; suppress only missing-braces.
            return f'static const {"int8_t" if a.dtype==np.int8 else "float"} {name}{shape}={{'+','.join(values)+'};\n'
        Path(path).write_text('#include <stdint.h>\n'+''.join(decl(n,a) for n,a in [('q_embedding',self.qe),('s_embedding',self.se),('q_layers',self.q),('s_layers',self.s),('bias',self.bias),('norm1',self.n1),('norm2',self.n2),('norm',self.norm),('inv',self.inv)]))

def generate(folder):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True);o=Oracle();o.header(folder/'inputs.h');expected={};ids={}
    def snap(label,tokens,decode=False,head=True):
        o.reset();y=None
        for t in tokens:y=o.forward(t)
        if decode:
            first=int(np.argmax(y));y=o.forward(first);ids[label]=[first,int(np.argmax(y))]
        group=10+label*10
        if head:expected[str(group)]=[float(x) for x in y]
        for l in range(2):
            for v,a in enumerate((o.k,o.v)):expected[str(group+1+l*2+v)]=a[l].ravel().tolist()
        expected[str(group+5)]=[o.k.shape[1]]*4
    snap(0,[1,2,3,4,5]);snap(1,[1,2,3,4,5]);snap(2,[1,2,3],head=False);snap(3,[1,2,3,7,8])
    snap(4,[1,2,3,4,5],decode=True);snap(5,[1,2,3,4,5],decode=True)
    value=dict(schema_version=1,seed=20261019,geometry=dict(H=8,F=16,V=32,L=2,D=4,KV=4,S=640),
               numeric=expected,generated={str(301+i):ids[4+i] for i in range(2)},
               checks=list(range(1,13))+list(range(20,38))+list(range(40,85)),
               exact={'100':[1,3],'110':[0]*11,'120':[3,3,0,512,3,3,1,511]},
               comparison=dict(atol=2e-5,rtol=2e-4),scope='TWO_COMPLETE_BLOCKS_GQA_2_TO_1_TIED_HEAD_INDEPENDENT_NUMPY')
    (folder/'golden.json').write_text(json.dumps(value,indent=2)+'\n');return folder

if __name__=='__main__':
    import sys
    generate(sys.argv[1])
