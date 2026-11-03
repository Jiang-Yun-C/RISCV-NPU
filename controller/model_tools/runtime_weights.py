#!/usr/bin/env python3
"""Bind sealed T10 physical views without pointer/file-offset conflation."""
import json
from pathlib import Path
import sys
import hashlib
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
def export(dest):
    dest=Path(dest);dest.mkdir(parents=True,exist_ok=True)
    manifest=json.loads((ROOT/'docs/spec/model-pack-v1-manifest.json').read_text())
    entries={e['name']:e for e in manifest['directory']}
    def pointer(name,kind):
        e=entries[name]
        if e['kind'] not in (1,2,3) or e['region']!=1 or e['region_offset']+e['length']>525123200:raise ValueError('T10 region/span')
        address=0x80000000+e['region_offset']
        if address%16:raise ValueError('T10 alignment')
        return f'(const {kind} *)(uintptr_t)0x{address:08x}u'
    rope=json.loads((ROOT/'configs/t11-reference.json').read_text())['canonical_rope'];p=ROOT/rope['path']
    if hashlib.sha256(p.read_bytes()).hexdigest()!=rope['sha256']:raise ValueError('RoPE identity')
    with np.load(p) as z:inv=z['inv_freq']
    h=['/* Exact physical views of sealed model-pack-v1; loader verifies the pack. */',
       'static const float canonical_inv[32]={'+','.join(float(f).hex()+'f' for f in inv)+'};',
       'static void load_full(nx_weights *w){memset(w,0,sizeof(*w));']
    def matrix(member,name):
        e=entries[name];n,k=e['shape'];bias=name.replace('.weight','.bias')
        h.append(f'{member}=(nx_matrix){{{pointer(name,"int8_t")},{pointer(name+".scale","float")},{pointer(bias,"float") if bias in entries else "NULL"},{n},{k}}};')
    matrix('w->embedding','model.embed_tokens.weight')
    for i in range(24):
        stem=f'model.layers.{i}.'
        h.extend([f'w->layer[{i}].norm1={pointer(stem+"input_layernorm.weight","float")};',f'w->layer[{i}].norm2={pointer(stem+"post_attention_layernorm.weight","float")};'])
        for key in ('q','k','v','o','gate','up','down'):matrix(f'w->layer[{i}].{key}',stem+('self_attn.' if key in ('q','k','v','o') else 'mlp.')+key+'_proj.weight')
    h.extend([f'w->norm={pointer("model.norm.weight","float")};','w->inv_freq=canonical_inv;','}'])
    (dest/'full_weights.h').write_text('\n'.join(h)+'\n')
    (dest/'full-model-identity.json').write_text(json.dumps({'pack_sha256':manifest['sha256'],'canonical_rope':rope,
        'weights_base':'0x80000000','runtime_total_context':512,'physical_kv_capacity':640,'input_address':'0xba000000','input_layout':'NQR1,u32 bytes,u32 max_new,u64 timeout_ticks,UTF-8 bytes'},indent=2)+'\n')
if __name__=='__main__':export(sys.argv[1])
