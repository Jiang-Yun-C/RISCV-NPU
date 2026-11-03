#!/usr/bin/env python3
"""T23 component qualification through the existing VCS/cocotb evidence gate."""
import argparse
import json
from pathlib import Path
import re
import shutil
import sys
import tarfile
import traceback

from evidence import EvidenceRun, StepFailure, content_id, sha256, write_json
from run_cocotb import environment

ROOT = Path(__file__).resolve().parents[1]
SOURCE_NAMES = [
    'Makefile', 'configs/t23-ddr.json', 'configs/cocotb-toolchain-lock.json',
    'docs/spec/toolchain-lock.json', 'scripts/run_t23.py', 'scripts/run_cocotb.py',
    'scripts/cocotb_case.py', 'scripts/evidence.py', 'scripts/probe_tools.py',
    'tests/cocotb/test_ddr_adapter.py', 'tests/cocotb/test_empty.py',
    'tests/cocotb/common/checks.py', 'tests/cocotb/common/ddr_waveform.py',
    'tests/rtl/tb_ddr_adapter.sv', 'rtl/soc/nx_ddr_adapter.sv',
    'tests/cocotb/fixtures/t04-memory-subset.json', 'tests/ddr/t14-boundaries.json',
    'board/mes2l676-200hp/ddr-user-port.json',
]



def freeze(run):
    files = {n: sha256(ROOT/n) for n in SOURCE_NAMES}
    run.manifest['source'] = {'files': files, 'sha256': content_id(files)}
    with tarfile.open(run.path/'source.tar.gz', 'w:gz') as tar:
        for n in files: tar.add(ROOT/n, arcname=n, recursive=False)
    return files


def archive(run):
    dest = run.path/'artifacts'
    if (run.build/'cocotb').exists():
        shutil.copytree(run.build/'cocotb', dest/'cocotb')
    run.manifest['artifacts'] = {str(p.relative_to(run.path)): sha256(p)
        for p in run.path.rglob('*') if p.is_file() and
        (p.parent != run.path or p.name in ('source.tar.gz','config.json','baseline-differences.json'))}


def run_case(run, tools, config, simulator, case_id, seed, negative=None):
    dest = run.build/'cocotb'/case_id
    dest.mkdir(parents=True)
    identity = content_id(run.manifest['source']['files'])
    cfg = dict(schema_version=1, task='T23', case_id=case_id, run_id=run.run_id,
               seed=seed, effective_seeds={'python':seed,'cocotb':seed,'vcs':seed,'memory':seed},
               profile='ddr', test_mode='COMPONENT', negative=negative,
               data_width=int(re.search(r'-w(\d+)',case_id)[1]) if '-w' in case_id else 128,
               max_cycles=config['max_cycles'], python_prefix=sys.prefix,
               cocotb_version=config['cocotb_version'], fixture_sha256=identity,
               golden_sha256=sha256(ROOT/'tests/cocotb/test_ddr_adapter.py'),
               simulator_sha256=sha256(simulator), expected_framework_status='FAIL' if negative else 'PASS')
    write_json(dest/'case.json', cfg)
    run.execute('case-'+case_id, [tools['python'], ROOT/'scripts/cocotb_case.py',
                '--case', dest/'case.json', '--sim', simulator], config['timeouts_seconds']['simulation'], cwd=dest)
    return json.loads((dest/'checks.json').read_text())


def verify_archive(path):
    from cocotb_case import validate
    from common.ddr_waveform import check_waveform
    path = Path(path).resolve()
    m = json.loads((path/'manifest.json').read_text())
    if m['status'] != 'PASS' or m['exit_code'] != 0 or (path/'exit-status.txt').read_text().strip() != '0':
        raise ValueError('not a completed PASS archive')
    for rel, expected in m['artifacts'].items():
        target = (path/rel).resolve()
        if not target.is_relative_to(path) or sha256(target) != expected:
            raise ValueError('archive artifact mismatch: '+rel)
    if content_id(m['source']['files']) != m['source']['sha256']:
        raise ValueError('source inventory identity mismatch')
    import hashlib
    with tarfile.open(path/'source.tar.gz') as tar:
        if set(tar.getnames()) != set(m['source']['files']):
            raise ValueError('source snapshot inventory mismatch')
        for rel, expected in m['source']['files'].items():
            if hashlib.sha256(tar.extractfile(rel).read()).hexdigest() != expected:
                raise ValueError('source snapshot hash mismatch: '+rel)
    commands = json.loads((path/'commands.json').read_text())
    checks = json.loads((path/'checks.json').read_text())['checks']
    if not commands or not checks or any(x['status'] != 'PASS' for x in commands+checks):
        raise ValueError('missing or failed qualification steps')
    cfg = json.loads((path/'config.json').read_text())
    if cfg['selected_cases'] != cfg['suites'][cfg['suite']]:
        raise ValueError('registered suite matrix mismatch')
    if not cfg['selected_cases'] or set(m['cases']) != set(cfg['selected_cases']) or len(set(cfg['selected_cases'])) != len(cfg['selected_cases']):
        raise ValueError('required matrix coverage mismatch')
    total = 0
    for name, record in m['cases'].items():
        case = path/'artifacts/cocotb'/name
        case_cfg = json.loads((case/'case.json').read_text())
        if case_cfg['run_id'] != m['run_id'] or case_cfg['case_id'] != name:
            raise ValueError('case identity mismatch')
        report = validate(case, case_cfg)
        check_waveform(case)
        if record['checks'] != report['check_count'] or record['sequence_sha256'] != report['sequence_sha256']:
            raise ValueError('case report identity mismatch')
        total += report['check_count']
    if 'ddr-w128-seed1-replay' in m['cases'] and m['cases']['ddr-w128-seed1']['sequence_sha256'] != m['cases']['ddr-w128-seed1-replay']['sequence_sha256']:
        raise ValueError('same-seed replay mismatch')
    if cfg['suite'] != 'smoke' and len(m.get('negative_evidence', [])) != len(cfg['negative_cases']):
        raise ValueError('negative coverage missing')
    for rel in m.get('negative_evidence', []):
        negative = ROOT/rel
        nm = json.loads((negative/'manifest.json').read_text())
        if nm['status'] != 'FAIL' or nm['exit_code'] != 1:
            raise ValueError('negative raw FAIL missing')
        for name, expected in nm['artifacts'].items():
            if sha256(negative/name) != expected:
                raise ValueError('negative artifact identity mismatch')
        status = json.loads((negative/'artifacts/cocotb'/nm['negative']/'case-status.json').read_text())
        if status['status'] != 'FAIL' or nm['expected_reason'] not in status['reason']:
            raise ValueError('negative rejection reason mismatch')
    return {'status':'PASS', 'cases':len(m['cases']), 'independent_checks':total,
            'negative_cases':len(m.get('negative_evidence', [])), 'board_qualification':False}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--suite', choices=('smoke','regression','full'), default='regression')
    p.add_argument('--run-id'); p.add_argument('--verify-archive', type=Path)
    args = p.parse_args(argv)
    if args.verify_archive:
        try:
            print(json.dumps(verify_archive(args.verify_archive), indent=2)); return 0
        except Exception as error:
            print('ARCHIVE_REJECT: '+str(error), file=sys.stderr); return 1
    run = EvidenceRun(ROOT, 'T23', args.run_id)
    code = 1
    try:
        files = freeze(run)
        parents = ['evidence/T22_NATIVE_IMPL/rc3-native110-20261010-v7-full1g/manifest.json',
                   'evidence/T23_NATIVE/native110-full1g-stress-20261010-v1/manifest.json',
                   'evidence/T22_HANDOFF/deferred-board-debug-20261011-v1/handoff.json']
        run.manifest['parents'] = {n: sha256(ROOT/n) for n in parents}
        write_json(run.path/'baseline-differences.json', {
            'parents':run.manifest['parents'], 'new_adapter':files['rtl/soc/nx_ddr_adapter.sv'],
            'changed_board_image':False, 'historical_results_reused_for_adapter':False,
            'native_id':0, 'upstream_id_mapping':'one transaction; preserved in adapter',
            'write_completion':'buffer entire W burst; drain; masked native readback; B',
            'model_scope':'sparse bytes; no physical calibration or real bandwidth'})
        config = json.loads((ROOT/'configs/t23-ddr.json').read_text())
        config.update(suite=args.suite, selected_cases=config['suites'][args.suite])
        write_json(run.path/'config.json', config)
        run.manifest.update(scope=config['scope'], qualification={'component':'RUNNING','physical_pll_phy':'NOT_TESTED','board':'NOT_TESTED'},
                            invocation=[sys.executable, *sys.argv], config={'sha256':sha256(run.path/'config.json')})
        tools = {k:v['path'] for k,v in json.loads((ROOT/'docs/spec/toolchain-lock.json').read_text())['tools'].items()}
        vpi = environment(run, config, tools)
        simulators = {}
        widths = sorted({int(re.search(r'-w(\d+)',n)[1]) for n in config['selected_cases']})
        for width in widths:
            compiled = run.build/('compiled-w'+str(width)); compiled.mkdir()
            simulator = compiled/'simv'; simulators[width]=simulator
            log = run.execute('vcs-build-w'+str(width), [tools['vcs'],'-full64','-sverilog','-timescale=1ns/1ps',
                              '-debug_access+all','+acc+3','-cc',tools['vcs_host_cc'],'-cpp',tools['vcs_host_cxx'],
                              '-LDFLAGS','-Wl,--no-as-needed','-load',vpi,'-top','tb_cpu',
                              '+define+DUT_DATA_W='+str(width),
                              *[ROOT/n for n in SOURCE_NAMES if n.endswith(('.v','.sv'))], '-o',simulator],
                              config['timeouts_seconds']['compile'], cwd=compiled)
            run.check('vcs-version-w'+str(width), 'X-2025.06' in log.read_text(), 'locked VCS compiler')
        results = {}
        for name in config['selected_cases']:
            seed = int(re.search(r'seed(\d+)',name)[1])
            results[name] = run_case(run, tools, config, simulators[int(re.search(r'-w(\d+)',name)[1])], name, seed)
            if name.endswith('-replay'):
                run.check('same-seed-replay', results[name]['sequence_sha256'] == results[name.removesuffix('-replay')]['sequence_sha256'],
                          'complete stimulus/traffic/result digest')
        run.manifest['cases'] = {n:{'status':d['status'],'checks':d['check_count'],'sequence_sha256':d['sequence_sha256']} for n,d in results.items()}
        negatives = []
        if args.suite != 'smoke':
            for name in config['negative_cases']:
                child = EvidenceRun(ROOT, 'T23_NEGATIVE', run.run_id+'-'+name)
                child.manifest.update(parent=str(run.path), negative=name, expected='FAIL', source=run.manifest['source'])
                shutil.copy2(run.path/'source.tar.gz', child.path/'source.tar.gz')
                reasons = {'held-reset':'XML failure/error/skip','bad-golden':'XML failure/error/skip',
                           'empty':'required testcase identity/count mismatch','missing-xml':'missing/stale results.xml'}
                child.manifest['expected_reason'] = reasons[name]
                try:
                    run_case(child, tools, config, simulators[128], name, 1, name)
                    child.check('must-reject', False, 'negative unexpectedly passed')
                except StepFailure:
                    pass
                archive(child); child.finish(1)
                status = json.loads((child.build/'cocotb'/name/'case-status.json').read_text())
                detected = status['status'] == 'FAIL' and reasons[name] in status['reason']
                if name in ('held-reset','bad-golden'):
                    report = json.loads((child.build/'cocotb'/name/'checks.json').read_text())
                    detected &= report['first_failure']['category'] == ('completion' if name=='held-reset' else 'read_data')
                run.check('negative-'+name, detected, status)
                negatives.append(str(child.path.relative_to(ROOT)))
        run.manifest['negative_evidence'] = negatives
        run.check('source-unchanged', files == {n:sha256(ROOT/n) for n in SOURCE_NAMES}, 'all build/checker inputs unchanged')
        run.manifest['qualification']['component'] = 'PASS'
        code = 0
    except Exception:
        (run.path/'failure.txt').write_text(traceback.format_exc())
        run.checks.append({'name':'runner-failure','status':'FAIL','detail':'failure.txt'})
    finally:
        archive(run); code = run.finish(code)
    print(f'T23 COMPONENT {run.manifest["status"]}: {run.path}', flush=True)
    return code


if __name__ == '__main__':
    sys.exit(main())
