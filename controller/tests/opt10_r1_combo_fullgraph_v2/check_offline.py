#!/usr/bin/env python3
"""Targeted offline checks for the five actual final169 draft boundary gaps."""
import argparse,ast,copy,json,shutil,subprocess,sys,traceback
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from evidence import EvidenceRun,sha256,write_json
import run_opt10_r1_combo_fullgraph_v2 as runner

PREP=ROOT/'evidence/OPT10_R1_COMBO_FULLGRAPH_PREP/opt10-r1-combo-fullgraph-offline-prep-20261021-v1/contract.json'
GATE=ROOT/'evidence/OPT10_R1_FULLN_COMBO_API/opt10-r1-fulln-combo-gate-down-20261021-v2'
DOWN=ROOT/'evidence/OPT10_R1_FULLN_COMBO_API/opt10-r1-fulln-combo-down-20261021-v1'

def main():
 p=argparse.ArgumentParser();p.add_argument('--run-id',required=True);a=p.parse_args();r=EvidenceRun(ROOT,'OPT10_R1_COMBO_FULLGRAPH_V2_OFFLINE',a.run_id);code=1
 try:
  sources=[Path(runner.__file__),Path(__file__),ROOT/'tests/opt10_r1_combo_fullgraph_v2/case.py',ROOT/'tests/opt10_r1_combo_fullgraph/observer.py'];write_json(r.path/'contract.json',dict(scope='FIVE_REAL_BOUNDARY_GAPS_OFFLINE_ONLY_NO_DUT',checker_sha256=sha256(__file__),source_sha256={str(f.relative_to(ROOT)):sha256(f) for f in sources},prepared_contract_sha256=sha256(PREP),limits=dict(wall_seconds=180),synthetic_inputs_are_never_authorization=True,DUT_compiled=False,DUT_executed=False,GO=False))
  c=runner.prepared(PREP);r.check('real-closed-prep-source-input-FW-closure',True,dict(source_files=len(c['composed_source_inventory']),overlays=len(c['overlay'])))
  results={}
  def reject(name,fn):
   try:fn()
   except (ValueError,KeyError,FileNotFoundError) as error:results[name]=str(error)
   else:raise ValueError('Boundary negative escaped: '+name)
  # 1. The contract itself must have a closed parent/artifact binding.
  loose=r.build/'loose';loose.mkdir();(loose/'contract.json').write_text(PREP.read_text());reject('unbound-execution-contract',lambda:runner.validate_execution_contract(loose/'contract.json'));reject('prep-is-not-execution-authority',lambda:runner.validate_execution_contract(PREP))
  # 2. A worker cannot launch from a Boolean in an arbitrary case document.
  worker=r.build/'worker';worker.mkdir();case=worker/'case.json';write_json(case,dict(execution_authorized=True,max_cycles=600000000,production_protection_cycles=900000000));process=subprocess.run([sys.executable,ROOT/'tests/opt10_r1_combo_fullgraph_v2/case.py','--case',case,'--sim','/bin/true'],cwd=worker,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=15)
  r.check('worker-Boolean-alone-refused-before-producer',process.returncode!=0 and not (worker/'simulation.log').exists() and not (worker/'case-status.json').exists(),process.stderr[-1200:])
  # 3. Admitted execution has no FW/input-generation call. Immutable worker
  # field checks are tested purely, with the outer gate validator substituted;
  # this test never supplies its synthetic data to CLI --execute or a worker.
  tree=ast.parse(Path(runner.__file__).read_text());execute=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='execute');calls=[n.func.attr if isinstance(n.func,ast.Attribute) else n.func.id if isinstance(n.func,ast.Name) else '' for n in ast.walk(execute) if isinstance(n,ast.Call)];r.check('execution-does-not-regenerate-Oracle-or-FW',not set(calls)&{'prepare_image','compose_repository','production','Oracle'},calls)
  image=Path(c['prepared_artifacts']['image']['path']);repo=Path(c['composed_repository']);cfg=dict(execution_contract=str(PREP),execution_contract_sha256=sha256(PREP),execution_authorized=True,experimental_content_id=c['planned_experimental_content_id'],scope=runner.SCOPE,max_cycles=600000000,production_protection_cycles=900000000,wall_seconds=28800,stable_cycles=4,seed=1,max_delay=3,fixture=str(image/'fixture.json'),golden=str(image/'golden.bin'),thresholds=str(ROOT/'configs/t05-thresholds.json'),norm_catalog=str(repo/'firmware/drivers/accel/opt10_norm_catalog.json'),image_plan=str(image/'load.plan'),ce_rom=str(image/'ce-rom.hex'))
  for name in ('fixture','golden','thresholds','norm_catalog'):cfg[name+'_sha256']=sha256(cfg[name])
  with patch.object(runner,'validate_execution_contract',return_value=(dict(experimental_content_id=c['planned_experimental_content_id']),c,{})):
   runner.validate_worker_case(cfg);bad=copy.deepcopy(cfg);bad['image_plan']=str(image/'different.plan');reject('worker-rejects-unfrozen-load-plan',lambda:runner.validate_worker_case(bad));bad=copy.deepcopy(cfg);bad['golden_sha256']='0'*64;reject('worker-rejects-unfrozen-golden',lambda:runner.validate_worker_case(bad))
  # 4. A semantic gate is bound to exact identity and three actual stages.
  for name,path in (('gate',GATE),('down',DOWN)):
   proof=runner.stage_closure(path,name,c);r.check(name+'-actual-source7-derived-from-realFW-and-compiledRTL',proof['overlay']==c['overlay'],proof['manifest_sha256'])
  reject('gate-cannot-be-relabelled-head',lambda:runner.stage_closure(GATE,'head',c))
  budget=dict(scope=runner.GATE_SCOPE,independent_review=True,allow_full169=True,allowed_shapes=['full169'],experimental_content_id=c['planned_experimental_content_id'],overlay=c['overlay'],combo_identity_sha256=c['combined_identity_sha256'],budget_kind=runner.BUDGET_KIND,RoPE_saving_cycles=None,complete_API_cycles=None,conditional_S25M_CE_min_remaining_cycles=2,conditional_S25M_CE_mean_remaining_cycles=1,conditional_S25M_CE_max_remaining_cycles=-1,decisions={n:'ACCEPT' for n in ('gate','down','head')},reviewed_overlay={n:c['overlay'] for n in ('gate','down','head')},reviewed_combo_identity_sha256={n:c['combined_identity_sha256'] for n in ('gate','down','head')})
  r.check('pure-conditional-schema-only',runner.validate_gate_fields(budget,c)==budget,'Synthetic fields only, no actual budget receipt, execution seal or DUT')
  mutations={'not169-only':lambda d:d.update(allowed_shapes=['head']),'wrong-seven-file-source':lambda d:d['overlay'].update({'firmware/runtime/reference/nx_reference.c':'0'*64}),'wrong-identity-hash':lambda d:d.update(combo_identity_sha256='0'*64),'head-unaccepted':lambda d:d['decisions'].update(head='PENDING'),'head-source-unbound':lambda d:d['reviewed_overlay'].update(head={}), 'negative-conditional-budget':lambda d:d.update(conditional_S25M_CE_mean_remaining_cycles=-1),'pretend-measured-RoPE':lambda d:d.update(RoPE_saving_cycles=25173404)}
  for name,mutate in mutations.items():
   bad=copy.deepcopy(budget);mutate(bad);reject(name,lambda:runner.validate_gate_fields(bad,c))
  # 5. Indirect Oracle/parser dependencies are part of the existing prep.
  spec=runner.load(ROOT/'configs/t11-reference.json')['canonical_rope'];required={'configs/t11-reference.json','docs/spec/memory-map-v1.json',spec['path']};r.check('indirect-Oracle-parser-inputs-frozen',required<=set(c['measurement_inputs']),sorted(required))
  # Missing real head/final169 gate refuses before any DUT evidence directory.
  refuse=a.run_id+'-must-not-exist';out=subprocess.run([sys.executable,Path(runner.__file__),'--seal-contract','--prepared-contract',PREP,'--budget-acceptance',r.build/'missing/final169-gate.json','--run-id',refuse],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=30);r.check('CLI-no-real-budget-no-contract-or-DUT-receipt',out.returncode!=0 and not (ROOT/'evidence/OPT10_R1_COMBO_FULLGRAPH_EXECUTION_CONTRACT'/refuse).exists() and not (ROOT/'evidence/OPT10_R1_COMBO_FULLGRAPH_V2'/refuse).exists(),out.stderr[-1200:])
  write_json(r.path/'negatives.json',results);write_json(r.path/'results.json',dict(scope='OFFLINE_BOUNDARY_REPAIR_CHECKS_ONLY',five_draft_blockers_repaired_in_new_v2=True,negative_cases=len(results),real_fullN_source_closures_checked=2,real_head_or_final169_acceptance_not_fabricated=True,existing_prepared_FW_and_inputs_reused=True,DUT_compiled=False,DUT_executed=False,full169_executed=False,complete_API_cycles=None,RoPE_saving_cycles=None,GO=False));code=0
 except BaseException:(r.path/'failure.txt').write_text(traceback.format_exc());print(traceback.format_exc(),flush=True)
 finally:
  for f in sources if 'sources' in locals() else []:
   out=r.path/'sources'/f.relative_to(ROOT);out.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(f,out)
  r.manifest.update(scope='OFFLINE_BOUNDARY_REPAIR_CHECKS_ONLY',DUT_compiled=False,DUT_executed=False,qualification=False,GO=False);r.manifest['artifacts']={str(f.relative_to(r.path)):sha256(f) for f in r.path.rglob('*') if f.is_file() and not(f.parent==r.path and f.name in ('manifest.json','commands.json','checks.json','exit-status.txt'))};r.finish(code)
 print(r.manifest['status'],r.path,flush=True);return code

if __name__=='__main__':raise SystemExit(main())
