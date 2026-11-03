#!/usr/bin/env python3
"""A/B real T09 plus production local SRAM; no physical-board score."""
import argparse,hashlib,importlib.util,json,os,shutil,subprocess,time
from pathlib import Path
from generate_wrapper import generate
ROOT=Path(__file__).resolve().parents[2]
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def module(name,path):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--builds',type=Path,required=True);p.add_argument('--verilator',default='verilator');p.add_argument('--reuse',action='store_true');p.add_argument('--cpu-rtl',type=Path);p.add_argument('--cpu-init',type=Path);p.add_argument('--cpu-label',default='original-v2');p.add_argument('--fast',choices=['0','1','both'],default='both');a=p.parse_args()
    out=a.output.resolve();out.mkdir(parents=True,exist_ok=a.reuse)
    files=['t27/cpu/T09Cpu.v','t27/cpu/T09Cpu.v_toplevel_RegFilePlugin_regFile.bin','rtl/interfaces/axi4_if.sv','rtl/soc/t03_uart_tx.sv','rtl/soc/t17_uart.sv','rtl/soc/t17_uart_router.sv','rtl/ce64/nx_ce64_local.sv','tests/cpu_local_sram/cpu_main.cpp','tests/cpu_local_sram/generate_wrapper.py']
    cpu_rtl=(a.cpu_rtl or ROOT/files[0]).resolve();cpu_init=(a.cpu_init or cpu_rtl.parent/Path(files[1]).name).resolve()
    origins={x:ROOT/x for x in files};origins[files[0]]=cpu_rtl;origins[files[1]]=cpu_init
    identity={x:sha(origins[x]) for x in files};version=subprocess.check_output([a.verilator,'--version'],text=True).strip()
    check=module('local_coremark_build',ROOT/'scripts/build_coremark.py');results=[]
    for fast in ([0,1] if a.fast=='both' else [int(a.fast)]):
      build=out/f'fast{fast}';build.mkdir(exist_ok=a.reuse)
      wrapper=build/'T09CpuLocal.sv';wrapper.write_text(generate(cpu_rtl))
      shutil.copy2(cpu_init,build/Path(files[1]).name)
      cmd=[a.verilator,'--cc','--exe','--build','-j','4','-Wno-fatal','--top-module','T09CpuLocal','-GLOCAL_READ_PIPELINE='+str(fast),'--Mdir',str(build/'obj'),'-CFLAGS','-O2 -std=c++17',str(ROOT/files[2]),*[str(ROOT/x) for x in files[3:5]],str(ROOT/files[6]),str(cpu_rtl),str(wrapper),str(ROOT/files[7])]
      with (build/'compile.log').open('w') as log:r=subprocess.run(cmd,cwd=build,stdout=log,stderr=subprocess.STDOUT)
      record={'command':cmd,'returncode':r.returncode,'sources':identity,'wrapper_sha256':sha(wrapper),'verilator_version':version,'cpu_label':a.cpu_label,'cpu_rtl_input':str(cpu_rtl),'cpu_init_input':str(cpu_init)}
      (build/'BUILD.json').write_text(json.dumps(record,indent=2)+'\n')
      if r.returncode:raise RuntimeError('build failed '+str(build))
      for mode,folder in [('performance','O3-tuned-debug-10'),('validation','O3-tuned-validation-10')]:
        binary=a.builds/folder/'coremark.bin';elf=a.builds/folder/'coremark.elf';receipt=json.loads((a.builds/folder/'BUILD_RECEIPT.json').read_text())
        if sha(binary)!=receipt['elf']['bin_sha256'] or sha(elf)!=receipt['elf_sha256']:raise RuntimeError('binary/ELF identity mismatch')
        payload,_=check.parse_elf(elf.read_bytes())
        if payload!=binary.read_bytes():raise RuntimeError('ELF load image mismatch')
        target=out/f'fast{fast}-{mode}.json'
        cmd=[str(build/'obj/VT09CpuLocal'),str(binary.resolve()),str(target), '20000000','3','3','0']
        started=time.monotonic();r=subprocess.run(cmd,cwd=build,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=240)
        (out/f'fast{fast}-{mode}.uart.log').write_text(r.stdout)
        if not target.exists():raise RuntimeError('missing result')
        raw=json.loads(target.read_text());raw.update(sources=identity,wrapper_sha256=sha(wrapper),binary_sha256=sha(binary),elf_sha256=sha(elf),build_receipt_sha256=sha(a.builds/folder/'BUILD_RECEIPT.json'),simulator_version=version,process_exit_code=r.returncode,command=cmd,local_read_pipeline=fast,cpu_label=a.cpu_label,cpu_rtl_input=str(cpu_rtl),cpu_init_input=str(cpu_init),host_wall_seconds=time.monotonic()-started)
        target.write_text(json.dumps(raw,indent=2)+'\n')
        if r.returncode or raw['status']!='PASS_CPU_LOCAL_SRAM_RTL' or raw['exit_code']!=0xc021 or raw['error']:raise RuntimeError('execution failed '+str(target))
        decoded=check.validate_log(raw['uart'],expected_mode=mode,require_formal=False)
        if decoded['iterations']!=10 or decoded['formal_run_log_valid'] or decoded['coremark'] is not None:raise RuntimeError('unexpected formal/iteration scope')
        crc='fcaf' if mode=='performance' else 'c64e'
        if '[0]crcfinal      : 0x'+crc not in raw['uart']:
          import re
          if not re.search(r'^\[0\]crcfinal\s*:\s*0x'+crc+r'\s*$',raw['uart'],re.M):raise RuntimeError('final CRC mismatch')
        results.append({'fast':fast,'mode':mode,'cycles':decoded['cycles'],'total':raw['total'],'binary_sha256':sha(binary),'result_sha256':sha(target),'crc_valid':True})
        print(json.dumps(results[-1]),flush=True)
    if identity!={x:sha(origins[x]) for x in files}:raise RuntimeError('source changed during execution')
    comparisons={}
    for mode in (['performance','validation'] if a.fast=='both' else []):
      old=next(x for x in results if x['mode']==mode and x['fast']==0);new=next(x for x in results if x['mode']==mode and x['fast']==1)
      if old['binary_sha256']!=new['binary_sha256']:raise RuntimeError('A/B binaries differ')
      comparisons[mode]={'before_cycles':old['cycles'],'after_cycles':new['cycles'],'cycle_reduction_percent':100*(old['cycles']-new['cycles'])/old['cycles'],'throughput_increase_percent':100*(old['cycles']/new['cycles']-1)}
    report={'status':'PASS_CPU_WITH_PRODUCTION_SRAM','scope':'10 iterations, actual T09 and production local SRAM, behavioral program DDR/MMIO; not complete SoC/PHY or formal/board CoreMark','simulator':version,'sources':identity,'results':results,'comparisons':comparisons,'formal_coremark':None,'formal_coremark_per_mhz':None,'board_tested':False,'pds_tested':False,'cpu_label':a.cpu_label,'cpu_rtl_input':str(cpu_rtl),'cpu_init_input':str(cpu_init),'selected_fast':a.fast}
    (out/'COMPARISON.json').write_text(json.dumps(report,indent=2)+'\n')
if __name__=='__main__':main()
