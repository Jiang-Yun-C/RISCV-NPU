#!/usr/bin/env python3
"""Read EVERY packaged parameter against independent Torch/T05 quantization."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
from safetensors import safe_open
import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT/'tests/vectors'))
from model_tools.verify_pack import verify, require
from check_v1 import quant


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def check(path, vectors):
    torch.set_num_threads(1)
    lock = json.loads((ROOT/'docs/spec/application-v2-model-lock.json').read_text())
    manifest = json.loads((ROOT/'docs/spec/operator-manifest.json').read_text())
    ckpt = ROOT/lock['local_path']/'model.safetensors'
    require(sha(ckpt) == lock['files']['model.safetensors']['sha256'], 'E_SOURCE', 'checkpoint')
    pack = verify(path)
    for key, filename in [('model_lock_sha256', 'docs/spec/application-v2-model-lock.json'),
                          ('operator_manifest_sha256', 'docs/spec/operator-manifest.json'),
                          ('memory_map_sha256', 'docs/spec/memory-map-v1.json'),
                          ('thresholds_sha256', 'configs/t05-thresholds.json')]:
        require(pack.metadata.get(key) == sha(ROOT/filename), 'E_SOURCE', key)
    require(pack.metadata['profile'] == 'qwen2.5-0.5b-application-v2' and
            pack.metadata['dimensions'] == manifest['dimensions'] and
            pack.metadata['model_revision'] == lock['revision'] and
            pack.metadata['tokenizer_files'] == lock['tokenizer_files'], 'E_SOURCE', 'model metadata')
    require(pack.metadata['generation'] == dict(eos_token_id=151645, bos_token_id=151643, pad_token_id=151643,
        max_input_tokens=512, max_new_tokens=128, max_context=640, do_sample=False, num_beams=1,
        repetition_penalty=1.0, use_model_defaults=False), 'E_SOURCE', 'generation policy')
    require(pack.metadata['config'] == json.loads((ROOT/lock['local_path']/'config.json').read_text()) and
            pack.metadata['rope_theta'] == 1e6 and pack.metadata['rms_norm_eps'] == 1e-6, 'E_SOURCE', 'network config')
    expected = {'metadata.json', 'lm_head.weight', 'lm_head.weight.scale'}
    expected |= {'tokenizer/'+n for n in lock['tokenizer_files']}
    for t in manifest['tensors']:
        expected.add(t['name'])
        if len(t['shape']) == 2:
            expected.add(t['name']+'.scale')
    require(set(pack.entries) == expected, 'E_SOURCE', 'complete pack inventory')
    weight_elements = scale_elements = small_elements = 0
    with safe_open(ckpt, framework='pt', device='cpu') as source:
        require(set(source.keys()) == {t['name'] for t in manifest['tensors']}, 'E_SOURCE', 'source inventory')
        for t in manifest['tensors']:
            name = t['name']
            require(pack.entries[name]['shape'] == t['shape'], 'E_SOURCE', 'tensor shape')
            if len(t['shape']) == 2:
                rows, k = t['shape']
                for lo in range(0, rows, 256):
                    hi = min(rows, lo+256)
                    q, scale = quant(source.get_slice(name)[lo:hi, :])
                    require(pack.rows(name, lo, hi).tobytes() == q.numpy().tobytes(), 'E_REFERENCE', name+' integers')
                    require(pack.rows(name+'.scale', lo, hi).tobytes() == scale.numpy().astype('<f4').tobytes(),
                            'E_REFERENCE', name+' scale bits')
                weight_elements += rows*k
                scale_elements += rows*((k+63)//64)
            else:
                require(pack.rows(name).tobytes() == source.get_tensor(name).numpy().astype('<f4').tobytes(),
                        'E_REFERENCE', name+' FP32 bits')
                small_elements += t['shape'][0]
    for n, spec in lock['tokenizer_files'].items():
        data = pack.blob('tokenizer/'+n)
        require(len(data) == spec['bytes'] and hashlib.sha256(data).hexdigest() == spec['sha256'], 'E_SOURCE', n)
        require(data == (ROOT/lock['tokenizer_local_path']/n).read_bytes(), 'E_SOURCE', 'original tokenizer')
    # Reconsume sealed T05 data as well as independently recomputing all 24 layers.
    index = json.loads((vectors/'index.json').read_text())
    require(index['model_lock_sha256'] == pack.metadata['model_lock_sha256'] and
            index['thresholds_sha256'] == pack.metadata['thresholds_sha256'], 'E_SOURCE', 'T05 identity')
    vector_files = {}
    for family, spec in index['weights'].items():
        for key, name in [('q', spec['tensor']), ('scale', spec['tensor']+'.scale'),
                          ('bias', spec['tensor'].replace('.weight', '.bias'))]:
            if not spec.get(key):
                continue
            file = vectors/spec[key]
            require(sha(file) == index['files'][spec[key]]['sha256'], 'E_SOURCE', 'T05 vector')
            a = np.load(file, allow_pickle=False, mmap_mode='r')
            for lo in range(0, a.shape[0], 256):
                hi = min(a.shape[0], lo+256)
                require(pack.rows(name, lo, hi).tobytes() == a[lo:hi].tobytes(), 'E_REFERENCE', 'T05 '+family+'/'+key)
            vector_files[spec[key]] = sha(file)
    return dict(status='PASS', pack=pack.summary, source_tensors=len(manifest['tensors']),
                weight_integer_elements_bitwise_checked=weight_elements,
                scale_fp32_elements_bitwise_checked=scale_elements,
                small_fp32_elements_bitwise_checked=small_elements,
                tokenizer_files_checked=len(lock['tokenizer_files']),
                t05_index_sha256=sha(vectors/'index.json'), t05_vector_files=vector_files,
                full_model_quality='NOT_TESTED_T11', rtl_consumption='NOT_TESTED_T14_T15_T18')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pack', type=Path)
    parser.add_argument('--vectors', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    result = check(args.pack, args.vectors)
    args.report.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result))
