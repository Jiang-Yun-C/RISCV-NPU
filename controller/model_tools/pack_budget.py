#!/usr/bin/env python3
"""Concrete bounded allocation plan against T08; not a T12 peak measurement."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from model_tools.verify_pack import verify


def calculate(pack, memory=None):
    memory = memory or json.loads((ROOT/'docs/spec/memory-map-v1.json').read_text())
    d = pack.metadata['dimensions']
    m, s = 8, 640
    h, ff, v, qh, kvh, hd, layers = (d[n] for n in ('hidden', 'intermediate', 'vocab',
                                                   'q_heads', 'kv_heads', 'head_dim', 'layers'))
    regions = {r['name']: r for r in memory['ddr_regions']}
    items = {r: [] for r in regions}
    def add(region, name, size, purpose):
        previous = items[region]
        offset = (previous[-1]['offset']+previous[-1]['bytes']+63)//64*64 if previous else 0
        if not isinstance(size, int) or size <= 0 or offset+size > regions[region]['size_bytes']:
            raise ValueError('allocation exceeds region: '+region+'/'+name)
        previous.append(dict(name=name, offset=offset, bytes=size,
                             soc_address=int(regions[region]['base'], 0)+offset, purpose=purpose))
    add('weights', 'sealed_unique_pack_tensors_and_metadata', pack.summary['region_bytes']['weights'],
        'Final storage only; embedding/head alias counted once; no full FP32 copy')
    add('tokenizer', 'original_tokenizer_files', pack.summary['region_bytes']['tokenizer'], 'Exact original bytes')
    add('tokenizer', 'bpe_vocab_and_merge_indices', (v*16 + 200000*16), 'Bounded 16-byte index entries; T12 must enforce')
    add('tokenizer', 'utf8_text_and_token_work', 1 << 20, 'Bounded text/token scratch')
    add('kv', 'all_layers_k_v_fp32', 2*layers*s*kvh*hd*4, '[layer,K/V,token,KV-head,dimension]')
    # Conservatively keep every activation below live, even across disjoint phases.
    for name in ('hidden_ping', 'hidden_pong', 'residual', 'norm1', 'norm2', 'q', 'q_rot', 'attention_out'):
        add('workspace', name, m*h*4, 'FP32 [M,hidden]')
    for name in ('k', 'v', 'k_rot'):
        add('workspace', name, m*kvh*hd*4, 'FP32 [M,KV-head,head-dim]')
    for name in ('gate', 'up', 'swiglu'):
        add('workspace', name, m*ff*4, 'FP32 [M,intermediate]')
    for name in ('scores', 'probabilities'):
        add('workspace', name, qh*m*s*4, 'FP32 [Q-head,M,context]')
    for name in ('reduction_products', 'reduction_tree'):
        add('workspace', name, qh*m*1024*hd*4, 'Worst padded FP32 QK/PV reduction, separate product/tree arenas')
    add('workspace', 'all_chunk_logits', m*v*4, 'Complete vocabulary for M=8; streaming greedy may use less')
    add('workspace', 'activation_q8', m*ff, 'Largest activation [M,K]')
    add('workspace', 'activation_scales', m*((ff+63)//64)*4, 'FP32 [M,G]')
    add('workspace', 'group_dot_audit', m*128*((ff+63)//64)*4, 'INT32 [M,N-tile,G]')
    add('workspace', 'linear_tile_output', m*128*4, 'FP32 [M,N-tile]')
    add('workspace', 'dequantized_embedding_chunk', m*h*4, 'Only selected rows, never the whole model')
    add('cpu_private', 'program_rodata', 8 << 20, 'Enforced link/load ceiling; actual T12 image pending')
    add('cpu_private', 'bounded_heap', 8 << 20, 'No unbounded allocator in inference')
    # T08 fixes the stack at the highest 64KiB, not immediately after the heap.
    items['cpu_private'].append(dict(name='stack', offset=regions['cpu_private']['size_bytes']-65536,
        bytes=65536, soc_address=int(memory['initial_stack_top'], 0)-65536, purpose='T08 fixed stack'))
    add('shared_io', 'loader_double_buffer', 2*65536, 'Stream to final addresses; never retain whole file twice')
    add('shared_io', 'pack_header_directory', 192+4096*256, 'Bounded v1 maximum directory')
    add('shared_io', 'task_logs_and_transport', 2 << 20, 'Bounded request/log/transport buffers')
    add('shared_io', 'weight_tile_double_buffer', 2*128*(ff+((ff+63)//64)*4), 'Optional bounded tiles; direct DDR preferred')
    add('reserved', 'unmapped_board_margin', regions['reserved']['size_bytes'], 'T08 forbids inference allocation')
    allocated = {r: sum(i['bytes'] for i in values) for r, values in items.items()}
    # Reserve ALL non-weight windows, including their unallocated gaps and the
    # inaccessible 64MiB. This ceiling is stricter than summing active buffers.
    ceiling = pack.summary['region_bytes']['weights'] + sum(r['size_bytes'] for n, r in regions.items() if n != 'weights')
    capacity = memory['ddr_size_bytes']
    if ceiling > capacity or allocated['weights'] > regions['weights']['size_bytes']:
        raise ValueError('1GiB capacity exceeded')
    return dict(status='PASS', physical_qualification=memory['physical_qualification'],
                scope='Concrete bounded allocation contract; T12 must enforce ceilings and measure its implementation peak; T23 validates board capacity',
                pack_file_bytes=pack.summary['bytes'], pack_sha256=pack.summary['sha256'],
                model_storage_bytes=pack.summary['region_bytes']['weights'],
                tokenizer_storage_bytes=pack.summary['region_bytes']['tokenizer'],
                max_context=s, max_prefill_chunk=m, kv_fp32_bytes=2*layers*s*kvh*hd*4,
                assumed_ddr_bytes=capacity, conservative_reserved_bytes=ceiling,
                additional_free_bytes=capacity-ceiling, unmapped_margin_bytes=regions['reserved']['size_bytes'],
                allocations=items, allocated_bytes=allocated,
                region_capacity_bytes={n: r['size_bytes'] for n, r in regions.items()},
                full_model_dequantization=False, runtime_weight_transpose=False,
                shared_embedding_duplicate_bytes=0)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pack', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = calculate(verify(args.pack))
    text = json.dumps(result, ensure_ascii=False, indent=2)+'\n'
    if args.output:
        args.output.write_text(text)
    print(text, end='')
