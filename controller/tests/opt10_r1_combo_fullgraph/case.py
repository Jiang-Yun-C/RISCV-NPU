#!/usr/bin/env python3
"""Final-stage case process: exit producer, then seal the complete raw suffix."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'scripts')]
from evidence import write_json
from opt10_r1_measurement import seal_cpu_trace
from opt10_r1_service_observer import TRACE_KINDS, verify_transport


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', type=Path, required=True)
    parser.add_argument('--sim', type=Path, required=True)
    args = parser.parse_args()
    cfg = json.loads(args.case.read_text())
    if cfg.get('execution_authorized') is not True:
        raise ValueError('Final-stage execution is not authorized by the frozen architecture gate.')
    if cfg['max_cycles'] != 600000000 or cfg['production_protection_cycles'] != 900000000:
        raise ValueError('Original graph/protection deadlines changed')
    if any(Path(n).exists() for n in ('results.xml', 'checks.json', 'observations.json', 'simulation.log')):
        raise ValueError('Old case artifacts')
    lock = json.loads((ROOT / 'configs/cocotb-toolchain-lock.json').read_text())
    lib = lock['files']['libpython']['path']
    env = os.environ.copy()
    for key in ('COCOTB_TEST_FILTER', 'COCOTB_TESTCASE', 'MODULE', 'TESTCASE', 'GPI_EXTRA', 'GPI_USERS', 'PYGPI_USERS'):
        env.pop(key, None)
    entry = subprocess.check_output([sys.executable, '-m', 'cocotb_tools.config', '--pygpi-entry-point'], text=True).strip()
    env.update(PYGPI_PYTHON_BIN=sys.executable, LIBPYTHON_LOC=lib, GPI_USERS=lib + ';' + entry,
        COCOTB_TEST_MODULES='observer', COCOTB_TOPLEVEL='tb_cpu', COCOTB_TOPLEVEL_LANG='verilog',
        COCOTB_RANDOM_SEED=str(cfg['seed']), COCOTB_RESULTS_FILE=str(Path('results.xml').resolve()),
        NEXUSRV_CASE=str(args.case.resolve()), PYTHONPATH=os.pathsep.join(
            [str(ROOT), str(ROOT / 'tests/cocotb'), str(ROOT / 'tests/opt10_r1_combo_fullgraph')]))
    argv = [str(args.sim), '-no_save', f"+ntb_random_seed={cfg['seed']}",
            f"+image_plan={cfg['image_plan']}", f"+ce_rom={cfg['ce_rom']}",
            f"+seed={cfg['seed']}", f"+max_cycles={cfg['max_cycles']}", f"+max_delay={cfg['max_delay']}"]
    started = time.time_ns()
    producer = None
    code = 1
    try:
        with Path('simulation.log').open('w') as stream:
            producer = subprocess.Popen(argv, env=env, stdout=stream, stderr=subprocess.STDOUT)
            try:
                producer.wait(timeout=cfg['wall_seconds'])
            except BaseException:
                producer.kill()
                producer.wait()
                raise
        xml = ET.parse('results.xml').getroot()
        tests = xml.findall('.//testcase')
        if producer.returncode or len(tests) != 1 or tests[0].get('name') != 'combo_fullgraph_observed' or any(
                x.tag in ('failure', 'error', 'skipped') for x in xml.iter()):
            raise ValueError('Missing/failed required complete graph observer testcase')
        checks = json.loads(Path('checks.json').read_text())
        if checks['status'] != 'PASS' or checks['check_count'] <= 0 or checks['first_failure'] is not None:
            raise ValueError('Complete graph numerical/report checks failed')
        for key in ('case_id', 'run_id', 'seed', 'fixture_sha256'):
            if checks[key] != cfg[key]:
                raise ValueError('Stale observer identity: ' + key)
        for name in ('checks.json', 'results.xml', 'observations.json', 'snapshot.bin', 'transactions.csv',
                     'linear.csv', 'vector.csv', 'transport-cpu.csv', 'transport-backend.csv', 'transport-ddr.csv', 'transport-native.csv'):
            if Path(name).stat().st_size < 20 or Path(name).stat().st_mtime_ns < started:
                raise ValueError('Missing/stale complete graph artifact: ' + name)
        observed = json.loads(Path('observations.json').read_text())
        if not observed.get('completed_observation'):
            raise ValueError('Post-inspection terminal observation incomplete')
        close = observed['terminal_close']
        cpu = seal_cpu_trace('transactions.csv', close, producer, allowed_kinds=TRACE_KINDS + ('BA',))
        transport = {name: verify_transport('transport-' + name + '.csv', close, producer,
                        native=name == 'native', strict_epoch=name == 'backend')
                     for name in ('cpu', 'backend', 'ddr', 'native')}
        if sum(v['records'] for v in transport.values()) != close['transport_activity']:
            raise ValueError('Raw transport event suffix differs from final live snapshot')
        from check_opt10_r1_fullgraph_phases_v30 import check as check_phases
        from opt10_r1_norm_bus_witness import verify as verify_norm
        phases = check_phases(Path('.'), observed)
        norm = verify_norm(Path('.'), cfg['norm_catalog'])
        if norm['immutable_norm_read_bytes'] != 175616:
            raise ValueError('Original sealed-norm fixture configuration changed')
        text = Path('simulation.log').read_text()
        if 'VCS' not in text or 'cocotb v2.1.0' not in text or any(s in text for s in ('Fatal:', 'Error-', 'UVM_FATAL')):
            raise ValueError('Simulator identity/fatal')
        write_json('actual-results.json', dict(observed, cpu_raw=cpu, transport_raw=transport,
            independent_phases=phases, norm_bus_witness=norm, raw_checks='PASS_AFTER_ORIGINAL_PRODUCER_EXIT',
            raw_producer=dict(pid=producer.pid, returncode=producer.returncode), GO=False))
        code = 0
    except BaseException:
        Path('case-failure.txt').write_text(traceback.format_exc())
    finally:
        write_json('case-status.json', dict(status='PASS' if code == 0 else 'FAIL', exit_code=code,
            started_ns=started, producer_pid=producer.pid if producer else None,
            producer_returncode=producer.returncode if producer else None))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
