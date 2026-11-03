#!/usr/bin/env python3
"""Independent scalar fixture oracle and CLI rejection audit. No writer imports."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from model_tools.verify_pack import verify, PackError, require


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def scalar_quant(x):
    q = np.zeros(x.shape, dtype=np.int8)
    scales = np.zeros((len(x), (x.shape[1]+63)//64), dtype='<f4')
    for r in range(len(x)):
        for g in range(scales.shape[1]):
            values = x[r, g*64:(g+1)*64]
            peak = max(abs(float(v)) for v in values)
            s = np.float32(0) if peak == 0 else max(np.float32(peak)/np.float32(127), np.finfo(np.float32).tiny)
            scales[r,g] = s
            for i, v in enumerate(values):
                q[r,g*64+i] = 0 if s == 0 else max(-127, min(127, round(float(np.float32(v/s)))))
    return q, scales


def check(out, log_dir=None):
    idx = json.loads((out/'manifest.json').read_text())
    require(idx['numeric_version'] == 'w8a8-g64-fp32-v1' and idx['verification_mode']=='golden_fixture', 'E_SOURCE', 'fixture contract')
    for file, expected in idx['identities'].items():
        require(sha(ROOT/file) == expected, 'E_SOURCE', file)
    expected_ids = {'legal-rvv','legal-tail','legal-down','truncated','wrong-version','corrupt-payload',
        'corrupt-header','address-overflow','address-outside-window','file-offset-overflow',
        'file-offset-outside','illegal-alias','alias-self-cycle','duplicate-name','overlap','load-overlap',
        'shape-overflow','unknown-layout','wrong-endian','misaligned','forbidden-int8',
        'zero-scale-nonzero-q','negative-zero-scale','nonfinite-scale'}
    require(len(idx['cases']) == len(expected_ids) and {c['case_id'] for c in idx['cases']} == expected_ids,
            'E_SOURCE', 'missing/duplicate required fixtures')
    if log_dir:
        log_dir.mkdir(parents=True, exist_ok=False)
    results = []
    checked = 0
    for case in idx['cases']:
        spec = case['pack']
        path = out/spec['file']
        require(path.stat().st_size == spec['bytes'] and sha(path) == spec['sha256'], 'E_SOURCE', case['case_id'])
        if case['expected_error']:
            try:
                verify(path)
            except PackError as e:
                actual = e.code
            else:
                actual = 'ACCEPTED'
            require(actual == case['expected_error'], 'E_REFERENCE', f"{case['case_id']}: {actual}")
            result = dict(case_id=case['case_id'], status='PASS_DETECTED', expected_error=actual)
            if log_dir:
                # Preserve raw nonzero runs, do not rewrite the reader's FAIL as PASS.
                argv = [sys.executable, str(ROOT/'model_tools/verify_pack.py'), str(path)]
                proc = subprocess.run(argv, capture_output=True, text=True, timeout=30)
                (log_dir/(case['case_id']+'.stdout.log')).write_text(proc.stdout)
                (log_dir/(case['case_id']+'.stderr.log')).write_text(proc.stderr)
                require(proc.returncode == 1 and json.loads(proc.stdout)['error'] == actual,
                        'E_REFERENCE', 'negative CLI exit/result')
                result.update(argv=argv, actual_exit_code=proc.returncode, raw_status='FAIL')
            results.append(result)
            checked += 1
            continue
        pack = verify(path, expected_sha256=spec['sha256'])
        arrays = {}
        for key, s in case['arrays'].items():
            file = out/s['file']
            require(sha(file)==s['sha256'] and file.stat().st_size==s['bytes'], 'E_SOURCE', key)
            a = np.load(file, allow_pickle=False)
            require(a.dtype.str==s['dtype'] and list(a.shape)==s['shape'] and list(a.strides)==s['stride_bytes']
                    and s['endianness']=='little', 'E_SOURCE', 'tensor metadata')
            arrays[key] = a
        q, sw = scalar_quant(arrays['w'])
        aq, sa = scalar_quant(arrays['x'])
        for key, a in [('q',q),('scale',sw),('aq',aq),('sa',sa)]:
            require(a.shape==arrays[key].shape and a.dtype==arrays[key].dtype and
                    a.tobytes()==arrays[key].tobytes(), 'E_REFERENCE', key)
            checked += a.size
        for name, a in [('model.embed_tokens.weight', q),('model.embed_tokens.weight.scale', sw),
                        ('lm_head.weight',q),('lm_head.weight.scale',sw),
                        ('fixture.bias',arrays['bias']),('fixture.norm',arrays['norm'])]:
            require(pack.rows(name).tobytes()==a.tobytes(), 'E_REFERENCE', name)
            checked += a.size
        for view in case['tensor_views']:
            e = pack.entries[view['name']]
            shape = e['shape']
            stride = [((shape[1]+63)//64)*64,1] if e['kind']==1 else [shape[1]*4,4] if e['kind']==2 else [4] if e['kind']==3 else None
            require(e['shape']==view['shape'] and e['offset']==view['file_offset'] and
                    e['region_offset']==view['region_offset'] and e['soc_address']==view['soc_address'] and
                    e['sha256']==view['sha256'] and e['length']==view['length'] and
                    e['layout_id']==view['layout_id'] and e['alias_of']==view['alias_of'] and
                    view['stride_bytes']==stride and view['endianness']=='little' and
                    view['dtype']=={1:'int8',2:'float32',3:'float32',4:'bytes'}[e['kind']] and
                    view['group_size']==(64 if e['kind'] in (1,2) else None) and
                    view['logical_view_id']==(1 if e['kind']!=4 else None) and
                    view['coral_local_address'] is None, 'E_SOURCE', 'fixture view')
        require(len(case['tensor_views'])==len(pack.entries) and
                {v['name'] for v in case['tensor_views']}==set(pack.entries), 'E_SOURCE', 'view coverage')
        y = np.zeros((len(aq),len(q)), dtype='<f4')
        dots = np.zeros((sa.shape[1],len(aq),len(q)), dtype='<i4')
        for g in range(sa.shape[1]):
            lo, hi = g*64, min(q.shape[1], (g+1)*64)
            for m in range(len(aq)):
                for n in range(len(q)):
                    acc = sum(int(aq[m,k])*int(q[n,k]) for k in range(lo,hi))
                    dots[g,m,n] = acc
                    restored = np.float32(np.float32(acc)*sa[m,g])
                    y[m,n] = np.float32(y[m,n]+np.float32(restored*sw[n,g]))
        y = (y+arrays['bias']).astype('<f4')
        require(dots.tobytes()==arrays['dots'].tobytes(), 'E_REFERENCE', 'group dots')
        require(y.tobytes()==arrays['y'].tobytes(), 'E_REFERENCE', 'ordered FP32 output')
        checked += dots.size+y.size
        results.append(dict(case_id=case['case_id'], status='PASS', pack=pack.summary,
                            group_dots=dots.size, output_elements=y.size))
    return dict(status='PASS', verification_mode='golden_fixture', rtl_consumption='NOT_EXECUTED',
                manifest_sha256=sha(out/'manifest.json'), cases=results, checks=checked,
                legal_packs=3, rejected_packs=21)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('fixtures', type=Path)
    p.add_argument('--report', type=Path, required=True)
    p.add_argument('--negative-logs', type=Path)
    a = p.parse_args()
    r = check(a.fixtures, a.negative_logs)
    a.report.write_text(json.dumps(r, indent=2)+'\n')
    print(json.dumps({k:v for k,v in r.items() if k!='cases'}))
