#!/usr/bin/env python3
"""Stage a complete, explicit baseline/enhanced source tree for board builds.

Writes only a new directory. Does not launch EDA, program hardware, invent model
assets or modify the original source. Build receipts describe actual staged bytes.
"""
import argparse
import hashlib
import json
import re
import shlex
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VARIANTS = ('original', 'global', 'rr', 'lru', 'btb', 'lru_btb')
ORIGINAL_CPU = {
    'T09Cpu.v': 'be3866488f1782aeecf6d52c4a8ea933edd56b937f078fae0ae4f23be29d2008',
    'T09Cpu.v_toplevel_RegFilePlugin_regFile.bin': 'b8b891b81fd1c062082faf97533834198d8a4c4b6867899d6218712132a8ed38',
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inventory(root):
    return {str(p.relative_to(root)): sha(p) for p in sorted(root.rglob('*'))
            if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc'}


def set_parameter(path, module, name, value):
    text = path.read_text()
    start = text.index('module ' + module) if module else 0
    end = text.index('endmodule', start) if module else len(text)
    header = text[start:end]
    changed, count = re.subn(r'(\b' + re.escape(name) + r'\s*=\s*)[01]\b',
                             lambda m: m[1] + str(value), header)
    if count != 1:
        raise ValueError(f'{path.name}: expected one {name} parameter, got {count}')
    path.write_text(text[:start] + changed + text[end:])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--profile', choices=('baseline', 'enhanced'), default='enhanced')
    p.add_argument('--cpu-variant', choices=VARIANTS)
    p.add_argument('--cpu-generated', type=Path, default=ROOT / 'cpu_gen/generated')
    p.add_argument('--sram-path', choices=('legacy', 'pipeline'))
    p.add_argument('--pmu', choices=('off', 'on'))
    p.add_argument('--long-pv', choices=('off', 'on'))
    p.add_argument('--head-argmax', choices=('off', 'on'))
    a = p.parse_args()
    out = a.output.resolve()
    if out.exists() or out.is_relative_to(ROOT):
        p.error('output must be new and outside the source tree')
    enhanced = a.profile == 'enhanced'
    cpu = a.cpu_variant or ('lru_btb' if enhanced else 'original')
    settings = {
        'LOCAL_READ_PIPELINE': int((a.sram_path or ('pipeline' if enhanced else 'legacy')) == 'pipeline'),
        'ENABLE_REQUEST_PMU': int((a.pmu or ('on' if enhanced else 'off')) == 'on'),
        'LONG_PV': int((a.long_pv or ('on' if enhanced else 'off')) == 'on'),
        'HEAD_ARGMAX': int((a.head_argmax or ('on' if enhanced else 'off')) == 'on'),
    }
    generated = a.cpu_generated.resolve()
    cpu_source = ROOT / 't27/cpu' if cpu == 'original' else generated / cpu
    required = ('T09Cpu.v', 'T09Cpu.v_toplevel_RegFilePlugin_regFile.bin')
    if any(not (cpu_source / name).is_file() for name in required):
        p.error('missing selected CPU RTL/initialization; run build_cpu_variants.py first')
    if cpu == 'original' and any(sha(cpu_source / name) != ORIGINAL_CPU[name] for name in required):
        p.error('original CPU identity changed; stage the baseline from the original delivered source tree')
    generation = None
    if cpu != 'original':
        receipt = generated / 'GENERATION.json'
        if not receipt.is_file():
            p.error('selected CPU needs the matching GENERATION.json')
        generation = json.loads(receipt.read_text())
        expected = generation.get('variants', {}).get(cpu, {}).get('files', {})
        if generation.get('exit_code') != 0 or any(expected.get(name) != sha(cpu_source / name) for name in required):
            p.error('CPU generation receipt does not match actual selected files')
    out.mkdir(parents=True)
    source = out / 'source'
    shutil.copytree(ROOT, source, ignore=shutil.ignore_patterns('target', '__pycache__', '*.pyc'))
    parent_receipt = ROOT.parent / 'context/PRODUCTION_COMPILE.json'
    if not parent_receipt.is_file():
        raise ValueError('missing historical production compiler receipt')
    (out / 'context').mkdir()
    shutil.copy2(parent_receipt, out / 'context/PRODUCTION_COMPILE.json')
    before = inventory(source)
    for name in required:
        shutil.copy2(cpu_source / name, source / 't27/cpu' / name)
    for module in ('nx_ce64_board_logic', 'nx_t25_board_logic'):
        path = source / 'board/mes2l676-200hp' / (module + '.sv')
        for name, value in settings.items():
            set_parameter(path, module, name, value)
    for module in ('nx_ce64_local', 'nx_t25_local'):
        path = source / 'rtl/ce64' / (module + '.sv')
        set_parameter(path, module, 'LOCAL_READ_PIPELINE', settings['LOCAL_READ_PIPELINE'])
        set_parameter(path, module, 'REQUEST_PMU', settings['ENABLE_REQUEST_PMU'])
    path = source / 'rtl/soc/nx_soc_ce64.sv'
    for name in ('ENABLE_REQUEST_PMU', 'LONG_PV', 'HEAD_ARGMAX'):
        set_parameter(path, 'nx_soc_ce64', name, settings[name])
    for filename in ('m4_pair_tb.sv', 'negative_tb.sv', 'production_tb.sv',
                     'production_fast_tb.sv', 'production_lean_tb.sv'):
        for name, value in settings.items():
            set_parameter(source / 't27' / filename, 'tb_cpu', name, value)
    for name, value in settings.items():
        set_parameter(source / 'tests/ce64_soc/tb_body.svh', None, name, value)
    flags = ['--profile', 'optimized' if enhanced else 'baseline']
    if enhanced:
        flags += ['--service-enhancements', '--kv-tail-direct']
    if settings['LONG_PV']:
        flags += ['--pv-long']
    if settings['HEAD_ARGMAX']:
        flags += ['--head-argmax']
    after = inventory(source)
    record = {
        'schema': 'topic1-staged-profile-v1', 'profile': a.profile,
        'status': 'SOURCE_STAGED', 'cpu_variant': cpu, 'hardware_parameters': settings,
        'software_builder_options': flags,
        'parent_compile_receipt_sha256': sha(parent_receipt),
        'cpu': {name: sha(source / 't27/cpu' / name) for name in required},
        'generation': generation,
        'source_changes': {name: {'before': before.get(name), 'after': digest}
                           for name, digest in after.items() if before.get(name) != digest},
        'source_inventory': after,
        'source_content_id': hashlib.sha256(json.dumps(after, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
        'synthesis': None, 'place_and_route': None, 'physical_board': None,
        'formal_coremark_score': None, 'full_model_accuracy': None,
    }
    (out / 'PROFILE.json').write_text(json.dumps(record, indent=2) + '\n')
    command = ['python3', str(source / 'scripts/build_t27_streaming.py'),
               '--source', str(source), *flags, '--generated', '/absolute/genuine-model-assets',
               '--output', str(out / 'runtime-build'), '--build']
    (out / 'BUILD_COMMAND.txt').write_text(shlex.join(command) + '\n')
    (out / 'README.txt').write_text(
        'This is a staged source profile, not a bitstream or board qualification.\n'
        'PROFILE.json binds the actual CPU, hardware parameters and source inventory.\n'
        'BUILD_COMMAND.txt is the matching software build; replace the genuine-model-assets path.\n'
        'The builder checks the pinned model/tokenizer identities and will not create substitutes.\n'
        'Point the existing vendor board/PLL/PHY project at this source tree, keep the native1024\n'
        'DDR completion path, and perform fresh synthesis, timing/resource checks and board tests.\n'
        'Use separate output directories for each A/B profile. Never combine old PDS results\n'
        'with this changed source inventory.\n')
    print(json.dumps({k: record[k] for k in ('status', 'profile', 'cpu_variant', 'hardware_parameters', 'software_builder_options', 'source_content_id')}, indent=2))


if __name__ == '__main__':
    main()
