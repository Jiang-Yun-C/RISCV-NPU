#!/usr/bin/env python3
"""Frozen parent54 real RV32 linear API A/B, changing only the guard RTL."""
import argparse,csv,json,os,shutil,subprocess,sys,traceback,xml.etree.ElementTree as ET
from collections import Counter,deque
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from evidence import EvidenceRun,sha256,write_json,content_id
from scripts.opt10_r1_measurement import seal_cpu_trace
PARENT=ROOT/'evidence/OPT16_CANDIDATE/opt10-r1-candidate-20261020-v54'
TEST=ROOT/'tests/opt10_r1_guard_cpu_ab'
GUARD='rtl/ce64/common/nx_ce64_guard.sv'
VARIANT=ROOT/'variants/opt10_r1_guard_refill_v1'/GUARD

class Arm:
 def __init__(self,r,name):self.parent=r;self.build=r.build/name;self.build.mkdir();self.manifest={};self.name=name
 def check(self,n,c,d):return self.parent.check(self.name+'-'+n,c,d)
 def execute(self,n,a,t,cwd=None):return self.parent.execute(self.name+'-'+n,a,t,cwd or self.build)

def inputs(r,repo,tools):
 from model_tools.verify_pack import verify
 from model_tools import numeric_v1 as num
 from tests.models.prepare_image import parse_elf
 image=r.build/'image';image.mkdir();manifest=json.loads((ROOT/'docs/spec/model-pack-v1-manifest.json').read_text());pack=verify(ROOT/manifest['pack_path'],expected_sha256=manifest['sha256'])
 def a(n):return pack.rows(n).copy()
 stem='model.layers.0.'
 def lin(x,name):
  name=stem+name+'.weight';aq,sa=num.quantize(x);bias=pack.entries.get(name.replace('.weight','.bias'))
  return num.linear_quantized(aq,sa,a(name),a(name+'.scale'),a(name.replace('.weight','.bias')) if bias else None)[0]
 x=num.dequantize(a('model.embed_tokens.weight')[:1],a('model.embed_tokens.weight.scale')[:1]);z=num.rmsnorm(x,a(stem+'input_layernorm.weight'))
 # For token0/context1, softmax has one member and is exactly 1. Each of
 # seven Q heads therefore consumes its corresponding unchanged V head.
 v=lin(z,'self_attn.v_proj').reshape(1,2,64);attention=np.repeat(v,7,axis=1).reshape(1,896)
 res=num.residual(x,lin(attention,'self_attn.o_proj'));norm=num.rmsnorm(res,a(stem+'post_attention_layernorm.weight'))
 gate=lin(norm,'mlp.gate_proj');up=lin(norm,'mlp.up_proj');e=np.exp(-np.abs(gate).astype('f8')).astype('f4');sig=np.where(gate>=0,np.float32(1)/(np.float32(1)+e),e/(np.float32(1)+e));act=((gate*sig)*up).astype('<f4')
 name=stem+'mlp.down_proj.weight';w=a(name)[:129];sw=a(name+'.scale')[:129];aq,sa=num.quantize(act);golden,dots=num.linear_quantized(aq,sa,w,sw)
 regions=[]
 def add(n,address,data,kind):
  f=image/(n+'.bin');f.write_bytes(data);regions.append(dict(name=n,address=address,bytes=len(data),path=str(f),sha256=sha256(f),kind=kind))
 add('layer0-down-token0-act',0xac000000,act.tobytes(),'independent_real_model_activation');add('down-W-first129',0x894a5200,w.tobytes(),'immutable_model_slice');add('down-Sw-first129',0x898cd200,sw.tobytes(),'immutable_model_slice')
 golden.tofile(image/'golden.bin');aq.tofile(image/'expected-aq.bin');sa.tofile(image/'expected-sa.bin');dots.tofile(image/'expected-dots.bin')
 elf=image/'linear.elf';src=repo/'firmware/drivers/accel';port=repo/'firmware/runtime/port';ref=repo/'firmware/runtime/reference'
 flags=['-march=rv32imf_zicsr_zifencei','-mabi=ilp32f','-DHARD_FLOAT','-DNX_PORTABLE','-O2','-g','-ffp-contract=off','-fno-fast-math','-fno-strict-aliasing','-ffreestanding','-fno-builtin','-fno-pic','-nostdlib','-nostartfiles','-msmall-data-limit=0','-ffunction-sections','-fdata-sections','-Wall','-Wextra','-Werror','-Wno-unknown-pragmas','-Wl,--gc-sections','-Wl,--build-id=none']
 r.execute('shared-rv32-firmware',[tools['rv32_gcc'],*flags,'-I',src,'-I',port,'-I',ref,'-I',repo/'software/include','-T',ROOT/'tests/opt12/link.ld',f'-Wl,-Map={image}/linear.map',repo/'firmware/cpu/start.S',TEST/'firmware.c',port/'ce64_backend.c',ref/'nx_reference.c',*[src/n for n in ('accel.c','target.c','linear_api.c','ce64_linear.c','opt12.c')],'-lm','-lc','-lgcc','-o',elf],120)
 entry,segments,abi=parse_elf(elf.read_bytes(),base=0x10000,capacity=0xb8000000-0x10000);r.check('actual-RV32-ABI',entry==0x10000 and abi==2,'actual frozen hard-FPU RV32; production API/transport, no stubs')
 rom=bytearray(65536)
 for i,s in enumerate(segments):
  add('elf-'+str(i),s.address,s.data,'firmware')
  if 0x10000<=s.address<0x20000:rom[s.address-0x10000:s.address-0x10000+len(s.data)]=s.data
 ordered=sorted(regions,key=lambda v:v['address']);r.check('shared-fixture-nonoverlap',all(a['address']+a['bytes']<=b['address'] for a,b in zip(ordered,ordered[1:])),len(regions))
 write_json(image/'fixture.json',dict(regions=regions,model_pack_sha256=manifest['sha256'],scope='REAL_MODEL_POSTLOAD_SLICE_NOT_AUTHENTICATED_LOADER'))
 (image/'load.plan').write_text(''.join(f"B {x['address']:x} {x['bytes']:x} {x['path']}\n" for x in regions));(image/'ce-rom.hex').write_text(''.join(f'{int.from_bytes(rom[i:i+4],"little"):08x}\n' for i in range(0,65536,4)))
 write_json(r.path/'fixture-freeze.json',dict(model_pack_sha256=manifest['sha256'],fixture=sha256(image/'fixture.json'),ELF=sha256(elf),golden=sha256(image/'golden.bin'),input=sha256(image/'layer0-down-token0-act.bin'),W=sha256(image/'down-W-first129.bin'),Sw=sha256(image/'down-Sw-first129.bin'),activation_provenance='Independent numeric-v1 layer0 token0 context1 embedding/norm/V/O/residual/norm/gate/up/SwiGLU, one-member attention identity; exp in binary64 rounded to binary32 matching graph oracle',thresholds=sha256(ROOT/'configs/t05-thresholds.json')))
 return image

def execute_case(cfgpath,sim):
 cfg=json.loads(cfgpath.read_text());lock=json.loads((ROOT/'configs/cocotb-toolchain-lock.json').read_text());lib=lock['files']['libpython']['path'];env=os.environ.copy()
 for n in ('COCOTB_TEST_FILTER','COCOTB_TESTCASE','MODULE','TESTCASE','GPI_EXTRA','GPI_USERS','PYGPI_USERS'):env.pop(n,None)
 entry=subprocess.check_output([sys.executable,'-m','cocotb_tools.config','--pygpi-entry-point'],text=True).strip()
 env.update(PYGPI_PYTHON_BIN=sys.executable,LIBPYTHON_LOC=lib,GPI_USERS=lib+';'+entry,COCOTB_TEST_MODULES='observer',COCOTB_TOPLEVEL='tb_cpu',COCOTB_TOPLEVEL_LANG='verilog',COCOTB_RANDOM_SEED='1',COCOTB_RESULTS_FILE=str(Path('results.xml').resolve()),NEXUSRV_CASE=str(cfgpath.resolve()),PYTHONPATH=os.pathsep.join([str(ROOT),str(ROOT/'tests/cocotb'),str(TEST)]))
 with Path('simulation.log').open('w') as log:
  producer=subprocess.Popen([str(sim),'-no_save','+seed=1','+max_delay=0','+max_cycles='+str(cfg['max_cycles']),'+head_run','+image_plan='+cfg['image_plan'],'+ce_rom='+cfg['ce_rom']],env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
  try:producer.wait(timeout=cfg['wall_seconds'])
  except subprocess.TimeoutExpired:EvidenceRun._kill_group(producer);raise
 xml=ET.parse('results.xml').getroot();tests=xml.findall('.//testcase')
 if producer.returncode or len(tests)!=1 or tests[0].get('name')!='guard_cpu_api' or any(x.tag in ('failure','error','skipped') for x in xml.iter()):raise ValueError('actual real-RV32 API failed; preserve raw')
 checks=json.loads(Path('checks.json').read_text());obs=json.loads(Path('observations.json').read_text())
 if checks['status']!='PASS':raise ValueError('observer failed')
 obs['sealed_CPU_raw']=seal_cpu_trace('transactions.csv',obs['terminal_close'],producer,allowed_kinds=('CW','CB','IRQ','CR','CD','SA','SW','BA','NA','NW','NB','NL','NR','ND','MA','MB','EARLY'))
 write_json('actual-results.json',obs)

def transport(path,close):
 rows=list(csv.reader(path.open()));pending=None;wpend=None;read_cmd=[];read_data=[];write_cmd=[];write_data=[];responses=[];counts=Counter();previous=-1
 for row in rows:
  if len(row)!=7:raise ValueError('transport grammar')
  cyc=int(row[0]);kind=row[1];v=[int(n,16) for n in row[2:]]
  if cyc<previous or cyc>close['cycle']:raise ValueError('transport outside closed boundary')
  previous=cyc;counts[kind]+=1
  if kind=='AR':
   if pending is not None:raise ValueError('more than one backend read')
   address,length,size,rid,burst=v;pending=[length+1,rid];read_cmd.append(v)
   if burst!=1 or length>31:raise ValueError('AR contract')
  elif kind=='R':
   data,rid,resp,last,_=v
   if pending is None or rid!=pending[1] or resp!=0 or last!=(pending[0]==1):raise ValueError('R identity/count/status/LAST')
   read_data.append(v);pending[0]-=1
   if pending[0]==0:pending=None
  elif kind=='AW':
   if wpend is not None:raise ValueError('more than one backend write')
   address,length,size,rid,burst=v;wpend=[length+1,rid,False];write_cmd.append(v)
  elif kind=='W':
   data,strobe,last,_,_=v
   if wpend is None or wpend[2] or last!=(wpend[0]==1):raise ValueError('W count/LAST')
   write_data.append(v);wpend[0]-=1;wpend[2]=wpend[0]==0
  elif kind=='B':
   rid,resp,*_=v
   if wpend is None or not wpend[2] or rid!=wpend[1] or resp!=0:raise ValueError('B count/status')
   responses.append(v);wpend=None
 if pending is not None or wpend is not None or sum(counts[k] for k in ('AR','R','AW','W','B','NAR','NR','NAW','NW'))!=close['transport_activity']:raise ValueError('transport incomplete or live/raw mismatch')
 return dict(counts=dict(counts),AR=read_cmd,R=read_data,AW=write_cmd,W=write_data,B=responses,raw_sha256=sha256(path),records=len(rows),entire_raw_checked=True)

def main():
 p=argparse.ArgumentParser();p.add_argument('--run-id');p.add_argument('--case',type=Path);p.add_argument('--sim',type=Path);args=p.parse_args()
 if args.case:execute_case(args.case,args.sim);return 0
 if not args.run_id:p.error('--run-id required')
 r=EvidenceRun(ROOT,'OPT10_R1_GUARD_CPU_AB',args.run_id);code=1
 try:
  from run_ce64_soc import build
  parent=json.loads((PARENT/'manifest.json').read_text());repo=Path(parent['candidate_repo']);sources=json.loads((PARENT/'candidate-sources.json').read_text())
  r.check('exact-parent54-before',all(sha256(repo/n)==h for n,h in sources.items()),parent['candidate_id'])
  r.check('guard-only-authorized-overlay',VARIANT.is_file() and sha256(VARIANT)=='b03e02d7fe86ce82944d3d474caa6e5617ce1e070a11877beb24dbf3b5f00b2e',str(VARIANT))
  lock=json.loads((ROOT/'configs/cocotb-toolchain-lock.json').read_text());r.check('locked-VPI',all(sha256(v['path'])==v['sha256'] for v in lock['files'].values()),lock)
  tools={k:v['path'] for k,v in json.loads((ROOT/'docs/spec/toolchain-lock.json').read_text())['tools'].items()}
  names=[Path(__file__),TEST/'firmware.c',TEST/'observer.py',TEST/'monitor.svh',ROOT/'scripts/opt10_r1_measurement.py',ROOT/'scripts/opt10_r1_measurement_cocotb.py',ROOT/'scripts/run_ce64_soc.py',ROOT/'tests/ce64_soc/tb_body.svh',ROOT/'tests/ce64_soc/native_memory_model.sv',ROOT/'model_tools/numeric_v1.py',ROOT/'configs/t05-thresholds.json']
  frozen={str(f.relative_to(ROOT)):sha256(f) for f in names};write_json(r.path/'frozen-checker-inputs.json',frozen)
  contract=dict(scope='ISOLATED_EXPERIMENT_REAL_RV32_M1_N129_K4864_GUARD_ONLY_AB',parent_candidate_id=parent['candidate_id'],parent_source_manifest_sha256=sha256(PARENT/'candidate-sources.json'),intervention={GUARD:sha256(VARIANT)},shared_ELF_and_input=True,api_boundary='nxr_ce64_linear_private entry-to-return including validation/quantize/descriptor/wait/original 128-column hardware publisher/native drain; explicit input lease registration immediately before API and host fixture generation outside timed call',native_model='unchanged ce64_native_memory_model; max_delay=0 gives fixed no-stall per-transaction native environment; not calibrated production DDR',limits=dict(compile_wall_seconds=600,simulation_wall_seconds=1800,max_CPU_cycles=20000000,production_call_deadline=900000000,effective_native_STALL_LIMIT=65536,WRITE_DRAIN_CYCLES=1024),deadline_basis='v5 retained FAIL: original startup clears about 34KB DDR bss via 4B native writes with 1024 drain and exceeded 5M before main; 20M is aggregate observation envelope, not the timed API acceptance target or a production deadline change',checker=frozen,accept=['both actual RV32 APIs succeed with original numeric thresholds','entire accepted backend AR/R/AW/W/B ledgers identical excluding cycle, ordered ID/RESP/LAST/count closure','same complete output object bits','strict positive complete API cycle saving explained by transport/control phase deltas'],stop=['any original API/numeric/protocol failure','no positive complete API improvement','needs multi-inflight/native/write/timeout redesign'],qualification=False,GO=False,fullgraph_cycles=None,TTFT_seconds=None,frequency_signoff_hz=None)
  write_json(r.path/'contract.json',contract);r.manifest.update(scope=contract['scope'],parent_candidate_id=parent['candidate_id'],qualification=False,board_execution=False,GO=False);r.flush()
  image=inputs(r,repo,tools);results={};ledgers={};compiled={}
  for name in ('baseline','refill'):
   arm=Arm(r,name);tb=arm.build/'tb_body.svh';body=(ROOT/'tests/ce64_soc/tb_body.svh').read_text().replace('soc.compute.ce.control.','soc.compute.ce.control.linear_control.').replace("cpu_bus.araddr<32'hac200000","cpu_bus.araddr<32'hb0000000")
   body=body.replace(".model_sealed(1'b1)",".model_sealed(1'b1),.startup_authorized(1'b0)");body=body.replace('backend.awlen!=0||backend.awburst!=1',"backend.awlen>31||backend.awburst!=1||(backend.awlen!=0&&backend.awsize!=4)")
   tb.write_text(body+'\n'+(TEST/'monitor.svh').read_text());overrides={str(f.relative_to(repo)):f for f in (repo/'rtl').rglob('*') if f.is_file()};overrides['tests/ce64_soc/tb_body.svh']=tb
   if name=='refill':overrides[GUARD]=VARIANT
   sim=build(arm,tools,Path(lock['files']['vpi']['path']),board_memory=True,wave_window=100,source_overrides=overrides,additional_sources=[str(f.relative_to(repo)) for f in sorted((repo/'rtl/sfu').glob('*.sv'))],defines=['OPT11_LANES=2'])
   compiled[name]={str(f.relative_to(arm.build/'sources')):sha256(f) for f in (arm.build/'sources/rtl').rglob('*') if f.is_file()};r.check(name+'-actual-compiled-source-closure',all(h==(sha256(VARIANT) if name=='refill' and n==GUARD else sources.get(n)) for n,h in compiled[name].items()),len(compiled[name]))
   case=arm.build/'case';case.mkdir()
   for f in sim.parent.glob('*.bin'):shutil.copy2(f,case/f.name)
   cfg=dict(run_id=r.run_id,arm=name,max_cycles=contract['limits']['max_CPU_cycles'],wall_seconds=contract['limits']['simulation_wall_seconds'],image_plan=str(image/'load.plan'),ce_rom=str(image/'ce-rom.hex'),golden=str(image/'golden.bin'),linear_thresholds=json.loads((ROOT/'configs/t05-thresholds.json').read_text())['operators']['linear']);write_json(case/'case.json',cfg)
   r.execute(name+'-real-cpu-api',[sys.executable,Path(__file__).resolve(),'--case',case/'case.json','--sim',sim],cfg['wall_seconds']+60,cwd=case)
   results[name]=json.loads((case/'actual-results.json').read_text());ledgers[name]=transport(case/'api-transport.csv',results[name]['terminal_close']);write_json(r.path/(name+'-transport-review.json'),ledgers[name])
  r.check('only-guard-compiled-RTL-diff',[n for n in compiled['baseline'] if compiled['baseline'][n]!=compiled['refill'][n]]==[GUARD],GUARD)
  for kind in ('AR','R','AW','W','B'):r.check('identical-complete-'+kind,ledgers['baseline'][kind]==ledgers['refill'][kind],len(ledgers['baseline'][kind]))
  r.check('complete-output-bits-identical',results['baseline']['numeric']['output_bits']==results['refill']['numeric']['output_bits'],129)
  saving=results['baseline']['CPU_API_cycles']-results['refill']['CPU_API_cycles'];r.check('actual-net-CPU-API-saving',saving>0,dict(saving_cycles=saving))
  for value in results.values():value['numeric'].pop('output_bits')
  write_json(r.path/'results.json',dict(arms=results,CPU_API_saving_cycles=saving,scope=contract['scope'],same_ELF_sha256=sha256(image/'linear.elf'),fullgraph_cycles=None,TTFT_seconds=None,frequency_signoff_hz=None,GO=False))
  write_json(r.path/'compiled-source-closures.json',compiled);r.check('parent54-after',all(sha256(repo/n)==h for n,h in sources.items()),parent['candidate_id']);r.check('checker-inputs-after',all(sha256(ROOT/n)==h for n,h in frozen.items()),len(frozen));code=0
 except BaseException:(r.path/'failure.txt').write_text(traceback.format_exc());print(traceback.format_exc(),flush=True)
 finally:
  for name in ('baseline','refill'):
   path=r.build/name
   if path.exists():
    for sub in ('case','sources'):
     f=path/sub
     if f.exists():shutil.copytree(f,r.path/name/sub)
  if (r.build/'image').exists():shutil.copytree(r.build/'image',r.path/'image')
  for f in (Path(__file__),TEST/'firmware.c',TEST/'observer.py',TEST/'monitor.svh'):
   out=r.path/'inputs'/f.relative_to(ROOT);out.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(f,out)
  r.manifest['artifacts']={str(f.relative_to(r.path)):sha256(f) for f in r.path.rglob('*') if f.is_file() and not(f.parent==r.path and f.name in ('manifest.json','commands.json','checks.json','exit-status.txt'))};code=r.finish(code)
 print(r.manifest['status'],r.path,flush=True);return code
if __name__=='__main__':raise SystemExit(main())
