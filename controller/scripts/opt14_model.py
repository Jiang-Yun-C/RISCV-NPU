"""Named-boundary accounting; measured components are never board predictions."""
import csv,json
from pathlib import Path

HZ=125000000
FEEDBACK='exports/OPT_V1_FEEDBACK_20261018_v2/NexusRV_OPT_V1_Feedback_20261018_v2/data'


def geometry(manifest):
    entries={x['name']:x for x in manifest['directory']}
    w=entries['model.embed_tokens.weight'];s=entries['model.embed_tokens.weight.scale']
    n,k=w['shape'];groups=k//64
    if (n,k)!=(151936,896) or k%64 or w['length']!=n*k or s['length']!=n*groups*4:
        raise ValueError('full head pack geometry')
    return dict(vocabulary=n,hidden=k,group_size=64,weight_bytes=w['length'],scale_bytes=s['length'],
                macs=n*k,group_restores=n*groups,rounded_fp32_multiplies=2*n*groups,
                rounded_fp32_adds=n*groups,logits_bytes=4*n,packed_m1_output_commands=n//4,
                row_blocks_256=n//256+bool(n%256),final_block_rows=n%256,
                fixed_output_drain_cycles=n//4*1024)


def history(root):
    root=Path(root)
    with (root/FEEDBACK/'operator_profile.csv').open() as f:ops=list(csv.DictReader(f))
    with (root/FEEDBACK/'measurements.csv').open() as f:samples=list(csv.DictReader(f))
    rows=[]
    for sample in samples:
        if sample['variant']!='B':continue
        case=sample['case'];selected=[r for r in ops if r['variant']=='B' and r['case']==case]
        profile={r['operator']:r for r in selected}
        if len(profile)!=8 or len(selected)!=8:raise ValueError('missing/duplicate historical operator')
        total=int(sample['total_ticks']);head=int(profile['head']['ticks']);calls=int(profile['head']['calls'])
        residual=total-sum(int(r['ticks']) for r in profile.values())
        if residual<0 or calls!=int(sample['generated']):raise ValueError('profile accounting')
        # Assign ALL request head work and ALL unprofiled work to decode. This
        # is an intentionally excessive, strict historical upper bound, with
        # no assumption about how aggregate head time splits between phases.
        relaxed=head+residual;intervals=max(0,int(sample['generated'])-1)
        decode_lower=max(0,int(sample['decode_ticks'])-relaxed)/HZ/intervals if intervals else None
        rows.append(dict(case=case,total_cycles=total,head_calls=calls,head_cycles=head,
                         mean_head_seconds=head/calls/HZ,unprofiled_cycles=residual,
                         zero_entire_head_and_all_unprofiled_upper_saving_seconds=relaxed/HZ,
                         corresponding_request_seconds_lower_bound=(total-relaxed)/HZ,
                         decode_interval_seconds_lower_bound=decode_lower,
                         scope='HISTORICAL_B_ONLY_NOT_POST_OPT08_OR_INTEGRATED_PREDICTION'))
    if [r['case'] for r in rows]!=['S','P']:raise ValueError('historical S/P inventory')
    return rows


def serial_floor(manifest,control):
    """Loose source-derived M1 floor for the unchanged sequential controller.

    Each listed state consumes a distinct clock. Ignore all DMA, FP pipeline
    latency beyond one FP_WAIT, DOT_WAIT, dot stores, scale fetching and output.
    No inter-group execution overlaps in this controller. This is an analytic
    lower bound, not a new RTL measurement or an integrated speed prediction.
    """
    sections={}
    for start,end in (('WEIGHT_CHECK','DOT_A'),('DOT_A','DOT_W'),('DOT_W','DOT_SEND'),
                      ('DOT_SEND','DOT_WAIT'),('RESTORE_DOT','RESTORE_SA'),
                      ('RESTORE_SA','RESTORE_SW'),('RESTORE_SW','FP_SEND'),
                      ('FP_SEND','FP_WAIT'),('FP_WAIT','AUDIT_SAVE'),('RAM_REQ','RAM_WAIT'),('RAM_WAIT','RAM_WRITE')):
        body=control.split('\n        '+start+':',1)[1].split('\n        '+end+':',1)[0]
        sections[start]=body
    if ('state<=RAM_WAIT' not in sections['RAM_REQ'] or 'state<=return_state' not in sections['RAM_WAIT']
        or 'fetch(' not in sections['DOT_A'] or 'state<=DOT_SEND' not in sections['DOT_W']
        or 'state<=FP_WAIT' not in sections['FP_SEND'] or 'state<=AUDIT_SAVE' not in sections['FP_WAIT']):
        raise ValueError('controller changed: analytic floor must be reviewed')
    entries={x['name']:x for x in manifest['directory']}
    layer_groups=0
    for layer in range(24):
        for op in ('q','k','v','o','gate','up','down'):
            part='self_attn' if op in ('q','k','v','o') else 'mlp'
            n,k=entries[f'model.layers.{layer}.{part}.{op}_proj.weight']['shape']
            if k%64:raise ValueError('floor requires complete G64 groups')
            layer_groups+=n*k//64
    per_group=dict(weight_check_scratch_and_check=4*3,
                   dot_activation_scratch_consume_weight_scratch_consume_send=4*7,
                   restore_dot_sa_sw_scratch_and_consume=3*3,
                   fp_send_wait_and_audit_save_minimum=3)
    minimum=sum(per_group.values());head_groups=geometry(manifest)['group_restores']
    return dict(scope='ANALYTIC_FLOOR_UNCHANGED_OPT10_OPT13_SEQUENTIAL_M1_CONTROLLER_ONLY',
                minimum_distinct_state_cycles_per_group=per_group,cycles_per_group=minimum,
                layer_groups_without_head=layer_groups,head_groups=head_groups,
                layer_only_cycles_floor=layer_groups*minimum,
                layer_only_seconds_floor=layer_groups*minimum/HZ,
                head_projection_cycles_floor=head_groups*minimum,
                all_projection_seconds_floor=(layer_groups+head_groups)*minimum/HZ,
                ignored='DMA, DOT_WAIT/stores, scale fetch, extra FP latency, all output/drain, all CPU/SFU/KV/control',
                invalidated_by='Compute/controller refactoring or replacement, frequency change, changed geometry; not an OPT16 prediction')


def assess(root,review):
    root=Path(root);load=lambda n:json.loads((root/n).read_text())
    g=geometry(load('docs/spec/model-pack-v1-manifest.json'))
    update=load('configs/opt08-model-update.json');budget=load('configs/opt05-budgets.json')
    if update['clock_hz']!=HZ or budget['clock_hz']!=HZ:raise ValueError('frozen clock changed')
    if update['per_head']['final_logits_copy_bytes_saved']!=g['logits_bytes'] or update['output_copy_eliminated'] or update['finite_argmax_scan_eliminated']:
        raise ValueError('OPT08 no-double-count contract')
    if review['status']!='PASS' or review['checks']<=0:raise ValueError('unverified CPU cost measurements')
    samples={n:v['observed'] for n,v in review['cases'].items() if n!='seed1-repeat'}
    costs=[]
    for name,v in samples.items():
        finite=[s['cycles'] for s in v['scans'] if s['status']==0]
        costs.append(dict(case=name,remaining_output_copy_cycles=v['copy_cycles'],
                          finite_scan_cycles_min=min(finite),finite_scan_cycles_max=max(finite),
                          zero_overhead_scan_only_saving_seconds_upper_on_measured_fixtures=max(finite)/HZ,
                          zero_overhead_copy_and_scan_saving_seconds_upper_on_measured_fixtures=(v['copy_cycles']+max(finite))/HZ))
    max_scan=max(x['finite_scan_cycles_max'] for x in costs)
    max_cpu=max(x['remaining_output_copy_cycles']+x['finite_scan_cycles_max'] for x in costs)
    controls=[(root/n).read_text() for n in ('variants/opt10/rtl/ce64/nx_ce64_control.sv',
              'build/OPT13_TRANSPORT/opt13-transport-20261019-v4/repo/rtl/ce64/nx_ce64_control.sv')]
    floors=[serial_floor(load('docs/spec/model-pack-v1-manifest.json'),c) for c in controls]
    if floors[0]!=floors[1]:raise ValueError('controller floor mismatch')
    return dict(schema_version=1,status='COMPLETED_NEGATIVE_ADOPTION_ASSESSMENT',
                decision='DO_NOT_SELECT_STREAMING_ARGMAX_FOR_CURRENT_CANDIDATE',selected_for_OPT16=False,
                geometry=g,component_samples=costs,historical_context=history(root),serial_projection_floor=floors[0],
                boundaries=dict(projection='All full-vocabulary weights/scales, INT32 dot and ordered FP32 group restore remain.',
                    backend_Y='607744 bytes and 37984 packed M1 writes remain whenever full logits are materialized.',
                    cpu_output_copy='BA staging -> AC runtime private logits; still present after OPT08.',
                    cpu_scan='Production nx_greedy finite pass plus ascending strict-greater scan.',
                    removed_final_copy='Already eliminated by OPT08; zero additional OPT14 credit.'),
                traffic=dict(projection_weight_and_scale_bytes_retained=g['weight_bytes']+g['scale_bytes'],
                    backend_Y_bytes=g['logits_bytes'],remaining_copy_read_bytes=g['logits_bytes'],
                    remaining_copy_write_bytes=g['logits_bytes'],
                    scan_logical_finite_and_candidate_pass_bytes=2*g['logits_bytes'],
                    scan_best_lookup_bytes_before_cache_upper=4*(g['vocabulary']-1),
                    traffic_boundaries_must_not_be_summed_as_one_bus=True,
                    final_copy_additional_saved_bytes=0),
                sensitivity=dict(full_logits_mode_measured_scan_only_upper_seconds=max_scan/HZ,
                    full_logits_mode_contract='Existing AC private-logits diagnostic view and driver ABI retained.',
                    new_BA_logits_view_measured_cpu_copy_and_scan_upper_seconds=max_cpu/HZ,
                    new_BA_logits_view_contract='Could retain full CE Y and omit CPU copy using a new borrowed staging view; lifecycle/diagnostic ABI not implemented or qualified.',
                    winner_only_mode_measured_cpu_copy_and_scan_upper_seconds=max_cpu/HZ,
                    winner_only_fixed_native_drain_floor_seconds=g['fixed_output_drain_cycles']/HZ,
                    winner_only_output_total_upper_seconds=None,
                    floor_is_not_an_upper_bound=True,
                    physical_DDR_and_cache_timing_transfer_valid=False,
                    hardware_compare_commit_mode_costs_seconds=None,
                    integrated_resource_cost=None,
                    end_to_end_speedup=None),
                decision_basis=[
                    'Full-logits mode can at most remove the measured scan interval on these fixtures; Y and the required staging copy stay.',
                    'Winner-only suppression also changes descriptor/completion, diagnostic and non-greedy contracts; no qualified implementation/resource evidence exists.',
                    'Historical full-head time includes projection/restoration and is not an argmax saving. Even zero entire head and residual is insufficient as a standalone route to the frozen decode target.',
                    'Under the unchanged serial M1 controller, mandatory distinct state cycles for layer projections alone exceed the 2-second target even with all head/CPU/output work free; matrix/controller improvements take priority.',
                    'Component-only synthetic memory costs cannot establish integrated benefit; do not activate an optional feature using unknown costs or reuse OPT08 copy savings.',
                    'This is a current-candidate engineering rejection, not proof that streaming argmax can never help; reassess if OPT16 attributes a target-limiting cost to head result handling.'
                ],
                semantic_contract=dict(vocabulary=g['vocabulary'],minimum_id_on_tie=True,eos_id=151645,
                    nonfinite='NX_NUMERIC without token publication; all rows must be checked even after an EOS maximum.',
                    sampling='Only explicitly greedy requests could use a future winner-only mode; other policies require full logits.',
                    diagnostics='Keep independent complete logits/golden and software scan fallback; no ABI changed in this assessment.'),
                baseline_cpu_checks=review['checks'],argmax_rtl_implemented=False,argmax_rtl_qualification='NOT_RUN_NOT_SELECTED',
                whole_model_numeric_for_new_mode='NOT_RUN_NO_NEW_MODE',pds_resources_for_new_mode='NOT_RUN_NO_NEW_MODE',
                adopted_savings=dict(cycles=0,bytes=0,luts=0,registers=0,drm36k=0,apm=0),
                frozen_decode_target_seconds=budget['decode_seconds_per_token_max'],
                ttft_prediction_seconds=None,decode_prediction_seconds=None,
                board_gate='NO_GO_PENDING_OFFLINE_EVIDENCE')
