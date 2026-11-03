#!/usr/bin/env python3
"""Frozen standalone Sw capture + exact54 DMA/native short experiment."""
import argparse
import json
from pathlib import Path
import re
import shutil
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from evidence import EvidenceRun, sha256, write_json
from audit_opt10_r1_sw_capture_raw import replay


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run-id', required=True)
    a = p.parse_args()
    run = EvidenceRun(ROOT, 'OPT10_R1_SW_CAPTURE', a.run_id)
    code = 1
    try:
        repo = ROOT / 'build/OPT16_CANDIDATE/opt10-r1-candidate-20261020-v54/repo'
        variant = ROOT / 'variants/opt10_r1_w_sw_integrated_v1'
        names = ['rtl/soc/nx_accel_map.sv', 'rtl/interfaces/axi4_if.sv',
                 'rtl/ce64/nx_ce64_math_pkg.sv', 'rtl/ce64/nx_ce64_dma.sv',
                 'rtl/ce64/common/nx_ce64_guard.sv', 'rtl/ce64/common/nx_ce64_ddr_adapter.sv']
        src = run.build / 'sources'
        src.mkdir()
        compiled = []
        for name in names:
            source = ROOT / 'variants/opt10_r1_guard_refill_v1' / name if name.endswith('nx_ce64_guard.sv') else repo / name
            dest = src / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest)
            compiled.append(dest)
        for name in ('sw_capture.sv', 'sw_capture_tb.sv'):
            shutil.copy2(variant / name, src / name)
            compiled.append(src / name)
        shutil.copy2(ROOT / 'scripts/audit_opt10_r1_sw_capture_raw.py', run.path / 'checker.py')
        hashes = {str(f.relative_to(run.build)): sha256(f) for f in compiled}
        write_json(run.path / 'input-hashes.json', hashes)
        contract = dict(schema_version=1, track='SANDBOX',
                        scope='STANDALONE_1216B_SW_CAPTURE_REAL_DMA_GUARD_NATIVE_NOT_INTEGRATED_API',
                        sources=hashes, checker_sha256=sha256(run.path / 'checker.py'),
                        parent_candidate_id='30baf1ecc6d83c130a126e508d461f917b69c997e283d1b82c1afec31cc17046',
                        inputs=dict(cases=24, payload_words=304, read_ports='one1-to4scale vector plus independent single scale',
                                    native_STALL_LIMIT=125000000, native_WRITE_DRAIN_CYCLES=1024,
                                    fragment_sizes=[4, 2], maximum_DMA_beats=32,
                                    shape='4x76 max, 1x14 narrow lead/tail, scalar lane12, page/16mod32 lead',
                                    failures='-0/NaN/subnormal, owner/epoch/generation/stop/revoke/transport/W lease, and explicit observer-tap ID/RESP/LAST/count/result corruptions'),
                        limits=dict(compile_wall_seconds=180, simulation_wall_seconds=90, aggregate_cycles=100000),
                        acceptance=['All original native bytes, actual DMA R and dual query bits independently replay.',
                                    'Full owner128+epoch32+generation32+row18/rows3/groups7 retained.',
                                    'Held result and drain barrier prevent certificate; accepted real R drains after revocation.',
                                    '304word payload has one clock-only process and no reset; metadata masks it.',
                                    'All24cases and deliberate raw checker negatives pass.'],
                        exclusions=['Original DMA writes an unconnected scratch output in this standalone test; integration must suppress Sw scratch writes.',
                                    'Tap corruption tests are observer-input unit faults; not native fault/recovery qualification.',
                                    'No W bank, DOT/FP, controller, publisher, CPU/API, CDC/RDC, PDS or125MHz qualification.'],
                        CPU_API_cycles=None, frequency_signoff_hz=None, GO=False)
        write_json(run.path / 'contract.json', contract)
        run.manifest.update(scope=contract['scope'], qualification=False, GO=False, board_execution=False)
        run.flush()
        vcs = json.loads((ROOT / 'docs/spec/toolchain-lock.json').read_text())['tools']['vcs']['path']
        sim = run.build / 'simv'
        run.execute('compile', [vcs, '-full64', '-sverilog', '-timescale=1ns/1ps', *compiled,
                               '-top', 'tb_sw_capture', '-o', sim], 180)
        output = run.execute('simulate', [sim, '-no_save'], 90).read_text()
        match = re.search(r'SW_CAPTURE_PASS cases=(\d+) checks=(\d+) cycles=(\d+) CMD=(\d+) R=(\d+) NR=(\d+) Q=(\d+)', output)
        run.check('frozen-Sw-module-checks', match is not None and 'Fatal:' not in output, output[-2000:])
        audited, rows = replay(run.build / 'sw-capture.csv')
        write_json(run.path / 'raw-replay.json', audited)
        negative = {}
        import csv
        for label, event, action, column in [('missing-native-R', 'NR', 'drop', 0),
                                            ('wrong-query-vector', 'Q', 'bits', 6),
                                            ('missing-result', 'RESULT', 'drop', 0)]:
            bad = [r[:] for r in rows]
            index = next(i for i, row in enumerate(bad) if row[1] == event)
            if action == 'drop':
                bad.pop(index)
            else:
                bad[index][column] = format(int(bad[index][column], 16) ^ 1, 'x')
            try:
                replay(run.build / 'sw-capture.csv', bad)
            except (ValueError, KeyError, IndexError) as error:
                artifact = run.path / ('negative-' + label + '.csv')
                with artifact.open('w', newline='') as stream:
                    csv.writer(stream, lineterminator='\n').writerows(bad)
                negative[label] = dict(status='REJECTED', reason=str(error), artifact=artifact.name)
            else:
                raise ValueError('raw negative escaped: ' + label)
        write_json(run.path / 'negative-replays.json', negative)
        write_json(run.path / 'results.json', dict(scope=contract['scope'], cases=int(match[1]), checks=int(match[2]),
                   cycles=int(match[3]), commands=int(match[4]), AXI_R=int(match[5]), native_R=int(match[6]),
                   dual_query_pairs=int(match[7]), CPU_API_cycles=None, frequency_signoff_hz=None, GO=False))
        run.check('full-raw-and-negative-replays', True, dict(cases=len(audited['cases']), negatives=len(negative)))
        run.check('source-closure-unchanged', all(sha256(run.build / n) == h for n, h in hashes.items()), len(hashes))
        code = 0
    except BaseException:
        (run.path / 'failure.txt').write_text(traceback.format_exc())
    finally:
        shutil.copy2(__file__, run.path / Path(__file__).name)
        if (run.build / 'sources').exists():
            shutil.copytree(run.build / 'sources', run.path / 'sources')
        if (run.build / 'sw-capture.csv').exists():
            shutil.copy2(run.build / 'sw-capture.csv', run.path / 'sw-capture.csv')
        run.manifest['artifacts'] = {str(f.relative_to(run.path)): sha256(f) for f in run.path.rglob('*')
                                     if f.is_file() and f.name not in ('manifest.json', 'commands.json', 'checks.json', 'exit-status.txt')}
        code = run.finish(code)
    print(run.manifest['status'], run.path)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
