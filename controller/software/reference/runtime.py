"""Host adapter: validated immutable T10 views, C arithmetic, Python tokenizer only."""
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import subprocess
import numpy as np
from model_tools.verify_pack import verify

ROOT=Path(__file__).resolve().parents[2]
P=C.c_void_p
class Matrix(C.Structure):
    _fields_=[('q',P),('s',P),('bias',P),('n',C.c_int),('k',C.c_int)]
class Layer(C.Structure):
    _fields_=[('norm1',P),('norm2',P)]+[(k,Matrix) for k in ('q','k','v','o','gate','up','down')]
class Weights(C.Structure):
    _fields_=[('embedding',Matrix),('layer',Layer*24),('norm',P),('inv_freq',P)]
TRACE=C.CFUNCTYPE(None,C.c_int,C.c_char_p,P,C.c_int,C.c_int)

def build(path):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    cmd=['gcc','-std=c11','-O3','-march=native','-fno-fast-math','-ffp-contract=off',
         '-fopenmp','-Wall','-Wextra','-Werror','-shared','-fPIC',
         str(ROOT/'firmware/runtime/reference/nx_reference.c'),'-lm','-o',str(path)]
    subprocess.run(cmd,check=True)
    return cmd

def library(path):
    lib=C.CDLL(str(Path(path).resolve()))
    signatures={
        'nx_create':([C.POINTER(Weights),C.c_int],P),'nx_destroy':([P],None),'nx_reset':([P],None),
        'nx_forward':([P,P,C.c_int,C.c_int,P,TRACE],C.c_int),
        'nx_cache':([P,C.c_int,C.c_int],P),'nx_length':([P],C.c_int),
        'nx_memory_bytes':([],C.c_size_t),'nx_profile':([P,P,P],None),
        'nx_quantize':([P,C.c_int,C.c_int,P,P],C.c_int),
        'nx_linear':([P,C.c_int,C.POINTER(Matrix),P,P],C.c_int),
        'nx_norm':([P,P,C.c_int,C.c_int,P],C.c_int),
        'nx_rope':([P,C.c_int,C.c_int,C.c_int,P],C.c_int),
        'nx_swiglu':([P,P,C.c_int,P],C.c_int)}
    signatures.update(nx_greedy=([P,P],C.c_int),nx_generate=([P,P,C.c_int,P,P,P],C.c_int))
    for name,(args,ret) in signatures.items():
        f=getattr(lib,name);f.argtypes=args;f.restype=ret
    return lib

def ptr(a):return None if a is None else a.ctypes.data

class Runtime:
    def __init__(self,lib,threads=4):
        self.lib=library(lib);self.session=None
        self.manifest=json.loads((ROOT/'docs/spec/model-pack-v1-manifest.json').read_text())
        self.pack=verify(ROOT/self.manifest['pack_path'],expected_sha256=self.manifest['sha256'])
        assert self.pack.metadata['profile']=='qwen2.5-0.5b-application-v2'
        self.storage=np.memmap(self.pack.path,mode='r',dtype=np.uint8)
        self.arrays={}
        for name,e in self.pack.entries.items():
            if e['kind']!=4:
                self.arrays[name]=np.ndarray(tuple(e['shape']),dtype=np.int8 if e['kind']==1 else '<f4',
                                            buffer=self.storage,offset=e['offset'])
        # Reuse the frozen T05 table; powf platform variation cannot shift long RoPE positions.
        rope=json.loads((ROOT/'configs/t11-reference.json').read_text())['canonical_rope']
        path=ROOT/rope['path']
        if hashlib.sha256(path.read_bytes()).hexdigest()!=rope['sha256']:raise ValueError('canonical RoPE identity')
        with np.load(path) as f:self.inv=f['inv_freq'].copy()
        self.weights=Weights();self.weights.embedding=self.matrix('model.embed_tokens.weight')
        for i in range(24):
            stem=f'model.layers.{i}.';layer=self.weights.layer[i]
            layer.norm1=ptr(self.arrays[stem+'input_layernorm.weight']);layer.norm2=ptr(self.arrays[stem+'post_attention_layernorm.weight'])
            for key in ('q','k','v','o','gate','up','down'):
                group='self_attn.' if key in ('q','k','v','o') else 'mlp.'
                setattr(layer,key,self.matrix(stem+group+key+'_proj.weight'))
        self.weights.norm=ptr(self.arrays['model.norm.weight']);self.weights.inv_freq=ptr(self.inv)
        self.session=self.lib.nx_create(C.byref(self.weights),threads)
        if not self.session:raise ValueError('C session creation/rounding mode')

    def matrix(self,name):
        q=self.arrays[name];s=self.arrays[name+'.scale'];b=self.arrays.get(name.replace('.weight','.bias'))
        return Matrix(ptr(q),ptr(s),ptr(b),*q.shape)
    def reset(self):self.lib.nx_reset(self.session)
    @property
    def length(self):return self.lib.nx_length(self.session)
    def forward(self,ids,logits=True,trace=None,past=None):
        ids=np.asarray(ids)
        if ids.ndim!=1 or ids.dtype.kind not in 'iu' or np.any(ids<0) or np.any(ids>=151936):raise ValueError('token IDs')
        ids=np.ascontiguousarray(ids,dtype=np.int32)
        y=np.empty((len(ids),151936),dtype=np.float32) if logits else None
        failures=[]
        def callback(layer,name,data,rows,cols):
            try:trace(layer,name.decode(),np.ctypeslib.as_array(C.cast(data,C.POINTER(C.c_float)),shape=(rows,cols)).copy())
            except BaseException as e:failures.append(e)
        cb=TRACE(callback) if trace else TRACE()
        rc=self.lib.nx_forward(self.session,ptr(ids),len(ids),self.length if past is None else past,ptr(y),cb)
        if rc:raise ValueError(f'C forward error {rc}')
        if failures:raise failures[0]
        return y
    def cache(self):
        n=self.length
        if n<0:raise ValueError('invalid session')
        return np.stack([np.stack([np.ctypeslib.as_array(C.cast(self.lib.nx_cache(self.session,l,v),C.POINTER(C.c_float)),shape=(640,128))[:n].copy() for v in range(2)]) for l in range(24)])
    def generate(self,ids):
        if not 1<=len(ids)<=512:raise ValueError('prompt length')
        ids=np.asarray(ids)
        if ids.ndim!=1 or ids.dtype.kind not in 'iu' or np.any(ids<0) or np.any(ids>=151936):raise ValueError('token IDs')
        ids=np.ascontiguousarray(ids,dtype=np.int32);out=np.empty(128,np.int32)
        count=np.zeros(1,np.int32);stop=np.zeros(1,np.int32)
        rc=self.lib.nx_generate(self.session,ptr(ids),len(ids),ptr(out),ptr(count),ptr(stop))
        if rc:raise ValueError(f'C generate error {rc}')
        maximum=min(128,512-len(ids))
        if not 0<=count[0]<=maximum or stop[0] not in (1,2,3):raise ValueError('C generation result')
        if stop[0]==3 and count[0]!=maximum:raise ValueError('C context stop count')
        if count[0]==0 and (len(ids)!=512 or stop[0]!=3):raise ValueError('C empty generation result')
        return out[:count[0]].tolist(),{1:'eos',2:'max_new_tokens',3:'context'}[stop[0]]
    def profile(self):
        seconds=np.zeros(8,np.float64);calls=np.zeros(8,np.uint64)
        self.lib.nx_profile(self.session,ptr(seconds),ptr(calls))
        return {'operators':{k:{'seconds':float(s),'calls':int(c)} for k,s,c in zip(
            ['embedding','rmsnorm','linear','rope','attention_softmax','swiglu','residual','lm_head'],seconds,calls)},
            'session_heap_bytes':self.lib.nx_memory_bytes(),'pack_mapped_bytes':self.storage.nbytes,
            'worker_stack_scratch_bound_bytes':131072,'max_context':640,'request_context_limit':512,'max_chunk':4}
    def close(self):
        if self.session:self.lib.nx_destroy(self.session);self.session=None
    def __del__(self):self.close()
