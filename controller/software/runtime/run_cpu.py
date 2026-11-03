#!/usr/bin/env python3
"""Full frozen W8 model, portable static C runtime and C text tokenizer.

The host owns the immutable mmap, arenas, and console; all tokenizer, graph,
request state, greedy and stop operations use the same C as RV32.
"""
import argparse
import ctypes as C
import json
from pathlib import Path
import resource
import subprocess
import sys
import time
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/'tests/runtime')]
from software.reference.runtime import Weights,Matrix,ptr,TRACE
from model_tools.verify_pack import verify
from tokenizer_reference import CTokenizer,Message

def build(path):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    src=[ROOT/p for p in ('firmware/runtime/reference/nx_reference.c','firmware/runtime/port/tokenizer.c',
        'firmware/runtime/port/runtime.c','firmware/runtime/port/model.c','tests/runtime/host_clock.c','firmware/runtime/board/diag.c')]
    cmd=['gcc','-std=c11','-D_POSIX_C_SOURCE=200809L','-DNX_DIAG_HOST=1','-include',str(ROOT/'firmware/runtime/board/diag.h'),'-I',str(ROOT/'firmware/drivers/accel'),'-I',str(ROOT/'software/include'),'-DNX_PORTABLE','-O3','-fno-fast-math','-ffp-contract=off','-fno-strict-aliasing',
        '-shared','-fPIC','-Wno-unknown-pragmas','-I',str(ROOT/'firmware/runtime/port'),'-I',str(ROOT/'firmware/runtime/reference'),
        *map(str,src),'-lm','-o',str(path)]
    subprocess.run(cmd,check=True);return cmd

class PortableModel:
    def __init__(self,library):
        self.lib=C.CDLL(str(Path(library).resolve()));P=C.c_void_p
        specs={'nx_state_bytes':([],C.c_size_t),'nx_kv_bytes':([],C.c_size_t),'nx_work_bytes':([],C.c_size_t),
            'nx_init_static':([P,P,C.c_size_t,P,C.c_size_t,P,C.c_size_t],P),
            'nx_forward':([P,P,C.c_int,C.c_int,P,TRACE],C.c_int),'nx_reset':([P],None),'nx_length':([P],C.c_int),
            'nx_cache':([P,C.c_int,C.c_int],P),
            'nxr_request_bytes':([],C.c_size_t),'nxr_model_bytes':([],C.c_size_t),'nxr_attach':([P,P,P,P,C.c_uint32],C.c_int),
            'nxr_begin_text':([P,P,P,P,C.c_size_t,P,C.c_size_t,C.c_uint32,C.c_uint64],C.c_int),
            'nxr_step':([P],C.c_int),'nxr_reset':([P],C.c_int),'nxr_state':([P],C.c_int),
            'nxr_count':([P],C.c_uint32),'nxr_reason':([P],C.c_uint32),'nxr_output':([P,C.c_uint32],C.c_uint32)}
        for name,(args,ret) in specs.items():fn=getattr(self.lib,name);fn.argtypes=args;fn.restype=ret
        manifest=json.loads((ROOT/'docs/spec/model-pack-v1-manifest.json').read_text())
        self.pack=verify(ROOT/manifest['pack_path'],expected_sha256=manifest['sha256'])
        self.storage=np.memmap(self.pack.path,mode='r',dtype='u1');self.arrays={}
        for name,e in self.pack.entries.items():
            if e['kind']!=4:self.arrays[name]=np.ndarray(e['shape'],dtype='i1' if e['kind']==1 else '<f4',buffer=self.storage,offset=e['offset'])
        rope=json.loads((ROOT/'configs/t11-reference.json').read_text())['canonical_rope']
        import hashlib
        if hashlib.sha256((ROOT/rope['path']).read_bytes()).hexdigest()!=rope['sha256']:raise ValueError('RoPE identity')
        with np.load(ROOT/rope['path']) as f:self.inv=f['inv_freq'].copy()
        def matrix(name):
            q=self.arrays[name];return Matrix(ptr(q),ptr(self.arrays[name+'.scale']),ptr(self.arrays.get(name.replace('.weight','.bias'))),*q.shape)
        self.weights=Weights();self.weights.embedding=matrix('model.embed_tokens.weight');self.weights.norm=ptr(self.arrays['model.norm.weight']);self.weights.inv_freq=ptr(self.inv)
        for i in range(24):
            stem=f'model.layers.{i}.';w=self.weights.layer[i];w.norm1=ptr(self.arrays[stem+'input_layernorm.weight']);w.norm2=ptr(self.arrays[stem+'post_attention_layernorm.weight'])
            for key in ('q','k','v','o','gate','up','down'):setattr(w,key,matrix(stem+('self_attn.' if key in ('q','k','v','o') else 'mlp.')+key+'_proj.weight'))
        self.state=np.zeros(self.lib.nx_state_bytes(),dtype='u1');self.kv=np.empty(self.lib.nx_kv_bytes(),dtype='u1');self.work=np.empty(self.lib.nx_work_bytes(),dtype='u1')
        self.session=self.lib.nx_init_static(C.byref(self.weights),ptr(self.state),self.state.nbytes,ptr(self.kv),self.kv.nbytes,ptr(self.work),self.work.nbytes)
        if not self.session:raise ValueError('static C model initialization')
        self.request=C.create_string_buffer(self.lib.nxr_request_bytes());self.binding=C.create_string_buffer(self.lib.nxr_model_bytes());self.logits=np.empty(151936,'f4')
        if self.lib.nxr_attach(self.request,self.binding,self.session,ptr(self.logits),151936):raise ValueError('request attachment')
    def forward(self,ids):
        out=[]
        for token in ids:
            a=np.array([token],dtype='i4');y=np.empty((1,151936),'f4')
            rc=self.lib.nx_forward(self.session,ptr(a),1,self.lib.nx_length(self.session),ptr(y),TRACE())
            if rc:raise ValueError(f'portable C forward {rc}')
            out.append(y.copy())
        return np.concatenate(out)
    def generate(self,tokenizer,messages,max_new=128,timeout=3600):
        if self.lib.nxr_reset(self.request):raise ValueError('request reset')
        data=[(m['role'].encode(),m['content'].encode()) for m in messages]
        msgs=(Message*len(data))(*(Message(a,b,len(b)) for a,b in data));buf=C.create_string_buffer(4096)
        rc=self.lib.nxr_begin_text(self.request,C.byref(tokenizer.state),tokenizer.work,msgs,len(msgs),buf,len(buf),max_new,int(timeout*1e9))
        if rc:raise ValueError(f'C text request {rc}')
        while self.lib.nxr_state(self.request) in (1,2):
            rc=self.lib.nxr_step(self.request)
            if rc:raise ValueError(f'C request execution {rc}')
        ids=[self.lib.nxr_output(self.request,i) for i in range(self.lib.nxr_count(self.request))]
        return {'output_ids':ids,'text':tokenizer.decode(ids)[0],'stop':{1:'eos',2:'max_new_tokens',3:'total_context'}[self.lib.nxr_reason(self.request)]}
    def cache(self):
        length=self.lib.nx_length(self.session)
        return np.stack([np.stack([np.ctypeslib.as_array(C.cast(self.lib.nx_cache(self.session,l,v),C.POINTER(C.c_float)),shape=(640,128))[:length].copy() for v in range(2)]) for l in range(24)])
    def memory(self):return {'state_bytes':self.state.nbytes,'kv_bytes':self.kv.nbytes,'work_bytes':self.work.nbytes,'external_logits_bytes':self.logits.nbytes,'request_bytes':len(self.request),'model_mmap_bytes':self.storage.nbytes,'peak_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--text',default='打开客厅灯。');p.add_argument('--system');p.add_argument('--max-new',type=int,default=128);p.add_argument('--timeout',type=float,default=3600)
    p.add_argument('--library',type=Path,default=ROOT/'build/runtime-cpu/libnxr.so');p.add_argument('--tokenizer',type=Path,default=ROOT/'build/runtime-cpu/tokenizer/tokenizer.nxt');p.add_argument('--verify-full',action='store_true');p.add_argument('--output',type=Path)
    a=p.parse_args();build(a.library)
    if not a.tokenizer.exists():
        from model_tools.export_tokenizer import export
        export(a.tokenizer.parent)
    model=PortableModel(a.library);start=time.monotonic()
    if a.verify_full:
        from software.reference.runtime import Runtime,build as ref_build
        reference_path=a.library.with_name('libt11.so');ref_build(reference_path);ref=Runtime(reference_path,4)
        ids=[0,255,1023];expected=ref.forward(ids);actual=model.forward(ids)
        error=np.abs(actual.astype('f8')-expected.astype('f8'));tol=json.loads((ROOT/'configs/t05-thresholds.json').read_text())['cumulative']['logits_24_layers']
        nrmse=float(np.sqrt(np.mean(error**2))/max(np.sqrt(np.mean(expected.astype('f8')**2)),1e-12))
        if not np.isfinite(actual).all() or not np.all(error<=tol['atol']+tol['rtol']*np.abs(expected)) or nrmse>tol['nrmse']:raise ValueError('portable full model numerical mismatch')
        np.testing.assert_array_equal(model.cache().view('u4'),ref.cache().view('u4'))
        result={'status':'PASS','model':'full frozen 24-layer W8','fixed_ids':ids,'elements':actual.size,'kv_elements_exact':int(model.cache().size),'max_abs':float(error.max()),'nrmse':nrmse,'argmax':actual.argmax(axis=1).tolist()}
    else:
        tokenizer=CTokenizer(a.library,a.tokenizer);messages=[]
        if a.system:messages.append({'role':'system','content':a.system})
        messages.append({'role':'user','content':a.text});result=model.generate(tokenizer,messages,a.max_new,a.timeout)
    result.update(seconds=time.monotonic()-start,memory=model.memory(),backend='CPU_C',scope='host execution of portable C; not FPGA performance')
    if a.output:a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
