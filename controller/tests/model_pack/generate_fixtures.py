#!/usr/bin/env python3
"""Generate deterministic legal packs and resealed malformed packs for T14/15/18."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from model_tools.export import write_pack, canonical, digest
from model_tools import numeric_v1 as ref

IDENTITY_FILES = ['tests/model_pack/generate_fixtures.py', 'tests/model_pack/check_fixtures.py',
                  'model_tools/export.py', 'model_tools/verify_pack.py', 'model_tools/numeric_v1.py',
                  'configs/t05-thresholds.json', 'docs/spec/application-v2-model-lock.json',
                  'docs/spec/memory-map-v1.json']


def reseal(data, payload=False):
    """For negative tests only: bypass hashes to exercise structural/numeric checks."""
    count = struct.unpack_from('<I', data, 32)[0]
    start = struct.unpack_from('<Q', data, 48)[0]
    if payload:
        for i in range(count):
            at = 192+i*256
            offset, length = struct.unpack_from('<QQ', data, at+160)
            data[at+192:at+224] = hashlib.sha256(data[offset:offset+length]).digest()
        data[96:128] = hashlib.sha256(data[start:]).digest()
    data[64:96] = hashlib.sha256(data[192:192+count*256]).digest()
    data[128:160] = hashlib.sha256(data[:128]).digest()
    return data


def malformed(good):
    count = struct.unpack_from('<I', good, 32)[0]
    names = {good[192+i*256:192+i*256+128].split(b'\0')[0].decode(): 192+i*256 for i in range(count)}
    weight = names['model.embed_tokens.weight']
    scale = names['model.embed_tokens.weight.scale']
    alias = names['lm_head.weight']
    bias = names['fixture.bias']
    cases = []
    def add(name, error, edit, seal=True, payload=False):
        data = bytearray(good)
        edit(data)
        cases.append((name, error, bytes(reseal(data, payload) if seal else data)))
    add('truncated', 'E_BOUNDS', lambda b: b.__delitem__(slice(-17, None)), False)
    add('wrong-version', 'E_VERSION', lambda b: struct.pack_into('<I', b, 8, 2))
    offset = struct.unpack_from('<Q', good, weight+160)[0]
    add('corrupt-payload', 'E_CHECKSUM', lambda b: b.__setitem__(offset+2, b[offset+2]^1), False)
    add('corrupt-header', 'E_CHECKSUM', lambda b: b.__setitem__(56, b[56]^1), False)
    add('address-overflow', 'E_OVERFLOW', lambda b: struct.pack_into('<Q', b, weight+184, 0xffffffffffffffc0))
    add('address-outside-window', 'E_BOUNDS', lambda b: struct.pack_into('<Q', b, weight+184, 671088640))
    add('file-offset-overflow', 'E_OVERFLOW', lambda b: struct.pack_into('<Q', b, weight+160, 0xffffffffffffffc0))
    add('file-offset-outside', 'E_BOUNDS', lambda b: struct.pack_into('<Q', b, weight+160, len(b)))
    add('illegal-alias', 'E_ALIAS', lambda b: struct.pack_into('<I', b, alias+180, (bias-192)//256))
    add('alias-self-cycle', 'E_ALIAS', lambda b: struct.pack_into('<I', b, alias+180, (alias-192)//256))
    add('duplicate-name', 'E_DUPLICATE', lambda b: b.__setitem__(slice(bias,bias+128), b[weight:weight+128]))
    add('overlap', 'E_OVERLAP', lambda b: struct.pack_into('<Q', b, bias+160, offset))
    def physical_overlap(b):
        struct.pack_into('<Q', b, bias+184, 0)
    add('load-overlap', 'E_OVERLAP', physical_overlap)
    def huge(b):
        struct.pack_into('<II', b, scale+144, 0xffffffff, 0xffffffff)
    add('shape-overflow', 'E_OVERFLOW', huge)
    add('unknown-layout', 'E_LAYOUT', lambda b: struct.pack_into('<I', b, 20, 1))
    add('wrong-endian', 'E_ENDIAN', lambda b: struct.pack_into('<I', b, 16, 0x04030201))
    add('misaligned', 'E_ALIGNMENT', lambda b: struct.pack_into('<Q', b, bias+184, 1))
    add('forbidden-int8', 'E_NUMERIC', lambda b: b.__setitem__(offset, 128), payload=True)
    scale_offset = struct.unpack_from('<Q', good, scale+160)[0]
    add('zero-scale-nonzero-q', 'E_NUMERIC', lambda b: struct.pack_into('<I', b, scale_offset, 0), payload=True)
    add('negative-zero-scale', 'E_NUMERIC', lambda b: struct.pack_into('<I', b, scale_offset, 0x80000000), payload=True)
    add('nonfinite-scale', 'E_NUMERIC', lambda b: struct.pack_into('<I', b, scale_offset, 0x7fc00000), payload=True)
    return cases


def generate(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    identities = {p: digest(ROOT/p) for p in IDENTITY_FILES}
    cases = []
    memory = json.loads((ROOT/'docs/spec/memory-map-v1.json').read_text())
    bases = {1: int(next(r['base'] for r in memory['ddr_regions'] if r['name']=='weights'), 0),
             2: int(next(r['base'] for r in memory['ddr_regions'] if r['name']=='tokenizer'), 0)}
    for case_id, m, n, k, seed in [('legal-rvv',4,129,896,1), ('legal-tail',4,129,65,7), ('legal-down',1,3,4864,19)]:
        folder = out/case_id
        folder.mkdir()
        rng = np.random.default_rng(seed)
        w = rng.standard_normal((n,k), dtype=np.float32)
        w[0] = 0
        w[0,:8] = [127, -127, .5, 1.5, 2.5, -.5, -1.5, -2.5]
        w[1] = 0
        w[-1] = -127
        x = rng.standard_normal((m,k), dtype=np.float32)
        x[0,:8] = [127, -127, .5, 1.5, 2.5, -.5, -1.5, -2.5]
        if m > 1:
            x[1] = 0
            x[-1] = 127
        bias = np.linspace(-.25, .25, n, dtype=np.float32)
        norm = np.linspace(.5, 1.5, k, dtype=np.float32)
        aq, sa = ref.quantize(x)
        q, scale = ref.quantize(w)
        y, dots = ref.linear_quantized(aq, sa, q, scale, bias)
        data = dict(x=x, w=w, bias=bias, norm=norm, aq=aq, sa=sa, q=q, scale=scale, y=y, dots=dots)
        arrays = {}
        for name, array in data.items():
            file = folder/(name+'.npy')
            np.save(file, array, allow_pickle=False)
            arrays[name] = dict(file=str(file.relative_to(out)), sha256=digest(file), bytes=file.stat().st_size,
                dtype=array.dtype.str, shape=list(array.shape), stride_bytes=list(array.strides), endianness='little',
                role='input' if name in ('x','w','bias','norm') else 'golden', layout_id=None,
                logical_view='C-order logical array; NPY is not the pack ABI')
        metadata = dict(format='model-pack-v1', profile='fixture-v1', numeric_version=ref.VERSION,
                        group_size=64, seed=seed, model_source='SYNTHETIC_TENSOR_FIXTURE_NOT_FULL_NETWORK',
                        model_lock_sha256=identities['docs/spec/application-v2-model-lock.json'])
        result = write_pack(folder/'model.nxpack', [('model.embed_tokens.weight', w),
                            ('fixture.bias', bias), ('fixture.norm', norm)],
                            {'config.json': b'{"fixture":true}\n', 'vocab.json': '{"测试":0}\n'.encode()},
                            metadata, {'lm_head.weight':'model.embed_tokens.weight'})
        views = []
        for e in result['directory']:
            shape = e['shape']
            strides = [((shape[1]+63)//64)*64,1] if e['kind']==1 else [shape[1]*4,4] if e['kind']==2 else [4] if e['kind']==3 else None
            views.append(dict(name=e['name'], shape=shape, dtype={1:'int8',2:'float32',3:'float32',4:'bytes'}[e['kind']],
                endianness='little', stride_bytes=strides, group_size=64 if e['kind'] in (1,2) else None,
                layout_id=0x1000+e['kind'], logical_view_id=1 if e['kind']!=4 else None,
                file_offset=e['offset'], length=e['length'], region_offset=e['region_offset'],
                soc_address=bases[e['region']]+e['region_offset'], coral_local_address=None,
                sha256=e['sha256'], alias_of=e['alias'] if e['alias']!=0xffffffff else None))
        cases.append(dict(case_id=case_id, seed=seed, format_version=1, layout_id=0x1001, group_size=64,
            pack=dict(file=f'{case_id}/model.nxpack', sha256=result['sha256'], bytes=result['bytes']),
            expected_error=None, arrays=arrays, tensor_views=views,
            consumers={'T14':'stream and verify each unique payload, output-row tail and zero K padding',
                       'T15':'W8 group dots and FP32 restored output' if k!=65 else 'unsupported K=65 must return NX_EUNSUPPORTED under T08; reader/generic tail semantics only',
                       'T18':'successful validate/load/seal; PROTOCOL_BOOT destination starts empty'},
            rtl_status='NOT_EXECUTED'))
    for name, error, data in malformed((out/'legal-rvv/model.nxpack').read_bytes()):
        file = out/(name+'.nxpack')
        file.write_bytes(data)
        cases.append(dict(case_id=name, format_version=1, layout_id=0x1001, group_size=64,
            pack=dict(file=file.name, bytes=len(data), sha256=digest(file)), expected_error=error,
            derived_from='legal-rvv', consumers={'T14':'reject before backend submission',
            'T15':'reject before arithmetic dispatch', 'T18':'reject, remain unready, never expose partial load'},
            rtl_status='NOT_EXECUTED'))
    result = dict(schema_version=1, producer='T10', verification_mode='golden_fixture',
        numeric_version=ref.VERSION, generator='tests/model_pack/generate_fixtures.py',
        checker='tests/model_pack/check_fixtures.py', identities=identities,
        model_identity='synthetic fixtures; numeric/model-lock identity pinned, no application dataset',
        tolerance_contract='configs/t05-thresholds.json', pack_format='model-pack-v1', cases=cases)
    (out/'manifest.json').write_bytes(canonical(result))
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('output', type=Path)
    a = p.parse_args()
    r = generate(a.output)
    print(json.dumps(dict(cases=len(r['cases']), manifest_sha256=digest(a.output/'manifest.json'))))
