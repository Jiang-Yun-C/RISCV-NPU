"""Export complete logical tensors and group dots from the locked adapted model."""
import argparse
import json
from pathlib import Path
import sys
import numpy as np
from safetensors import safe_open

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT)); sys.path.insert(0,str(ROOT/'scripts'))
from model_tools import numeric_v1 as ref
from evidence import sha256, write_json

STEMS={'q':'self_attn.q_proj','k':'self_attn.k_proj','v':'self_attn.v_proj','o':'self_attn.o_proj',
       'gate':'mlp.gate_proj','up':'mlp.up_proj','down':'mlp.down_proj','head':'model.embed_tokens'}


def small(path):
    # Ties are intentional: max 127 makes scale exactly 1 for these groups.
    x=np.zeros((4,65),np.float32)
    x[0,:8]=[127,-127,.5,1.5,2.5,-.5,-1.5,-2.5]; x[0,64]=4
    x[1,:64]=127; x[1,64]=-2
    x[2,:64]=-127; x[2,64]=1
    w=np.zeros((3,65),np.float32); w[0]=1; w[1,:64]=-127; w[1,64]=127
    bias=np.array([.125,-.25,1],np.float32)
    aq,sa=ref.quantize(x); wq,sw=ref.quantize(w)
    y,d=ref.linear_quantized(aq,sa,wq,sw,bias)
    path.parent.mkdir(parents=True,exist_ok=True)
    np.savez(path,x=x,w=w,bias=bias,aq=aq,sa=sa,wq=wq,sw=sw,dots=d,y=y)


def main():
    p=argparse.ArgumentParser(); p.add_argument('output',type=Path); p.add_argument('--small-only',action='store_true'); a=p.parse_args()
    if a.small_only: small(a.output); return
    out=a.output; out.mkdir(parents=True,exist_ok=False)
    cfg=json.loads((ROOT/'configs/t05-numeric.json').read_text()); lock=json.loads((ROOT/cfg['model_lock']).read_text())
    manifest=json.loads((ROOT/cfg['operator_manifest']).read_text())
    rng=np.random.default_rng(cfg['seed']); tile=cfg['output_tile']
    index={'schema_version':1,'numeric_version':ref.VERSION,'seed':cfg['seed'],'weights':{},'cases':[],
           'blocks':[],'input_origin':'fixed-seed synthetic FP32 activations; real locked merged weights, no application dataset',
           'model_lock_sha256':sha256(ROOT/cfg['model_lock']),'thresholds_sha256':sha256(ROOT/cfg['thresholds'])}
    small(out/'small.npz')
    assert (out/'small.npz').read_bytes()==(ROOT/'tests/vectors/v1/small.npz').read_bytes(), 'versioned small vector changed'
    with safe_open(ROOT/lock['local_path']/'model.safetensors',framework='numpy') as ckpt:
        expected={t['name']:t['shape'] for t in manifest['tensors']}
        assert set(ckpt.keys())==set(expected),'checkpoint tensor inventory'
        for name,shape in expected.items():
            assert ckpt.get_slice(name).get_shape()==shape and ckpt.get_slice(name).get_dtype()=='F32',name
        for key,stem in STEMS.items():
            tensor=stem+'.weight' if key=='head' else f'model.layers.{cfg["layer"]}.'+stem+'.weight'
            source=ckpt.get_slice(tensor); n,k=source.get_shape(); g=(k+63)//64
            wd=out/'weights'/key; wd.mkdir(parents=True)
            wq=np.lib.format.open_memmap(wd/'q.npy',mode='w+',dtype=np.int8,shape=(n,k))
            sw=np.lib.format.open_memmap(wd/'scale.npy',mode='w+',dtype=np.float32,shape=(n,g))
            for lo in range(0,n,tile):
                hi=min(n,lo+tile)
                wq[lo:hi],sw[lo:hi]=ref.quantize(source[lo:hi,:])
            wq.flush(); sw.flush()
            bname=tensor.replace('.weight','.bias'); bias=ckpt.get_tensor(bname) if bname in expected else None
            if bias is not None: np.save(wd/'bias.npy',bias)
            index['weights'][key]={'tensor':tensor,'shape':[n,k],'q':str((wd/'q.npy').relative_to(out)),
                                   'scale':str((wd/'scale.npy').relative_to(out)),
                                   'bias':str((wd/'bias.npy').relative_to(out)) if bias is not None else None}
            xall=rng.standard_normal((8,k),dtype=np.float32)
            xall[1]*=np.float32(0.01); xall[2]*=np.float32(3); xall[3]=0
            for m in cfg['M']:
                case=out/f'{key}-m{m}'; case.mkdir(); x=xall[:m]; aq,sa=ref.quantize(x)
                for name,value in [('x',x),('aq',aq),('sa',sa)]: np.save(case/(name+'.npy'),value)
                y=np.lib.format.open_memmap(case/'y.npy',mode='w+',dtype=np.float32,shape=(m,n))
                dots=np.lib.format.open_memmap(case/'dots.npy',mode='w+',dtype=np.int32,shape=(g,m,n))
                err2=base2=0.; maxerr=0.
                for lo in range(0,n,tile):
                    hi=min(n,lo+tile)
                    y[:,lo:hi],dots[:,:,lo:hi]=ref.linear_quantized(aq,sa,wq[lo:hi],sw[lo:hi],None if bias is None else bias[lo:hi])
                    fp=x.astype(np.float64)@source[lo:hi,:].astype(np.float64).T
                    if bias is not None: fp+=bias[None,lo:hi]
                    delta=y[:,lo:hi].astype(np.float64)-fp
                    err2+=float(np.sum(delta*delta)); base2+=float(np.sum(fp*fp)); maxerr=max(maxerr,float(np.max(np.abs(delta))))
                y.flush(); dots.flush()
                item={'path':case.name,'weight':key,'shape_MKN':[m,k,n],'groups':g,'output_tile':tile,
                      'tiles':(n+tile-1)//tile,'last_tile_rows':n%tile or tile,
                      'quantization_vs_unquantized_fp64_accumulation':{'max_abs':maxerr,'relative_l2':(err2/max(base2,1e-30))**.5,'acceptance':'report_only_not_backend_error'}}
                index['cases'].append(item); print('generated',case.name,flush=True)
        weights={key.split(f'model.layers.{cfg["layer"]}.')[1]:ckpt.get_tensor(key) for key in expected if key.startswith(f'model.layers.{cfg["layer"]}.')}
        for name in ['input_layernorm.weight','post_attention_layernorm.weight']:
            np.save(out/(name+'.npy'),weights[name])
        np.save(out/'final_norm.npy',ckpt.get_tensor('model.norm.weight'))
        ids=np.array(cfg['sample_token_ids'],dtype=np.int64)
        eq=np.load(out/'weights/head/q.npy',mmap_mode='r')[ids]
        es=np.load(out/'weights/head/scale.npy',mmap_mode='r')[ids]
        x=ref.dequantize(eq,es)
        np.savez(out/'embedding.npz',ids=ids,q=eq,scale=es,y=x)
        for m in cfg['M']:
            trace=ref.block(x[:m],weights); trace['final_norm']=ref.rmsnorm(trace['output'],ckpt.get_tensor('model.norm.weight'))
            np.savez(out/f'block-m{m}.npz',**trace); index['blocks'].append(f'block-m{m}.npz')
        cache=None; chunks=[]
        for lo,hi in [(0,1),(1,4),(4,8)]:
            trace=ref.block(x[lo:hi],weights,cache); cache=(trace['cache_k'],trace['cache_v']); chunks.append(trace['output'])
        np.savez(out/'cache-chunks.npz',output=np.concatenate(chunks),cache_k=cache[0],cache_v=cache[1])
        positions=np.array([0,1,63,64,511,512,2047,32767],dtype=np.int64)
        rx=rng.standard_normal((8,14,64),dtype=np.float32)
        # Shared canonical inv_freq avoids platform pow rounding amplification at long positions.
        inv=np.float32(1)/np.power(np.float32(1e6),np.arange(0,64,2,dtype=np.float32)/np.float32(64))
        np.savez(out/'rope-positions.npz',x=rx,positions=positions,inv_freq=inv,y=ref.rope(rx,positions))
    index['files']={str(f.relative_to(out)):{'sha256':sha256(f),'bytes':f.stat().st_size} for f in sorted(out.rglob('*')) if f.is_file()}
    write_json(out/'index.json',index)
    print(json.dumps({'cases':len(index['cases']),'files':len(index['files']),'bytes':sum(x['bytes'] for x in index['files'].values())}))


if __name__=='__main__': main()
