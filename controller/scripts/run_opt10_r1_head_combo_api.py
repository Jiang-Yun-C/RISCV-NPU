#!/usr/bin/env python3
"""Freeze real head inputs and RV32 ELFs; DUT execution is an independent gate.

The default prepares only. All postprocessing is bounded in raw-file size.
"""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import traceback
import xml.etree.ElementTree as ET

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'scripts')]
from evidence import EvidenceRun, sha256, write_json
from scripts.opt10_r1_measurement import seal_cpu_trace

TEST = ROOT / 'tests/opt10_r1_head_combo_api'
PARENT = ROOT / 'evidence/OPT16_CANDIDATE/opt10-r1-candidate-20261020-v54'
COMBO = ROOT / 'variants/opt10_r1_w_sw_rope_combo_v1'
ORACLE = ROOT / 'evidence/OPT10_R1/opt10-r1-fulln-terminal-observer-contract-20261020-v7'
OFFLINE = ROOT / 'evidence/OPT10_R1_STREAMING_CHECKER/opt10-r1-head-streaming-offline-20261021-v2'
EID = 'a74c87ae4e8b0290abd825bfe8d1708323f95a2fc7619ada0638a010ea6c27bc'
CHECKER_SHA = '8d0e9c24ed0c15cccfbb89069195862441e322a575eb8941e33168871c8a9b07'
MAKE_SHA = '7513d21860df4bd822b0133a68d8bf6c7fd02afb2e0924d5d45dca32fca0e5eb'
SCOPE = 'EXPERIMENT3_TIER2_REAL_HEAD_DIRECT_COMBO_API_AB_NOT_FULL169_OR_QUALIFICATION'
LIMITS = dict(FW_compile_wall_seconds=120, DUT_compile_wall_seconds=600,
              head_aggregate_verification_cycles=600000000, head_simulation_wall_seconds=10800,
              production_call_protection_cycles=900000000, complete_API_target_cycles=250000000,
              separate_full169_verification_cycles=600000000, clock_hz=125000000,
              effective_native_STALL_LIMIT=65536, WRITE_DRAIN_CYCLES=1024)


def load(path):
    return json.loads(Path(path).read_text())


def need(ok, why):
    if not ok:
        raise ValueError(why)


def measurement_sources():
    names = {str(Path(__file__).relative_to(ROOT)), 'scripts/evidence.py',
             'scripts/opt10_r1_measurement.py', 'scripts/opt10_r1_measurement_cocotb.py',
             'scripts/run_ce64_soc.py', 'scripts/run_ce64_e0.py', 'scripts/run_cocotb.py',
             'scripts/run_t07.py', 'tests/ce64_soc/tb_body.svh',
             'tests/ce64_soc/native_memory_model.sv', 'tests/opt12/link.ld',
             'configs/t05-thresholds.json', 'configs/cocotb-toolchain-lock.json',
             'docs/spec/toolchain-lock.json', 'docs/spec/model-pack-v1-manifest.json'}
    for directory in ('model_tools', 'tests/reference', 'tests/models', 'tests/cocotb/common'):
        names.update(str(f.relative_to(ROOT)) for f in (ROOT / directory).rglob('*.py'))
    names.update(str(f.relative_to(ROOT)) for f in TEST.iterdir() if f.suffix in ('.py', '.c', '.svh', '.md'))
    return {n: sha256(ROOT / n) for n in sorted(names)}


def original_closure():
    parent = load(PARENT / 'manifest.json')
    need(parent['status'] == 'PASS' and parent['exit_code'] == 0, 'Parent54 is not terminal PASS')
    repo = Path(parent['candidate_repo'])
    inventory = load(PARENT / 'candidate-sources.json')
    need(all(sha256(repo / n) == h for n, h in inventory.items()), 'Exact54 frozen source differs')
    return parent, repo, inventory


def base_contract():
    parent, repo, inventory = original_closure()
    combo = load(COMBO / 'identity.json')
    need(combo['experimental_content_id'] == EID and len(combo['overlay']) == 7, 'Seven-file combo differs')
    need(combo['parent_candidate_id'] == parent['candidate_id'], 'Combo parent differs')
    need(all(sha256(COMBO / n) == h for n, h in combo['overlay'].items()), 'Combo source changed')
    need(sha256(COMBO / 'contract.json') == combo['architecture_contract_sha256'], 'Combo architecture changed')
    need(sha256(TEST / 'check_consumers_streaming.py') == CHECKER_SHA, 'Frozen streaming checker changed')
    offline = load(OFFLINE / 'manifest.json')
    need(offline['status'] == 'PASS' and offline['exit_code'] == 0 and
         offline['artifacts']['check_consumers_streaming.py'] == CHECKER_SHA and
         sha256(OFFLINE / 'check_consumers_streaming.py') == CHECKER_SHA,
         'Offline-v2 streaming comparison is absent or changed')
    need(sha256(ROOT / 'Makefile') == MAKE_SHA, 'Root Makefile changed')
    old = load(ORACLE / 'contract.json')
    need(old['aggregate_cycles'] == LIMITS['head_aggregate_verification_cycles'] and
         old['production_call_cycles'] == LIMITS['production_call_protection_cycles'] and
         old['wall_seconds'] == LIMITS['head_simulation_wall_seconds'] and
         old['head_shape'] == ['head', 1], 'Original head verification envelope differs')
    return dict(schema_version=1, scope=SCOPE, status='PREPARING_NO_DUT_AUTHORIZATION',
        execution_authorized=False, DUT_compiled=False, DUT_executed=False, head_executed=False,
        experimental_content_id=EID, combo_identity_path=str(COMBO / 'identity.json'),
        combo_identity_sha256=sha256(COMBO / 'identity.json'), overlay=combo['overlay'],
        combo_architecture_contract_sha256=sha256(COMBO / 'contract.json'),
        parent_candidate_id=parent['candidate_id'], parent_repo=str(repo),
        parent_source_manifest_sha256=sha256(PARENT / 'candidate-sources.json'),
        baseline='Exact54 original guard/DMA/controller and original reference C',
        intervention='Exactly the existing seven-file combo; no new architecture',
        measurement_inputs=measurement_sources(), root_Makefile_sha256=MAKE_SHA,
        limits=LIMITS, original_head_deadline_contract=str(ORACLE / 'contract.json'),
        original_head_deadline_contract_sha256=sha256(ORACLE / 'contract.json'),
        deadline_scope='Head fixture aggregate600M inherited from original fullN/head contract; '
                       'separate from full169 aggregate600M and production900M protection; '
                       '20M gate/down limit does not apply to head',
        checker_sha256=CHECKER_SHA, independent_offline_checker_receipt=str(OFFLINE),
        independent_offline_checker_manifest_sha256=sha256(OFFLINE / 'manifest.json'),
        shape=dict(M=1, N=151936, K=896, W=0x80000000, Sw=0x881d4000, bias=0, Y=0xac037800),
        api_boundary='Original nx_port_ticks immediately around nxr_ce64_linear_private '
          'entry/return, including software validation, real quantize, descriptors, wait, '
          'all original128-column hardware Y publishers and original native drain; no CPU Y copy',
        input_boundary='Actual original production tied embedding/head physical addresses; '
          'same frozen token0 final_norm activation in both arms; read-only shared inputs; '
          'postload fixture only, startup_authorized0',
        numerical_rule='Per G64 two separately rounded FP32 multiplies and original row-ordered FP32 add',
        RoPE_compiled=True, RoPE_executed=False, RoPE_saving_cycles=None,
        RoPE_link_retention='The real translation unit is compiled; --gc-sections may discard '
                            'unused RoPE functions. ELF differences do not establish RoPE behavior coverage.',
        native_environment='Unchanged frozen digital DDR model, max_delay0; no production DDR calibration claim',
        raw_policy='Complete consumer and backend/native raw retained; bounded streaming review to EOF; '
          'no list(reader), all inspections before close, seal after producer exit; output bits in output.bin',
        required_before_execution=dict(independent_budget_file=None,
          scope='OPT10_R1_COMBO_GATE_DOWN_INDEPENDENT_BUDGET_GATE',
          requires=['terminal independent budget decision allows_head for exact seven-file combo',
                    'gate ACCEPT and down ACCEPT with exact terminal receipt manifest hashes',
                    'gate/down source-closure hashes equal this combo overlay',
                    'conditional S25M reference-event mean margin positive; max pressure margin retained explicitly',
                    'no measured completeAPI or RoPE saving claimed; full169 permission false',
                    'prepared input and ELF hashes unchanged; original baselines and thresholds unchanged']),
        accept=['Original numeric and all DOT/FP/owner/tag/lease/publisher/native-drain checks pass',
                'Complete head API has direct net benefit versus exact54',
                'Measured exclusive costs support independent complete250M budget; no duplicate overlap subtraction'],
        stop=['Any numeric/protocol/credit/accepted-drain/late-publish failure',
              'No complete head API net benefit or complete budget fails; do not execute169'],
        CPU_API_cycles=None, fullgraph_cycles=None, visible_TTFT=None, frequency_signoff_hz=None,
        vendor_resources=None, qualification=False, GO=False, OPT17='DEFERRED')


def shared_inputs(run, contract):
    from model_tools.verify_pack import verify
    from model_tools import numeric_v1 as num
    image = run.path / 'shared-inputs'
    image.mkdir()
    manifest = load(ROOT / 'docs/spec/model-pack-v1-manifest.json')
    pack = verify(ROOT / manifest['pack_path'], expected_sha256=manifest['sha256'])
    name = 'model.embed_tokens.weight'
    w, sw = pack.rows(name), pack.rows(name + '.scale')
    n, k, groups = 151936, 896, 14
    header = (PARENT / 'production/full_weights.h').read_text()
    expected = 'w->embedding=(nx_matrix){(const int8_t *)(uintptr_t)0x80000000u,(const float *)(uintptr_t)0x881d4000u,NULL,151936,896};'
    run.check('actual-production-head-matrix', expected in header and w.shape == (n, k) and
        sw.shape == (n, groups) and pack.entries[name]['soc_address'] == 0x80000000 and
        pack.entries[name + '.scale']['soc_address'] == 0x881d4000, expected)
    old = load(ORACLE / 'contract.json')
    oracle = ORACLE / 'oracle-m1.npz'
    run.check('frozen-independent-token0-oracle', sha256(oracle) == old['oracles'][oracle.name], old['oracles'][oracle.name])
    with np.load(oracle, allow_pickle=False) as saved:
        x = np.ascontiguousarray(saved['24_final_norm'], dtype='<f4').reshape(1, k)
        golden = np.ascontiguousarray(saved['24_logits'], dtype='<f4').reshape(n)
    aq, sa = num.quantize(x)
    x.tofile(image / 'input.bin')
    w.tofile(image / 'W-full.bin')
    sw.astype('<f4', copy=False).tofile(image / 'Sw-full.bin')
    golden.tofile(image / 'golden.bin')
    aq.tofile(image / 'expected-aq.bin')
    sa.astype('<f4', copy=False).tofile(image / 'expected-sa.bin')
    dots = np.memmap(image / 'expected-dots.bin', dtype='<i4', mode='w+', shape=(groups, n))
    fp = np.memmap(image / 'expected-fp.bin', dtype='<f4', mode='w+', shape=(n, groups, 3))
    max_abs = sq_error = sq_reference = 0.0
    mismatched_bits = 0
    thresholds = load(ROOT / 'configs/t05-thresholds.json')['operators']['linear']
    for lo in range(0, n, 2048):
        hi = min(n, lo + 2048)
        output, chunk_dots = num.linear_quantized(aq, sa, w[lo:hi], sw[lo:hi])
        dots[:, lo:hi] = chunk_dots[:, 0, :]
        p = (chunk_dots[:, 0, :].T.astype('<f4') * sa[0]).astype('<f4')
        v = (p * sw[lo:hi]).astype('<f4')
        partial = np.zeros(hi - lo, dtype='<f4')
        fp[lo:hi, :, 0], fp[lo:hi, :, 1] = p, v
        for group in range(groups):
            partial = (partial + v[:, group]).astype('<f4')
            fp[lo:hi, group, 2] = partial
        need(np.array_equal(partial.view('<u4'), output.reshape(-1).view('<u4')), 'Independent FP chain disagreement')
        err = np.abs(output.reshape(-1).astype('f8') - golden[lo:hi].astype('f8'))
        need(np.isfinite(output).all() and np.all(err <= thresholds['atol'] +
             thresholds['rtol'] * np.abs(golden[lo:hi])), 'Frozen oracle head elementwise mismatch')
        max_abs = max(max_abs, float(err.max()))
        sq_error += float(np.sum(err ** 2))
        sq_reference += float(np.sum(golden[lo:hi].astype('f8') ** 2))
        mismatched_bits += int(np.count_nonzero(output.reshape(-1).view('<u4') != golden[lo:hi].view('<u4')))
    nrmse = float(np.sqrt(sq_error / max(sq_reference, 1e-24)))
    run.check('independent-head-numeric-oracle', nrmse <= thresholds['nrmse'],
              dict(max_abs=max_abs, nrmse=nrmse, mismatched_bits=mismatched_bits, elements=n))
    dots.flush(); fp.flush(); del dots, fp
    need((image / 'W-full.bin').stat().st_size == 136134656 and
         (image / 'Sw-full.bin').stat().st_size == 8508416, 'Actual full head payload extent')
    for f in image.iterdir():
        f.chmod(0o444)
    regions = [dict(name=name, address=addr, bytes=(image / file).stat().st_size,
                    path=str(image / file), sha256=sha256(image / file), kind=kind)
               for name, addr, file, kind in (
                   ('actual-token0-final-norm', 0xac000000, 'input.bin', 'independent_real_model_activation'),
                   ('W-full', 0x80000000, 'W-full.bin', 'immutable_model_slice'),
                   ('Sw-full', 0x881d4000, 'Sw-full.bin', 'immutable_model_slice'))]
    result = dict(path=str(image), files={f.name: sha256(f) for f in image.iterdir()},
        regions=regions, M=1, N=n, K=k, W=0x80000000, Sw=0x881d4000, bias=0, Y=0xac037800,
        model_pack_sha256=manifest['sha256'], production_header_sha256=sha256(PARENT / 'production/full_weights.h'),
        oracle_path=str(oracle), oracle_sha256=sha256(oracle), oracle_contract_sha256=sha256(ORACLE / 'contract.json'),
        activation='Independent frozen token0 24_final_norm', golden='Independent frozen token0 24_logits',
        regenerated_numeric=dict(max_abs=max_abs, nrmse=nrmse, mismatched_bits=mismatched_bits),
        payload_copies=1, shared_read_only=True)
    write_json(run.path / 'shared-inputs.json', result)
    return result


def compile_firmware(run, repo, tools, shared, arm):
    from tests.models.prepare_image import parse_elf
    image = run.path / 'firmware' / arm
    image.mkdir(parents=True)
    src, port, ref = (repo / 'firmware' / p for p in ('drivers/accel', 'runtime/port', 'runtime/reference'))
    reference = COMBO / 'firmware/runtime/reference/nx_reference.c' if arm == 'variant' else ref / 'nx_reference.c'
    c_inputs = [repo / 'firmware/cpu/start.S', TEST / 'firmware.c', port / 'ce64_backend.c', reference]
    c_inputs += [src / n for n in ('accel.c', 'target.c', 'linear_api.c', 'ce64_linear.c', 'opt12.c')]
    flags = ['-march=rv32imf_zicsr_zifencei', '-mabi=ilp32f', '-DHARD_FLOAT', '-DNX_PORTABLE',
        '-O2', '-g', '-ffp-contract=off', '-fno-fast-math', '-fno-strict-aliasing', '-ffreestanding',
        '-fno-builtin', '-fno-pic', '-nostdlib', '-nostartfiles', '-msmall-data-limit=0',
        '-ffunction-sections', '-fdata-sections', '-Wall', '-Wextra', '-Werror',
        '-Wno-unknown-pragmas', '-Wl,--gc-sections', '-Wl,--build-id=none']
    elf = image / 'head.elf'
    argv = [tools['rv32_gcc'], *flags, '-I', src, '-I', port, '-I', ref,
        '-I', repo / 'software/include', '-T', ROOT / 'tests/opt12/link.ld',
        '-Wl,-Map=' + str(image / 'head.map'), *c_inputs, '-lm', '-lc', '-lgcc', '-o', elf]
    run.execute(arm + '-actual-rv32-head-firmware', argv, LIMITS['FW_compile_wall_seconds'])
    entry, segments, abi = parse_elf(elf.read_bytes(), base=0x10000, capacity=0xb8000000 - 0x10000)
    run.check(arm + '-actual-RV32-hard-FPU-entry', entry == 0x10000 and abi == 2, dict(entry=entry, abi=abi))
    regions, rom = list(shared['regions']), bytearray(65536)
    for index, segment in enumerate(segments):
        blob = image / ('elf-' + str(index) + '.bin')
        blob.write_bytes(segment.data)
        regions.append(dict(name=blob.stem, address=segment.address, bytes=len(segment.data),
                            path=str(blob), sha256=sha256(blob), kind='actual_firmware'))
        if 0x10000 <= segment.address < 0x20000:
            need(segment.address + len(segment.data) <= 0x20000, 'Firmware crosses actual ROM window')
            rom[segment.address - 0x10000:segment.address - 0x10000 + len(segment.data)] = segment.data
    ordered = sorted(regions, key=lambda v: v['address'])
    run.check(arm + '-all-firmware-tensor-region-nonoverlap',
        all(a['address'] + a['bytes'] <= b['address'] for a, b in zip(ordered, ordered[1:])), len(regions))
    write_json(image / 'fixture.json', dict(regions=regions, shared_input_manifest_sha256=sha256(run.path / 'shared-inputs.json'),
                                          scope='POSTLOAD_REAL_HEAD_NOT_AUTHENTICATED_LOADER'))
    (image / 'load.plan').write_text(''.join(f"B {x['address']:x} {x['bytes']:x} {x['path']}\n" for x in regions))
    (image / 'ce-rom.hex').write_text(''.join(f'{int.from_bytes(rom[i:i+4], "little"):08x}\n' for i in range(0, 65536, 4)))
    run.execute(arm + '-head-elf-headers', [tools['rv32_readelf'], '-h', '-l', elf], 30)
    result = dict(arm=arm, path=str(image), entry=entry, ABI=abi,
        files={f.name: sha256(f) for f in image.iterdir()},
        shared_input_path=shared['path'], reference_source=str(reference), reference_sha256=sha256(reference),
        actual_gcc_source_inputs={str(f): sha256(f) for f in c_inputs},
        tool_sha256=sha256(tools['rv32_gcc']), original_gcc_flags=flags, RoPE_compiled=arm == 'variant', RoPE_executed=False)
    for f in image.iterdir():
        f.chmod(0o444)
    return result


def validate_prepared(path, require_closed=True):
    path = Path(path)
    if require_closed:
        manifest = load(path.parent / 'manifest.json')
        need(manifest['status'] == 'PASS' and manifest['exit_code'] == 0 and manifest.get('finished_at'),
             'Prepared contract parent receipt is not terminal PASS')
        need(manifest['artifacts'][path.name] == sha256(path),
             'Prepared contract differs from terminal parent artifact hash')
    contract = load(path)
    current = base_contract()
    need(contract['status'] == 'PREPARED_FROZEN_NO_DUT_AUTHORIZATION' and
         contract['execution_authorized'] is False, 'Only prepared frozen inputs can be used')
    for key in ('experimental_content_id', 'combo_identity_sha256', 'overlay', 'parent_candidate_id',
                'parent_source_manifest_sha256', 'measurement_inputs', 'limits', 'root_Makefile_sha256',
                'independent_offline_checker_manifest_sha256', 'checker_sha256', 'shape'):
        need(contract[key] == current[key], 'Prepared dependency changed: ' + key)
    need(all(contract['shared_input'][name] == value for name, value in current['shape'].items()),
         'Shared input shape or production physical address differs')
    need(set(contract['firmware']) == {'baseline', 'variant'}, 'Prepared firmware must contain exactly two arms')
    references = dict(baseline=Path(current['parent_repo']) / 'firmware/runtime/reference/nx_reference.c',
                      variant=COMBO / 'firmware/runtime/reference/nx_reference.c')
    for arm, reference in references.items():
        need(contract['firmware'][arm]['arm'] == arm and
             Path(contract['firmware'][arm]['reference_source']) == reference and
             contract['firmware'][arm]['reference_sha256'] == sha256(reference),
             'Prepared actual firmware arm/reference source differs: ' + arm)
    for image in [contract['shared_input'], *contract['firmware'].values()]:
        need(all(sha256(Path(image['path']) / name) == digest for name, digest in image['files'].items()),
             'Prepared tensor/ELF/load-plan file changed')
        need(all((Path(image['path']) / name).stat().st_mode & 0o222 == 0 for name in image['files']),
             'Prepared shared input/firmware files must remain read-only')
    for image in contract['firmware'].values():
        need(all(sha256(name) == digest for name, digest in image['actual_gcc_source_inputs'].items()),
             'Actual prepared gcc source changed')
    return contract


def validate_budget(path, contract):
    path = Path(path).resolve()
    receipt = path.parent
    manifest = load(receipt / 'manifest.json')
    need(manifest['status'] == 'PASS' and manifest['exit_code'] == 0 and manifest.get('finished_at'),
         'Independent gate/down budget receipt is not terminal PASS')
    need(manifest['artifacts'][path.name] == sha256(path), 'Independent budget artifact changed')
    gate = load(path)
    need(gate.get('scope') == 'OPT10_R1_COMBO_GATE_DOWN_INDEPENDENT_BUDGET_GATE' and
         gate.get('independent_review') is True and gate.get('allow_head') is True,
         'Head execution is not independently accepted')
    need(gate.get('allowed_shapes') == ['head'] and gate.get('allows_169_fullgraph') is False,
         'Independent acceptance must be head-only and must not authorize full169')
    need(gate['experimental_content_id'] == contract['experimental_content_id'] and
         gate['overlay'] == contract['overlay'] and
         gate['combo_identity_sha256'] == contract['combo_identity_sha256'], 'Budget accepts another source closure')
    need(gate.get('budget_kind') == 'CONDITIONAL_REFERENCE_EVENT_SCREEN_NOT_MEASURED_COMPLETE_API' and
         gate.get('RoPE_saving_cycles') is None, 'Conditional screen must not become measured API/RoPE savings')
    need(isinstance(gate.get('conditional_S25M_CE_mean_remaining_cycles'), (int, float)) and
         gate['conditional_S25M_CE_mean_remaining_cycles'] > 0,
         'Conditional S25M reference-event mean screen rejected')
    need(isinstance(gate.get('conditional_S25M_CE_max_remaining_cycles'), (int, float)),
         'Conditional S25M pressure envelope must be explicitly retained, including a negative result')
    for shape in ('gate', 'down'):
        need(gate['decisions'][shape] == 'ACCEPT', 'Earlier fullN stage not accepted: ' + shape)
        prior = Path(gate['reviewed_receipts'][shape])
        state = load(prior / 'manifest.json')
        need(state['status'] == 'PASS' and state['exit_code'] == 0 and state.get('finished_at') and
             sha256(prior / 'manifest.json') == gate['reviewed_manifest_sha256'][shape],
             'Earlier fullN terminal receipt differs: ' + shape)
        need(gate['reviewed_overlay'][shape] == contract['overlay'], 'Earlier fullN source closure differs: ' + shape)
    return gate


def streaming_workload(path, image, close):
    sys.path.insert(0, str(TEST))
    from check_consumers_streaming import RawRows
    reads, events, digests = {}, Counter(), {kind: hashlib.sha256() for kind in ('AW', 'W', 'B')}
    commit, commit_count, last = None, 0, -1
    raw = RawRows(path)
    for row in raw:
        need(len(row) == 7, 'Transport summary grammar')
        cycle, kind = int(row[0]), row[1]
        values = [int(value, 16) for value in row[2:]]
        need(last <= cycle <= close['cycle'], 'Transport summary outside sealed boundary')
        last = cycle
        events[kind] += 1
        if kind in digests:
            digests[kind].update((','.join(format(value, 'x') for value in values) + '\n').encode('ascii'))
        if kind == 'COMMIT':
            commit, commit_count = values, commit_count + 1
        if kind != 'AR':
            continue
        address, burst_len, size, _, _ = values
        count = burst_len + 1
        logical = count * (1 << size)
        if image['W'] <= address < image['W'] + image['N'] * image['K']:
            name = 'W'
        elif image['Sw'] <= address < image['Sw'] + image['N'] * (image['K'] // 64) * 4:
            name = 'Sw'
        elif image['bias'] and image['bias'] <= address < image['bias'] + image['N'] * 4:
            name = 'bias'
        elif 0xba1c0000 <= address < 0xba1c0000 + image['K']:
            name = 'Aq'
        elif 0xba1c5000 <= address < 0xba1c5000 + image['K'] // 64 * 4:
            name = 'Sa'
        elif 0xac000000 <= address < 0xac000000 + image['K'] * 4:
            name = 'quantize_input'
        else:
            name = 'other'
        entry = reads.setdefault(name, dict(AR=0, R=0, logical_bytes=0))
        entry['AR'] += 1; entry['R'] += count; entry['logical_bytes'] += logical
    need(commit is not None, 'No actual backend commit')
    return dict(reads=reads, event_counts=dict(events), raw=raw.metadata(), commit_count=commit_count,
        linear_counters=dict(zip(('total', 'load', 'compute', 'write', 'restore_overlap'), commit)),
        publisher_transport={kind: dict(count=events[kind], sha256=digests[kind].hexdigest()) for kind in digests})


def execute_case(cfgpath, sim):
    cfg = load(cfgpath)
    contract = validate_prepared(cfg['prepared_contract'])
    need(sha256(cfg['budget_file']) == cfg['budget_sha256'], 'Worker budget file changed')
    validate_budget(cfg['budget_file'], contract)
    lock = load(ROOT / 'configs/cocotb-toolchain-lock.json')
    lib = lock['files']['libpython']['path']
    env = os.environ.copy()
    for name in ('COCOTB_TEST_FILTER', 'COCOTB_TESTCASE', 'MODULE', 'TESTCASE', 'GPI_EXTRA', 'GPI_USERS', 'PYGPI_USERS'):
        env.pop(name, None)
    entry = subprocess.check_output([sys.executable, '-m', 'cocotb_tools.config', '--pygpi-entry-point'], text=True).strip()
    env.update(PYGPI_PYTHON_BIN=sys.executable, LIBPYTHON_LOC=lib, GPI_USERS=lib + ';' + entry,
        COCOTB_TEST_MODULES='observer', COCOTB_TOPLEVEL='tb_cpu', COCOTB_TOPLEVEL_LANG='verilog',
        COCOTB_RANDOM_SEED='1', COCOTB_RESULTS_FILE=str(Path('results.xml').resolve()),
        NEXUSRV_CASE=str(Path(cfgpath).resolve()),
        PYTHONPATH=os.pathsep.join([str(ROOT), str(ROOT / 'tests/cocotb'), str(TEST)]))
    with Path('simulation.log').open('w') as log:
        producer = subprocess.Popen([str(sim), '-no_save', '+seed=1', '+max_delay=0',
            '+max_cycles=' + str(cfg['max_cycles']), '+head_run', '+image_plan=' + cfg['image_plan'],
            '+ce_rom=' + cfg['ce_rom']], env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            producer.wait(timeout=cfg['wall_seconds'])
        except subprocess.TimeoutExpired:
            EvidenceRun._kill_group(producer)
            raise
    xml = ET.parse('results.xml').getroot()
    tests = xml.findall('.//testcase')
    need(producer.returncode == 0 and len(tests) == 1 and tests[0].get('name') == 'head_combo_cpu_api' and
         not any(e.tag in ('failure', 'error', 'skipped') for e in xml.iter()), 'Real head CPU API failed; retain all raw')
    need(load('checks.json')['status'] == 'PASS', 'Head observer failed')
    obs = load('observations.json')
    obs['sealed_CPU_raw'] = seal_cpu_trace('transactions.csv', obs['terminal_close'], producer,
        allowed_kinds=('CW', 'CB', 'IRQ', 'CR', 'CD', 'SA', 'SW', 'BA', 'NA', 'NW', 'NB', 'NL', 'NR', 'ND', 'MA', 'MB', 'EARLY'))
    obs['numeric']['output_sha256'] = sha256('output.bin')
    obs['RoPE_executed'] = False
    obs['RoPE_saving_cycles'] = None
    write_json('actual-results.json', obs)


class Arm:
    def __init__(self, run, name):
        self.parent, self.name = run, name
        self.build = run.build / name
        self.build.mkdir()
        self.manifest = {}

    def check(self, name, condition, detail):
        return self.parent.check(self.name + '-' + name, condition, detail)

    def execute(self, name, argv, timeout, cwd=None):
        return self.parent.execute(self.name + '-' + name, argv, timeout, cwd or self.build)


def execute_head(run, prepared_path, budget_path, tools):
    from run_ce64_soc import build
    sys.path.insert(0, str(TEST))
    from check_consumers_streaming import review
    contract = validate_prepared(prepared_path)
    validate_budget(budget_path, contract)
    _, repo, inventory = original_closure()
    lock = load(ROOT / 'configs/cocotb-toolchain-lock.json')
    need(all(sha256(item['path']) == item['sha256'] for item in lock['files'].values()), 'Locked VPI environment differs')
    write_json(run.path / 'execution-contract.json', dict(prepared_contract=str(prepared_path.resolve()),
        prepared_contract_sha256=sha256(prepared_path), independent_budget_file=str(budget_path.resolve()),
        independent_budget_sha256=sha256(budget_path), limits=LIMITS, overlay=contract['overlay']))
    shutil.copy2(budget_path, run.path / 'budget-acceptance.json')
    results, closures = {}, {}
    shared = contract['shared_input']
    for armname in ('baseline', 'variant'):
        firmware = contract['firmware'][armname]
        arm = Arm(run, armname)
        tb = arm.build / 'tb_body.svh'
        body = (ROOT / 'tests/ce64_soc/tb_body.svh').read_text().replace('soc.compute.ce.control.', 'soc.compute.ce.control.linear_control.')
        body = body.replace("cpu_bus.araddr<32'hac200000", "cpu_bus.araddr<32'hb0000000")
        body = body.replace(".model_sealed(1'b1)", ".model_sealed(1'b1),.startup_authorized(1'b0)")
        body = body.replace('backend.awlen!=0||backend.awburst!=1', "backend.awlen>31||backend.awburst!=1||(backend.awlen!=0&&backend.awsize!=4)")
        tb.write_text(body + '\n' + (TEST / 'monitor.svh').read_text())
        overrides = {str(f.relative_to(repo)): f for f in (repo / 'rtl').rglob('*') if f.is_file()}
        overrides['tests/ce64_soc/tb_body.svh'] = tb
        overlay = {n: h for n, h in contract['overlay'].items() if n.startswith('rtl/')}
        if armname == 'variant':
            overrides.update({n: COMBO / n for n in overlay})
        extra = [n for n in overlay if n.endswith('.sv') and not (repo / n).exists()] if armname == 'variant' else []
        sim = build(arm, tools, Path(lock['files']['vpi']['path']), board_memory=True, wave_window=100,
            source_overrides=overrides,
            additional_sources=[str(f.relative_to(repo)) for f in sorted((repo / 'rtl/sfu').glob('*.sv'))] + extra,
            defines=['OPT11_LANES=2'] + (['API_W_SW_VARIANT'] if armname == 'variant' else []))
        run.manifest['DUT_compiled'] = True
        run.flush()
        compiled = {str(f.relative_to(arm.build / 'sources')): sha256(f)
                    for f in (arm.build / 'sources/rtl').rglob('*') if f.is_file()}
        expected = dict(inventory)
        if armname == 'variant':
            expected.update(overlay)
        run.check(armname + '-exact-compiled-RTL', all(expected.get(n) == h for n, h in compiled.items()), len(compiled))
        if armname == 'variant':
            run.check('variant-all-six-RTL-overlay-files-compiled', set(overlay) <= set(compiled), sorted(overlay))
        closures[armname] = compiled
        case = arm.build / 'case'
        case.mkdir()
        for f in sim.parent.glob('*.bin'):
            shutil.copy2(f, case / f.name)
        cfg = dict(run_id=run.run_id, shape='head', K=896, N=151936, Y=0xac037800, arm=armname,
            max_cycles=LIMITS['head_aggregate_verification_cycles'], wall_seconds=LIMITS['head_simulation_wall_seconds'],
            prepared_contract=str(prepared_path.resolve()), budget_file=str(budget_path.resolve()),
            budget_sha256=sha256(budget_path), image_plan=str(Path(firmware['path']) / 'load.plan'),
            ce_rom=str(Path(firmware['path']) / 'ce-rom.hex'), golden=str(Path(shared['path']) / 'golden.bin'),
            expected_aq=str(Path(shared['path']) / 'expected-aq.bin'), expected_sa=str(Path(shared['path']) / 'expected-sa.bin'),
            linear_thresholds=load(ROOT / 'configs/t05-thresholds.json')['operators']['linear'])
        write_json(case / 'case.json', cfg)
        run.execute(armname + '-real-head-cpu-api', [sys.executable, Path(__file__).resolve(), '--case', case / 'case.json', '--sim', sim],
                    cfg['wall_seconds'] + 60, cwd=case)
        run.manifest.update(DUT_executed=True, head_executed=True)
        run.flush()
        obs = load(case / 'actual-results.json')
        obs['consumer_review'] = review(case / 'consumer.csv', shared, obs['terminal_close'], variant=armname == 'variant')
        obs['workload'] = streaming_workload(case / 'api-transport.csv', shared, obs['terminal_close'])
        obs['API_other_residual_cycles'] = obs['CPU_API_cycles'] - obs['counts']['linear_backend_cycles'] - obs['counts']['quantize_backend_cycles']
        run.check(armname + '-state-sum', obs['consumer_review']['state_residence_sum'] == obs['counts']['linear_backend_cycles'], obs['consumer_review']['state_residence_sum'])
        run.check(armname + '-all1187-original-publishers', obs['workload']['event_counts']['AW'] == 1187,
                  obs['workload']['event_counts']['AW'])
        results[armname] = obs
        write_json(run.path / (armname + '-results.json'), obs)
    for kind in ('AW', 'W', 'B'):
        run.check('same-complete-' + kind, results['baseline']['workload']['publisher_transport'][kind] ==
            results['variant']['workload']['publisher_transport'][kind], kind)
    run.check('same-complete-head-output', results['baseline']['numeric']['output_sha256'] ==
              results['variant']['numeric']['output_sha256'], 151936)
    saving = results['baseline']['CPU_API_cycles'] - results['variant']['CPU_API_cycles']
    run.check('net-complete-head-API-saving', saving > 0, saving)
    write_json(run.path / 'compiled-source-closures.json', closures)
    write_json(run.path / 'results.json', dict(scope=SCOPE, arms=results, CPU_API_saving_cycles=saving,
        RoPE_executed=False, RoPE_saving_cycles=None, fullgraph_cycles=None, TTFT_seconds=None,
        frequency_signoff_hz=None, qualification=False, GO=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id')
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--preflight', action='store_true',
                        help='Read-only closed contract/budget validation; no DUT compile or execution')
    parser.add_argument('--prepared-contract', type=Path)
    parser.add_argument('--budget-acceptance', type=Path)
    parser.add_argument('--reuse-prepared-inputs', type=Path,
                        help='Prep only: reuse immutable tensors/actual ELFs; all file/source hashes are checked')
    parser.add_argument('--case', type=Path)
    parser.add_argument('--sim', type=Path)
    args = parser.parse_args()
    if args.case:
        need(args.sim is not None, 'Worker requires explicit simulator and accepted frozen contract')
        execute_case(args.case, args.sim)
        return 0
    if args.preflight:
        if args.execute or not args.prepared_contract or not args.budget_acceptance:
            parser.error('--preflight requires prepared contract and independent budget, without --execute')
        contract = validate_prepared(args.prepared_contract)
        gate = validate_budget(args.budget_acceptance, contract)
        print(json.dumps(dict(status='PREFLIGHT_PASS_READ_ONLY',
            prepared_contract_sha256=sha256(args.prepared_contract), budget_sha256=sha256(args.budget_acceptance),
            experimental_content_id=contract['experimental_content_id'], allowed_shapes=gate['allowed_shapes'],
            budget_kind=gate['budget_kind'], conditional_S25M_CE_mean_remaining_cycles=gate['conditional_S25M_CE_mean_remaining_cycles'],
            conditional_S25M_CE_max_remaining_cycles=gate['conditional_S25M_CE_max_remaining_cycles'],
            allows_169_fullgraph=False, DUT_compiled=False, DUT_executed=False, head_executed=False), indent=2))
        return 0
    if not args.run_id:
        parser.error('--run-id is required')
    if args.execute:
        if not args.prepared_contract or not args.budget_acceptance:
            parser.error('Head DUT execution refuses: exact prepared contract and independent gate/down budget acceptance are required')
        contract = validate_prepared(args.prepared_contract)
        validate_budget(args.budget_acceptance, contract)
    run = EvidenceRun(ROOT, 'OPT10_R1_HEAD_COMBO_API', args.run_id)
    code = 1
    try:
        contract = base_contract()
        write_json(run.path / 'contract.json', contract)
        run.manifest.update(scope=SCOPE, experimental_content_id=EID, qualification=False, GO=False,
            DUT_compiled=False, DUT_executed=False, head_executed=False, execution_authorized=False)
        run.flush()
        tools_lock = load(ROOT / 'docs/spec/toolchain-lock.json')['tools']
        tools = {n: item['path'] for n, item in tools_lock.items()}
        run.check('locked-gcc-and-readelf', all(sha256(tools[n]) == tools_lock[n]['sha256'] for n in ('rv32_gcc', 'rv32_readelf')),
                  {n: tools_lock[n]['sha256'] for n in ('rv32_gcc', 'rv32_readelf')})
        if args.execute:
            run.manifest.update(execution_authorized=True, DUT_execution_requested=True)
            run.flush()
            execute_head(run, args.prepared_contract, args.budget_acceptance, tools)
        else:
            _, repo, _ = original_closure()
            if args.reuse_prepared_inputs:
                prior = load(args.reuse_prepared_inputs)
                need(prior['status'] == 'PREPARED_FROZEN_NO_DUT_AUTHORIZATION' and
                     prior['execution_authorized'] is False and prior['DUT_executed'] is False,
                     'Reuse must be closed prep-only data')
                for key in ('experimental_content_id', 'overlay', 'parent_candidate_id', 'shape', 'limits'):
                    need(prior[key] == contract[key], 'Immutable prep reuse differs: ' + key)
                parent_manifest = load(args.reuse_prepared_inputs.parent / 'manifest.json')
                need(parent_manifest['status'] == 'PASS' and parent_manifest['exit_code'] == 0 and
                     parent_manifest['artifacts'][args.reuse_prepared_inputs.name] == sha256(args.reuse_prepared_inputs),
                     'Reuse prep receipt is not terminal and hash-bound')
                shared, firmware = prior['shared_input'], prior['firmware']
                for image in [shared, *firmware.values()]:
                    need(all(sha256(Path(image['path']) / n) == h for n, h in image['files'].items()),
                         'Immutable shared inputs/ELF changed')
                for image in firmware.values():
                    need(all(sha256(n) == h for n, h in image['actual_gcc_source_inputs'].items()),
                         'Actual reused gcc source changed')
                contract['reused_prepared_inputs'] = dict(path=str(args.reuse_prepared_inputs.resolve()),
                    sha256=sha256(args.reuse_prepared_inputs), manifest_sha256=sha256(args.reuse_prepared_inputs.parent / 'manifest.json'),
                    scope='Only unchanged actual tensor/FP input bytes and actual compiled FW/ELFs; no DUT/performance evidence exists')
                write_json(run.path / 'shared-inputs.json', shared)
            else:
                shared = shared_inputs(run, contract)
                firmware = {arm: compile_firmware(run, repo, tools, shared, arm) for arm in ('baseline', 'variant')}
            contract.update(status='PREPARED_FROZEN_NO_DUT_AUTHORIZATION', shared_input=shared, firmware=firmware)
            write_json(run.path / 'contract.json', contract)
            run.check('prepared-input-and-actual-ELF-closure', validate_prepared(run.path / 'contract.json', require_closed=False) == contract,
                      dict(shared_bytes=sum(f.stat().st_size for f in Path(shared['path']).iterdir()),
                           firmware_ELFs={arm: info['files']['head.elf'] for arm, info in firmware.items()}))
            write_json(run.path / 'results.json', dict(scope='PREP_BUILD_ONLY_NO_DUT_NO_HEAD',
                firmware_compiled=True, actual_ELF_sha256={arm: info['files']['head.elf'] for arm, info in firmware.items()},
                shared_input_manifest_sha256=sha256(run.path / 'shared-inputs.json'), experimental_content_id=EID,
                execution_authorized=False, DUT_compiled=False, DUT_executed=False, head_executed=False,
                CPU_API_cycles=None, head_saving_cycles=None, fullgraph_cycles=None, RoPE_executed=False,
                RoPE_saving_cycles=None, TTFT_seconds=None, frequency_signoff_hz=None, qualification=False, GO=False))
        run.check('all-frozen-measurement-dependencies-after', contract['measurement_inputs'] == measurement_sources(), len(contract['measurement_inputs']))
        original_closure()
        code = 0
    except BaseException:
        (run.path / 'failure.txt').write_text(traceback.format_exc())
        print(traceback.format_exc(), flush=True)
    finally:
        for name in measurement_sources():
            source = ROOT / name
            target = run.path / 'inputs' / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        if args.execute:
            # Large raw stays at its single original build path. Archive hashes
            # preserve exact closed artifacts without a second multi-GB copy.
            index = {}
            for arm in ('baseline', 'variant'):
                case = run.build / arm / 'case'
                if case.exists():
                    index[arm] = {str(f): dict(bytes=f.stat().st_size, sha256=sha256(f))
                                  for f in case.iterdir() if f.is_file()}
            write_json(run.path / 'raw-artifact-index.json', index)
        run.manifest['artifacts'] = {str(f.relative_to(run.path)): sha256(f) for f in run.path.rglob('*')
            if f.is_file() and not (f.parent == run.path and f.name in ('manifest.json', 'commands.json', 'checks.json', 'exit-status.txt'))}
        code = run.finish(code)
    print(run.manifest['status'], run.path, flush=True)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
