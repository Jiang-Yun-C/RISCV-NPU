#!/usr/bin/env python3
"""Offline closed-N129 original/streaming comparison; never executes a DUT."""
import argparse
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import resource
import shutil
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'scripts')]
from evidence import EvidenceRun, sha256, write_json

PARENT = ROOT / 'evidence/OPT10_R1_W_SW_API/opt10-r1-w-sw-api-ab-20261021-v2'
HERE = ROOT / 'tests/opt10_r1_head_combo_api'
OLD = PARENT / 'inputs/tests/opt10_r1_w_sw_api/check_consumers.py'


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def digest(lines):
    h = hashlib.sha256()
    for line in lines:
        h.update((line + '\n').encode('ascii'))
    return h.hexdigest()


def normalize(result, image):
    keys = ['entire_raw_checked', 'records', 'event_counts', 'actual_DOT_inputs', 'actual_DOT_results',
            'actual_FP_inputs', 'actual_FP_results', 'original_two_mul_ordered_accumulate_bitwise',
            'full_owner', 'epoch_generation', 'leases_remaining', 'completion', 'state_residence_cycles',
            'state_residence_sum', 'overlap', 'state_transition_records']
    normalized = {key: result[key] for key in keys}
    for key in ('publisher_handoffs', 'Sw_block_certificates', 'release_DOT_links'):
        value = result[key]
        normalized[key + '_count'] = value['count'] if isinstance(value, dict) else len(value)
    if isinstance(result['release_DOT_links'], dict):
        normalized['release_links_sha256'] = result['release_DOT_links']['sha256']
        normalized['publisher_sha256'] = result['publisher_handoffs']['sha256']
        normalized['Sw_certificates_sha256'] = result['Sw_block_certificates']['sha256']
    else:
        normalized['release_links_sha256'] = digest(f'{x["cycle"]},{x["bank"]},{x["row"]},{x["group"]},{x["beat"]}' for x in result['release_DOT_links'])
        normalized['publisher_sha256'] = digest(f'{x["cycle"]},{x["row"]},{x["address"]:x}' for x in result['publisher_handoffs'])
        owner = int(result['full_owner'], 16) if result['full_owner'] else 0
        identity = result['epoch_generation'] or (0, 0)
        groups = image['K'] // 64
        normalized['Sw_certificates_sha256'] = digest(f'{first},{min(4,image["N"]-first)},{groups},{owner:x},{identity[0]:x},{identity[1]:x}' for first in result['Sw_block_certificates'])
    return normalized


def read_rows(path):
    with Path(path).open() as stream:
        yield from csv.reader(stream)


def mutation(rows, name, close):
    """One-row transformations; do not duplicate or materialize the raw file."""
    changed = False
    pending = None
    for original in rows:
        row = original[:]
        kind = row[1]
        if pending is not None and int(row[0]) >= int(pending[0]):
            yield pending
            pending = None
        if not changed:
            if name == 'wrong-DOT-W' and kind == 'DOT_IN':
                row[9] = format(int(row[9], 16) ^ 1, 'x');changed = True
            elif name == 'wrong-FP-product' and kind == 'FP_OUT':
                row[5] = format(int(row[5], 16) ^ 1, 'x');changed = True
            elif name == 'missing-FP-result' and kind == 'FP_OUT':
                changed = True;continue
            elif name == 'release-wrong-consumer' and kind == 'W_RELEASE':
                row[5] = '2';changed = True
            elif name == 'release-next-cycle' and kind == 'W_RELEASE':
                row[0] = str(int(row[0]) + 1);pending = row;changed = True;continue
            elif name == 'Sw-incomplete-certificate' and kind == 'SW_CERT' and int(row[6], 16):
                row[5] = format(int(row[5], 16) - 1, 'x');changed = True
            elif name == 'wrong-upper-owner' and kind == 'W_CMD':
                row[7] = format(int(row[7], 16) ^ (1 << 127), 'x');changed = True
            elif name == 'wrong-HIST' and kind == 'HIST':
                row[3] = str(int(row[3]) + 1);changed = True
            elif name == 'missing-enabled-STATE' and kind == 'STATE' and int(row[5]):
                changed = True;continue
        yield row
    if pending is not None:
        yield pending
    if name == 'suffix-after-close':
        changed = True
        yield [str(close['cycle'] + 1), 'OVERLAP', '0', '0', '0']
    if not changed:
        raise ValueError('negative target absent: ' + name)


def transport_mutation(rows, name, image, close):
    changed = False
    sw_read = y_write = False
    for original in rows:
        row = original[:]
        kind = row[1]
        if kind == 'AR':
            sw_read = image['Sw'] <= int(row[2], 16) < image['Sw'] + image['N'] * (image['K'] // 64) * 4
        if kind == 'AW':
            y_write = image['Y'] <= int(row[2], 16) < image['Y'] + image['N'] * 4
        if not changed and name == 'wrong-Sw-R-bits' and kind == 'R' and sw_read:
            row[2] = format(int(row[2], 16) ^ 1, 'x');changed = True
        elif not changed and name == 'missing-Y-native-readback' and kind == 'NAR' and y_write:
            changed = True;continue
        yield row
    if name == 'transport-suffix-after-close':
        changed = True
        yield [str(close['cycle'] + 1), 'NAR', '0', '0', '0', '0', '0']
    if not changed:
        raise ValueError('transport negative target absent: ' + name)


def worker(args):
    image = json.loads(Path(args.image).read_text())
    case = Path(args.case)
    close = json.loads((case / 'actual-results.json').read_text())['terminal_close']
    loaded = module(Path(args.checker), 'closed_consumer_checker')
    started = time.monotonic()
    if args.mode == 'legacy':
        result = loaded.review(case / 'consumer.csv', image, close, variant=args.variant)
    else:
        result = loaded.review(case / 'consumer.csv', image, close, variant=args.variant)
    write_json(args.result, dict(normalized=normalize(result, image),
        bounded_state=result.get('bounded_state'), state_intervals_match_HIST=result.get('state_intervals_match_HIST'),
        host_max_RSS_KiB=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        wall_seconds=time.monotonic() - started, DUT_executed=False))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run-id')
    p.add_argument('--worker', action='store_true')
    p.add_argument('--mode', choices=('legacy', 'streaming'))
    p.add_argument('--checker', type=Path)
    p.add_argument('--image', type=Path)
    p.add_argument('--case', type=Path)
    p.add_argument('--result', type=Path)
    p.add_argument('--variant', action='store_true')
    args = p.parse_args()
    if args.worker:
        worker(args)
        return 0
    if not args.run_id:
        p.error('--run-id required')
    run = EvidenceRun(ROOT, 'OPT10_R1_STREAMING_CHECKER', args.run_id)
    code = 1
    try:
        manifest = json.loads((PARENT / 'manifest.json').read_text())
        if manifest['status'] != 'PASS' or manifest['exit_code'] != 0 or not manifest.get('finished_at'):
            raise ValueError('Only a closed successful parent raw receipt may be compared')
        for name in ('contract.json', 'inputs/tests/opt10_r1_w_sw_api/check_consumers.py'):
            if sha256(PARENT / name) != manifest['artifacts'][name]:
                raise ValueError('Frozen parent changed: ' + name)
        new = HERE / 'check_consumers_streaming.py'
        shutil.copy2(new, run.path / new.name)
        shutil.copy2(OLD, run.path / 'legacy_check_consumers.py')
        parent_contract = json.loads((PARENT / 'contract.json').read_text())
        references = {}
        for shape in ('q', 'down'):
            image = dict(parent_contract['images'][shape], N=129, Y=0xac010000)
            write_json(run.build / (shape + '-image.json'), image)
            for arm in ('baseline', 'variant'):
                case = PARENT / (shape + '-' + arm) / 'case'
                for name in ('consumer.csv', 'api-transport.csv', 'actual-results.json'):
                    relative = str((case / name).relative_to(PARENT))
                    if sha256(case / name) != manifest['artifacts'][relative]:
                        raise ValueError('Closed parent raw changed: ' + relative)
                    references[relative] = manifest['artifacts'][relative]
        negatives = ['wrong-DOT-W', 'wrong-FP-product', 'missing-FP-result', 'release-wrong-consumer', 'release-next-cycle',
                     'Sw-incomplete-certificate', 'wrong-upper-owner', 'wrong-HIST', 'missing-enabled-STATE', 'suffix-after-close']
        transport_negatives = ['wrong-Sw-R-bits', 'missing-Y-native-readback', 'transport-suffix-after-close']
        write_json(run.path / 'contract.json', dict(scope='OFFLINE_STREAMING_CHECKER_PREPARATION_ON_CLOSED_N129_RAW_NOT_HEAD_OR_DUT',
            parent_receipt=str(PARENT.relative_to(ROOT)), parent_manifest_sha256=sha256(PARENT / 'manifest.json'),
            source_sha256={new.name: sha256(new), 'legacy_check_consumers.py': sha256(OLD)},
            raw_references=references, cases=['q-baseline', 'q-variant', 'down-baseline', 'down-variant'],
            negatives=negatives, transport_negatives=transport_negatives, mutation_mode='bounded generator; no raw copy',
            limits=dict(per_worker_wall_seconds=180, aggregate_offline_wall_seconds=600),
            acceptance=['Original complete numeric/identity/count/histogram summary and bounded digests identical.',
                        'STATE interval reconstruction matches original HIST.',
                        'All generator negatives rejected; entire EOF/close boundary retained.'],
            head_executed=False, DUT_executed=False, head_peak_RSS=None, GO=False))
        outputs = {}
        deadline = time.monotonic() + 600
        for shape in ('q', 'down'):
            for arm in ('baseline', 'variant'):
                label = shape + '-' + arm
                pair = {}
                for mode, checker in [('legacy', run.path / 'legacy_check_consumers.py'), ('streaming', run.path / new.name)]:
                    out = run.path / (label + '-' + mode + '.json')
                    argv = [sys.executable, HERE / 'compare_streaming.py', '--worker', '--mode', mode,
                            '--checker', checker, '--image', run.build / (shape + '-image.json'),
                            '--case', PARENT / label / 'case', '--result', out]
                    if arm == 'variant':
                        argv.append('--variant')
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError('Frozen600s aggregate offline deadline')
                    run.execute('offline-' + label + '-' + mode, argv, min(180, remaining))
                    pair[mode] = json.loads(out.read_text())
                run.check(label + '-original-summary-and-full-link-digests-identical',
                          pair['legacy']['normalized'] == pair['streaming']['normalized'], label)
                run.check(label + '-STATE-intervals-match-HIST', pair['streaming']['state_intervals_match_HIST'] is True,
                          pair['streaming']['bounded_state'])
                outputs[label] = pair
        streaming = module(run.path / new.name, 'streaming_negative_checker')
        image = json.loads((run.build / 'q-image.json').read_text())
        case = PARENT / 'q-variant/case'
        close = json.loads((case / 'actual-results.json').read_text())['terminal_close']
        rejected = {}
        for name in negatives:
            if time.monotonic() >= deadline:
                raise TimeoutError('Frozen600s aggregate offline deadline')
            try:
                streaming.review_rows(mutation(read_rows(case / 'consumer.csv'), name, close),
                    read_rows(case / 'api-transport.csv'), image, close, variant=True)
            except (ValueError, KeyError, IndexError) as error:
                rejected[name] = dict(status='REJECTED', reason=str(error), raw_materialized=False)
            else:
                raise ValueError('Generator negative escaped: ' + name)
        for name in transport_negatives:
            if time.monotonic() >= deadline:
                raise TimeoutError('Frozen600s aggregate offline deadline')
            try:
                streaming.review_rows(read_rows(case / 'consumer.csv'),
                    transport_mutation(read_rows(case / 'api-transport.csv'), name, image, close),
                    image, close, variant=True)
            except (ValueError, KeyError, IndexError) as error:
                rejected[name] = dict(status='REJECTED', reason=str(error), raw_materialized=False)
            else:
                raise ValueError('Transport generator negative escaped: ' + name)
        write_json(run.path / 'negative-generators.json', rejected)
        write_json(run.path / 'results.json', dict(scope='OFFLINE_CHECKER_COMPARISON_ONLY',
            comparisons=outputs, negative_generators=rejected, original_result_unchanged=True,
            head_executed=False, DUT_executed=False, head_peak_RSS=None, GO=False))
        run.check('all-generator-negative-replays-rejected', len(rejected) == len(negatives) + len(transport_negatives), rejected)
        run.check('checker-source-after', sha256(new) == sha256(run.path / new.name), sha256(new))
        code = 0
    except BaseException:
        (run.path / 'failure.txt').write_text(traceback.format_exc())
    finally:
        shutil.copy2(__file__, run.path / Path(__file__).name)
        run.manifest.update(scope='OFFLINE_STREAMING_CHECKER_PREPARATION_NOT_HEAD_EXECUTION',
                            qualification=False, DUT_executed=False, head_executed=False, GO=False)
        run.manifest['artifacts'] = {str(f.relative_to(run.path)): sha256(f) for f in run.path.rglob('*')
            if f.is_file() and f.name not in ('manifest.json', 'commands.json', 'checks.json', 'exit-status.txt')}
        code = run.finish(code)
    print(run.manifest['status'], run.path)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
