#!/usr/bin/env python3
"""Independent model-pack-v1 parser. No exporter/numeric-oracle imports.

All metadata, file spans and load spans are checked before payload access.
Checksums detect corruption, not malicious replacement of an entire package;
the loader must additionally pin the expected whole-file SHA-256.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


class PackError(ValueError):
    def __init__(self, code, detail):
        super().__init__(code + ': ' + detail)
        self.code = code


def require(ok, code, detail):
    if not ok:
        raise PackError(code, detail)


def sha_range(stream, offset, length):
    stream.seek(offset)
    h = hashlib.sha256()
    while length:
        data = stream.read(min(length, 1 << 20))
        require(data, 'E_BOUNDS', 'truncated payload')
        h.update(data)
        length -= len(data)
    return h.digest()


def product(shape):
    p = 1
    for d in shape:
        require(d > 0, 'E_SHAPE', 'zero dimension')
        require(p <= (2**64-1)//d, 'E_OVERFLOW', 'shape product')
        p *= d
    return p


def end_of(offset, length, bits=64):
    require(0 <= offset < 2**bits and 0 < length < 2**bits and
            length <= 2**bits-1-offset, 'E_OVERFLOW', 'offset + length')
    return offset + length


def strict_json(data):
    def pairs(items):
        out = {}
        for key, value in items:
            require(key not in out, 'E_METADATA', 'duplicate JSON key')
            out[key] = value
        return out
    try:
        return json.loads(data, object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))
    except (ValueError, UnicodeError) as e:
        raise PackError('E_METADATA', str(e)) from e


class Pack:
    """A fully verified immutable file; rows() returns logical data, without padding.

    Callers must keep the file immutable after validation (the board equivalent
    is loader seal/ownership). No model-sized FP32 allocation or transpose.
    """
    def __init__(self, path, entries, metadata, summary):
        self.path = Path(path)
        self.entries = {e['name']: e for e in entries}
        self.metadata = metadata
        self.summary = summary

    def rows(self, name, lo=0, hi=None):
        e = self.entries[name]
        shape = e['shape']
        require(e['kind'] != 4, 'E_SHAPE', 'blob is not a tensor')
        hi = shape[0] if hi is None else hi
        require(0 <= lo < hi <= shape[0], 'E_BOUNDS', 'row selection')
        width = ((shape[1]+63)//64*64 if e['kind'] == 1 else shape[1]) if len(shape) == 2 else 1
        item = 1 if e['kind'] == 1 else 4
        with self.path.open('rb') as f:
            f.seek(e['offset'] + lo*width*item)
            data = f.read((hi-lo)*width*item)
        require(len(data) == (hi-lo)*width*item, 'E_BOUNDS', 'file changed')
        array = np.frombuffer(data, dtype='i1' if item == 1 else '<f4')
        return array.reshape(hi-lo, width)[:, :shape[1]] if len(shape) == 2 else array

    def blob(self, name):
        e = self.entries[name]
        require(e['kind'] == 4, 'E_SHAPE', 'not a blob')
        with self.path.open('rb') as f:
            f.seek(e['offset'])
            data = f.read(e['length'])
        require(len(data) == e['length'], 'E_BOUNDS', 'file changed')
        return data


def verify(path, memory_map=None, expected_sha256=None):
    path = Path(path)
    memory_map = memory_map or json.loads((ROOT/'docs/spec/memory-map-v1.json').read_text())
    regions = {1: next(r for r in memory_map['ddr_regions'] if r['name'] == 'weights'),
               2: next(r for r in memory_map['ddr_regions'] if r['name'] == 'tokenizer')}
    size = path.stat().st_size
    entries = []
    with path.open('rb') as f:
        raw = f.read(160)
        require(len(raw) == 160, 'E_BOUNDS', 'truncated header')
        magic = raw[:8]
        v, hsize, endian, layout, group, alignment, count, esize = struct.unpack_from('<8I', raw, 8)
        directory_offset, data_offset, total = struct.unpack_from('<3Q', raw, 40)
        require(magic == b'NXW8PK1\0', 'E_MAGIC', 'magic')
        require(v == 1 and hsize == 160 and esize == 256, 'E_VERSION', 'format version or structure size')
        require(endian == 0x01020304, 'E_ENDIAN', 'little endian marker')
        require(layout == 0x1001 and group == 64, 'E_LAYOUT', 'layout/group_size')
        require(alignment == 64, 'E_ALIGNMENT', 'alignment')
        require(hashlib.sha256(raw[:128]).digest() == raw[128:], 'E_CHECKSUM', 'header')
        require(1 <= count <= 4096, 'E_BOUNDS', 'directory count')
        require(total == size, 'E_BOUNDS', 'file length (truncation or trailing bytes)')
        require(directory_offset == 192 and data_offset == ((192+count*256+63)//64)*64 and
                data_offset < size and size % 64 == 0, 'E_BOUNDS', 'directory/data span')
        require(f.read(32) == bytes(32), 'E_RESERVED', 'header padding')
        directory = f.read(count*256)
        require(hashlib.sha256(directory).digest() == raw[64:96], 'E_CHECKSUM', 'directory')
        seen = set()
        file_ranges = []
        load_ranges = {1: [], 2: []}
        for index in range(count):
            record = directory[index*256:(index+1)*256]
            name_raw = record[:128]
            stop = name_raw.find(b'\0')
            require(0 < stop < 128 and name_raw[stop:] == bytes(128-stop), 'E_METADATA', 'name encoding/padding')
            try:
                name = name_raw[:stop].decode('ascii')
            except UnicodeError as e:
                raise PackError('E_METADATA', 'name encoding') from e
            require(re.fullmatch(r'[A-Za-z0-9_./-]+', name) and '..' not in name and not name.startswith('/'),
                    'E_METADATA', 'name')
            require(name not in seen, 'E_DUPLICATE', name)
            seen.add(name)
            kind, entry_layout, rank, flags, *dims = struct.unpack_from('<8I', record, 128)
            offset, length = struct.unpack_from('<2Q', record, 160)
            region, alias = struct.unpack_from('<2I', record, 176)
            region_offset = struct.unpack_from('<Q', record, 184)[0]
            require(record[224:] == bytes(32), 'E_RESERVED', name)
            require(kind in (1, 2, 3, 4) and entry_layout == 0x1000+kind, 'E_LAYOUT', name)
            require(flags in (0, 1) and (flags == 1) == (alias != 0xffffffff), 'E_ALIAS', name)
            require(region in regions, 'E_BOUNDS', 'load region')
            require(rank == (2 if kind in (1, 2) else 1 if kind == 3 else 0) and not any(dims[rank:]),
                    'E_SHAPE', name)
            shape = dims[:rank]
            if rank:
                elements = product(shape)
                expected = shape[0]*((shape[1]+63)//64*64) if kind == 1 else elements*4
                require(expected < 2**64, 'E_OVERFLOW', 'tensor bytes')
                require(length == expected, 'E_SHAPE', 'byte length: '+name)
            end = end_of(offset, length)
            load_end = end_of(region_offset, length)
            base = int(regions[region]['base'], 0)
            end_of(base + region_offset, length, 32)
            require(offset >= data_offset and end <= size and load_end <= regions[region]['size_bytes'],
                    'E_BOUNDS', name)
            require(offset % 64 == region_offset % 64 == 0, 'E_ALIGNMENT', name)
            require((kind == 4 and name.startswith('tokenizer/')) == (region == 2), 'E_METADATA', 'region/type')
            entry = dict(name=name, kind=kind, layout_id=entry_layout, shape=shape, offset=offset,
                         length=length, region=region, region_offset=region_offset,
                         soc_address=base+region_offset, alias_of=alias if flags else None,
                         sha256=record[192:224].hex())
            if flags:
                require(alias < index, 'E_ALIAS', 'forward/self alias')
                target = entries[alias]
                suffix = '.scale' if kind == 2 else ''
                require(kind in (1, 2) and name == 'lm_head.weight'+suffix and
                        target['name'] == 'model.embed_tokens.weight'+suffix and target['alias_of'] is None,
                        'E_ALIAS', 'only embedding/head sharing is allowed')
                require(all(entry[k] == target[k] for k in ('kind','layout_id','shape','offset','length',
                                                         'region','region_offset','sha256')), 'E_ALIAS', name)
            else:
                file_ranges.append((offset, end, name))
                load_ranges[region].append((region_offset, load_end, name))
            entries.append(entry)
        # Check overlap before enforcing canonical compact order for meaningful errors.
        for spans in [file_ranges, *load_ranges.values()]:
            ordered = sorted(spans)
            for a, b in zip(ordered, ordered[1:]):
                require(a[1] <= b[0], 'E_OVERLAP', a[2]+' / '+b[2])
        cursor = data_offset
        region_cursors = {1: 0, 2: 0}
        for e in entries:
            if e['alias_of'] is not None:
                continue
            require(e['offset'] == cursor and e['region_offset'] == region_cursors[e['region']],
                    'E_BOUNDS', 'noncanonical gap/order')
            end = e['offset'] + e['length']
            cursor = (end+63)//64*64
            region_cursors[e['region']] = (e['region_offset']+e['length']+63)//64*64
            f.seek(end)
            require(f.read(cursor-end) == bytes(cursor-end), 'E_RESERVED', 'payload padding')
            require(sha_range(f, e['offset'], e['length']).hex() == e['sha256'], 'E_CHECKSUM', e['name'])
        require(cursor == size, 'E_BOUNDS', 'unclaimed payload')
        require(sha_range(f, data_offset, size-data_offset) == raw[96:128], 'E_CHECKSUM', 'payload')
        whole_sha = sha_range(f, 0, size).hex()
        if expected_sha256 is not None:
            require(whole_sha == expected_sha256, 'E_CHECKSUM', 'pinned whole-file identity')
    pack = Pack(path, entries, {}, {})
    require('metadata.json' in pack.entries and pack.entries['metadata.json']['kind'] == 4 and
            pack.entries['metadata.json']['length'] <= 1 << 20, 'E_METADATA', 'metadata.json')
    metadata = strict_json(pack.blob('metadata.json'))
    require(isinstance(metadata, dict) and metadata.get('format') == 'model-pack-v1' and
            metadata.get('numeric_version') == 'w8a8-g64-fp32-v1' and metadata.get('group_size') == 64 and
            metadata.get('profile') in ('fixture-v1', 'qwen2.5-0.5b-application-v2'), 'E_METADATA', 'contract')
    count_q = count_scale = count_fp32 = 0
    for e in entries:
        if e['alias_of'] is not None or e['kind'] == 4:
            continue
        name = e['name']
        if e['kind'] == 2:
            require(name.endswith('.scale') and name[:-6] in pack.entries and
                    pack.entries[name[:-6]]['kind'] == 1, 'E_SHAPE', 'orphan scale')
        if e['kind'] == 1:
            n, k = e['shape']
            scales = pack.entries.get(name+'.scale')
            require(scales and scales['kind'] == 2 and scales['shape'] == [n, (k+63)//64] and
                    scales['alias_of'] is None, 'E_SHAPE', 'missing/mismatched scales')
            for lo in range(0, n, 256):
                hi = min(n, lo+256)
                q = pack.rows(name, lo, hi)
                scale = pack.rows(name+'.scale', lo, hi)
                require(not np.any(q == -128), 'E_NUMERIC', 'forbidden -128')
                require(np.isfinite(scale).all() and not np.signbit(scale).any() and
                        not np.any((scale > 0) & (scale < np.finfo(np.float32).tiny)), 'E_NUMERIC', 'invalid scale')
                padded = np.pad(q, ((0,0), (0, ((k+63)//64)*64-k))).reshape(hi-lo, -1, 64)
                require(not np.any(np.any(padded != 0, axis=2) & (scale == 0)), 'E_NUMERIC', 'nonzero q with zero scale')
                if k % 64:
                    physical = q.base.reshape(hi-lo, -1) if isinstance(q.base, np.ndarray) else None
                    require(physical is not None and not np.any(physical[:, k:]), 'E_NUMERIC', 'K padding')
            count_q += n*k
            count_scale += n*((k+63)//64)
        elif e['kind'] == 3:
            require(np.isfinite(pack.rows(name)).all(), 'E_NUMERIC', 'nonfinite parameter')
            count_fp32 += product(e['shape'])
    aliases = {e['name'] for e in entries if e['alias_of'] is not None}
    head_names = {'lm_head.weight', 'lm_head.weight.scale'}
    require((not head_names.intersection(pack.entries) and not aliases) or aliases == head_names,
            'E_ALIAS', 'head must alias both embedding weights and scales')
    if metadata['profile'] == 'qwen2.5-0.5b-application-v2':
        manifest_file = ROOT/'docs/spec/operator-manifest.json'
        lock_file = ROOT/'docs/spec/application-v2-model-lock.json'
        operator = strict_json(manifest_file.read_bytes())
        lock = strict_json(lock_file.read_bytes())
        require(metadata.get('operator_manifest_sha256') == hashlib.sha256(manifest_file.read_bytes()).hexdigest()
                and metadata.get('model_lock_sha256') == hashlib.sha256(lock_file.read_bytes()).hexdigest()
                and metadata.get('dimensions') == operator['dimensions'] and metadata.get('tokenizer_files') == lock['tokenizer_files'],
                'E_METADATA', 'full model identity')
        require(metadata.get('model_revision') == lock['revision'] and
                metadata.get('memory_map_sha256') == hashlib.sha256((ROOT/'docs/spec/memory-map-v1.json').read_bytes()).hexdigest() and
                metadata.get('thresholds_sha256') == hashlib.sha256((ROOT/'configs/t05-thresholds.json').read_bytes()).hexdigest(),
                'E_METADATA', 'source/contracts identity')
        require(metadata.get('generation') == dict(eos_token_id=151645, bos_token_id=151643,
            pad_token_id=151643, max_input_tokens=512, max_new_tokens=128, max_context=640,
            do_sample=False, num_beams=1, repetition_penalty=1.0, use_model_defaults=False),
            'E_METADATA', 'frozen generation policy')
        config = metadata.get('config')
        d = operator['dimensions']
        require(isinstance(config, dict) and all(config.get(k)==d[n] for k,n in
                [('num_hidden_layers','layers'),('hidden_size','hidden'),('intermediate_size','intermediate'),
                 ('num_attention_heads','q_heads'),('num_key_value_heads','kv_heads'),('vocab_size','vocab')])
                and config.get('tie_word_embeddings') is True and metadata.get('rope_theta')==1e6 and
                metadata.get('rms_norm_eps')==1e-6, 'E_METADATA', 'network configuration')
        expected_names = {'metadata.json'} | head_names | {'tokenizer/'+n for n in lock['tokenizer_files']}
        for tensor in operator['tensors']:
            name, shape = tensor['name'], tensor['shape']
            expected_names.add(name)
            require(name in pack.entries and pack.entries[name]['shape'] == shape and
                    pack.entries[name]['kind'] == (1 if len(shape)==2 else 3) and
                    pack.entries[name]['alias_of'] is None, 'E_METADATA', 'required tensor: '+name)
            if len(shape) == 2:
                expected_names.add(name+'.scale')
        require(set(pack.entries) == expected_names and aliases == head_names, 'E_METADATA', 'full model inventory')
        for name, spec in lock['tokenizer_files'].items():
            e = pack.entries['tokenizer/'+name]
            require(e['length'] == spec['bytes'] and e['sha256'] == spec['sha256'], 'E_METADATA', 'original tokenizer')
    pack.metadata = metadata
    pack.summary = dict(status='PASS', format='model-pack-v1', layout_id=0x1001, bytes=size,
                        sha256=whole_sha, entries=len(entries), aliases=len(aliases),
                        quantized_elements=count_q, scale_elements=count_scale, fp32_elements=count_fp32,
                        region_bytes={regions[r]['name']: n for r, n in region_cursors.items()})
    return pack


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pack', type=Path)
    parser.add_argument('--sha256')
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    try:
        result = verify(args.pack, expected_sha256=args.sha256).summary
        code = 0
    except (PackError, OSError) as e:
        result = dict(status='FAIL', error=getattr(e, 'code', 'E_IO'), detail=str(e))
        code = 1
    text = json.dumps(result, indent=2) + '\n'
    if args.report:
        args.report.write_text(text)
    print(text, end='')
    return code


if __name__ == '__main__':
    sys.exit(main())
