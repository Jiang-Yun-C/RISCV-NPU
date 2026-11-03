#!/usr/bin/env python3
"""Execute the passive PMU RTL against independent handshake accounting."""
import argparse,hashlib,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def main():
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--verilator',default='verilator');p.add_argument('--cc',default='cc');p.add_argument('--reuse',action='store_true');a=p.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=a.reuse)
 files=['rtl/interfaces/axi4_if.sv','rtl/ce64/common/nx_ce64_request_pmu.sv','tests/request_pmu/tb_pmu.sv']
 result={'scope':'passive request PMU RTL; no CPU or board performance inference','sources':{x:sha(ROOT/x) for x in files},'simulator':subprocess.check_output([a.verilator,'--version'],text=True).strip(),'cases':[]}
 for width in [64,8]:
  cmd=[a.verilator,'--binary','--timing','--assert','-j','4','-Wno-fatal','--top-module','tb_pmu','-GWIDTH='+str(width),'--Mdir',str(out/f'obj{width}'),*[str(ROOT/x) for x in files]]
  with (out/f'build{width}.log').open('w') as f:r=subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT)
  if r.returncode:raise RuntimeError('build failed '+str(width))
  r=subprocess.run([str(out/f'obj{width}/Vtb_pmu')],cwd=out,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
  (out/f'run{width}.log').write_text(r.stdout);print(r.stdout,flush=True)
  if r.returncode:raise RuntimeError('PMU assertions failed')
  rows=[json.loads(x[7:]) for x in r.stdout.splitlines() if x.startswith('RESULT ')]
  if len(rows)!=1 or rows[0]['status']!='PASS':raise RuntimeError('missing result')
  result['cases'].append(rows[0])
 api_source=ROOT/'tests/request_pmu/test_api.c';header=ROOT/'firmware/runtime/board/request_pmu.h'
 api_cmd=[a.cc,'-std=c11','-Wall','-Wextra','-Werror','-O2',str(api_source),'-o',str(out/'test_api')]
 with (out/'api_build.log').open('w') as f:r=subprocess.run(api_cmd,stdout=f,stderr=subprocess.STDOUT)
 if r.returncode:raise RuntimeError('API C compile failed')
 r=subprocess.run([str(out/'test_api')],capture_output=True,text=True)
 (out/'api_run.log').write_text(r.stdout+r.stderr)
 if r.returncode:raise RuntimeError('API C assertions failed')
 result['api_test']={'status':'PASS','command':api_cmd,'source_sha256':sha(api_source),'header_sha256':sha(header),'scope':'C callback/API tests, not hardware execution'}
 result['status']='PASS';(out/'RESULT.json').write_text(json.dumps(result,indent=2)+'\n')
if __name__=='__main__':main()
