#!/usr/bin/env python3
"""Rebuild the same targeted PV page-boundary fixture against a selected tree.

The RTL controller, descriptor checks and FP arithmetic are real. External DMA
responses, memory, scratch SRAM and delayed transport drain are behavioral.
An illegal crossing command returns DECERR without transferring DDR payload,
matching the page-rejection contract of nx_ce64_dma. The complete-CE test is a
separate gate. These results do not establish board, DDR/PDS or model timing.
"""
import argparse
import difflib
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

from lower_fp_pipeline import lower

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RTL = [
    'rtl/ce64/vendor/registers.svh',
    'rtl/ce64/vendor/cf_math_pkg.sv',
    'rtl/ce64/vendor/fpnew_pkg.sv',
    'rtl/ce64/vendor/lzc.sv',
    'rtl/ce64/vendor/fpnew_classifier.sv',
    'rtl/ce64/vendor/fpnew_rounding.sv',
    'rtl/ce64/vendor/fpnew_fma.sv',
    'rtl/ce64/nx_ce64_fma_retimed.sv',
    'rtl/sfu/nx_opt11_fp.sv',
    'rtl/sfu/nx_opt11_dispatch.sv',
]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rtl-source', type=Path, default=ROOT,
                        help='Source root providing production RTL; the fixture always comes from this script directory')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--verilator', default=shutil.which('verilator'))
    parser.add_argument('--verilator-root', default=os.getenv('VERILATOR_ROOT'))
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--max-length', type=int, choices=(64, 512), action='append')
    parser.add_argument('--expect-v3-defect', action='store_true',
                        help='Require the named P/V/Y crossings to fail specifically with a page rejection and status=-11; record them as expected negatives')
    parser.add_argument('--seed', type=lambda n: int(n, 0), default=0x11223344)
    parser.add_argument('--split-fp-registers', action='store_true',
                        help='Use the existing representation-only old-Verilator compatibility conversion; original FP source and patch are retained')
    args = parser.parse_args()
    if not args.verilator:
        parser.error('Set --verilator or put Verilator on PATH')
    root, out = args.rtl_source.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    if args.verilator_root:
        env['VERILATOR_ROOT'] = args.verilator_root
    files = [root / name for name in RTL]
    fixtures = [HERE / name for name in (
        'pv_boundary_component.sv', 'pv_boundary_sim.cpp', 'run_pv_boundaries.py', 'lower_fp_pipeline.py')]
    input_hashes = {str(path): sha(path) for path in files + fixtures}
    receipt = {
        'tool': subprocess.check_output([args.verilator, '--version'], env=env, text=True).strip(),
        'scope': __doc__.strip(),
        'rtl_source': str(root),
        'fixture_source': str(HERE),
        'mode': 'v3_expected_negative' if args.expect_v3_defect else 'fixed',
        'seed': args.seed,
        'source_sha256': input_hashes,
        'cases': {},
    }
    snapshots = out / 'recorded-inputs'
    snapshots.mkdir(exist_ok=True)
    shutil.copy2(root / 'rtl/sfu/nx_opt11_dispatch.sv', snapshots / 'nx_opt11_dispatch.sv')
    for path in fixtures:
        shutil.copy2(path, snapshots / path.name)
    if args.split_fp_registers:
        fp_path = root / 'rtl/ce64/nx_ce64_fma_retimed.sv'
        original = fp_path.read_text()
        converted, counts = lower(original)
        converted_path = out / 'compat-fp.sv'
        converted_path.write_text(converted)
        (out / 'original-fp.sv').write_text(original)
        patch = ''.join(difflib.unified_diff(original.splitlines(True), converted.splitlines(True),
                                           fromfile='original-fp.sv', tofile='compat-fp.sv'))
        (out / 'compat-fp.patch').write_text(patch)
        files = [converted_path if path == fp_path else path for path in files]
        receipt['simulation_compatibility'] = {
            **counts,
            'original_sha256': hashlib.sha256(original.encode()).hexdigest(),
            'converted_sha256': hashlib.sha256(converted.encode()).hexdigest(),
            'patch_sha256': hashlib.sha256(patch.encode()).hexdigest(),
            'scope': 'The existing pure per-element FP register representation conversion. Same arithmetic, FF macros, enables/resets, latency and fixed-ready FP protocol; no BLKANDNBLK waiver. No general FP output-backpressure claim.',
        }
    for maximum in args.max_length or [64, 512]:
        label = 'max' + str(maximum)
        build = out / (label + '-obj')
        command = [args.verilator, '--cc', '--exe', '--build', '-j', str(args.jobs),
                   '--top-module', 'pv_boundary_component', '-GMAX_LENGTH=' + str(maximum),
                   '-DOPT11_LANES=2', '-Wno-fatal', '-I' + str(root / 'rtl/ce64/vendor'),
                   '--Mdir', str(build), '-CFLAGS',
                   '-O2 -ffp-contract=off -frounding-math -DTEST_MAX_LENGTH=' + str(maximum)]
        if not args.split_fp_registers:
            command += ['-Wno-BLKANDNBLK']
        command += [str(path) for path in files]
        command += [str(HERE / 'pv_boundary_component.sv'), str(HERE / 'pv_boundary_sim.cpp')]
        record = {'build_command': command, 'result': 'FAIL'}
        receipt['cases'][label] = record
        started = time.monotonic()
        print('Building ' + label + ' against ' + str(root), flush=True)
        with (out / (label + '-build.log')).open('w') as log:
            built = subprocess.run(command, cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT)
        record['build_returncode'] = built.returncode
        if not built.returncode:
            run = [str(build / 'Vpv_boundary_component'), '--trace', str(out / (label + '-dma.jsonl')),
                   '--seed', str(args.seed)]
            if args.expect_v3_defect:
                run += ['--expect-v3-defect']
            record['run_command'] = run
            print('Running ' + label, flush=True)
            with (out / (label + '-results.jsonl')).open('w') as log, (out / (label + '-stderr.txt')).open('w') as err:
                result = subprocess.run(run, cwd=root, env=env, stdout=log, stderr=err, timeout=600)
            record['run_returncode'] = result.returncode
            records = [json.loads(line) for line in (out / (label + '-results.jsonl')).read_text().splitlines()]
            record['observed_cases'] = len([x for x in records if 'case' in x])
            record['expected_negatives'] = len([x for x in records if x.get('result') == 'EXPECTED_NEGATIVE'])
            record['successful_bitwise_words'] = sum(x.get('words_checked', 0) for x in records)
            record['result'] = 'PASS_EXPECTATIONS' if result.returncode == 0 else 'FAIL'
        record['elapsed_seconds'] = time.monotonic() - started
        receipt['sources_unchanged_during_run'] = all(sha(Path(path)) == digest for path, digest in input_hashes.items())
        (out / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
        if record['result'] != 'PASS_EXPECTATIONS' or not receipt['sources_unchanged_during_run']:
            raise SystemExit(label + ' failed; inspect ' + str(out))
        print(label + ' PASS_EXPECTATIONS', flush=True)
    artifact_hashes = {str(path.relative_to(out)): sha(path) for path in sorted(out.rglob('*'))
                       if path.is_file() and '-obj' not in str(path.relative_to(out)) and path.name not in ('receipt.json', 'SHA256.json')}
    receipt['artifact_sha256'] = artifact_hashes
    (out / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    (out / 'SHA256.json').write_text(json.dumps({**artifact_hashes, 'receipt.json': sha(out / 'receipt.json')}, indent=2) + '\n')


if __name__ == '__main__':
    main()
