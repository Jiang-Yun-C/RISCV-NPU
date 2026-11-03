#!/usr/bin/env python3
"""Pure offline gate negatives and bounded transport-summary comparison.

Synthetic budget documents never authorize a DUT. Closed N129 raw is read only.
"""
import argparse
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import traceback

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'scripts')]
from evidence import EvidenceRun, sha256, write_json
import run_opt10_r1_head_combo_api as runner

CLOSED = ROOT / 'evidence/OPT10_R1_W_SW_API/opt10-r1-w-sw-api-ab-20261021-v2'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    run = EvidenceRun(ROOT, 'OPT10_R1_HEAD_PREP_CHECK', args.run_id)
    code = 1
    try:
        contract = runner.base_contract()
        write_json(run.path / 'contract.json', dict(scope='OFFLINE_HEAD_GATE_AND_TRANSPORT_SUMMARY_CHECK_ONLY',
            runner_sha256=sha256(Path(runner.__file__)), source_sha256=sha256(Path(__file__)),
            closed_parent_manifest_sha256=sha256(CLOSED / 'manifest.json'),
            limits=dict(aggregate_wall_seconds=180), DUT_executed=False, head_executed=False,
            synthetic_budget_files_are_not_authorization=True))
        # Small synthetic manifests test refusal without involving a simulator.
        synthetic = run.build / 'synthetic'
        synthetic.mkdir()
        receipts, manifests = {}, {}
        for shape in ('gate', 'down'):
            path = synthetic / shape
            path.mkdir()
            write_json(path / 'manifest.json', dict(status='PASS', exit_code=0, finished_at='synthetic-only'))
            receipts[shape], manifests[shape] = str(path), sha256(path / 'manifest.json')
        budget = dict(scope='OPT10_R1_COMBO_GATE_DOWN_INDEPENDENT_BUDGET_GATE', independent_review=True,
            allow_head=True, allowed_shapes=['head'], allows_169_fullgraph=False,
            experimental_content_id=contract['experimental_content_id'], overlay=contract['overlay'],
            combo_identity_sha256=contract['combo_identity_sha256'], decisions=dict(gate='ACCEPT', down='ACCEPT'),
            reviewed_receipts=receipts, reviewed_manifest_sha256=manifests,
            reviewed_overlay={shape: contract['overlay'] for shape in ('gate', 'down')},
            budget_kind='CONDITIONAL_REFERENCE_EVENT_SCREEN_NOT_MEASURED_COMPLETE_API', RoPE_saving_cycles=None,
            conditional_S25M_CE_mean_remaining_cycles=1, conditional_S25M_CE_max_remaining_cycles=-1)
        def check_budget(value):
            # Hash binding is updated so each negative tests its semantic gate.
            write_json(synthetic / 'head-gate.json', value)
            write_json(synthetic / 'manifest.json', dict(status='PASS', exit_code=0, finished_at='synthetic-only',
                artifacts={'head-gate.json': sha256(synthetic / 'head-gate.json')}))
            return runner.validate_budget(synthetic / 'head-gate.json', contract)
        run.check('synthetic-schema-positive-only', check_budget(budget) == budget,
                  'Pure function only; never passed to --execute')
        mutations = {
            'wrong-stage': lambda value: value.update(allowed_shapes=['gate', 'down']),
            'broad-stage': lambda value: value.update(allowed_shapes=['head', 'gate']),
            'full169-permission': lambda value: value.update(allows_169_fullgraph=True),
            'wrong-combo': lambda value: value.update(experimental_content_id='0' * 64),
            'wrong-upper-source': lambda value: value['overlay'].update({'firmware/runtime/reference/nx_reference.c': '0' * 64}),
            'down-rejected': lambda value: value['decisions'].update(down='REJECT'),
            'wrong-reviewed-manifest': lambda value: value['reviewed_manifest_sha256'].update(down='0' * 64),
            'wrong-reviewed-overlay': lambda value: value['reviewed_overlay'].update(down={}),
            'unconditional-budget': lambda value: value.update(budget_kind='MEASURED_COMPLETE_API'),
            'mechanical-RoPE-saving': lambda value: value.update(RoPE_saving_cycles=25173404),
            'zero-mean-margin': lambda value: value.update(conditional_S25M_CE_mean_remaining_cycles=0),
            'missing-negative-envelope': lambda value: value.pop('conditional_S25M_CE_max_remaining_cycles'),
        }
        negatives = {}
        for name, mutate in mutations.items():
            changed = copy.deepcopy(budget)
            mutate(changed)
            try:
                check_budget(changed)
            except (ValueError, KeyError) as error:
                negatives[name] = str(error)
            else:
                raise ValueError('Gate mutation escaped: ' + name)
        run.check('all-semantic-head-gate-negatives-rejected', len(negatives) == len(mutations), negatives)
        write_json(run.path / 'gate-negatives.json', negatives)
        # CLI refusal must happen before EvidenceRun, simulator build or launch.
        refusal_id = args.run_id + '-must-not-exist'
        refused = subprocess.run([sys.executable, str(Path(runner.__file__)), '--run-id', refusal_id, '--execute'],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10, text=True)
        run.check('CLI-default-refuses-unaccepted-head', refused.returncode == 2 and
                  not (ROOT / 'evidence/OPT10_R1_HEAD_COMBO_API' / refusal_id).exists() and
                  'execution refuses' in refused.stderr, refused.stderr)
        write_json(run.path / 'CLI-refusal.json', dict(returncode=refused.returncode, stderr=refused.stderr,
                                                     no_DUT_or_receipt_created=True))
        # Compare the new constant-memory summary against the terminal old
        # small-N receipt. No large head input or head raw is involved.
        parent = runner.load(CLOSED / 'contract.json')
        closed = runner.load(CLOSED / 'results.json')
        comparisons = {}
        for shape in ('q', 'down'):
            image = dict(parent['images'][shape], N=129, Y=0xac010000)
            for arm in ('baseline', 'variant'):
                case = CLOSED / (shape + '-' + arm) / 'case'
                obs = runner.load(case / 'actual-results.json')
                summary = runner.streaming_workload(case / 'api-transport.csv', image, obs['terminal_close'])
                expected = closed['shapes'][shape][arm]['workload']
                for key in ('reads', 'linear_counters', 'commit_count'):
                    run.check(shape + '-' + arm + '-old-new-' + key, summary[key] == expected[key], summary[key])
                run.check(shape + '-' + arm + '-entire-EOF', summary['raw']['entire_file_checked'] and
                    summary['raw']['sha256'] == sha256(case / 'api-transport.csv'), summary['raw'])
                comparisons[shape + '-' + arm] = summary
        for shape in ('q', 'down'):
            run.check(shape + '-same-full-publisher-digests',
                comparisons[shape + '-baseline']['publisher_transport'] == comparisons[shape + '-variant']['publisher_transport'],
                comparisons[shape + '-baseline']['publisher_transport'])
        write_json(run.path / 'transport-summary-comparison.json', comparisons)
        write_json(run.path / 'results.json', dict(scope='OFFLINE_ONLY_NO_DUT_NO_HEAD',
            semantic_negatives_rejected=len(negatives), closed_raw_cases=len(comparisons),
            streaming_checker_sha256=runner.CHECKER_SHA, DUT_executed=False, head_executed=False,
            CPU_API_cycles=None, fullgraph_cycles=None, head_RSS=None, GO=False))
        code = 0
    except BaseException:
        (run.path / 'failure.txt').write_text(traceback.format_exc())
        print(traceback.format_exc(), flush=True)
    finally:
        for source in (Path(__file__), Path(runner.__file__)):
            shutil.copy2(source, run.path / source.name)
        run.manifest.update(DUT_executed=False, head_executed=False, qualification=False, GO=False,
                            scope='OFFLINE_HEAD_GATE_AND_TRANSPORT_SUMMARY_CHECK_ONLY')
        run.manifest['artifacts'] = {str(f.relative_to(run.path)): sha256(f) for f in run.path.rglob('*')
            if f.is_file() and not (f.parent == run.path and f.name in ('manifest.json', 'commands.json', 'checks.json', 'exit-status.txt'))}
        code = run.finish(code)
    print(run.manifest['status'], run.path, flush=True)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
