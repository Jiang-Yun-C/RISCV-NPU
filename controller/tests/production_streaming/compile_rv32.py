#!/usr/bin/env python3
"""Compile the full production C/assembly units with every enhancement enabled.

This is deliberately object-only: genuine model/tokenizer assets are unavailable.
The test supplies only a load_full declaration and labeled identity placeholders,
never weights, a tokenizer or an executable pretending to be production.
"""
import argparse
import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--cc', required=True)
    p.add_argument('--receipt', type=Path, default=ROOT.parent / 'context/PRODUCTION_COMPILE.json')
    a = p.parse_args()
    out = a.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    spec = importlib.util.spec_from_file_location('production_builder', ROOT / 'scripts/build_t27_streaming.py')
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    receipt = json.loads(a.receipt.read_text())
    compiler = str(Path(a.cc).resolve())
    command = builder.rewrite_command(receipt, ROOT, out, compiler, 'optimized',
                                      enhancements=True, kv_tail_direct=True,
                                      pv_long=True, head_argmax=True)
    (out / 'full_weights.h').write_text(
        '/* OBJECT-ONLY TEST DECLARATION. No model asset or initializer. */\n'
        '#include "nx_reference.h"\nextern void load_full(nx_weights *weights);\n')
    (out / 't25_identity.h').write_text(
        '/* OBJECT-ONLY PLACEHOLDERS, NOT OBSERVED MODEL/TOKENIZER IDENTITIES. */\n'
        '#define T25_MODEL_SHA256 "' + '0'*64 + '"\n'
        '#define T25_TOKENIZER_SHA256 "' + '0'*64 + '"\n')
    _, header = builder.runtime_identity(ROOT, command, sha(compiler))
    (out / 't27_runtime_identity.h').write_text(header)
    # Use the exact compiler/backend/numeric options selected by the production
    # builder, dropping only linking inputs/options for independent compilation.
    options, units = [], []
    skip = False
    for arg in command[1:]:
        if skip:
            skip = False
            continue
        if arg in ('-o', '-T'):
            skip = True
        elif arg.startswith(('-Wl,', '-l')):
            continue
        elif arg.endswith(('.c', '.S')):
            if Path(arg).is_relative_to(ROOT):
                units.append(Path(arg))
        else:
            options.append(arg)
    rows = []
    for index, unit in enumerate(units):
        stem = f'{index:02d}-' + unit.stem
        obj, log = out / (stem + '.o'), out / (stem + '.log')
        dep = out / (stem + '.d')
        cmd = [compiler, *options, '-MMD', '-MF', str(dep), '-c', str(unit), '-o', str(obj)]
        with log.open('w') as stream:
            result = subprocess.run(cmd, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, timeout=120)
        rows.append({'source': str(unit.relative_to(ROOT)), 'source_sha256': sha(unit),
                     'command': cmd, 'exit_code': result.returncode, 'log_sha256': sha(log),
                     'object_sha256': sha(obj) if obj.is_file() else None})
    inputs = {str(p.relative_to(ROOT)): sha(p) for directory in ('firmware/runtime', 'firmware/drivers/accel', 'software/include')
              for p in sorted((ROOT / directory).rglob('*')) if p.is_file() and p.suffix in ('.h', '.c', '.S')}
    value = {'status': 'PASS_RV32_OBJECT_COMPILATION' if all(row['exit_code'] == 0 for row in rows) else 'FAIL',
             'scope': 'Actual production compilation units, full geometry, all enhancement flags; object-only declaration placeholders, no model assets or executable',
             'compiler': compiler, 'compiler_sha256': sha(compiler),
             'compiler_version': subprocess.check_output([compiler, '--version'], text=True),
             'production_selected_command': command, 'units': rows, 'source_inventory': inputs,
             'declaration_headers': {name: sha(out / name) for name in ('full_weights.h', 't25_identity.h', 't27_runtime_identity.h')},
             'genuine_model_assets': False, 'production_elf': None, 'model_accuracy': None, 'board_execution': None}
    (out / 'RESULT.json').write_text(json.dumps(value, indent=2) + '\n')
    print(json.dumps({'status': value['status'], 'units': len(rows), 'failed': [row['source'] for row in rows if row['exit_code']]}, indent=2))
    if value['status'] == 'FAIL':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
