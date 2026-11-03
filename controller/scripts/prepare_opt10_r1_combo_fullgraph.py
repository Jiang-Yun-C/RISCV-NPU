#!/usr/bin/env python3
"""Prepare real final169 firmware/inputs only; this file cannot launch a DUT."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import traceback

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from evidence import EvidenceRun,sha256,write_json
import run_opt10_r1_combo_fullgraph as draft
from prepare_opt16 import production

PARENT=draft.PARENT
COMBO=draft.COMBO
HEAD_PREP=ROOT/'evidence/OPT10_R1_HEAD_COMBO_API/opt10-r1-head-combo-prep-20261021-v3/contract.json'
PRODUCTION_COMMAND_PARENT=ROOT/'evidence/OPT05/opt05-freeze-20261019-v6'

def load(path):return json.loads(Path(path).read_text())
def need(ok,why):
 if not ok:raise ValueError(why)

def validate_prepared(path):
 """Read-only validation of the terminal prep closure, never execution authority."""
 path=Path(path).resolve();manifest=load(path.parent/'manifest.json');c=load(path)
 need(manifest['status']=='PASS' and manifest['exit_code']==0 and manifest.get('finished_at'),'Prep receipt is not terminal PASS')
 need(manifest['artifacts'][path.name]==sha256(path),'Prepared contract is not terminal-artifact bound')
 need(c['status']=='PREPARED_INPUTS_AND_FW_ONLY_NO_DUT_AUTHORIZATION' and c['execution_authorized'] is False and c['DUT_compiled'] is False and c['DUT_executed'] is False,'Prep cannot authorize DUT execution')
 need(c['planned_experimental_content_id']==load(COMBO/'identity.json')['experimental_content_id'] and c['overlay']==load(COMBO/'identity.json')['overlay'] and c['combined_identity_sha256']==sha256(COMBO/'identity.json'),'Prepared source identity differs')
 need(all(sha256(ROOT/n)==h for n,h in c['measurement_inputs'].items()),'Prepared measurement/source dependency differs')
 need(all(sha256(n)==h for n,h in c['actual_gcc_source_inputs'].items()),'Actual GCC source dependency differs')
 for image in c['prepared_artifacts'].values():
  need(all(sha256(Path(image['path'])/name)==h for name,h in image['files'].items()),'Prepared file differs')
 need(all(sha256(c['composed_repository']/Path(n))==h for n,h in c['composed_source_inventory'].items()),'Prepared composed repository differs')
 need(c['limits']['aggregate_verification_cycles']==600000000 and c['limits']['production_call_protection_cycles']==900000000 and c['limits']['target_complete_API_cycles']==250000000,'Original scoped deadlines differ')
 return c

def source_inputs(commands):
 result={}
 for command in commands:
  for token in command['argv']:
   if token.endswith(('.c','.S','.s','.ld')) and Path(token).is_file():result[str(Path(token).resolve())]=sha256(token)
   elif token.startswith('-T') and len(token)>2 and Path(token[2:]).is_file():result[str(Path(token[2:]).resolve())]=sha256(token[2:])
 return result

def static_review():
 """Known draft gaps are blockers for future execution, not preparation."""
 text=(ROOT/'scripts/run_opt10_r1_combo_fullgraph.py').read_text();case=(ROOT/'tests/opt10_r1_combo_fullgraph/case.py').read_text()
 tree=ast.parse(text);fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='validate_execution_contract');validation=ast.get_source_segment(text,fn)
 return [dict(id='DRAFT_EXECUTION_CONTRACT_NOT_PARENT_ARTIFACT_BOUND',blocking_before_first_169_DUT=True,evidence='validate_execution_contract receives only a dictionary; no path/terminal artifact binding to its own frozen contract.',repair='Future execution entry must accept a terminal prepared contract path, verify parent manifest/hash and exact reused FW/input closure.'),
  dict(id='DRAFT_CASE_ACCEPTS_BOOLEAN_AUTHORITY',blocking_before_first_169_DUT=True,evidence="case.py checks cfg.execution_authorized and two deadlines, without revalidating the terminal independent full169 gate or prepared closure.",repair='Worker must independently validate prepared contract and final169 acceptance file hash, exact source7 and three terminal stage manifests before spawning simulator.'),
  dict(id='DRAFT_PREPARES_AFTER_ACCEPTANCE',blocking_before_first_169_DUT=True,evidence='execute compiles fresh Oracle/FW artifacts after validating source-only contract; resulting ELF/input bytes are not prebound.',repair='Future execution must reuse this exact closed prepared image/ELF/load plan and reject any new unbound regeneration.'),
  dict(id='DRAFT_STAGE_SOURCE_AND_SCOPE_BINDING',blocking_before_first_169_DUT=True,evidence='Draft budget gate checks overlay globally and earlier manifest hashes; it does not require exact allowed_shapes/full169-only scope, per-stage source7 or combo identity SHA.',repair='Require explicit full169-only acceptance, seven-file identity hash and reviewed per-stage source closures for gate/down/head; retain conditional budget kind and unmeasured RoPE/completeAPI as null.'),
  dict(id='DRAFT_ORACLE_INDIRECT_INPUTS_NOT_EXPLICIT',blocking_before_first_169_DUT=True,evidence='Original draft measurement inventory omits configs/t11-reference.json, canonical RoPE NPZ and docs/spec/memory-map-v1.json read by the Oracle/parser.',repair='This prep explicitly freezes these inputs; future execution must bind the same closure.')]

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run-id',required=True);p.add_argument('--token',type=int,choices=(0,255),default=0);p.add_argument('--validate-prepared',type=Path);a=p.parse_args()
 if a.validate_prepared:
  validate_prepared(a.validate_prepared);print('PREPARED_CLOSURE_VALID_NO_DUT_AUTHORIZATION',a.validate_prepared);return 0
 r=EvidenceRun(ROOT,'OPT10_R1_COMBO_FULLGRAPH_PREP',a.run_id);code=1
 try:
  c=draft.draft_contract(a.token);head=load(HEAD_PREP);protected=dict(head['measurement_inputs']);protected['Makefile']=c['root_Makefile_sha256'];r.check('active-head-dependencies-unchanged-before',all(sha256(ROOT/n)==h for n,h in protected.items()),len(protected))
  deps=set(c['measurement_inputs']);deps.update(['scripts/prepare_opt10_r1_combo_fullgraph.py','scripts/prepare_opt16.py','scripts/run_opt07.py','scripts/opt16_model.py','configs/t11-reference.json','docs/spec/memory-map-v1.json'])
  rope_spec=load(ROOT/'configs/t11-reference.json')['canonical_rope'];rope_path=ROOT/rope_spec['path'];r.check('canonical-oracle-RoPE-input',sha256(rope_path)==rope_spec['sha256'],rope_spec);deps.add(rope_spec['path'])
  c.update(status='PREPARATION_STARTED_NO_DUT_AUTHORIZATION',execution_authorized=False,DUT_compiled=False,DUT_executed=False,head_decision_pending=True,actual_full169_execution_allowed=False,
   measurement_inputs={n:sha256(ROOT/n) for n in sorted(deps)},offline_prepare=dict(wrapper_sha256=sha256(__file__),wall_seconds=600,production_command_parent=str(PRODUCTION_COMMAND_PARENT),production_commands_sha256=sha256(PRODUCTION_COMMAND_PARENT/'build-commands.json'),purpose='Fresh actual production application/loader plus byte-identical successful41 measurement fixture; no application/loader execution'),
   protected_active_head_dependencies=protected,known_execution_blockers=static_review())
  write_json(r.path/'contract.json',c);r.manifest.update(scope='OFFLINE_REAL_FW_INPUT_PREPARATION_ONLY_NOT_169_AUTHORIZATION',planned_experimental_content_id=c['planned_experimental_content_id'],DUT_compiled=False,DUT_executed=False,head_executed=False,qualification=False,GO=False);r.flush()
  lock=load(ROOT/'docs/spec/toolchain-lock.json')['tools'];tools={k:v['path'] for k,v in lock.items()};r.check('locked-offline-RV32-tools',all(sha256(tools[n])==lock[n]['sha256'] for n in ('rv32_gcc','rv32_readelf','rv32_objcopy','rv32_objdump')),{n:lock[n]['sha256'] for n in ('rv32_gcc','rv32_readelf','rv32_objcopy','rv32_objdump')})
  repo,closure=draft.compose_repository(r,c)
  production(r,repo,PRODUCTION_COMMAND_PARENT)
  image=draft.prepare_image(r,repo,tools,a.token)
  commands=r.steps;sources=source_inputs(commands);r.check('all-fresh-source-no-object-inputs',all(not str(x).endswith(('.o','.a')) for cmd in commands for x in cmd['argv']),len(sources))
  fixture_command=next(cmd for cmd in commands if cmd['name']=='firmware');need(str(repo/'firmware/runtime/reference/nx_reference.c') in fixture_command['argv'] and str(ROOT/'tests/opt10_r1_combo_fullgraph/fullgraph.c') in fixture_command['argv'],'Fixture did not compile the actual combo/reference and original successful41 source')
  production_command=next(cmd for cmd in commands if cmd['name']=='production-link');need(str(repo/'firmware/runtime/reference/nx_reference.c') in production_command['argv'],'Production app did not compile actual combo reference')
  r.check('actual-reference-and-successful41-fixture',sha256(repo/'firmware/runtime/reference/nx_reference.c')==draft.EXPECTED_ROPE and sha256(ROOT/'tests/opt10_r1_combo_fullgraph/fullgraph.c')==draft.FIXTURE_HASH,dict(reference=draft.EXPECTED_ROPE,fixture=draft.FIXTURE_HASH))
  r.check('actual-production-layout-header',sha256(image/'full_weights.h')==sha256(r.build/'production/full_weights.h')==sha256(PARENT/'production/full_weights.h'),sha256(image/'full_weights.h'))
  fixture=load(image/'fixture.json');model_regions=[x for x in fixture['regions'] if x['kind']=='immutable_model'];r.check('verified-full-pack-physical-payloads',len(model_regions)==len({x['name'] for x in model_regions}) and all(sha256(x['path'])==x['sha256'] for x in model_regions),dict(regions=len(model_regions),bytes=sum(x['bytes'] for x in model_regions)))
  old_fixture=load(draft.V41/'fixture-freeze.json');r.check('independent-token0-oracle-closure',a.token!=0 or sha256(image/'golden.bin')==old_fixture['golden_sha256'],dict(current=sha256(image/'golden.bin'),prior41=old_fixture['golden_sha256'],scope='Only immutable independent oracle/input identity; no41 performance or acceptance inherited'))
  trusted=(r.build/'loader/trusted.h').read_text();hashes={n:''.join(re.findall(r'0x([0-9a-f]{2})',body)) for n,body in re.findall(r'nx_trusted_(apps|models)\[\]\[32\]=\{\{([^}]+)\}',trusted)};r.check('fresh-loader-trust-bound-to-fresh-app-and-original-model',hashes==dict(apps=sha256(r.build/'production/application.bin'),models=fixture['model_pack_sha256']),hashes)
  for directory in ('production','loader','image'):
   destination=r.path/directory;shutil.copytree(r.build/directory,destination)
  artifacts={directory:dict(path=str(r.build/directory),files={str(f.relative_to(r.build/directory)):sha256(f) for f in (r.build/directory).rglob('*') if f.is_file()}) for directory in ('production','loader','image')}
  c.update(status='PREPARED_INPUTS_AND_FW_ONLY_NO_DUT_AUTHORIZATION',prepared_artifacts=artifacts,composed_repository=str(repo),composed_source_inventory=closure,actual_gcc_source_inputs=sources,actual_gcc_commands=[cmd for cmd in commands if any(str(x).endswith(('-gcc','-objcopy','-objdump','-readelf')) for x in cmd['argv'][:1])],model_input=dict(full_pack_sha256=fixture['model_pack_sha256'],physical_model_regions=len(model_regions),physical_model_bytes=sum(x['bytes'] for x in model_regions),golden_sha256=sha256(image/'golden.bin'),golden_scope='Fresh independent Python Oracle.forward token plusKV, no candidate outputs',fixture_sha256=sha256(image/'fixture.json'),load_plan_sha256=sha256(image/'load.plan')),complete_API_cycles=None,RoPE_saving_cycles=None,production_service=None,TTFT_seconds=None,frequency_signoff_hz=None,qualification=False,GO=False)
  write_json(r.path/'contract.json',c);write_json(r.path/'review-findings.json',dict(scope='SOURCE_REVIEW_ONLY_PREPARATION_ALLOWED_EXECUTION_BLOCKED',findings=c['known_execution_blockers'],all_before_first169=True,DUT_executed=False))
  r.check('exact-composed-source-after',all(sha256(repo/n)==h for n,h in closure.items()),len(closure));r.check('active-head-dependencies-unchanged-after',all(sha256(ROOT/n)==h for n,h in protected.items()),len(protected));r.check('frozen-preparation-inputs-after',all(sha256(ROOT/n)==h for n,h in c['measurement_inputs'].items()),len(c['measurement_inputs']))
  write_json(r.path/'results.json',dict(scope='OFFLINE_REAL_APPLICATION_LOADER_AND_FULL169_FIXTURE_PREPARATION_ONLY',planned_experimental_content_id=c['planned_experimental_content_id'],actual_production_application_ELF_sha256=sha256(r.build/'production/application.elf'),actual_loader_ELF_sha256=sha256(r.build/'loader/loader.elf'),actual_measurement_ELF_sha256=sha256(image/'fullgraph.elf'),golden_sha256=sha256(image/'golden.bin'),model_pack_sha256=fixture['model_pack_sha256'],execution_blockers=len(c['known_execution_blockers']),DUT_compiled=False,DUT_executed=False,loader_executed=False,full169_executed=False,complete_API_cycles=None,RoPE_saving_cycles=None,TTFT_seconds=None,frequency_signoff_hz=None,qualification=False,GO=False));code=0
 except BaseException:(r.path/'failure.txt').write_text(traceback.format_exc());print(traceback.format_exc(),flush=True)
 finally:
  for n in c.get('measurement_inputs',{}) if 'c' in locals() else []:
   out=r.path/'measurement-sources'/n;out.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/n,out)
  r.manifest['artifacts']={str(f.relative_to(r.path)):sha256(f) for f in r.path.rglob('*') if f.is_file() and not(f.parent==r.path and f.name in ('manifest.json','commands.json','checks.json','exit-status.txt'))};r.finish(code)
 print(r.manifest['status'],r.path,flush=True);return code

if __name__=='__main__':raise SystemExit(main())
