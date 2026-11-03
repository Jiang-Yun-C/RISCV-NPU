#!/usr/bin/env python3
"""Build and execute generated CPU variants with recorded real RTL identities."""
import argparse,hashlib,json,os,re,runpy,shutil,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def dump(p,v):Path(p).write_text(json.dumps(v,indent=2)+'\n')
def compile_firmware(cc,out):
 out.mkdir(parents=True,exist_ok=False);rows=[]
 for i in range(5):
  d=out/str(i);d.mkdir()
  command=[cc,'-std=c11','-O2','-DHARD_FLOAT',f'-DPROBE_CASE={i}','-march=rv32imf_zicsr_zifencei','-mabi=ilp32f',
   '-ffreestanding','-fno-builtin','-fno-pic','-nostdlib','-nostartfiles','-msmall-data-limit=0',
   '-ffunction-sections','-fdata-sections','-Wall','-Wextra','-Werror','-Wl,--gc-sections','-Wl,--build-id=none',
   '-T',str(ROOT/'firmware/runtime/board/link.ld'),str(ROOT/'firmware/runtime/board/start.S'),
   str(HERE/'firmware.c'),'-lgcc','-o',str(d/'firmware.elf')]
  r=subprocess.run(command,capture_output=True,text=True,timeout=90)
  (d/'compile.log').write_text(r.stdout+r.stderr)
  if r.returncode:raise RuntimeError('firmware compile failed: '+str(d))
  entry,segments,flags=runpy.run_path(str(ROOT/'tests/models/prepare_image.py'))['parse_elf']((d/'firmware.elf').read_bytes(),base=0xb4000000,capacity=8<<20)
  if entry!=0xb4000000 or flags!=2 or len(segments)!=1:raise ValueError('ELF identity')
  (d/'firmware.bin').write_bytes(segments[0].data)
  row={'case':i,'command':command,'compiler_version':subprocess.check_output([cc,'--version'],text=True),
       'source_sha256':sha(HERE/'firmware.c'),'startup_sha256':sha(ROOT/'firmware/runtime/board/start.S'),
       'shared_startup_sha256':sha(ROOT/'firmware/cpu/start.S'),
       'linker_sha256':sha(ROOT/'firmware/runtime/board/link.ld'),
       'elf_sha256':sha(d/'firmware.elf'),'binary_sha256':sha(d/'firmware.bin')}
  dump(d/'BUILD.json',row);rows.append(row)
 dump(out/'BUILDS.json',rows)
def build(rtl,out,verilator,env):
 out.mkdir(parents=True,exist_ok=False)
 init=rtl.parent/'T09Cpu.v_toplevel_RegFilePlugin_regFile.bin'
 if not init.is_file():raise ValueError('missing matching register initialization')
 shutil.copy2(init,out/init.name)
 command=[verilator,'--cc','--exe','--build','-j','2','-Wno-fatal','--top-module','T09Cpu','--Mdir',str(out/'obj'),
          '-CFLAGS','-O2 -std=c++17',str(rtl),str(HERE/'cpu_main.cpp')]
 before={'rtl_sha256':sha(rtl),'init_sha256':sha(init),'harness_sha256':sha(HERE/'cpu_main.cpp')}
 with (out/'compile.log').open('w') as log:r=subprocess.run(command,cwd=out,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=300)
 if r.returncode==0:(out/'obj/VT09Cpu').chmod(0o755)
 if before!={'rtl_sha256':sha(rtl),'init_sha256':sha(init),'harness_sha256':sha(HERE/'cpu_main.cpp')}:raise RuntimeError('inputs changed')
 dump(out/'BUILD.json',{**before,'command':command,'exit_code':r.returncode,
      'simulator_sha256':sha(out/'obj/VT09Cpu') if r.returncode==0 else None,
      'verilator_version':subprocess.check_output([verilator,'--version'],env=env,text=True).strip()})
 if r.returncode:raise RuntimeError('simulator compile failed: '+str(out))
def execute(sim,binary,out,latency,cycles):
 if out.exists():raise ValueError('refusing existing result')
 built=json.loads((sim/'BUILD.json').read_text())
 if built['exit_code'] or sha(sim/'T09Cpu.v_toplevel_RegFilePlugin_regFile.bin')!=built['init_sha256']:raise ValueError('simulator build identity')
 if sha(built['command'][-2])!=built['rtl_sha256'] or sha(built['command'][-1])!=built['harness_sha256']:raise ValueError('simulator source identity changed')
 executable=sim/'obj/VT09Cpu';exe_sha=sha(executable);binary_sha=sha(binary)
 if built.get('simulator_sha256') and exe_sha!=built['simulator_sha256']:raise ValueError('simulator executable changed')
 cmd=[str(sim/'obj/VT09Cpu'),str(binary),str(out),str(cycles),str(latency),str(latency),'0']
 executable.chmod(executable.stat().st_mode | 0o100)
 start=time.monotonic();r=subprocess.run(cmd,cwd=sim,capture_output=True,text=True,timeout=300)
 if sha(executable)!=exe_sha or sha(binary)!=binary_sha:raise RuntimeError('execution inputs changed')
 value=json.loads(out.read_text())
 value.update(command=cmd,process_exit_code=r.returncode,host_wall_seconds=time.monotonic()-start,
  build=built,binary_sha256=binary_sha,simulator_sha256=exe_sha,formal_coremark_score=None,physical_board=False,
  memory_model={'external_extra_wait':latency,'earliest_external_response_cycles':latency+1,'local_extra_wait':1})
 uart=value['uart'];valid=False
 if 'CPU_VARIANT case=' in uart:
  m=re.search(r'CPU_VARIANT case=([0-9a-f]{8}) sum=([0-9a-f]{8}) expected=([0-9a-f]{8}) pass=00000001',uart)
  valid=bool(m and m[2]==m[3] and value['marker_starts']==1 and value['marker_stops']==1)
 elif 'CM_DONE' in uart:
  perf='mode=performance' in uart
  expected={'seedcrc':'e9f5','crclist':'e714','crcmatrix':'1fd7','crcstate':'8e3a','crcfinal':'fcaf'} if perf else {'seedcrc':'18f2','crclist':'e3c1','crcmatrix':'0747','crcstate':'8d84','crcfinal':'c64e'}
  valid=all(re.search(k+r'\s*:\s*0x'+v+r'\b',uart) for k,v in expected.items()) and 'iterations=10 data=2000' in uart
  m=re.search(r'Total ticks\s*:\s*(\d+)',uart);value['kernel_cycles']=int(m[1]) if m else None
 value['workload_validated']=valid
 dump(out,value);out.with_suffix('.uart.log').write_text(uart)
 if r.returncode or not valid:raise RuntimeError('workload failed: '+str(out))
 print(json.dumps({'result':str(out),'kernel_cycles':value.get('kernel_cycles'),'window':value['window']}))
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['firmware','build','run'])
 p.add_argument('--output',type=Path,required=True);p.add_argument('--cc');p.add_argument('--rtl',type=Path)
 p.add_argument('--verilator',default='verilator');p.add_argument('--verilator-root');p.add_argument('--sim',type=Path);p.add_argument('--binary',type=Path)
 p.add_argument('--latency',type=int,default=3);p.add_argument('--max-cycles',type=int,default=12000000)
 a=p.parse_args();env=dict(os.environ)
 if a.verilator_root:env['VERILATOR_ROOT']=a.verilator_root
 if a.action=='firmware':compile_firmware(a.cc,a.output.resolve())
 elif a.action=='build':build(a.rtl.resolve(),a.output.resolve(),a.verilator,env)
 else:execute(a.sim.resolve(),a.binary.resolve(),a.output.resolve(),a.latency,a.max_cycles)
if __name__=='__main__':main()
