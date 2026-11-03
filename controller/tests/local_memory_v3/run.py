#!/usr/bin/env python3
"""Build/run the actual local-memory RTL in both selectable configurations."""
from pathlib import Path
import argparse,hashlib,json,os,shutil,subprocess,time
ROOT=Path(__file__).resolve().parents[2]
def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--verilator',default='verilator');p.add_argument('--reuse',action='store_true');p.add_argument('--fast',choices=['0','1','both'],default='both');a=p.parse_args()
    out=a.output.resolve();out.mkdir(parents=True,exist_ok=a.reuse)
    (out/'rom.hex').write_text(''.join(f'{0x76540000^i:08x}\n' for i in range(16384)))
    files=['rtl/interfaces/axi4_if.sv','rtl/soc/t03_uart_tx.sv','rtl/soc/t17_uart.sv','rtl/ce64/nx_ce64_local.sv','tests/local_memory_v3/tb_local.sv']
    result={'schema':'nx-local-memory-comparison-v1','scope':'actual production local RTL, digital simulation; no PDS or physical timing claim','sources':{x:digest(ROOT/x) for x in files},'simulator':subprocess.check_output([a.verilator,'--version'],text=True).strip(),'cases':[]}
    for fast in ([0,1] if a.fast=='both' else [int(a.fast)]):
        cmd=[a.verilator,'--binary','--timing','--assert','-j','4','-Wno-fatal','--top-module','tb_local','-GFAST='+str(fast),'--Mdir',str(out/f'obj{fast}'),*[str(ROOT/x) for x in files]]
        with (out/f'build{fast}.log').open('w') as f:r=subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT)
        if r.returncode:raise RuntimeError(f'build failed, see {out}/build{fast}.log')
        r=subprocess.run([str(out/f'obj{fast}/Vtb_local')],cwd=out,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
        (out/f'run{fast}.log').write_text(r.stdout);print(r.stdout,flush=True)
        if r.returncode:raise RuntimeError('RTL assertions failed')
        rows=[json.loads(x[7:]) for x in r.stdout.splitlines() if x.startswith('RESULT ')]
        if len(rows)!=1:raise RuntimeError('missing unique result')
        result['cases'].append(rows[0])
    if a.fast=='both':
        old,new=result['cases']
        for key in ['d_single_cycles','i_single_cycles','d_8beat_cycles','i_8beat_cycles']:
            if new[key]>=old[key]:raise RuntimeError('no latency improvement '+key)
        if new['d_8beat_cycles']!=8 or new['i_8beat_cycles']!=8:raise RuntimeError('fast burst not one beat per cycle')
    result['status']='PASS';(out/'RESULT.json').write_text(json.dumps(result,indent=2)+'\n')
if __name__=='__main__':main()
