#!/usr/bin/env python3
"""Check the positive control and the specific P/V/Y before/after evidence."""
import argparse
import hashlib
import json
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rows(path):
    return {x['case']: x for x in map(json.loads, path.read_text().splitlines()) if 'case' in x}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--before', type=Path, required=True)
    p.add_argument('--after', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    before, after = (json.loads((root / 'receipt.json').read_text()) for root in (a.before, a.after))
    assert before['mode'] == 'v3_expected_negative' and after['mode'] == 'fixed'
    assert before['sources_unchanged_during_run'] and after['sources_unchanged_during_run']
    assert before['simulation_compatibility'] == after['simulation_compatibility']
    for name in ('pv_boundary_component.sv', 'pv_boundary_sim.cpp', 'run_pv_boundaries.py', 'lower_fp_pipeline.py'):
        old = before['source_sha256'][str(Path(before['fixture_source']) / name)]
        new = after['source_sha256'][str(Path(after['fixture_source']) / name)]
        assert old == new, 'before/after fixture differs: ' + name
    compared, negatives, source_changes = [], [], []
    for source, digest in before['source_sha256'].items():
        root = Path(before['rtl_source'])
        if not Path(source).is_relative_to(root):
            continue
        relative = Path(source).relative_to(root)
        other = after['source_sha256'][str(Path(after['rtl_source']) / relative)]
        if digest != other:
            source_changes.append({'path': str(relative), 'before_sha256': digest, 'after_sha256': other})
    assert [x['path'] for x in source_changes] == ['rtl/sfu/nx_opt11_dispatch.sv']
    for maximum in (64, 512):
        key = 'max' + str(maximum)
        assert before['cases'][key]['result'] == after['cases'][key]['result'] == 'PASS_EXPECTATIONS'
        old, new = (rows(root / (key + '-results.jsonl')) for root in (a.before, a.after))
        assert old.keys() == new.keys()
        for name, value in old.items():
            if value['status'] == 0:
                assert new[name]['status'] == 0
                for field in ('length', 'local_p', 'p', 'v', 'y', 'words_checked', 'read_bytes', 'write_bytes', 'command_hash', 'output_hash'):
                    assert value[field] == new[name][field], (maximum, name, field)
                compared.append({'max_length': maximum, 'case': name,
                                 'command_hash': value['command_hash'], 'output_hash': value['output_hash'],
                                 'words': value['words_checked']})
        for name, path in (
            ('local_y_3840_len1', 'Y'),
            ('external_p_4080_len1', 'P'),
            ('short_v_ff0_len1', 'V'),
        ):
            b, f = old[name], new[name]
            assert b['result'] == 'EXPECTED_NEGATIVE' and b['status'] == -11 and not b['success']
            assert b['page_rejections'] == 1 and b['rejected_path'] == path
            assert f['result'] == 'PASS' and f['status'] == 0 and f['success'] and f['page_rejections'] == 0
            trace = [x for x in map(json.loads, (a.after / (key + '-dma.jsonl')).read_text().splitlines())
                     if x['case'] == name and x['path'] == path]
            sizes = [x['bytes'] for x in trace]
            assert sizes == {'P': [16, 512, 512, 512, 240], 'Y': [256, 512, 512, 512], 'V': [16, 240]}[path]
            assert all(x['page_ok'] and x['response'] == 0 for x in trace)
            negatives.append({'max_length': maximum, 'case': name, 'path': path,
                              'before_status': b['status'], 'before_rejected_address': b['rejected_address'],
                              'before_rejected_bytes': b['rejected_bytes'], 'after_status': f['status'],
                              'after_sizes': sizes, 'after_words_checked': f['words_checked']})
        for name in ('aligned_ddr_len1', 'aligned_ddr_len63', 'aligned_ddr_len64', 'production_first_group_len1'):
            assert old[name]['status'] == new[name]['status'] == 0
    output = {
        'result': 'PASS',
        'scope': 'Same fixture and FP representation for both trees. Compare all originally successful cases by exact output and DMA command digest; require distinct P/V/Y page-rejection negatives and successful legal split commands after the patch.',
        'comparison_script_sha256': sha(Path(__file__)),
        'before_receipt_sha256': sha(a.before / 'receipt.json'),
        'after_receipt_sha256': sha(a.after / 'receipt.json'),
        'production_source_changes': source_changes,
        'same_output_and_commands': compared,
        'page_rejection_to_bitwise_success': negatives,
    }
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(output, indent=2) + '\n')
    print(json.dumps({'result': 'PASS', 'positive_pairs': len(compared), 'negative_pairs': len(negatives)}))


if __name__ == '__main__':
    main()
