#!/usr/bin/env python3
"""Validate measured CPU variant runs and create a scoped comparison."""
import argparse
import hashlib
import json
from pathlib import Path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--runs', type=Path, required=True)
    p.add_argument('--generation', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    if a.output.exists():
        p.error('refusing existing comparison')
    gen = json.loads(a.generation.read_text())
    assert gen['exit_code'] == 0
    variants = list(gen['variants'])
    evidence = {}
    def read(name):
        path = a.runs / (name + '.json')
        raw = path.read_bytes()
        evidence[path.name] = hashlib.sha256(raw).hexdigest()
        value = json.loads(raw)
        assert value['process_exit_code'] == 0 and value['exit_code'] == 0xc021
        if 'build' in value:
            assert value['workload_validated'] is True
        return value
    counts = ('uart', 'total', 'window', 'exit_code', 'marker_starts', 'marker_stops')
    equivalent = []
    for index in range(5):
        original = read(f'original-probe{index}')
        reconstructed = read(f'reconstructed-probe{index}')
        global_cpu = read(f'global-probe{index}')
        assert all(original[k] == reconstructed[k] == global_cpu[k] for k in counts)
        assert original['binary_sha256'] == reconstructed['binary_sha256'] == global_cpu['binary_sha256']
        equivalent.append(index)
    baselines = {}
    for seed in ('debug', 'validation'):
        original = read(f'reconstructed-O3-tuned-{seed}-10')
        current = read(f'global-O3-tuned-{seed}-10')
        assert original['kernel_cycles'] == current['kernel_cycles']
        assert original['binary_sha256'] == current['binary_sha256']
        baselines[seed] = current
    rows = {}
    for variant in variants:
        row = {'coremark': {}, 'directed': {}}
        rtl = gen['variants'][variant]['files']['T09Cpu.v']
        for index in range(5):
            value = read(f'{variant}-probe{index}')
            baseline = read(f'global-probe{index}')
            assert value['build']['rtl_sha256'] == rtl
            assert value['binary_sha256'] == baseline['binary_sha256']
            assert value['uart'] == baseline['uart']
            assert value['memory_model'] == baseline['memory_model']
            assert value['build']['harness_sha256'] == baseline['build']['harness_sha256']
            row['directed'][str(index)] = value['window']
        for seed in baselines:
            value = read(f'{variant}-O3-tuned-{seed}-10')
            baseline = baselines[seed]
            assert value['build']['rtl_sha256'] == rtl
            assert value['binary_sha256'] == baseline['binary_sha256']
            assert value['memory_model'] == baseline['memory_model']
            assert value['build']['harness_sha256'] == baseline['build']['harness_sha256']
            b, c = baseline['kernel_cycles'], value['kernel_cycles']
            row['coremark'][seed] = {'cycles': c, 'cycle_reduction_percent': 100*(b-c)/b,
                                     'throughput_increase_percent': 100*(b/c-1),
                                     'binary_sha256': value['binary_sha256'], 'crc_pass': True}
        rows[variant] = row
    result = {'status': 'PASS_ACTUAL_CPU_VARIANT_REGRESSION',
              'scope': 'Actual generated CPU RTL, bounded behavioral AXI; fixed frequency assumption for cycle ratio only',
              'baseline_equivalence': {'directed_cases_exact_uart_and_all_counters': equivalent,
                                        'both_coremark_kernel_cycles_exact': True},
              'variants': rows, 'evidence_sha256': evidence,
              'generation_sha256': hashlib.sha256(a.generation.read_bytes()).hexdigest(),
              'formal_coremark_score': None, 'fmax': None, 'lut': None, 'physical_board': False}
    a.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'status': result['status'], 'variants': {k:v['coremark'] for k,v in rows.items()}}, indent=2))


if __name__ == '__main__':
    main()
