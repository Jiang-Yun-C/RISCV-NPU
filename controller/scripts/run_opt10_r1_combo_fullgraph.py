#!/usr/bin/env python3
"""Prepare the final169 combined API witness; default is source-only draft.

No production candidate is created. Execution requires a subsequently frozen
contract and independent gate/down/head budget decisions for one exact source
closure. This draft must not be used to skip those preceding experiments.
"""
import argparse
import inspect
import json
from pathlib import Path
import shutil
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'scripts')]
from evidence import EvidenceRun, sha256, write_json

TEST = ROOT / 'tests/opt10_r1_combo_fullgraph'
PARENT = ROOT / 'evidence/OPT16_CANDIDATE/opt10-r1-candidate-20261020-v54'
WSW = ROOT / 'evidence/OPT10_R1_W_SW_API/opt10-r1-w-sw-api-ab-20261021-v2'
ROPE = ROOT / 'variants/opt10_r1_rope_store_elision_v2'
COMBO = ROOT / 'variants/opt10_r1_w_sw_rope_combo_v1'
V41 = ROOT / 'evidence/OPT10_R1_FULLGRAPH/opt10-r1-fullgraph-v41-token0-20261020-v1'
ROPE_FILE = 'firmware/runtime/reference/nx_reference.c'
EXPECTED_WSW = 'e6554c4016585e32f4dc55b67c0c903266b20809cc9409f5f1770d3f95ebe1ae'
EXPECTED_ROPE = 'a28800f0b9f169c920e7fa4a5bec17504da2a091ecb659cca0a9ab91fe57abc8'
FIXTURE_HASH = '1104504ab467cf47d8b4f4edaf7fb6026c8f596eeef9822ddc7498434868c587'
MAKEFILE_HASH = '7513d21860df4bd822b0133a68d8bf6c7fd02afb2e0924d5d45dca32fca0e5eb'
FILES = ['scripts/run_opt10_r1_combo_fullgraph.py',
    'tests/opt10_r1_combo_fullgraph/fullgraph.c', 'tests/opt10_r1_combo_fullgraph/observer.py',
    'tests/opt10_r1_combo_fullgraph/case.py', 'scripts/run_opt10_r1_sfu_quant_bulk_fullgraph.py',
    'scripts/run_ce64_soc.py', 'scripts/run_cocotb.py', 'scripts/opt10_r1_measurement.py',
    'scripts/opt10_r1_measurement_cocotb.py', 'scripts/opt10_r1_service_observer.py',
    'scripts/check_opt10_r1_fullgraph_phases_v30.py', 'scripts/opt10_r1_norm_bus_witness.py',
    'tests/opt10_r1_service_observer/transport_monitors.sv', 'tests/ce64_soc/tb_body.svh',
    'tests/ce64_soc/native_memory_model.sv', 'tests/opt12/monitor.svh',
    'tests/opt10_r1_sfu_quant_bulk/fullgraph_monitor_v5.svh', 'tests/opt12/link.ld',
    'tests/cocotb/common/checks.py', 'configs/t05-thresholds.json', 'configs/opt12-vector.json',
    'configs/cocotb-toolchain-lock.json', 'docs/spec/toolchain-lock.json',
    'docs/spec/model-pack-v1-manifest.json', 'tests/reference/oracle.py',
    'model_tools/verify_pack.py', 'model_tools/numeric_v1.py', 'scripts/evidence.py']


def measurement_dependencies():
    names = set(FILES)
    names.update(['scripts/run_ce64_e0.py', 'scripts/run_t07.py',
                  'scripts/verify_opt14.py', 'scripts/opt10_r1_service_postload_support_v41.py'])
    for directory in ('model_tools', 'tests/reference', 'tests/models', 'tests/cocotb/common'):
        names.update(str(p.relative_to(ROOT)) for p in (ROOT / directory).rglob('*.py'))
    return sorted(names)


def load(path):
    return json.loads(Path(path).read_text())


def need(ok, why):
    if not ok:
        raise ValueError(why)


def draft_contract(token):
    parent = load(PARENT / 'manifest.json')
    wsw = load(WSW / 'variant-identity.json')
    wsw_contract = load(WSW / 'contract.json')
    rope = load(ROPE / 'experimental-identity.json')
    combo = load(COMBO / 'identity.json')
    fixture_parent = load(V41 / 'measurement-inputs.json')
    need(parent['status'] == 'PASS' and parent['exit_code'] == 0, 'Exact54 snapshot is not terminal PASS')
    need(load(WSW / 'manifest.json')['status'] == 'PASS', 'W+Sw parent API run is not terminal PASS')
    need(wsw['experimental_content_id'] == EXPECTED_WSW, 'Unexpected W+Sw experimental identity')
    need(len(wsw['overlay']) == 6 and wsw['overlay'] == wsw_contract['overlay'], 'W+Sw six-file closure differs')
    need(rope['source'] == {ROPE_FILE: EXPECTED_ROPE}, 'Unexpected RoPE intervention')
    need(sha256(TEST / 'fullgraph.c') == FIXTURE_HASH == fixture_parent['variants/opt10_r1_fullgraph_v30_v1/fullgraph.c'],
         'Fixture is not the exact successful41 fullgraph application')
    overlay = dict(wsw['overlay'], **rope['source'])
    need(combo['overlay'] == overlay and combo['parent_experimental_content_id'] == EXPECTED_WSW,
         'Frozen proposed combined identity differs from the seven reviewed files')
    need(sha256(COMBO / 'contract.json') == combo['architecture_contract_sha256'], 'Combined architecture contract changed')
    overlay_sources = {n: str(COMBO / n) for n in overlay}
    need(all(sha256(Path(overlay_sources[n])) == h for n, h in overlay.items()), 'Planned overlay files changed')
    need(sha256(ROOT / 'Makefile') == MAKEFILE_HASH, 'Frozen root Makefile changed')
    return dict(schema_version=1, status='DRAFT_SOURCE_ONLY_NOT_EXECUTION_AUTHORIZATION',
        scope='FINAL_STAGE_SAME_CLOSURE_FULL169_ONE_CONTEXT_POSTLOAD_API_WITNESS_ONLY',
        execution_authorized=False, experimental_content_id=None, qualification=False, GO=False,
        planned_experimental_content_id=combo['experimental_content_id'],
        combined_identity_path=str(COMBO / 'identity.json'),
        combined_identity_sha256=sha256(COMBO / 'identity.json'),
        combined_architecture_contract_sha256=sha256(COMBO / 'contract.json'),
        parent_candidate=str(PARENT.relative_to(ROOT)), parent_candidate_id=parent['candidate_id'],
        parent_source_manifest_sha256=sha256(PARENT / 'candidate-sources.json'),
        planned_RTL_overlay=wsw['overlay'], planned_firmware_overlay=rope['source'], overlay=overlay,
        overlay_sources=overlay_sources,
        W_Sw_parent_experimental_content_id=EXPECTED_WSW,
        W_Sw_parent_manifest_sha256=sha256(WSW / 'manifest.json'),
        RoPE_parent_identity_sha256=sha256(ROPE / 'experimental-identity.json'),
        measurement_inputs={name: sha256(ROOT / name) for name in measurement_dependencies()},
        fixture=dict(source='tests/opt10_r1_combo_fullgraph/fullgraph.c', sha256=FIXTURE_HASH,
            inherited_from=str(V41.relative_to(ROOT)), token=token,
            full_weights_header=str((PARENT / 'production/full_weights.h').relative_to(ROOT)),
            full_weights_sha256=sha256(PARENT / 'production/full_weights.h'),
            preserves=['Original nx_port_ticks -> nx_forward_token_v2 -> return elapsed API boundary.',
                       'Existing sealed_norm_read fixture callback and175616B direct coefficient reads.',
                       'Real verified immutable nxpack physical tensor views; original production driver arithmetic.',
                       'Same original125MHz, cumulative numerical thresholds and56KiB stack plus8KiB guard.'],
            authenticated_loader=False, visible_TTFT_qualification=False),
        limits=dict(target_complete_API_cycles=250000000, aggregate_verification_cycles=600000000,
                    production_call_protection_cycles=900000000, attention_matrix_cycles=150000000,
                    firmware_compile_wall_seconds=120, DUT_compile_wall_seconds=600,
                    simulation_wall_seconds=28800, stable_cycles=4),
        unchanged_qualification_budgets=dict(clock_hz=125000000, LUT=76500, FF=73800, DRM36K=140, APM=57,
            scope='These full-candidate obligations are not measured by this graph fixture.'),
        required_before_execution=dict(independent_combo_budget_gate=None,
            gate_fullN_receipt=None, down_fullN_receipt=None, head_fullN_receipt=None,
            all_must_use_this_exact_overlay=True,
            allow_full169_must_be_true=True,
            note='No169 DUT compile/run is authorized by this source-only draft; independent gate/down/head and remaining completeAPI budget must pass first.'),
        observer=dict(write_phase='inspect_writable before every passive memory scan',
            close='All158080logit/KV words and all memory checks complete, then real transport/CPU counters stable.',
            seal='Original producer exits before CPU and all4transport raw ledgers are checked through their full suffix.',
            backend_accounting='Backend is inside API; restore is overlapping and is never added or subtracted again.'),
        acceptance=['Original numerical/reports/stack/169linear and218SFU counts.',
                    'Original phases plus explicit unprofiled residual equal completeAPI.',
                    'Full raw retirement and norm witness pass after original producer exit.',
                    'Measured combined completeAPI <=250000000; no component-delta addition.'],
        stop=['Any earlier fullN/head independent budget rejection prevents this stage.',
              'Any source/checker/input hash change requires a new frozen contract.',
              'No additional Aq/N2/reset/startup/MMIO/adapter changes may enter this closure.'],
        unmeasured=dict(complete_API_cycles=None, production_service=None, visible_TTFT=None,
                        frequency_signoff_hz=None, vendor_resources=None),
        root_Makefile_sha256=MAKEFILE_HASH)


def validate_execution_contract(contract):
    need(contract.get('status') == 'FROZEN_ACCEPTED_FOR_FINAL169' and contract.get('execution_authorized') is True,
         'Source-only draft cannot launch a DUT')
    expected = draft_contract(contract['fixture']['token'])
    for key in ('parent_candidate_id', 'parent_source_manifest_sha256', 'overlay', 'measurement_inputs',
                'planned_experimental_content_id', 'combined_identity_sha256',
                'combined_architecture_contract_sha256', 'root_Makefile_sha256'):
        need(contract[key] == expected[key], 'Frozen final169 dependency changed: ' + key)
    need(contract['limits'] == expected['limits'], 'Original budgets/deadlines changed')
    gate_path = Path(contract['required_before_execution']['independent_combo_budget_gate'])
    manifest = load(gate_path / 'manifest.json')
    need(manifest['status'] == 'PASS' and manifest['exit_code'] == 0 and manifest.get('finished_at'), 'Independent budget gate not terminal PASS')
    need(manifest['artifacts']['final169-gate.json'] == sha256(gate_path / 'final169-gate.json'), 'Independent budget gate artifact changed')
    gate = load(gate_path / 'final169-gate.json')
    need(gate.get('scope') == 'OPT10_R1_COMBO_FULLN_HEAD_INDEPENDENT_BUDGET_GATE' and gate.get('independent_review') is True,
         'Required independent combined budget decision is absent')
    need(gate['overlay'] == contract['overlay'] and gate.get('experimental_content_id') == contract['planned_experimental_content_id'] and gate.get('allow_full169') is True,
         'Budget gate does not accept this exact combined source closure')
    for name in ('gate', 'down', 'head'):
        need(gate['decisions'][name] == 'ACCEPT', 'Earlier completeN/head stage not accepted: ' + name)
        path = Path(contract['required_before_execution'][name + '_fullN_receipt'])
        parent = load(path / 'manifest.json')
        need(parent['status'] == 'PASS' and parent['exit_code'] == 0 and parent.get('finished_at'), 'Earlier stage is not terminal PASS: ' + name)
        need(gate['reviewed_manifest_sha256'][name] == sha256(path / 'manifest.json'), 'Earlier stage differs from independent review: ' + name)
    need(gate['complete_API_budget_remaining_cycles'] >= 0, 'Independent remaining completeAPI budget is negative')
    need(contract.get('experimental_content_id') == expected['planned_experimental_content_id'],
         'Combined experimental source identity was not frozen')


def compose_repository(run, contract):
    parent = load(PARENT / 'manifest.json')
    repo = Path(parent['candidate_repo'])
    inventory = load(PARENT / 'candidate-sources.json')
    need(all(sha256(repo / n) == h for n, h in inventory.items()), 'Exact54 frozen source changed')
    combined = run.build / 'combined-repo'
    for name, digest in inventory.items():
        source = Path(contract['overlay_sources'][name]) if name in contract['overlay'] else repo / name
        expected = contract['overlay'].get(name, digest)
        need(sha256(source) == expected, 'Proposed source overlay changed: ' + name)
        dest = combined / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)
    for name, digest in contract['overlay'].items():
        if name not in inventory:
            source = Path(contract['overlay_sources'][name])
            need(sha256(source) == digest, 'New overlay source changed: ' + name)
            dest = combined / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest)
    closure = dict(inventory, **contract['overlay'])
    write_json(run.path / 'combined-source-closure.json', closure)
    return combined, closure


def prepare_image(run, repo, tools, token):
    # Reuse the original verified-pack/oracle/ELF flow exactly. Only the fixture
    # C path changes to the byte-identical application from successful41.
    import run_opt10_r1_sfu_quant_bulk_fullgraph as original
    source = inspect.getsource(original.prepare)
    marker = "ROOT/'tests/opt10_r1_direct_quant/fullgraph.c'"
    need(source.count(marker) == 1, 'Original fullgraph prepare helper changed')
    source = source.replace(marker, "TEST/'fullgraph.c'")
    (run.build / 'isolated_prepare.py').write_text(source)
    namespace = dict(original.__dict__, TEST=TEST)
    exec(compile(source, str(run.build / 'isolated_prepare.py'), 'exec'), namespace)
    return namespace['prepare'](run, repo, PARENT, tools, token)


def build_dut(run, repo, closure, tools, vpi):
    import run_ce64_soc
    from opt10_r1_service_observer import MONITORS, transport_declarations
    from opt10_r1_norm_bus_witness import monitor as norm_monitor
    body = (ROOT / 'tests/ce64_soc/tb_body.svh').read_text()
    body = body.replace('soc.compute.ce.control.', 'soc.compute.ce.control.linear_control.')
    body = body.replace("cpu_bus.araddr<32'hac200000", "cpu_bus.araddr<32'hb0000000")
    body = body.replace(".model_sealed(1'b1)", ".model_sealed(1'b1),.startup_authorized(1'b0)")
    body = body.replace('backend.awlen!=0||backend.awburst!=1',
        "backend.awlen>31||backend.awburst!=1||(backend.awlen!=0&&backend.awsize!=4)")
    body = body.replace('      if(backend.awvalid&&backend.awready)$fwrite',
        '      if(backend.awvalid&&backend.awready)$fwrite(trace_fd,"%0d,BA,%h,%h,%h,%0d\\n",cycles,backend.awaddr,backend.awlen,backend.awsize,owner);\n      if(backend.awvalid&&backend.awready)$fwrite')
    tb = run.build / 'tb_body.svh'
    tb.write_text(body + '\n' + (ROOT / 'tests/opt12/monitor.svh').read_text() + '\n' +
        (ROOT / 'tests/opt10_r1_sfu_quant_bulk/fullgraph_monitor_v5.svh').read_text() + '\n' +
        norm_monitor(repo / 'firmware/drivers/accel/opt10_norm_catalog.json'))
    def wrapper_with_transport(wrapper):
        head, tail = wrapper.rsplit('endmodule', 1)
        return head + transport_declarations() + '\nendmodule\n' + MONITORS.read_text() + tail
    source = inspect.getsource(run_ce64_soc.build)
    marker = "    tb=compiled/'tb_cpu.sv';tb.write_text(wrapper);shutil.copy2(tb,src/'tb_cpu.sv')"
    need(source.count(marker) == 1, 'Locked source builder hook changed')
    source = source.replace(marker, '    wrapper=wrapper_with_transport(wrapper)\n' + marker)
    (run.build / 'isolated_combo_builder.py').write_text(source)
    namespace = dict(run_ce64_soc.__dict__, wrapper_with_transport=wrapper_with_transport)
    exec(compile(source, str(run.build / 'isolated_combo_builder.py'), 'exec'), namespace)
    overrides = {str(f.relative_to(repo)): f for f in (repo / 'rtl').rglob('*') if f.is_file()}
    overrides['tests/ce64_soc/tb_body.svh'] = tb
    extras = [str(f.relative_to(repo)) for f in sorted((repo / 'rtl/sfu').glob('*.sv'))]
    extras.append('rtl/ce64/nx_ce64_sw_capture.sv')
    sim = namespace['build'](run, tools, vpi, board_memory=True, wave_window=4000,
        source_overrides=overrides, additional_sources=extras, defines=['OPT11_LANES=2'])
    actual = {str(f.relative_to(run.build / 'sources')): sha256(f)
              for f in (run.build / 'sources/rtl').rglob('*') if f.is_file()}
    need(all(closure.get(n) == h for n, h in actual.items()), 'Compiled DUT source differs from exact combined closure')
    write_json(run.path / 'compiled-source-closure.json', actual)
    return sim


def execute(args):
    contract = load(args.frozen_contract)
    validate_execution_contract(contract)
    run = EvidenceRun(ROOT, 'OPT10_R1_COMBO_FULLGRAPH', args.run_id)
    code = 1
    try:
        write_json(run.path / 'contract.json', contract)
        run.manifest.update(scope=contract['scope'], experimental_content_id=contract['experimental_content_id'],
            qualification=False, board_execution=False, target_cycles=250000000,
            aggregate_test_cycle_deadline=600000000, production_call_deadline=900000000,
            frequency_signoff_hz=None, GO=False)
        run.flush()
        for name in contract['measurement_inputs']:
            out = run.path / 'measurement-sources' / name
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, out)
        repo, closure = compose_repository(run, contract)
        tools = {k: v['path'] for k, v in load(ROOT / 'docs/spec/toolchain-lock.json')['tools'].items()}
        from run_cocotb import environment
        cfg = load(ROOT / 'configs/opt12-vector.json')
        cfg['max_cycles'] = 600000000
        vpi = environment(run, cfg, tools)
        image = prepare_image(run, repo, tools, contract['fixture']['token'])
        write_json(run.path / 'application-inputs.json', dict(
            production_sources={n: h for n, h in closure.items() if n.startswith(('firmware/', 'software/include/'))},
            fixture_sha256=sha256(TEST / 'fullgraph.c'), header_sha256=sha256(image / 'full_weights.h'),
            linker_sha256=sha256(ROOT / 'tests/opt12/link.ld')))
        write_json(run.path / 'application-artifacts.json',
            {n: sha256(image / n) for n in ('fullgraph.elf', 'fullgraph.map', 'ce-rom.hex')})
        sim = build_dut(run, repo, closure, tools, vpi)
        case = run.build / 'case'
        case.mkdir()
        for f in sim.parent.glob('*.bin'):
            shutil.copy2(f, case / f.name)
        cfg.update(case_id='token' + str(contract['fixture']['token']) + '-seed1', run_id=run.run_id, seed=1,
            scope=contract['scope'], execution_authorized=True, experimental_content_id=contract['experimental_content_id'],
            wall_seconds=28800, stable_cycles=4, production_protection_cycles=900000000,
            fixture=str(image / 'fixture.json'), fixture_sha256=sha256(image / 'fixture.json'),
            golden=str(image / 'golden.bin'), golden_sha256=sha256(image / 'golden.bin'),
            thresholds=str(ROOT / 'configs/t05-thresholds.json'), thresholds_sha256=sha256(ROOT / 'configs/t05-thresholds.json'),
            norm_catalog=str(repo / 'firmware/drivers/accel/opt10_norm_catalog.json'),
            norm_catalog_sha256=sha256(repo / 'firmware/drivers/accel/opt10_norm_catalog.json'),
            image_plan=str(image / 'load.plan'), ce_rom=str(image / 'ce-rom.hex'))
        write_json(case / 'case.json', cfg)
        run.execute('actual-combined-full169', [sys.executable, TEST / 'case.py', '--case', case / 'case.json', '--sim', sim], 28860, cwd=case)
        observed = load(case / 'actual-results.json')
        write_json(run.path / 'results.json', observed)
        run.check('measured-complete-API-within-original250M', observed['api_cycles'] <= 250000000, observed['api_cycles'])
        run.check('measurement-inputs-after', all(sha256(ROOT / n) == h for n, h in contract['measurement_inputs'].items()), len(contract['measurement_inputs']))
        run.check('combined-source-after', all(sha256(repo / n) == h for n, h in closure.items()), len(closure))
        run.check('root-Makefile-unchanged', sha256(ROOT / 'Makefile') == contract['root_Makefile_sha256'], contract['root_Makefile_sha256'])
        code = 0
    except BaseException:
        (run.path / 'failure.txt').write_text(traceback.format_exc())
    finally:
        for name in ('case', 'image', 'sources'):
            if (run.build / name).exists():
                shutil.copytree(run.build / name, run.path / name)
        run.manifest['artifacts'] = {str(f.relative_to(run.path)): sha256(f) for f in run.path.rglob('*')
            if f.is_file() and not (f.parent == run.path and f.name in ('manifest.json', 'commands.json', 'checks.json', 'exit-status.txt'))}
        code = run.finish(code)
    print(run.manifest['status'], run.path)
    return code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--freeze-only', action='store_true', help='Default; hash sources and write a draft, no tools/DUT/pack execution')
    parser.add_argument('--output', type=Path, default=TEST / 'contract.draft.json')
    parser.add_argument('--token', type=int, choices=(0, 255), default=0)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--frozen-contract', type=Path)
    parser.add_argument('--run-id')
    args = parser.parse_args()
    if args.execute:
        if args.freeze_only or args.frozen_contract is None or not args.run_id:
            parser.error('--execute requires --frozen-contract and --run-id; incompatible with --freeze-only')
        return execute(args)
    draft = draft_contract(args.token)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_json(args.output, draft)
    print('DRAFT_ONLY_NO_DUT', args.output)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
