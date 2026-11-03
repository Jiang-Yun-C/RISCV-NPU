#!/usr/bin/env python3
"""Materialize the offline V2 union and rebuild all production consumers."""
import argparse
import json
from pathlib import Path
import re
import shutil
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'scripts')]
from evidence import sha256, write_json, content_id
from run_opt07 import Run
from tests.models.prepare_image import parse_elf
from opt16_model import assess


def inventory(repo):
    return {str(p.relative_to(repo)): sha256(p) for folder in ('rtl', 'firmware', 'software')
            for p in (repo/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts}


def production(r, repo, parent):
    original = ROOT/'build/OPT01/opt01-integration-20261018-v2/repo'
    old = original/'build/T25_PREPARE/opt02-full-20261018-v2/application'
    out = r.build/'production'; out.mkdir()
    generated = original/'evidence/T25_PREPARE/opt02-full-20261018-v2/application'
    for f in generated.glob('*.h'):
        shutil.copy2(f, out/f.name)
    for n in ('tokenizer.S', 'tokenizer.nxt'):
        shutil.copy2(old/n, out/n)
    commands = json.loads((parent/'build-commands.json').read_text())
    command = next(x for x in commands if x['name'] == 'application-link')
    argv = [x.replace(str(old), str(out)).replace(str(original), str(repo)) for x in command['argv']]
    argv[1:1] = ['-DNX_OPT07_DEFAULT=0', '-Wl,--undefined=nxp_begin', '-Wl,--undefined=nxp_prepare',
                 '-Wl,--undefined=nx_opt12_run', '-Wl,--undefined=nx_opt11_down']
    argv[-2:-2] = [str(repo/'firmware/runtime/port/prefix.c'),
                  *[str(repo/'firmware/drivers/accel'/n) for n in ('accel.c', 'opt12.c')]]
    if any(x.endswith(('.o', '.a')) for x in argv):
        raise ValueError('old object/archive input in production command')
    r.execute('production-link', argv, 180, cwd=out)
    elf = out/'application.elf'
    entry, segments, abi = parse_elf(elf.read_bytes(), base=0xb4000000, capacity=8*1024*1024)
    r.check('full-production-abi', entry == 0xb4000000 and abi == 2 and len(segments) == 1,
            'Fresh full application, M4/prefix and both vector consumer drivers, ILP32F')
    dis = r.execute('production-disassembly', [argv[0].replace('-gcc', '-objdump'), '-d', elf], 60)
    shutil.copy2(dis, out/'application.dis')
    names = set(re.findall(r'^[0-9a-f]+ <([^>]+)>:', dis.read_text(), re.M))
    r.check('linked-consumers', {'nxp_begin', 'nxp_prepare', 'nx_opt12_run', 'nx_opt11_down'} <= names, sorted(names))
    frames = {}; qualifiers = {}
    for p in out.glob('*.su'):
        for line in p.read_text().splitlines():
            loc, size, kind = line.split('\t'); name = loc.rsplit(':', 1)[-1]
            if name in names:
                frames[name] = max(frames.get(name, 0), int(size)); qualifiers[name] = kind
    write_json(r.path/'stack.json', dict(status='REVIEW_REQUIRED_NOT_RELEASE_SIGNOFF',
        source_frames_bytes=frames, qualifiers=qualifiers, source_frame_sum=sum(frames.values()),
        stack_total_bytes=65536, usable_budget_bytes=57344, reserved_bytes=8192,
        unresolved=['linked library/indirect call bound and maximum M4 VLA high-water qualification'],
        memory_map='production/application.map'))
    # Recompile the boot consumer too, with the same immutable generated input.
    loader = r.build/'loader'; loader.mkdir()
    r.execute('application-binary', [argv[0].replace('-gcc', '-objcopy'), '-O', 'binary', elf, out/'application.bin'], 60)
    trusted = (old.parent/'loader/trusted.h').read_text()
    app_digest = ','.join('0x'+sha256(out/'application.bin')[i:i+2] for i in range(0, 64, 2))
    trusted = re.sub(r'(nx_trusted_apps\[\]\[32\]=\{\{)[^}]*(\}\};)',
                     lambda match: match[1]+app_digest+match[2], trusted)
    (loader/'trusted.h').write_text(trusted)
    cmd = next(x for x in commands if x['name'] == 'sd-loader-link')
    old_loader = original/'build/T25_PREPARE/opt02-full-20261018-v2/loader'
    loader_argv = [x.replace(str(old_loader), str(loader)).replace(str(original), str(repo)) for x in cmd['argv']]
    # The original command uses a differently named ROM output folder; replace
    # every output location explicitly and retain all source/compile arguments.
    for i, x in enumerate(loader_argv):
        if x.startswith('-Wl,-Map='):
            loader_argv[i] = '-Wl,-Map='+str(loader/'loader.map')
        if x == '-o':
            loader_argv[i+1] = str(loader/'loader.elf')
    r.execute('loader-link', loader_argv, 180, cwd=loader)
    r.execute('loader-binary', [argv[0].replace('-gcc', '-objcopy'), '-O', 'binary', loader/'loader.elf', loader/'loader.bin'], 60)
    rom = (loader/'loader.bin').read_bytes()
    if len(rom) > 65536: raise ValueError('loader exceeds board ROM')
    rom = rom.ljust(65536, b'\0')
    (loader/'loader.hex').write_text(''.join(f'{int.from_bytes(rom[i:i+4], "little"):08x}\n' for i in range(0, 65536, 4)))
    write_json(r.path/'production-identity.json', dict(entry=entry, abi='ILP32F',
        elf_sha256=sha256(elf), loader_elf_sha256=sha256(loader/'loader.elf'),
        memory_bytes=segments[0].memory_size, source_files=[x for x in argv if x.endswith(('.c', '.S'))],
        old_objects_used=False, shared_sfu_drivers_linked=True,
        automatic_shared_sfu_model_scheduling='NOT_IMPLEMENTED_RELEASE_BLOCKER',
        programming_performed=False))


def main():
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--run-id', required=True)
    a = p.parse_args(); r = Run(ROOT, 'OPT16_CANDIDATE', a.run_id); code = 1
    try:
        cfg = json.loads((ROOT/'configs/opt16-integration.json').read_text())
        parent = ROOT/cfg['frozen_parent']; base = ROOT/cfg['base']
        protected = json.loads((parent/'protected-before.json').read_text())
        r.check('protected-inputs', all(sha256(ROOT/n) == h for n, h in protected.items()), 'root A, B and releases')
        frozen = json.loads((parent/'source-B.json').read_text())
        r.check('frozen-b', all(sha256(base/n) == h for n, h in frozen.items()), content_id(frozen))
        write_json(r.path/'protected-before.json', protected)
        repo = r.build/'repo'; shutil.copytree(base, repo)
        for n in json.loads((parent/'dependency-relocations.json').read_text()):
            f = repo/n; f.write_text(f.read_text().replace(str(base), str(repo)))
        providers = {}
        for overlay in cfg['overlays']:
            src = ROOT/'variants'/overlay
            for f in src.rglob('*'):
                if f.is_file() and '__pycache__' not in f.parts:
                    n = str(f.relative_to(src)); d = repo/n; d.parent.mkdir(parents=True, exist_ok=True)
                    providers.setdefault(n, []).append(dict(overlay=overlay, sha256=sha256(f)))
                    shutil.copy2(f, d)
        write_json(r.path/'overlay-resolution.json', providers)
        for n, history in providers.items():
            r.check('overlay-'+n.replace('/', '-').replace('.', '-'), sha256(repo/n) == history[-1]['sha256'], history)
        # SFU dispatch surrounds the OPT13 controller; no controller rewrite.
        r.check('single-scratch-dispatch', 'nx_ce64_control linear_control' in (repo/'rtl/sfu/nx_opt11_dispatch.sv').read_text(),
                'linear and vector commands share existing DMA/scratch serially')
        sources = inventory(repo); write_json(r.path/'candidate-sources.json', sources)
        write_json(r.path/'config.json', cfg)
        r.manifest.update(candidate_repo=str(repo), candidate_id=content_id(sources),
            programming_performed=False, board_gate='NO_GO_PENDING_OFFLINE_EVIDENCE',
            scope='SOURCE_UNION_AND_FRESH_CONSUMER_REBUILD_NOT_RELEASE_QUALIFICATION')
        production(r, repo, parent)
        write_json(r.path/'necessary-bound.json', assess(repo, ROOT))
        r.check('source-freeze', inventory(repo) == sources, content_id(sources))
        r.check('protected-after', all(sha256(ROOT/n) == h for n, h in protected.items()), 'original artifacts unchanged')
        code = 0
    except Exception:
        (r.path/'failure.txt').write_text(traceback.format_exc()); print(traceback.format_exc(), flush=True)
    finally:
        for n in ('production', 'loader'):
            if (r.build/n).exists(): shutil.copytree(r.build/n, r.path/n)
        r.manifest['artifacts'] = {str(f.relative_to(r.path)): sha256(f) for f in r.path.rglob('*')
            if f.is_file() and not(f.parent == r.path and f.name in ('manifest.json', 'commands.json', 'checks.json', 'exit-status.txt'))}
        code = r.finish(code)
    print(r.manifest['status']+' '+str(r.path), flush=True); return code


if __name__ == '__main__': sys.exit(main())
