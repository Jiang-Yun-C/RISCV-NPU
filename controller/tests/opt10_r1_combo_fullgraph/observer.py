"""Prepared final-stage full169 observer; no DUT execution is authorized here."""
import hashlib
import json
import os
from pathlib import Path
import numpy as np
import cocotb
from cocotb.triggers import Timer
from common.checks import Checks
from scripts.opt10_r1_measurement_cocotb import close_observation, save_observer_output


@cocotb.test()
async def combo_fullgraph_observed(dut):
    cfg = json.loads(Path(os.environ['NEXUSRV_CASE']).read_text())
    checks = Checks()
    result = dict(scope=cfg['scope'], experimental_content_id=cfg['experimental_content_id'],
                  completed_observation=False, raw_checks='PENDING_PRODUCER_EXIT', GO=False)
    try:
        for name in ('fixture', 'golden', 'thresholds', 'norm_catalog'):
            checks.equal(hashlib.sha256(Path(cfg[name]).read_bytes()).hexdigest(), cfg[name + '_sha256'], 'identity', name)
        while not int(dut.completed.value) and not int(dut.timed_out.value):
            await Timer(100000, unit='ns')
        checks.equal(int(dut.completed.value), 1, 'completion', 'real complete graph guest return')
        checks.equal(int(dut.exit_code.value), 0, 'completion', 'guest success')

        async def inspect_all():
            # close_observation enters this callback through inspect_writable.
            # Every passive peek and all numerical checks finish before closing.
            reports = {}
            for line in Path('cpu-output.txt').read_text().splitlines():
                group, index, value = map(int, line.split())
                checks.require((group, index) not in reports, 'report', 'unique metadata')
                reports[group, index] = value
            checks.require(not any(g == 255 for g, _ in reports), 'execution', 'no CPU trap')
            u64 = lambda g, i: reports[g, i] | reports[g, i + 1] << 32
            for i in range(3):
                checks.equal(reports.get((1, i)), 0, 'setup', str(i))
            for i in (0, 4, 5, 10):
                checks.equal(reports.get((2, i)), 0, 'graph', 'rc/IDLE/owner/fallback')
            checks.equal(reports.get((2, 6)), 1, 'KV', 'committed context length')
            for i in (8, 9):
                checks.equal(reports.get((2, i)), 169, 'graph', 'all169 projections execute on hardware')
            # Same fixture contract as successful41, including existing direct
            # norm coefficient reads. This is not a new optimization saving.
            expected = [169, 169, 218, 449920 * 4, 6144 * 4, 203648 * 4,
                        0, 0, 182144, 11384, 0]
            for i, wanted in enumerate(expected):
                checks.equal(u64(3, i * 2), wanted, 'workload', str(i))
            checks.equal(u64(3, 26), 175616, 'norm', 'existing direct coefficient bytes')
            checks.equal(u64(3, 28), 175616, 'norm', 'existing avoided coefficient copy bytes')
            checks.equal(int(dut.owner.value), 0, 'owner', 'backend released')
            checks.equal(int(dut.backend_idle.value), 1, 'drain', 'backend idle')
            checks.equal(int(dut.ddr_fault.value), 0, 'fault', 'no native fault/quarantine')
            checks.equal(reports.get((6, 0)), 0, 'stack', 'original8KiB guard')
            checks.require(0 < reports.get((6, 1), 0) <= 57344, 'stack', 'original56KiB budget')
            addresses = [(reports[2, 7], 151936)]
            checks.require(0xac000000 <= reports[2, 7] and reports[2, 7] + 151936 * 4 <= 0xac000000 + 835072,
                           'bounds', 'complete logits in owned workspace')
            for layer in range(24):
                for value in range(2):
                    address = reports[4, layer * 2 + value]
                    checks.equal(address, 0xa8000000 + value * 7864320 + layer * 327680, 'KV', 'bounded physical view')
                    addresses.append((address, 128))
            words = []
            for address, count in addresses:
                for index in range(count):
                    dut.peek_address.value = address + index * 4
                    await Timer(2, unit='ns')
                    words.append(int(dut.peek_value.value))
            actual = np.asarray(words, dtype='<u4').view('<f4')
            actual.tofile('snapshot.bin')
            wanted = np.fromfile(cfg['golden'], dtype='<f4')
            checks.equal(actual.size, 158080, 'numeric', 'complete logits and24layer KV')
            checks.equal(wanted.size, actual.size, 'numeric', 'frozen golden size')
            limits = json.loads(Path(cfg['thresholds']).read_text())['cumulative']
            numeric = {}
            for label, low, high, key in [('logits', 0, 151936, 'logits_24_layers'), ('KV', 151936, 158080, 'kv')]:
                av = actual[low:high].astype('f8')
                ev = wanted[low:high].astype('f8')
                error = np.abs(av - ev)
                limit = limits[key]
                checks.require(bool(np.isfinite(av).all() and np.all(error <= limit['atol'] + limit['rtol'] * np.abs(ev))),
                               'numeric', label + ' original cumulative thresholds')
                nrmse = float(np.sqrt(np.mean(error ** 2)) / max(np.sqrt(np.mean(ev ** 2)), 1e-12))
                checks.require(nrmse <= limit['nrmse'], 'numeric', label + ' original NRMSE')
                numeric[label] = dict(elements=high - low, max_abs=float(error.max()), nrmse=nrmse)
            order = np.argsort(-wanted[:151936], kind='stable')
            margin = float(wanted[order[0]] - wanted[order[1]])
            if margin > 2 * numeric['logits']['max_abs']:
                checks.equal(reports[2, 3], int(order[0]), 'greedy', 'reference with stable margin')
            checks.equal(reports[2, 3], int(np.argmax(actual[:151936])), 'greedy', 'actual lowest-ID argmax')
            names = ('embedding', 'norm', 'linear', 'rope', 'attention', 'swiglu', 'residual', 'head')
            phases = {name: dict(cycles=u64(5, i * 4), calls=u64(5, i * 4 + 2)) for i, name in enumerate(names)}
            for name, count in dict(embedding=1, norm=49, linear=168, rope=48, attention=24,
                                    swiglu=24, residual=48, head=1).items():
                checks.equal(phases[name]['calls'], count, 'phase', name)
            api = u64(2, 1)
            phase_cycles = sum(p['cycles'] for p in phases.values())
            checks.require(0 < api and phase_cycles <= api, 'timing', 'original complete API boundary')
            expected_reports = ({(1, i) for i in range(3)} | {(2, i) for i in range(11)} |
                                {(3, i) for i in range(30)} | {(4, i) for i in range(48)} |
                                {(5, i) for i in range(32)} | {(6, i) for i in range(3)})
            checks.equal(sorted(reports), sorted(expected_reports), 'report', 'exact complete metadata set')
            result.update(api_cycles=api, performance_target_cycles=250000000,
                          complete_API_within_250M=api <= 250000000,
                          nominal_125mhz_seconds=api / 125000000, phases=phases,
                          greedy_and_unprofiled_cycles=api - phase_cycles,
                          numeric=numeric, next=reports[2, 3], reference_next=int(order[0]), reference_margin=margin,
                          actual_stack_watermark_bytes=reports[6, 1], guard_bad_words=reports[6, 0],
                          linear_backend_cycles=u64(3, 22), sfu_backend_cycles=u64(3, 24),
                          frequency_signoff_hz=None, visible_TTFT_seconds=None, calibrated_decode_seconds=None)
            return dict(inspected_words=len(words), inspection_end_cycle=int(dut.cycles.value))

        inspected, close = await close_observation(dut, inspect_all,
            transport_state=lambda: (bool(int(dut.service_transport_drained.value)),
                                     int(dut.service_transport_activity.value)),
            deadline=cfg['max_cycles'], stable_cycles=cfg['stable_cycles'])
        result.update(inspection=inspected, terminal_close=close, terminal_drain=close,
                      completed_observation=True, aggregate_cycles=close['cycle'])
        # No coroutine advances simulator time after this close. Parent process
        # waits for producer exit, then checks every raw suffix before sealing.
    except BaseException as error:
        if checks.first_failure is None:
            checks.first_failure = dict(category='test_exception', detail=repr(error))
        result.update(failure=repr(error), aggregate_cycles=int(dut.cycles.value))
        raise
    finally:
        await save_observer_output(result, checks,
            {k: cfg[k] for k in ('case_id', 'run_id', 'seed', 'fixture_sha256')})
