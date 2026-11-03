"""Executable logical capacity / traffic / MAC model, independent of a backend layout."""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def calculate(manifest, context=512, m=1):
    if context < 1 or context > 32768 or m < 1 or m > context:
        raise ValueError('require 1 <= M <= context <= 32768')
    tensors = manifest['tensors']
    matrices = [t for t in tensors if len(t['shape']) == 2]
    small = [t for t in tensors if len(t['shape']) == 1]
    elements = sum(n*k for n,k in (t['shape'] for t in matrices))
    groups = sum(n*((k+63)//64) for n,k in (t['shape'] for t in matrices))
    small_elements = sum(t['shape'][0] for t in small)
    weight_bytes = elements + 4*groups + 4*small_elements
    d = manifest['dimensions']; h=d['hidden']; l=d['layers']; kv=d['kv_heads']; hd=d['head_dim']; v=d['vocab']
    linear_macs = elements*m  # Each shared embedding element is read once by lm_head, not a second matrix.
    # S=context includes this chunk. Each of M causal rows sees S-M+i+1 keys.
    pairs = m*(context-m) + m*(m+1)//2
    attention_macs = 2*l*h*pairs
    kv_bytes = 2*l*kv*hd*context*4
    kv_read = 2*l*kv*hd*pairs*4
    kv_read_unique = 2*l*kv*hd*context*4
    embedding_read = m*h + m*((h+63)//64)*4
    # Ideal logical traffic: stream each matrix once for all M, keep activation tiles/KV reuse on chip.
    ideal = weight_bytes + embedding_read + kv_read_unique + 2*l*kv*hd*m*4
    return {'scope':'logical lower bounds/explicit schedules; not a physical package, bandwidth or peak allocation measurement',
            'M':m,'context_including_chunk':context,'matrix_elements':elements,'small_fp32_elements':small_elements,
            'unique_parameters':elements+small_elements,'int8_weight_bytes':elements,'fp32_scale_bytes':4*groups,
            'fp32_small_tensor_bytes':4*small_elements,'w8_logical_bytes':weight_bytes,'w8_logical_MiB':weight_bytes/2**20,
            'original_fp32_bytes':4*(elements+small_elements),'kv_fp32_bytes':kv_bytes,
            'linear_MACs':linear_macs,'attention_QK_PV_MACs':attention_macs,'total_MACs':linear_macs+attention_macs,
            'causal_query_key_pairs':pairs,'ideal_read_once_weight_and_kv_plus_write_bytes':ideal,
            'kv_read_per_query_bytes_without_M_reuse':kv_read,
            'kv_read_bytes_if_repeated_for_each_query_head':kv_read*(d['q_heads']//kv),
            'kv_write_bytes':2*l*kv*hd*m*4,'embedding_lookup_bytes':embedding_read,
            'logits_output_bytes':m*v*4,'largest_linear_activation_bytes':m*d['intermediate']*4,
            'unfused_attention_scores_bytes_per_layer':d['q_heads']*m*context*4,
            'one_GiB_minus_weights_and_kv_bytes':2**30-weight_bytes-kv_bytes,
            'excludes':['physical padding/header/alignment/tokenizer','firmware/heap/stack','activation lifetimes and spills','DMA buffers','non-MAC scalar operations'],
            'formulae':{'matrix':'sum(N*K), shared embedding counted once','scales':'4*sum(N*ceil(K/64))',
                       'KV':'2*L*KV_heads*head_dim*S*4','linear_MACs':'M*sum(unique matrix elements)',
                       'attention_MACs':'2*L*hidden*(M*(S-M)+M*(M+1)/2)'}}


def main():
    p=argparse.ArgumentParser(); p.add_argument('--context',type=int,default=512); p.add_argument('--m',type=int,default=1); p.add_argument('--output',type=Path)
    a=p.parse_args(); result=calculate(json.loads((ROOT/'docs/spec/operator-manifest.json').read_text()),a.context,a.m)
    text=json.dumps(result,indent=2,ensure_ascii=False)+'\n'
    if a.output: a.output.write_text(text)
    print(text,end='')


if __name__=='__main__': main()
