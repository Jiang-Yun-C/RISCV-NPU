#!/usr/bin/env python3
"""Seal/run one real final169 witness only after the independent three-stage gate."""
import argparse
import json
import math
from pathlib import Path
import shutil
import sys
import traceback

ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from evidence import EvidenceRun,sha256,write_json
import prepare_opt10_r1_combo_fullgraph as prep
import run_opt10_r1_combo_fullgraph as original

TEST=ROOT/'tests/opt10_r1_combo_fullgraph_v2'
OBSERVER=ROOT/'tests/opt10_r1_combo_fullgraph/observer.py'
SCOPE='ONE_SAME_A74_FULL169_POSTLOAD_API_MEASUREMENT_NOT_QUALIFICATION'
GATE_SCOPE='OPT10_R1_COMBO_FULLN_HEAD_INDEPENDENT_BUDGET_GATE'
BUDGET_KIND='CONDITIONAL_REFERENCE_EVENT_SCREEN_NOT_MEASURED_COMPLETE_API'

def load(path):return json.loads(Path(path).read_text())
def need(ok,why):
 if not ok:raise ValueError(why)

def terminal(path):
 path=Path(path).resolve();m=load(path/'manifest.json')
 need(m['status']=='PASS' and m['exit_code']==0 and m.get('finished_at'),'Required receipt is not terminal PASS: '+str(path))
 return m

def bound(path,name,manifest=None):
 path=Path(path).resolve();m=manifest or terminal(path);f=path/name
 need(m['artifacts'][name]==sha256(f),'Terminal artifact differs: '+str(f));return load(f)

def stage_closure(path,shape,c):
 """Derive seven-file identity from actual earlier FW inputs and compiled RTL."""
 path=Path(path).resolve();m=terminal(path);contract=bound(path,'contract.json',m);result=bound(path,'results.json',m)
 overlay=c['overlay'];identity=c['combined_identity_sha256'];ref='firmware/runtime/reference/nx_reference.c';rtl={n:h for n,h in overlay.items() if n.startswith('rtl/')}
 if shape in ('gate','down'):
  need(contract['selected_shapes']==[shape] and set(result['shapes'])=={shape},'Earlier fullN shape differs: '+shape)
  proposed=bound(path,'variant-identity.json',m);need(sha256(path/'variant-identity.json')==identity and proposed['overlay']==overlay,'Earlier fullN identity differs: '+shape)
  need(contract['variant_identity_sha256']==identity and contract['overlay']==rtl,'Earlier fullN RTL closure differs: '+shape)
  image=contract['images'][shape+'_variant'];fw=image['actual_gcc_source_inputs'];need(image['reference_source_sha256']==overlay[ref] and fw[image['reference_source']]==overlay[ref],'Earlier actual fullN reference C differs: '+shape)
  expected=dict(gate=(4864,896),down=(896,4864))[shape];witness=result['shapes'][shape];need((image['N'],image['K'])==expected and (witness['variant']['N'],witness['variant']['K'])==expected and witness['CPU_API_saving_cycles']>0,'Earlier fullN actual shape/gain differs: '+shape)
  actual=bound(path,'compiled-source-closures.json',m)[shape]['variant']
 else:
  need(shape=='head' and contract['experimental_content_id']==c['planned_experimental_content_id'] and contract['overlay']==overlay and contract['combo_identity_sha256']==identity,'Earlier head identity differs')
  execution=bound(path,'execution-contract.json',m);hp=Path(execution['prepared_contract']);hm=terminal(hp.parent);need(hm['artifacts'][hp.name]==sha256(hp)==execution['prepared_contract_sha256'],'Head actual prepared contract differs');h=load(hp)
  need(h['shape']==dict(M=1,N=151936,K=896,W=0x80000000,Sw=0x881d4000,bias=0,Y=0xac037800) and h['overlay']==overlay and h['combo_identity_sha256']==identity,'Head actual prepared source/input identity differs')
  image=h['firmware']['variant'];fw=image['actual_gcc_source_inputs'];need(image['reference_sha256']==overlay[ref] and fw[image['reference_source']]==overlay[ref],'Head actual reference C differs')
  need(result['CPU_API_saving_cycles']>0 and result['arms']['variant']['N']==151936 and result['arms']['variant']['K']==896,'Actual complete head shape/gain differs')
  actual=bound(path,'compiled-source-closures.json',m)['variant']
 need(all(actual.get(n)==h for n,h in rtl.items()) and all(c['composed_source_inventory'].get(n)==h for n,h in actual.items()),'Earlier compiled RTL differs: '+shape)
 need(result.get('RoPE_executed') is False and result.get('RoPE_saving_cycles') is None,'Earlier single-linear stage may not claim RoPE execution/saving')
 return dict(path=str(path),manifest_sha256=sha256(path/'manifest.json'),overlay=overlay,combo_identity_sha256=identity)

def validate_gate_fields(g,c):
 """Pure semantic gate; a positive synthetic unit input never launches a DUT."""
 need(g.get('scope')==GATE_SCOPE and g.get('independent_review') is True and g.get('allow_full169') is True,'No independent final169 acceptance')
 need(g.get('allowed_shapes')==['full169'],'Gate must permit only the full169 witness')
 need(g.get('experimental_content_id')==c['planned_experimental_content_id'] and g.get('overlay')==c['overlay'] and g.get('combo_identity_sha256')==c['combined_identity_sha256'],'Gate accepts a different source identity')
 need(g.get('budget_kind')==BUDGET_KIND and 'RoPE_saving_cycles' in g and g['RoPE_saving_cycles'] is None and 'complete_API_cycles' in g and g['complete_API_cycles'] is None,'Conditional budget must not become measured API/RoPE saving')
 need(g.get('GO',False) is False and g.get('qualification',False) is False,'A measurement gate cannot grant release qualification/GO')
 for name in ('min','mean','max'):
  value=g.get('conditional_S25M_CE_'+name+'_remaining_cycles');need(type(value) in (int,float) and math.isfinite(value),'Conditional budget envelope missing/nonfinite: '+name)
 need(g['conditional_S25M_CE_mean_remaining_cycles']>=0,'Conditional S25M mean budget is negative')
 for name in ('gate','down','head'):
  need(g['decisions'][name]=='ACCEPT' and g['reviewed_overlay'][name]==c['overlay'] and g['reviewed_combo_identity_sha256'][name]==c['combined_identity_sha256'],'Earlier reviewed stage/source not accepted: '+name)
 return g

def validate_budget(path,c):
 path=Path(path).resolve();need(path.name=='final169-gate.json','Final gate filename differs');m=terminal(path.parent);g=bound(path.parent,path.name,m);validate_gate_fields(g,c);stages={}
 for shape in ('gate','down','head'):
  witness=stage_closure(g['reviewed_receipts'][shape],shape,c);need(witness['manifest_sha256']==g['reviewed_manifest_sha256'][shape],'Earlier manifest differs from independent review: '+shape);stages[shape]=witness
 need(len({v['path'] for v in stages.values()})==3,'Each actual stage must be its own complete receipt')
 return g,stages

def dependencies(c):
 names=set(c['measurement_inputs']);names.update(['scripts/run_opt10_r1_combo_fullgraph_v2.py','tests/opt10_r1_combo_fullgraph_v2/case.py'])
 return {n:sha256(ROOT/n) for n in sorted(names)}

def prepared(path):
 path=Path(path).resolve();c=prep.validate_prepared(path)
 need(len(c['composed_source_inventory'])==233 and len(c['overlay'])==7,'Prepared full source closure differs')
 need(c['fixture']['sha256']==original.FIXTURE_HASH and c['fixture']['token'] in (0,255),'Original successful41 fixture differs')
 return c

def validate_execution_contract(path):
 path=Path(path).resolve();m=terminal(path.parent);e=bound(path.parent,path.name,m)
 need(e['scope']==SCOPE and e['status']=='SEALED_ONE_FINAL169_EXECUTION_CONTRACT' and e['execution_authorized'] is True,'No sealed final169 contract')
 p=Path(e['prepared_contract']);need(sha256(p)==e['prepared_contract_sha256'] and sha256(p.parent/'manifest.json')==e['prepared_manifest_sha256'],'Prepared parent identity differs');c=prepared(p)
 need(e['experimental_content_id']==c['planned_experimental_content_id'] and e['overlay']==c['overlay'] and e['combo_identity_sha256']==c['combined_identity_sha256'],'Sealed execution source differs')
 need(e['measurement_inputs']==dependencies(c),'Sealed execution measurement dependency differs')
 need(e['limits']==c['limits'] and e['native_max_delay']==load(ROOT/'configs/opt12-vector.json')['max_delay']==3,'Original scoped deadline/native environment differs')
 b=Path(e['independent_budget']);need(sha256(b)==e['independent_budget_sha256'] and sha256(b.parent/'manifest.json')==e['independent_budget_manifest_sha256'],'Independent budget parent/artifact identity differs');g,stages=validate_budget(b,c);need(stages==e['reviewed_stages'],'Actual reviewed stage closure differs')
 return e,c,g

def seal(prepared_path,budget_path,run_id):
 # Every refusal is before EvidenceRun, tools, DUT compilation or simulation.
 p=Path(prepared_path).resolve();b=Path(budget_path).resolve();c=prepared(p);g,stages=validate_budget(b,c)
 r=EvidenceRun(ROOT,'OPT10_R1_COMBO_FULLGRAPH_EXECUTION_CONTRACT',run_id);code=1
 try:
  e=dict(schema_version=1,scope=SCOPE,status='SEALED_ONE_FINAL169_EXECUTION_CONTRACT',execution_authorized=True,prepared_contract=str(p),prepared_contract_sha256=sha256(p),prepared_manifest_sha256=sha256(p.parent/'manifest.json'),independent_budget=str(b),independent_budget_sha256=sha256(b),independent_budget_manifest_sha256=sha256(b.parent/'manifest.json'),experimental_content_id=c['planned_experimental_content_id'],overlay=c['overlay'],combo_identity_sha256=c['combined_identity_sha256'],measurement_inputs=dependencies(c),limits=c['limits'],native_max_delay=3,reviewed_stages=stages,budget_kind=BUDGET_KIND,budget_scope='Conditional reference-event screen only; this once-only actual full API witness must measure <=250M. max_delay3 preserves original41 environment; prior stage max_delay0 is not a production DDR calibration.',RoPE_saving_cycles=None,complete_API_cycles=None,qualification=False,GO=False)
  write_json(r.path/'contract.json',e);write_json(r.path/'results.json',dict(scope='CONTRACT_SEAL_ONLY_NO_DUT',DUT_compiled=False,DUT_executed=False,complete_API_cycles=None,RoPE_saving_cycles=None,GO=False));code=0
 finally:
  r.manifest.update(scope='SEALED_CONTRACT_ONLY_NO_DUT',DUT_compiled=False,DUT_executed=False,qualification=False,GO=False);r.manifest['artifacts']={str(f.relative_to(r.path)):sha256(f) for f in r.path.rglob('*') if f.is_file() and f.name not in ('manifest.json','commands.json','checks.json','exit-status.txt')};r.finish(code)
 print(r.manifest['status'],r.path,flush=True);return code

def validate_worker_case(cfg,sim=None):
 path=Path(cfg['execution_contract']);need(sha256(path)==cfg['execution_contract_sha256'],'Worker execution contract differs');e,c,g=validate_execution_contract(path);image=Path(c['prepared_artifacts']['image']['path']);repo=Path(c['composed_repository'])
 need(cfg['execution_authorized'] is True and cfg['experimental_content_id']==e['experimental_content_id'] and cfg['scope']==SCOPE,'Worker source/scope differs')
 expected=dict(max_cycles=600000000,production_protection_cycles=900000000,wall_seconds=28800,stable_cycles=4,seed=1,max_delay=3,fixture=str(image/'fixture.json'),golden=str(image/'golden.bin'),thresholds=str(ROOT/'configs/t05-thresholds.json'),norm_catalog=str(repo/'firmware/drivers/accel/opt10_norm_catalog.json'),image_plan=str(image/'load.plan'),ce_rom=str(image/'ce-rom.hex'))
 for key,value in expected.items():need(cfg[key]==value,'Worker prepared/environment field differs: '+key)
 for name in ('fixture','golden','thresholds','norm_catalog'):need(sha256(cfg[name])==cfg[name+'_sha256'],'Worker immutable input differs: '+name)
 if sim is not None:
  need(str(Path(sim).resolve())==cfg['compiled_simulator'] and sha256(sim)==cfg['compiled_simulator_sha256'],'Worker simulator binary differs from admitted compile')
  source=Path(cfg['compiled_source_closure']);need(sha256(source)==cfg['compiled_source_closure_sha256'],'Worker compiled source inventory differs');actual=load(source)
  need(all(c['composed_source_inventory'].get(n)==h for n,h in actual.items()) and all(actual.get(n)==h for n,h in c['overlay'].items() if n.startswith('rtl/')),'Worker compiled RTL differs from all prepared source/overlay')
  compiled=Path(cfg['compiled_source_directory']);need(all(sha256(compiled/n)==h for n,h in actual.items()),'Worker actual compiled source files differ')
 return e,c,g

def execute(contract_path,run_id):
 e,c,g=validate_execution_contract(contract_path)
 # Sealed contract is for one witness. Refuse any earlier admitted attempt,
 # including preserved FAIL; a second attempt needs a new explicit gate/seal.
 family=ROOT/'evidence/OPT10_R1_COMBO_FULLGRAPH_V2'
 if family.exists():
  for old in family.glob('*/contract.json'):
   prior=load(old);need(prior.get('sealed_execution_contract_sha256')!=sha256(contract_path),'This one-witness contract already has a preserved attempt')
 r=EvidenceRun(ROOT,'OPT10_R1_COMBO_FULLGRAPH_V2',run_id);code=1
 try:
  write_json(r.path/'contract.json',dict(scope=SCOPE,sealed_execution_contract=str(Path(contract_path).resolve()),sealed_execution_contract_sha256=sha256(contract_path),prepared_contract=e['prepared_contract'],overlay=e['overlay'],experimental_content_id=e['experimental_content_id']));r.manifest.update(scope=SCOPE,DUT_compiled=False,DUT_executed=False,qualification=False,GO=False);r.flush()
  repo=Path(c['composed_repository']);image=Path(c['prepared_artifacts']['image']['path']);tool_lock=load(ROOT/'docs/spec/toolchain-lock.json')['tools'];tools={n:v['path'] for n,v in tool_lock.items()};lock=load(ROOT/'configs/cocotb-toolchain-lock.json');need(sha256(tools['vcs'])==tool_lock['vcs']['sha256'],'Locked VCS executable differs');need(all(sha256(v['path'])==v['sha256'] for v in lock['files'].values()),'Locked VPI environment differs')
  sim=original.build_dut(r,repo,c['composed_source_inventory'],tools,Path(lock['files']['vpi']['path']));r.manifest['DUT_compiled']=True;r.flush();case=r.build/'case';case.mkdir()
  for f in sim.parent.glob('*.bin'):shutil.copy2(f,case/f.name)
  cfg=load(ROOT/'configs/opt12-vector.json');cfg.update(case_id='token'+str(c['fixture']['token'])+'-seed1',run_id=r.run_id,scope=SCOPE,execution_authorized=True,experimental_content_id=e['experimental_content_id'],execution_contract=str(Path(contract_path).resolve()),execution_contract_sha256=sha256(contract_path),max_cycles=600000000,production_protection_cycles=900000000,wall_seconds=28800,stable_cycles=4,seed=1,max_delay=3,fixture=str(image/'fixture.json'),golden=str(image/'golden.bin'),thresholds=str(ROOT/'configs/t05-thresholds.json'),norm_catalog=str(repo/'firmware/drivers/accel/opt10_norm_catalog.json'),image_plan=str(image/'load.plan'),ce_rom=str(image/'ce-rom.hex'))
  for name in ('fixture','golden','thresholds','norm_catalog'):cfg[name+'_sha256']=sha256(cfg[name])
  cfg.update(compiled_simulator=str(sim.resolve()),compiled_simulator_sha256=sha256(sim),compiled_source_closure=str(r.path/'compiled-source-closure.json'),compiled_source_closure_sha256=sha256(r.path/'compiled-source-closure.json'),compiled_source_directory=str(r.build/'sources'))
  validate_worker_case(cfg,sim);write_json(case/'case.json',cfg);r.manifest.update(DUT_execution_attempted=True,DUT_executed=None);r.flush();r.execute('actual-once-only-combined-full169',[sys.executable,TEST/'case.py','--case',case/'case.json','--sim',sim],28860,cwd=case);observed=load(case/'actual-results.json');write_json(r.path/'results.json',observed);r.check('actual-complete-API-within-original250M',observed['api_cycles']<=250000000,observed['api_cycles']);validate_execution_contract(contract_path);code=0
 except BaseException:(r.path/'failure.txt').write_text(traceback.format_exc());print(traceback.format_exc(),flush=True)
 finally:
  status=r.build/'case/case-status.json'
  if status.exists():r.manifest['DUT_executed']=load(status).get('producer_pid') is not None
  if (r.build/'case').exists():shutil.copytree(r.build/'case',r.path/'case')
  r.manifest['artifacts']={str(f.relative_to(r.path)):sha256(f) for f in r.path.rglob('*') if f.is_file() and not(f.parent==r.path and f.name in ('manifest.json','commands.json','checks.json','exit-status.txt'))};r.finish(code)
 print(r.manifest['status'],r.path,flush=True);return code

def main():
 p=argparse.ArgumentParser(description=__doc__);mode=p.add_mutually_exclusive_group(required=True);mode.add_argument('--seal-contract',action='store_true');mode.add_argument('--execute',action='store_true');mode.add_argument('--preflight',action='store_true');p.add_argument('--run-id');p.add_argument('--prepared-contract',type=Path);p.add_argument('--budget-acceptance',type=Path);p.add_argument('--execution-contract',type=Path);a=p.parse_args()
 if a.seal_contract:
  if not a.prepared_contract or not a.budget_acceptance or not a.run_id:p.error('Sealing refuses: terminal prepared contract and actual independent final169 gate are required')
  return seal(a.prepared_contract,a.budget_acceptance,a.run_id)
 if not a.execution_contract:p.error('Execution/preflight refuses: sealed terminal execution contract is required')
 if a.preflight:validate_execution_contract(a.execution_contract);print('CLOSED_FINAL169_CONTRACT_VALID_NO_DUT_EXECUTION',a.execution_contract);return 0
 if not a.run_id:p.error('Execution requires --run-id')
 return execute(a.execution_contract,a.run_id)

if __name__=='__main__':raise SystemExit(main())
