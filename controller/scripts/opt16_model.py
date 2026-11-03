"""Necessary state-occupancy bounds, not complete latency predictions."""
import json
import math
import re
from pathlib import Path

HZ = 125_000_000


def state_bodies(control):
    # Only labels in the clocked controller, excluding combinational case arms.
    body = control[control.index('        WEIGHT_CHECK:'):]
    labels = list(re.finditer(r'^        ([A-Z][A-Z_0-9]*):', body, re.M))
    return {m[1]: body[m.end():labels[i+1].start() if i+1 < len(labels) else len(body)]
            for i, m in enumerate(labels)}


def proof(control):
    """Count disjoint mandatory states on the successful full-G64 M1 path.

    A fetch executes RAM_REQ, RAM_WAIT, and the consuming state on separate
    rising edges. DMA/ready stalls can only add cycles. Error paths do not
    produce a successful model token. Zero scales do not skip these states.
    """
    s = state_bodies(control)
    required = {
        'WEIGHT_CHECK': ['if(bad_weight)', '(beat+1)*16<group_elements',
                         'fetch(weight_local_base+', 'WEIGHT_CHECK)', 'fetch(16\'(g*64),DOT_A)'],
        'DOT_A': ['activation_data<=read_data', 'fetch(weight_local_base+', 'DOT_W)'],
        'DOT_W': ['weight_data<=read_data', 'state<=DOT_SEND'],
        'DOT_SEND': ['if(dot_ready)', '(beat+1)*16>=group_elements',
                     'state<=DOT_WAIT', 'fetch(16\'(token*padded_k+g*64+(beat+1)*16),DOT_A)'],
        'RESTORE_DOT': ['fetch(16\'h5000+', 'RESTORE_SA)'],
        'RESTORE_SA': ['fetch(16\'h5800+', 'RESTORE_SW)'],
        'RESTORE_SW': ['state<=FP_SEND'],
        'FP_SEND': ['if(fp_ready)state<=FP_WAIT'],
        'FP_WAIT': ['if(fp_valid)', 'state<=AUDIT_SAVE'],
        'RAM_REQ': ['state<=RAM_WAIT'],
        'RAM_WAIT': ['state<=return_state'],
    }
    for name, fragments in required.items():
        if name not in s or any(x not in s[name] for x in fragments):
            raise ValueError('unreviewed controller transition: '+name)
    # Reject alternate successful branches, extra labels, or changed arithmetic
    # using the separately archived, previously reviewed OPT13 complete source.
    reference = Path(__file__).resolve().parents[1]/'variants/opt13/rtl/ce64/nx_ce64_control.sv'
    if control != reference.read_text():
        raise ValueError('controller differs from reviewed OPT13 source')
    parts = dict(weight_validation=4*(2+1), dot_operand_and_send=4*(2+1+2+1+1),
                 restore_operands=3*(2+1), fp_send_wait_save=3)
    return dict(kind='ANALYTIC_NECESSARY_LOWER_BOUND', parts=parts,
                m1_cycles_per_matrix_group=sum(parts.values()),
                shared_weight_cycles_per_group=parts['weight_validation'],
                per_token_cycles_per_group=sum(parts.values())-parts['weight_validation'],
                ignored_nonnegative_costs=['DMA and scale fetch', 'dot pipeline/store',
                    'FP latency beyond first wait', 'output and 1024-cycle drain',
                    'CPU validation/quantization/copy/scan/control',
                    'all vector/SFU/norm/attention/RoPE/KV', 'tokenizer/UTF8/UART'],
                overlap='One sequential controller and one shared scratch port; counted state visits are mutually exclusive.',
                invalidated_by=['changed controller/parallel execution', 'changed model/precision',
                                'changed frequency', 'pruning or skipped projections'])


def projections(manifest):
    d = {x['name']: x for x in manifest['directory']}
    result = []
    for layer in range(24):
        for op in ('q', 'k', 'v', 'o', 'gate', 'up', 'down'):
            prefix = 'self_attn' if op in ('q', 'k', 'v', 'o') else 'mlp'
            name = f'model.layers.{layer}.{prefix}.{op}_proj.weight'
            w = d[name]; n, k = w['shape']
            if k % 64 or w['length'] != n*k or d[name+'.scale']['length'] != n*k//16:
                raise ValueError('invalid frozen matrix geometry')
            result.append(dict(layer=layer, op=op, n=n, k=k, groups=n*k//64))
    w = d['model.embed_tokens.weight']; n, k = w['shape']
    if (n, k) != (151936, 896) or w['length'] != n*k:
        raise ValueError('incomplete vocabulary')
    result.append(dict(layer=24, op='head', n=n, k=k, groups=n*k//64))
    return result


def assess(repo, root):
    root, repo = Path(root), Path(repo)
    load = lambda n: json.loads((root/n).read_text())
    cfg = load('configs/opt16-integration.json'); budget = load('configs/opt05-budgets.json')
    if cfg['clock_hz'] != HZ or budget['clock_hz'] != HZ:
        raise ValueError('frozen frequency changed')
    p = proof((repo/'rtl/ce64/nx_ce64_control.sv').read_text())
    matrices = projections(load('docs/spec/model-pack-v1-manifest.json'))
    layers = sum(x['groups'] for x in matrices if x['op'] != 'head')
    head = matrices[-1]['groups']; cycles = (layers+head)*p['m1_cycles_per_matrix_group']
    seconds = cycles/HZ; target = budget['decode_seconds_per_token_max']
    if seconds <= target:
        raise ValueError('necessary bound does not justify NO_GO; complete release qualification required')
    workloads = []
    blank = {s: None for s in ('optimistic', 'median', 'conservative')}
    for w in load('configs/opt05-workloads.json')['cases']:
        for mode in ('cold', 'warm_prefix'):
            prefix = w['warm_prefix_tokens'] if mode == 'warm_prefix' else 0
            suffix = w['prompt']-prefix; batches = math.ceil(suffix/4)
            minimum = layers*(12*batches+40*suffix)+52*head
            workloads.append(dict(id=w['id'], mode=mode, prompt=w['prompt'], prefix=prefix,
                suffix_tokens=suffix, m4_batches=batches, tail_rows=suffix % 4,
                ttft_metric_applicable=w['ttft_metric_applicable'],
                visible_budget_seconds=w[mode+'_visible_ttft_budget_seconds'],
                prefill_plus_one_head_cycles_floor=minimum,
                prefill_plus_one_head_seconds_floor=minimum/HZ,
                first_request_must_add_prefix_preparation=prefix > 0,
                predictions_label='ESTIMATED',
                prefill_seconds=dict(blank), internal_ttft_seconds=dict(blank),
                visible_ttft_seconds=dict(blank), decode_mean_seconds=dict(blank),
                decode_tail_seconds=dict(blank), total_seconds=dict(blank), memory_peak_bytes=dict(blank),
                prediction_status='UNKNOWN_NO_COMPLETE_CALIBRATED_MODEL'))
    return dict(schema_version=1, decision='NO_GO', board_gate='NO_GO_OFFLINE_SPEED_BOUND',
        proof=p, projections=matrices, clock_hz=HZ, frequency_signoff_hz=None,
        layer_groups=layers, head_groups=head, decode_cycles_floor=cycles,
        decode_seconds_floor=seconds, decode_target_seconds=target,
        minimum_excess_seconds=seconds-target, minimum_excess_fraction=seconds/target-1,
        necessary_projection_cycle_reduction_fraction=1-target/seconds,
        maximum_group_cycles_at_target=target*HZ/(layers+head),
        frequency_needed_for_counted_states_alone_hz=cycles/target,
        actual_decode_seconds=None, integrated_prediction_seconds=None,
        workloads=workloads, scope='SOURCE_DERIVED_REJECTION_NOT_SPEED_MEASUREMENT_OR_SIGNOFF')
