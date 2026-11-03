#!/usr/bin/env python3
"""Stop only the named offline head simulator after the independent model3 budget rejection."""
import json,os,signal,sys,time,traceback,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from evidence import EvidenceRun,sha256,write_json
RUN='opt10-r1-head-combo-api-ab-20261021-v1'
HEAD=ROOT/'evidence/OPT10_R1_HEAD_COMBO_API'/RUN
BUILD=ROOT/'build/OPT10_R1_HEAD_COMBO_API'/RUN
DECISION=ROOT/'evidence/OPT10_R1_GUARD_REVIEW/opt10-r1-model3-gate-raw-independent-20261021-v1/final169-gate.json'
PIDS={'runner':2761034,'worker':2762368,'simulator':2762433}
def info(pid):
 p=Path('/proc')/str(pid)
 try:return dict(pid=pid,argv=(p/'cmdline').read_bytes().rstrip(b'\0').decode().split('\0'),cwd=str((p/'cwd').resolve()),pgid=os.getpgid(pid),state=(p/'stat').read_text().split(') ',1)[1].split()[0])
 except (FileNotFoundError,ProcessLookupError):return None
def alive(pid):
 r=info(pid);return r is not None and r['state']!='Z'
def main():
 r=EvidenceRun(ROOT,'OPT10_R1_EXECUTION_STOP','opt10-r1-native3-budget-stop-20261021-v1');code=1
 try:
  m=json.loads((DECISION.parent/'manifest.json').read_text());d=json.loads(DECISION.read_text())
  r.check('independent-terminal-stop',m['status']=='PASS' and m['exit_code']==0 and m['artifacts'][DECISION.name]==sha256(DECISION) and d['decision']=='REJECT_169_AND_ADDITIONAL_HEAD0_ARMS' and d['allow_full169'] is False,d['status'])
  before={k:info(pid) for k,pid in PIDS.items()};write_json(r.path/'processes-before.json',before)
  sim=str(BUILD/'baseline/compiled/simv');worker_case=str(BUILD/'baseline/case/case.json')
  r.check('exact-head0-simulator',before['simulator'] is not None and before['simulator']['argv'][0]==sim and '+max_delay=0' in before['simulator']['argv'] and before['simulator']['pgid']==PIDS['simulator'],before['simulator'])
  r.check('exact-head-worker',before['worker'] is not None and worker_case in before['worker']['argv'] and sim in before['worker']['argv'],before['worker'])
  r.check('exact-head-parent',before['runner'] is not None and RUN in before['runner']['argv'] and '--execute' in before['runner']['argv'],before['runner'])
  r.check('no-new-variant-before-stop',not(BUILD/'variant').exists(),'baseline incomplete; variant absent')
  contract=dict(scope='CANCELLATION_OF_UNFINISHED_OFFLINE_HEAD0_AFTER_INDEPENDENT_NATIVE3_MEAN_BUDGET_STOP_NOT_DUT_FAILURE',decision=str(DECISION),decision_sha256=sha256(DECISION),head_receipt=str(HEAD),processes=before,action='SIGTERM only the exact baseline simulator process group; worker and parent seal their own FAIL',raw_complete=False,numeric_failure_claimed=False,protocol_failure_claimed=False,accepted_transport_closure_claimed=False,head_API_cycles=None,fullgraph_cycles=None,GO=False,board_execution=False)
  write_json(r.path/'contract.json',contract);shutil.copy2(DECISION,r.path/'budget-stop.json')
  os.killpg(PIDS['simulator'],signal.SIGTERM);actions=[dict(signal='SIGTERM',process_group=PIDS['simulator'],time_ns=time.time_ns())]
  deadline=time.monotonic()+5
  while alive(PIDS['simulator']) and time.monotonic()<deadline:time.sleep(.1)
  if alive(PIDS['simulator']):
   os.killpg(PIDS['simulator'],signal.SIGKILL);actions.append(dict(signal='SIGKILL',process_group=PIDS['simulator'],time_ns=time.time_ns()))
  write_json(r.path/'actions.json',actions)
  deadline=time.monotonic()+60
  while (alive(PIDS['runner']) or alive(PIDS['worker']) or alive(PIDS['simulator'])) and time.monotonic()<deadline:time.sleep(.2)
  after={k:info(pid) for k,pid in PIDS.items()};write_json(r.path/'processes-after.json',after)
  r.check('all-exact-head-processes-ended',not any(alive(pid) for pid in PIDS.values()),after)
  hm=json.loads((HEAD/'manifest.json').read_text());r.check('head-original-failure-preserved',hm['status']=='FAIL' and hm['exit_code']!=0 and bool(hm.get('finished_at')),hm)
  r.check('variant-never-started',not(BUILD/'variant').exists(),'no variant directory')
  write_json(r.path/'results.json',dict(status='EXPECTED_BUDGET_CANCELLATION_RECORDED',head_manifest_sha256=sha256(HEAD/'manifest.json'),head_process_status='FAIL_INTERRUPTED_PARTIAL_RAW_NOT_QUALIFYING',head_API_cycles=None,fullgraph_cycles=None,numeric_failure_claimed=False,protocol_failure_claimed=False,accepted_transport_closure_claimed=False,variant_started=False,GO=False,board_execution=False));code=0
 except BaseException:(r.path/'failure.txt').write_text(traceback.format_exc());print(traceback.format_exc(),flush=True)
 finally:
  shutil.copy2(Path(__file__),r.path/Path(__file__).name);r.manifest.update(qualification=False,GO=False,board_execution=False)
  r.manifest['artifacts']={str(f.relative_to(r.path)):sha256(f) for f in r.path.rglob('*') if f.is_file() and f.name not in ('manifest.json','commands.json','checks.json','exit-status.txt')};code=r.finish(code)
 print(r.manifest['status'],r.path,flush=True);return code
if __name__=='__main__':raise SystemExit(main())
