#!/usr/bin/env python3
"""Elaborate both digital board wrappers with explicitly selected features.

The FP array BLKANDNBLK diagnostic is suppressed for the existing separately
assigned pipeline-array elements in Verilator 5.006. This is not PDS signoff.
"""
from pathlib import Path
import argparse,hashlib,json,subprocess
ROOT=Path(__file__).resolve().parents[2]
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def main():
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--verilator',default='verilator');p.add_argument('--memory-source',type=Path);p.add_argument('--reuse',action='store_true');a=p.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=a.reuse)
 first=['rtl/interfaces/axi4_if.sv','rtl/soc/nx_accel_map.sv','rtl/ce64/vendor/registers.svh','rtl/ce64/vendor/cf_math_pkg.sv','rtl/ce64/vendor/fpnew_pkg.sv','rtl/ce64/nx_ce64_math_pkg.sv']
 names=first+[str(p.relative_to(ROOT)) for d in ['rtl/ce64','rtl/sfu','rtl/soc'] for p in sorted((ROOT/d).rglob('*.sv')) if str(p.relative_to(ROOT)) not in first and p.name!='nx_soc_core.sv']
 names+=['t27/cpu/T09Cpu.v']+['board/mes2l676-200hp/'+x for x in ['ce64_axi_bist.sv','t25_pressure_gate.sv','nx_t25_board_logic.sv','nx_ce64_board_logic.sv']]
 overrides={'rtl/ce64/nx_ce64.sv','rtl/ce64/nx_ce64_regs.sv','rtl/sfu/nx_opt11_dispatch.sv'}
 origins={n:(a.memory_source if a.memory_source and n in overrides else ROOT)/n for n in names}
 before={n:sha(f) for n,f in origins.items()};rows=[]
 for top in ['nx_t25_board_logic','nx_ce64_board_logic']:
  for enhanced in [0,1]:
   cmd=[a.verilator,'--lint-only','-Wno-fatal','-Wno-BLKANDNBLK','-DOPT11_LANES=2','--top-module',top,'-I'+str(ROOT/'rtl/ce64/vendor'),*[f'-G{x}={enhanced}' for x in ['LOCAL_READ_PIPELINE','ENABLE_REQUEST_PMU','LONG_PV','HEAD_ARGMAX']],*[str(f) for f in origins.values()]]
   log=out/f'{top}-{enhanced}.log'
   with log.open('w') as f:r=subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT)
   rows.append({'top':top,'enhanced':enhanced,'exit_code':r.returncode,'command':cmd,'log_sha256':sha(log)});print(top,enhanced,r.returncode,flush=True)
 after={n:sha(f) for n,f in origins.items()}
 result={'scope':'digital board elaboration/lint only; inherited warnings allowed, existing FP array BLKANDNBLK unsupported diagnostic suppressed; not PDS or physical timing','status':'PASS' if before==after and all(x['exit_code']==0 for x in rows) else 'FAIL','sources':before,'source_origins':{n:str(p) for n,p in origins.items()},'inputs_stable':before==after,'results':rows}
 (out/'RESULT.json').write_text(json.dumps(result,indent=2)+'\n')
 if result['status']!='PASS':raise SystemExit(1)
if __name__=='__main__':main()
