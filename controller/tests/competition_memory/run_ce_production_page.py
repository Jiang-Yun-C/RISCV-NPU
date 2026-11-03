#!/usr/bin/env python3
"""Replay reported production PV addresses through actual CE registers and DMA.

Uses explicitly modeled external MMIO/DDR and the recorded per-element FP
simulation representation. External guard/adapter inputs remain fixed as in
ce_component.sv. No board, physical PHY, full model or first-Q qualification.
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

from run_rtl import sources
from lower_fp_pipeline import lower

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--rtl-source', type=Path, default=ROOT)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--enhanced', type=int, choices=(0, 1), required=True)
    p.add_argument('--expect-old-failure', action='store_true')
    p.add_argument('--verilator', default=shutil.which('verilator'))
    p.add_argument('--verilator-root', default=os.getenv('VERILATOR_ROOT'))
    p.add_argument('--jobs', type=int, default=2)
    a = p.parse_args()
    if not a.verilator:
        p.error('Set --verilator or place Verilator on PATH')
    src = a.rtl_source.resolve()
    out = a.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    env = dict(os.environ)
    if a.verilator_root:
        env['VERILATOR_ROOT'] = a.verilator_root
    files = sources('ce')
    production = {n: sha(src/n) for n in files}
    tests = {str(f.relative_to(ROOT)): sha(f) for f in [
        HERE/'ce_production_page.cpp', HERE/'ce_sim.cpp', HERE/'run_ce_production_page.py',
        HERE/'run_rtl.py', HERE/'lower_fp_pipeline.py']}
    original = (src/'rtl/ce64/nx_ce64_fma_retimed.sv').read_text()
    converted, counts = lower(original)
    (out/'original-fp.sv').write_text(original)
    (out/'compat-fp-metadata.sv').write_text(converted)
    patch = ''.join(difflib.unified_diff(original.splitlines(True), converted.splitlines(True),
                                      fromfile='original-fp.sv', tofile='compat-fp-metadata.sv'))
    (out/'compat-fp.patch').write_text(patch)
    inputs = [out/'compat-fp-metadata.sv' if n=='rtl/ce64/nx_ce64_fma_retimed.sv' else src/n for n in files]
    cmd = [a.verilator, '--cc', '--exe', '--build', '-j', str(a.jobs),
           '--top-module', 'ce_component', '-DOPT11_LANES=2', '-Wno-fatal',
           '-I'+str(src/'rtl/ce64/vendor'), '-GENHANCED='+str(a.enhanced),
           '--Mdir', str(out/'obj'), '-CFLAGS', '-O2 -ffp-contract=off -frounding-math',
           *map(str, inputs), str(HERE/'ce_production_page.cpp')]
    record = {'schema':'t27-pv-production-page-v1', 'scope':__doc__.strip(),
              'tool':subprocess.check_output([a.verilator, '--version'], env=env, text=True).strip(),
              'rtl_source':str(src), 'production_source_sha256':production,
              'test_source_sha256':tests, 'enhanced':a.enhanced,
              'expected_old_failure':a.expect_old_failure, 'build_command':cmd,
              'simulation_compatibility':{**counts, 'input_sha256':sha(out/'original-fp.sv'),
                  'generated_sha256':sha(out/'compat-fp-metadata.sv'),
                  'patch_sha256':sha(out/'compat-fp.patch'),
                  'qualification':'Same documented per-element FP register representation; no production FP edit and no BLKANDNBLK waiver. Does not qualify general output backpressure.'}}
    started = time.monotonic()
    print('Building production-page CE enhanced='+str(a.enhanced), flush=True)
    with (out/'build.log').open('w') as log:
        built = subprocess.run(cmd, cwd=src, env=env, stdout=log, stderr=subprocess.STDOUT)
    record['build_returncode'] = built.returncode
    record['result'] = 'FAIL'
    if built.returncode==0:
        run = [str(out/'obj/Vce_component')]
        if a.expect_old_failure:
            run += ['--expect-old-failure']
        record['run_command'] = run
        print('Running production-page CE', flush=True)
        with (out/'results.jsonl').open('w') as log, (out/'stderr.txt').open('w') as err:
            done = subprocess.run(run, cwd=src, env=env, stdout=log, stderr=err, timeout=120)
        record['run_returncode'] = done.returncode
        if done.returncode==0:
            record['result'] = 'EXPECTED_OLD_FAILURE_REPRODUCED' if a.expect_old_failure else 'PASS'
        record['executable_sha256'] = sha(out/'obj/Vce_component')
    record['elapsed_seconds'] = time.monotonic()-started
    record['inputs_stable'] = production=={n:sha(src/n) for n in files} and tests=={
        n:sha(ROOT/n) for n in tests}
    if not record['inputs_stable']:
        record['result'] = 'INPUTS_CHANGED_DURING_RUN'
    for name in ['build.log', 'results.jsonl', 'stderr.txt']:
        if (out/name).is_file():
            record[name+'_sha256'] = sha(out/name)
    (out/'receipt.json').write_text(json.dumps(record, indent=2)+'\n')
    print(json.dumps({k:record[k] for k in ['result','elapsed_seconds','inputs_stable']}, indent=2))
    return 0 if record['result'] in ('PASS','EXPECTED_OLD_FAILURE_REPRODUCED') else 1


if __name__=='__main__':
    raise SystemExit(main())
