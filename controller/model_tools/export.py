#!/usr/bin/env python3
"""Deterministic, streaming writer for model-pack-v1. Reader is independent."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys

import numpy as np
from safetensors import safe_open

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from model_tools.numeric_v1 import quantize

HEADER = struct.Struct('<8s8I3Q32s32s32s')
ENTRY = struct.Struct('<128s8I2Q2IQ32s32s')
ALIGN = 64
LAYOUT = 0x1001
NONE = 0xffffffff


def align(n):
    return (n + 63) // 64 * 64


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
                       allow_nan=False) + '\n').encode('utf-8')


def locked_sources(root=ROOT):
    lock = json.loads((root / 'docs/spec/application-v2-model-lock.json').read_text())
    for folder, files in [(lock['local_path'], lock['files']),
                          (lock['tokenizer_local_path'], lock['tokenizer_files'])]:
        for name, spec in files.items():
            p = root / folder / name
            if p.stat().st_size != spec['bytes'] or digest(p) != spec['sha256']:
                raise ValueError('source identity mismatch: ' + str(p))
    return lock


def consumption_order(manifest):
    names = ['model.embed_tokens.weight']
    for layer in range(manifest['dimensions']['layers']):
        stem = f'model.layers.{layer}.'
        names.append(stem + 'input_layernorm.weight')
        for op in ('q', 'k', 'v'):
            names.extend(stem + f'self_attn.{op}_proj.' + suffix for suffix in ('weight', 'bias'))
        names += [stem + 'self_attn.o_proj.weight', stem + 'post_attention_layernorm.weight']
        names.extend(stem + f'mlp.{op}_proj.weight' for op in ('gate', 'up', 'down'))
    names.append('model.norm.weight')
    if len(names) != len(manifest['tensors']) or set(names) != {t['name'] for t in manifest['tensors']}:
        raise ValueError('unsupported tensor inventory')
    return names


def write_pack(path, tensors, blobs, metadata, aliases=None):
    """tensors: ordered (name, FP32 array or safetensors slice); bounded row export.

    Only the exporter owns this serialization. verify_pack.py deliberately does
    not import it. Files are created exclusively; failed partials are retained.
    """
    aliases = aliases or {}
    entries = []
    sources = []
    for name, tensor in tensors:
        shape = list(tensor.get_shape() if hasattr(tensor, 'get_shape') else tensor.shape)
        if len(shape) not in (1, 2) or min(shape) < 1:
            raise ValueError('unsupported tensor shape')
        kinds = [(name, 1, shape), (name + '.scale', 2, [shape[0], (shape[1]+63)//64])] if len(shape) == 2 else [(name, 3, shape)]
        for entry_name, kind, dims in kinds:
            entries.append(dict(name=entry_name, kind=kind, shape=dims, region=1, alias=NONE))
            sources.append(tensor)
    for alias, target in aliases.items():
        for suffix in ('', '.scale'):
            targets = [i for i, e in enumerate(entries) if e['name'] == target + suffix]
            if len(targets) != 1:
                raise ValueError('missing alias target')
            entry = dict(entries[targets[0]], name=alias+suffix, alias=targets[0])
            entries.append(entry)
            sources.append(None)
    entries.append(dict(name='metadata.json', kind=4, shape=[], region=1, alias=NONE))
    sources.append(canonical(metadata))
    for name, data in sorted(blobs.items()):
        entries.append(dict(name='tokenizer/' + name, kind=4, shape=[], region=2, alias=NONE))
        sources.append(data)
    if not 1 <= len(entries) <= 4096 or len({e['name'] for e in entries}) != len(entries):
        raise ValueError('invalid directory count/names')
    start = align(192 + len(entries)*256)
    cursor = start
    regions = {1: 0, 2: 0}
    for entry, source in zip(entries, sources):
        if entry['alias'] != NONE:
            target = entries[entry['alias']]
            entry.update({k: target[k] for k in ('offset', 'length', 'region_offset')})
            continue
        kind, shape = entry['kind'], entry['shape']
        length = (shape[0] * align(shape[1]) if kind == 1 else
                  int(np.prod(shape))*4 if kind in (2, 3) else len(source))
        if not length:
            raise ValueError('empty payload')
        entry.update(offset=cursor, length=length, region_offset=regions[entry['region']])
        cursor = align(cursor + length)
        regions[entry['region']] = align(entry['region_offset'] + length)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x+b') as out:
        out.write(bytes(start))
        for entry, source in zip(entries, sources):
            if entry['alias'] != NONE:
                entry['sha256'] = entries[entry['alias']]['sha256']
                continue
            out.seek(entry['offset'])
            h = hashlib.sha256()
            def emit(data):
                out.write(data)
                h.update(data)
            kind = entry['kind']
            if kind in (1, 2):
                n, k = (list(source.get_shape()) if hasattr(source, 'get_shape') else source.shape)
                for lo in range(0, n, 256):
                    q, scale = quantize(source[lo:min(n, lo+256), :])
                    if kind == 1:
                        emit(np.pad(q, ((0, 0), (0, align(k)-k))).tobytes())
                    else:
                        emit(scale.astype('<f4').tobytes())
            elif kind == 3:
                data = np.asarray(source[:] if hasattr(source, 'get_shape') else source, dtype='<f4')
                if not np.isfinite(data).all():
                    raise ValueError('nonfinite parameter')
                emit(data.tobytes())
            else:
                emit(source)
            if out.tell() != entry['offset'] + entry['length']:
                raise ValueError('payload size mismatch')
            out.write(bytes(align(out.tell())-out.tell()))
            entry['sha256'] = h.hexdigest()
        directory = bytearray()
        for e in entries:
            name = e['name'].encode('ascii')
            if not 0 < len(name) < 128:
                raise ValueError('invalid name')
            directory += ENTRY.pack(name, e['kind'], 0x1000+e['kind'], len(e['shape']),
                                    int(e['alias'] != NONE), *(e['shape']+[0]*(4-len(e['shape']))),
                                    e['offset'], e['length'], e['region'], e['alias'],
                                    e['region_offset'], bytes.fromhex(e['sha256']), bytes(32))
        out.seek(192)
        out.write(directory)
        out.flush()
        out.seek(start)
        h = hashlib.sha256()
        for block in iter(lambda: out.read(1 << 20), b''):
            h.update(block)
        head = HEADER.pack(b'NXW8PK1\0', 1, 160, 0x01020304, LAYOUT, 64, 64, len(entries), 256,
                           192, start, cursor, hashlib.sha256(directory).digest(), h.digest(), bytes(32))
        head = head[:128] + hashlib.sha256(head[:128]).digest()
        out.seek(0)
        out.write(head)
    return dict(format='model-pack-v1', layout_id=LAYOUT, bytes=path.stat().st_size,
                sha256=digest(path), unique_region_bytes={str(k): v for k, v in regions.items()},
                directory=entries)


def export_full(path):
    lock = locked_sources()
    manifest_path = ROOT / 'docs/spec/operator-manifest.json'
    manifest = json.loads(manifest_path.read_text())
    names = consumption_order(manifest)
    metadata = dict(format='model-pack-v1', profile='qwen2.5-0.5b-application-v2',
                    numeric_version='w8a8-g64-fp32-v1', group_size=64,
                    dimensions=manifest['dimensions'], model_revision=lock['revision'],
                    model_lock_sha256=digest(ROOT/'docs/spec/application-v2-model-lock.json'),
                    operator_manifest_sha256=digest(manifest_path),
                    memory_map_sha256=digest(ROOT/'docs/spec/memory-map-v1.json'),
                    thresholds_sha256=digest(ROOT/'configs/t05-thresholds.json'),
                    tokenizer_files=lock['tokenizer_files'],
                    generation=dict(eos_token_id=151645, bos_token_id=151643, pad_token_id=151643,
                                    max_input_tokens=512, max_new_tokens=128, max_context=640,
                                    do_sample=False, num_beams=1, repetition_penalty=1.0,
                                    use_model_defaults=False),
                    rope_theta=1000000.0, rms_norm_eps=1e-6,
                    config=json.loads((ROOT/lock['local_path']/'config.json').read_text()))
    blobs = {n: (ROOT/lock['tokenizer_local_path']/n).read_bytes() for n in lock['tokenizer_files']}
    with safe_open(ROOT/lock['local_path']/'model.safetensors', framework='numpy') as checkpoint:
        if set(checkpoint.keys()) != set(names):
            raise ValueError('checkpoint inventory mismatch')
        for t in manifest['tensors']:
            s = checkpoint.get_slice(t['name'])
            if s.get_shape() != t['shape'] or s.get_dtype() != 'F32':
                raise ValueError('checkpoint shape/dtype mismatch')
        result = write_pack(path, [(n, checkpoint.get_slice(n)) for n in names], blobs,
                            metadata, manifest['aliases'])
    result['model_lock_sha256'] = metadata['model_lock_sha256']
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    result = export_full(args.output)
    args.output.with_suffix('.manifest.json').write_bytes(canonical(result))
    print(json.dumps({k: v for k, v in result.items() if k != 'directory'}))


if __name__ == '__main__':
    main()
