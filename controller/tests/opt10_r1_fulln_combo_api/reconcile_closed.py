#!/usr/bin/env python3
"""Independently integrate a closed fullN STATE timeline and reconcile API totals."""
import argparse,csv,json,sys,traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'scripts'))
from evidence import EvidenceRun,sha256,write_json

def integral(path,close):
 states=[]
 for row in csv.reader(path.open()):
  if row[1]=='STATE':
   if len(row)!=20:raise ValueError('STATE grammar')
   states.append((int(row[0]),int(row[5]),int(row[6]),int(row[7])))
 values=dict(total=0,load=0,compute=0,write=0,other=0,restore_overlap=0)
 for i,state in enumerate(states):
  cycle,enabled,phase,restoring=state;end=states[i+1][0] if i+1<len(states) else close
  if end<cycle:raise ValueError('STATE timeline reverses')
  if enabled:
   cycles=end-cycle;values['total']+=cycles;values[('other','load','compute','write')[phase]]+=cycles
   if restoring:values['restore_overlap']+=cycles
 return values

def main():
 p=argparse.ArgumentParser();p.add_argument('--receipt',type=Path,required=True);p.add_argument('--shape',choices=('gate','down'),required=True);p.add_argument('--run-id',required=True);a=p.parse_args();r=EvidenceRun(ROOT,'OPT10_R1_FULLN_COMBO_API',a.run_id);code=1
 try:
  source=a.receipt.resolve();manifest=json.loads((source/'manifest.json').read_text());result=json.loads((source/'results.json').read_text());r.check('closed-source-receipt',manifest['status']=='PASS',sha256(source/'manifest.json'))
  contract=dict(scope='POSTPROCESS_ONLY_COMPLETE_STATE_PHASE_AND_API_RECONCILIATION',source_receipt=str(source),source_manifest_sha256=sha256(source/'manifest.json'),source_results_sha256=sha256(source/'results.json'),checker_sha256=sha256(__file__),shape=a.shape,qualification=False,DUT_started=False,GO=False);write_json(r.path/'contract.json',contract)
  arms={}
  for arm in ('baseline','variant'):
   metrics=result['shapes'][a.shape][arm];path=source/(a.shape+'-'+arm)/'case/consumer.csv';key=str(path.relative_to(source));r.check(arm+'-closed-raw-hash',sha256(path)==manifest['artifacts'][key],manifest['artifacts'][key]);actual=integral(path,metrics['terminal_close']['cycle']);reported=metrics['workload']['linear_counters'];r.check(arm+'-independent-phase-integrals',all(actual[name]==reported[name] for name in reported),dict(independent=actual,reported=reported))
   counts=metrics['counts'];residual=metrics['CPU_API_cycles']-counts['linear_backend_cycles']-counts['quantize_backend_cycles'];r.check(arm+'-API-partition',residual==metrics['API_other_residual_cycles'],residual)
   arms[arm]=dict(CPU_API_cycles=metrics['CPU_API_cycles'],linear_CE_cycles=counts['linear_backend_cycles'],quantize_CE_cycles=counts['quantize_backend_cycles'],API_other_cycles=residual,independent_CE_phase_integrals=actual,consumer_raw_sha256=manifest['artifacts'][key])
  old,new=arms['baseline'],arms['variant'];delta={name:old[name]-new[name] for name in ('CPU_API_cycles','linear_CE_cycles','quantize_CE_cycles','API_other_cycles')};r.check('complete-API-saving-exact-sum',delta['CPU_API_cycles']==delta['linear_CE_cycles']+delta['quantize_CE_cycles']+delta['API_other_cycles'],delta)
  phases={name:old['independent_CE_phase_integrals'][name]-new['independent_CE_phase_integrals'][name] for name in ('load','compute','write','other')};r.check('complete-CE-saving-exact-exclusive-sum',sum(phases.values())==delta['linear_CE_cycles'],phases)
  write_json(r.path/'results.json',dict(scope=contract['scope'],shape=a.shape,arms=arms,savings=delta,exclusive_CE_phase_savings=phases,restore_is_overlap_only=True,RoPE_executed=False,RoPE_saving_cycles=None,GO=False));code=0
 except BaseException:(r.path/'failure.txt').write_text(traceback.format_exc());print(traceback.format_exc(),flush=True)
 finally:r.finish(code)
 print(r.manifest['status'],r.path,flush=True);return code
if __name__=='__main__':raise SystemExit(main())
