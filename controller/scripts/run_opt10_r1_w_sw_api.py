#!/usr/bin/env python3
"""Frozen real RV32 q/down N129 W+Sw API experiments; common accepted guard."""
import argparse,csv,json,os,shutil,subprocess,sys,traceback,xml.etree.ElementTree as ET
from collections import Counter,deque
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from evidence import EvidenceRun,sha256,write_json,content_id
from scripts.opt10_r1_measurement import seal_cpu_trace
PARENT=ROOT/'evidence/OPT16_CANDIDATE/opt10-r1-candidate-20261020-v54'
TEST=ROOT/'tests/opt10_r1_w_sw_api'
GUARD='rtl/ce64/common/nx_ce64_guard.sv'
VARIANT=ROOT/'variants/opt10_r1_guard_refill_v1'/GUARD

class Arm:
 def __init__(self,r,name):self.parent=r;self.build=r.build/name;self.build.mkdir();self.manifest={};self.name=name
 def check(self,n,c,d):return self.parent.check(self.name+'-'+n,c,d)
 def execute(self,n,a,t,cwd=None):return self.parent.execute(self.name+'-'+n,a,t,cwd or self.build)

def inputs(r,repo,tools,shape):
 from model_tools.verify_pack import verify
 from model_tools import numeric_v1 as num
 from tests.models.prepare_image import parse_elf
 image=r.build/('image-'+shape);image.mkdir();manifest=json.loads((ROOT/'docs/spec/model-pack-v1-manifest.json').read_text());pack=verify(ROOT/manifest['pack_path'],expected_sha256=manifest['sha256'])
 def a(n):return pack.rows(n).copy()
 stem='model.layers.0.'
 def lin(x,name):
  name=stem+name+'.weight';aq,sa=num.quantize(x);bias=pack.entries.get(name.replace('.weight','.bias'))
  return num.linear_quantized(aq,sa,a(name),a(name+'.scale'),a(name.replace('.weight','.bias')) if bias else None)[0]
 x=num.dequantize(a('model.embed_tokens.weight')[:1],a('model.embed_tokens.weight.scale')[:1]);z=num.rmsnorm(x,a(stem+'input_layernorm.weight'))
 if shape=='q':
  k=896;name=stem+'self_attn.q_proj.weight';act=z.astype('<f4');waddr=0x889f2200;swaddr=0x88ab6200;biasaddr=0x88ac2600;bias=a(stem+'self_attn.q_proj.bias')[:129]
 else:
  k=4864;name=stem+'mlp.down_proj.weight';waddr=0x894a5200;swaddr=0x898cd200;biasaddr=0;bias=None
  # Context1 softmax has one member, exactly 1; seven Q heads consume each V.
  v=lin(z,'self_attn.v_proj').reshape(1,2,64);attention=np.repeat(v,7,axis=1).reshape(1,896)
  res=num.residual(x,lin(attention,'self_attn.o_proj'));norm=num.rmsnorm(res,a(stem+'post_attention_layernorm.weight'))
  gate=lin(norm,'mlp.gate_proj');up=lin(norm,'mlp.up_proj')
  # Match tests/reference/oracle.py: Oracle.swiglu, including exp rounding.
  e=np.exp(-np.abs(gate).astype('f8')).astype('f4');sig=np.where(gate>=0,np.float32(1)/(np.float32(1)+e),e/(np.float32(1)+e));act=((gate*sig)*up).astype('<f4')
 w=a(name)[:129];sw=a(name+'.scale')[:129];aq,sa=num.quantize(act);golden,dots=num.linear_quantized(aq,sa,w,sw,bias)
 regions=[]
 def add(n,address,data,kind):
  f=image/(n+'.bin');f.write_bytes(data);regions.append(dict(name=n,address=address,bytes=len(data),path=str(f),sha256=sha256(f),kind=kind))
 add('layer0-'+shape+'-token0-input',0xac000000,act.tobytes(),'independent_real_model_activation');add('W-first129',waddr,w.tobytes(),'immutable_model_slice');add('Sw-first129',swaddr,sw.tobytes(),'immutable_model_slice')
 if bias is not None:add('bias-first129',biasaddr,bias.astype('<f4').tobytes(),'immutable_model_slice')
 golden.tofile(image/'golden.bin');aq.tofile(image/'expected-aq.bin');sa.tofile(image/'expected-sa.bin');dots.tofile(image/'expected-dots.bin')
 products=(dots[:,0,:].T.astype('<f4')*sa[0]).astype('<f4');values=(products*sw).astype('<f4');partials=np.empty_like(values);total=np.zeros(129,dtype='<f4')
 for group in range(k//64):total=(total+values[:,group]).astype('<f4');partials[:,group]=total
 np.stack((products,values,partials),axis=-1).astype('<f4').tofile(image/'expected-fp.bin')
 elf=image/'linear.elf';src=repo/'firmware/drivers/accel';port=repo/'firmware/runtime/port';ref=repo/'firmware/runtime/reference'
 flags=['-march=rv32imf_zicsr_zifencei','-mabi=ilp32f','-DHARD_FLOAT','-DNX_PORTABLE','-DCASE_Q='+str(int(shape=='q')),'-O2','-g','-ffp-contract=off','-fno-fast-math','-fno-strict-aliasing','-ffreestanding','-fno-builtin','-fno-pic','-nostdlib','-nostartfiles','-msmall-data-limit=0','-ffunction-sections','-fdata-sections','-Wall','-Wextra','-Werror','-Wno-unknown-pragmas','-Wl,--gc-sections','-Wl,--build-id=none']
 r.execute('shared-rv32-firmware-'+shape,[tools['rv32_gcc'],*flags,'-I',src,'-I',port,'-I',ref,'-I',repo/'software/include','-T',ROOT/'tests/opt12/link.ld',f'-Wl,-Map={image}/linear.map',repo/'firmware/cpu/start.S',TEST/'firmware.c',port/'ce64_backend.c',ref/'nx_reference.c',*[src/n for n in ('accel.c','target.c','linear_api.c','ce64_linear.c','opt12.c')],'-lm','-lc','-lgcc','-o',elf],120)
 entry,segments,abi=parse_elf(elf.read_bytes(),base=0x10000,capacity=0xb8000000-0x10000);r.check('actual-RV32-ABI-'+shape,entry==0x10000 and abi==2,'frozen hard-FPU RV32 production API/transport; no stubs')
 rom=bytearray(65536)
 for i,s in enumerate(segments):
  add('elf-'+str(i),s.address,s.data,'firmware')
  if 0x10000<=s.address<0x20000:rom[s.address-0x10000:s.address-0x10000+len(s.data)]=s.data
 ordered=sorted(regions,key=lambda v:v['address']);r.check('shared-fixture-nonoverlap-'+shape,all(a['address']+a['bytes']<=b['address'] for a,b in zip(ordered,ordered[1:])),len(regions))
 write_json(image/'fixture.json',dict(regions=regions,model_pack_sha256=manifest['sha256'],scope='REAL_MODEL_POSTLOAD_SLICE_NOT_AUTHENTICATED_LOADER'))
 (image/'load.plan').write_text(''.join(f"B {x['address']:x} {x['bytes']:x} {x['path']}\n" for x in regions));(image/'ce-rom.hex').write_text(''.join(f'{int.from_bytes(rom[i:i+4],"little"):08x}\n' for i in range(0,65536,4)))
 frozen=dict(shape=shape,M=1,N=129,K=k,W=waddr,Sw=swaddr,bias=biasaddr,input_address=0xac000000,Y=0xac010000,path=str(image),model_pack_sha256=manifest['sha256'],files={f.name:sha256(f) for f in image.iterdir() if f.is_file()},activation_provenance='q: numeric-v1 dequantized actual token0 embedding then layer0 input norm; down: independent numeric-v1 layer0 primitives, exact context1 attention identity, and tests/reference/oracle.py Oracle.swiglu binary64 exp rounded to binary32; no candidate activation values')
 return frozen

def fault_input(r,normal):
 image=r.build/'image-q-sw-nan';shutil.copytree(Path(normal['path']),image)
 sw=image/'Sw-first129.bin';data=bytearray(sw.read_bytes());data[:4]=(0x7fc00000).to_bytes(4,'little');sw.write_bytes(data)
 fixture=json.loads((image/'fixture.json').read_text())
 for region in fixture['regions']:
  region['path']=str(image/Path(region['path']).name);region['sha256']=sha256(region['path'])
 fixture['expected_fault']='FIRST_Q_SW_QUIET_NAN';write_json(image/'fixture.json',fixture)
 (image/'load.plan').write_text(''.join(f"B {v['address']:x} {v['bytes']:x} {v['path']}\n" for v in fixture['regions']))
 result=dict(normal);result.update(path=str(image),expected_fault='FIRST_Q_SW_QUIET_NAN',same_q_normal_ELF=True,files={f.name:sha256(f) for f in image.iterdir() if f.is_file()})
 r.check('fault-same-normal-q-ELF',result['files']['linear.elf']==normal['files']['linear.elf'],normal['files']['linear.elf'])
 return result

def fault_cpu_trace(path,close,producer):
 if producer.poll() is None or producer.returncode!=0:raise ValueError('fault raw producer not closed successfully')
 pending=deque();accepted=responses=terminal=0;previous=-1;records=0
 for row in csv.reader(Path(path).open()):
  cycle=int(row[0]);records+=1
  if len(row)!=6 or cycle<previous or cycle>close['cycle']:raise ValueError('fault raw grammar/boundary')
  previous=cycle
  if row[1]=='CW':
   address,data,mask=[int(v,16) for v in row[2:5]]
   if 0xac010000<=address<0xac010000+516:raise ValueError('failed API used CPU Y copy')
   is_exit=address==0x10000020
   if is_exit and (data!=4 or mask!=15):raise ValueError('fault guest exit value')
   pending.append(is_exit);accepted+=1;terminal+=int(is_exit)
  elif row[1]=='CB':
   if not pending or int(row[4],16)!=0:raise ValueError('fault CPU B response')
   pending.popleft();responses+=1
 if pending or terminal!=1 or (accepted,responses)!=(close['accepted'],close['responses']) or not close['transport_idle']:raise ValueError('fault CPU terminal closure')
 return dict(sha256=sha256(path),records=records,accepted=accepted,responses=responses,entire_file_checked=True,expected_guest_exit=4)

def execute_case(cfgpath,sim):
 cfg=json.loads(cfgpath.read_text());lock=json.loads((ROOT/'configs/cocotb-toolchain-lock.json').read_text());lib=lock['files']['libpython']['path'];env=os.environ.copy()
 for n in ('COCOTB_TEST_FILTER','COCOTB_TESTCASE','MODULE','TESTCASE','GPI_EXTRA','GPI_USERS','PYGPI_USERS'):env.pop(n,None)
 entry=subprocess.check_output([sys.executable,'-m','cocotb_tools.config','--pygpi-entry-point'],text=True).strip()
 env.update(PYGPI_PYTHON_BIN=sys.executable,LIBPYTHON_LOC=lib,GPI_USERS=lib+';'+entry,COCOTB_TEST_MODULES='fault_observer' if cfg.get('expected_fault') else 'observer',COCOTB_TOPLEVEL='tb_cpu',COCOTB_TOPLEVEL_LANG='verilog',COCOTB_RANDOM_SEED='1',COCOTB_RESULTS_FILE=str(Path('results.xml').resolve()),NEXUSRV_CASE=str(cfgpath.resolve()),PYTHONPATH=os.pathsep.join([str(ROOT),str(ROOT/'tests/cocotb'),str(TEST)]))
 with Path('simulation.log').open('w') as log:
  producer=subprocess.Popen([str(sim),'-no_save','+seed=1','+max_delay=0','+max_cycles='+str(cfg['max_cycles']),'+head_run','+image_plan='+cfg['image_plan'],'+ce_rom='+cfg['ce_rom']],env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
  try:producer.wait(timeout=cfg['wall_seconds'])
  except subprocess.TimeoutExpired:EvidenceRun._kill_group(producer);raise
 xml=ET.parse('results.xml').getroot();tests=xml.findall('.//testcase')
 expected_test='bad_sw_cpu_api' if cfg.get('expected_fault') else 'w_sw_cpu_api'
 if producer.returncode or len(tests)!=1 or tests[0].get('name')!=expected_test or any(x.tag in ('failure','error','skipped') for x in xml.iter()):raise ValueError('actual real-RV32 API failed; preserve raw')
 checks=json.loads(Path('checks.json').read_text());obs=json.loads(Path('observations.json').read_text())
 if checks['status']!='PASS':raise ValueError('observer failed')
 obs['sealed_CPU_raw']=fault_cpu_trace('transactions.csv',obs['terminal_close'],producer) if cfg.get('expected_fault') else seal_cpu_trace('transactions.csv',obs['terminal_close'],producer,allowed_kinds=('CW','CB','IRQ','CR','CD','SA','SW','BA','NA','NW','NB','NL','NR','ND','MA','MB','EARLY'))
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

def read_budget(path,shape):
 rows=list(csv.reader(path.open()));commit=[row for row in rows if row[1]=='COMMIT'];stats=Counter();totals={};k=shape['K'];w=shape['W'];sw=shape['Sw'];bias=shape['bias']
 for row in rows:
  if row[1]!='AR':continue
  a,n,size=[int(v,16) for v in row[2:5]];beats=n+1;length=beats*(1<<size)
  name='W' if w<=a<w+129*k else 'Sw' if sw<=a<sw+129*(k//64)*4 else 'bias' if bias and bias<=a<bias+516 else 'Aq' if 0xba1c0000<=a<0xba1c0000+k else 'Sa' if 0xba1c5000<=a<0xba1c5000+k//64*4 else 'quantize_input' if 0xac000000<=a<0xac000000+k*4 else 'other'
  v=totals.setdefault(name,dict(AR=0,R=0,logical_bytes=0));v['AR']+=1;v['R']+=beats;v['logical_bytes']+=length
 y=[]
 for row in rows:
  if row[1]=='AW' and 0xac010000<=int(row[2],16)<0xac010000+516:y.append(dict(address=int(row[2],16),beats=int(row[3],16)+1,size=int(row[4],16)))
 values=[int(n,16) for n in commit[-1][2:]]
 return dict(reads=totals,Y_writes=y,linear_counters=dict(zip(('total','load','compute','write','restore_overlap'),values)),commit_count=len(commit))

def main():
 p=argparse.ArgumentParser();p.add_argument('--run-id');p.add_argument('--freeze-only',action='store_true');p.add_argument('--frozen-contract',type=Path);p.add_argument('--variant',type=Path);p.add_argument('--identity',type=Path);p.add_argument('--case',type=Path);p.add_argument('--sim',type=Path);args=p.parse_args()
 if args.case:execute_case(args.case,args.sim);return 0
 if not args.run_id:p.error('--run-id required')
 if not args.freeze_only and (not args.frozen_contract or not args.variant):p.error('execution requires --frozen-contract and --variant')
 r=EvidenceRun(ROOT,'OPT10_R1_W_SW_API',args.run_id);code=1
 try:
  from run_ce64_soc import build
  parent=json.loads((PARENT/'manifest.json').read_text());repo=Path(parent['candidate_repo']);sources=json.loads((PARENT/'candidate-sources.json').read_text())
  r.check('exact-parent54-before',all(sha256(repo/n)==h for n,h in sources.items()),parent['candidate_id'])
  r.check('common-accepted-guard',sha256(VARIANT)=='b03e02d7fe86ce82944d3d474caa6e5617ce1e070a11877beb24dbf3b5f00b2e',str(VARIANT))
  lock=json.loads((ROOT/'configs/cocotb-toolchain-lock.json').read_text());r.check('locked-VPI',all(sha256(v['path'])==v['sha256'] for v in lock['files'].values()),lock)
  tools={k:v['path'] for k,v in json.loads((ROOT/'docs/spec/toolchain-lock.json').read_text())['tools'].items()}
  names=[Path(__file__),TEST/'firmware.c',TEST/'observer.py',TEST/'fault_observer.py',TEST/'check_consumers.py',TEST/'monitor.svh',ROOT/'scripts/opt10_r1_measurement.py',ROOT/'scripts/opt10_r1_measurement_cocotb.py',ROOT/'scripts/run_ce64_soc.py',ROOT/'tests/ce64_soc/tb_body.svh',ROOT/'tests/ce64_soc/native_memory_model.sv',ROOT/'tests/reference/oracle.py',ROOT/'model_tools/numeric_v1.py',ROOT/'configs/t05-thresholds.json']
  frozen={str(f.relative_to(ROOT)):sha256(f) for f in names};write_json(r.path/'frozen-checker-inputs.json',frozen)
  limits=dict(compile_wall_seconds=600,simulation_wall_seconds=1800,max_CPU_cycles=20000000,production_call_deadline=900000000,effective_native_STALL_LIMIT=65536,WRITE_DRAIN_CYCLES=1024)
  base_contract=dict(scope='ISOLATED_REAL_RV32_Q_DOWN_N129_W_SW_API_AB',parent_candidate_id=parent['candidate_id'],parent_source_manifest_sha256=sha256(PARENT/'candidate-sources.json'),common_guard_sha256=sha256(VARIANT),same_ELF_and_input_per_shape=True,limits=limits,checker=frozen,api_boundary='original nxr_ce64_linear_private entry-to-return including validation, actual quantize, descriptor, wait, original hardware128-column Y publisher plus 4B tail and original native drain; input lease registration and host model fixture preparation precede timed API',native_model='unchanged digital native memory model max_delay0; transaction-relative no-stall environment, not production DDR calibration',startup_boundary='original hard-FPU CPU and original start.S/BSS zeroing; aggregate20M envelope based on retained guard v6 startup about9M; startup_authorized0 postload fixture only, no authenticated loader or service authority',expected_variant_workload=dict(q=dict(W=dict(logical_bytes=115584,AR=516,R=7224),Sw=dict(logical_bytes=7224,AR=34,R=453)),down=dict(W=dict(logical_bytes=627456,AR=2451,R=39216),Sw=dict(logical_bytes=39216,AR=101,R=2451))),accept=['both shapes original numeric thresholds and identical complete Y object bits versus shared-guard original-path baseline','complete Aq integer and Sa scale bits match independent fixed-input oracle','all accepted backend transactions ID/RESP/LAST/count closure and no outstanding terminal native work','W and Sw logical bytes/AR/R match frozen exact shape/address enumeration','original Y512B hardware bulk plus4B tail with no CPU Y copy','strict net complete API improvement for each shape; phase plus API residual reconcile without subtracting restore overlap'],stop=['normal original API/numeric/protocol failure','missing real owner/tag/credit/consumer handoff evidence','no positive complete API improvement','budget only survives by Aq cache, N2, CPU Y copy, early bank release or changed native drain/deadlines'],qualification=False,GO=False,fullgraph_cycles=None,TTFT_seconds=None,frequency_signoff_hz=None)
  base_contract['consumer_raw']='Complete actual DOT/Aq/W requests and INT32 results; each ordered FP32 p/v/partial tuple checked bitwise; real full owner/tag/epoch/generation, bank credits/certification/release, W-to-Y-to-W and row128 restart; single scratch assertion; state residence histogram sums original CE ticks; W pending intersects DOT-live/FP-busy counts are overlaps, never additive savings'
  base_contract['expected_fault']=dict(input='q first actual Sw quietNaN 0x7fc00000; all other payload and normal q ELF unchanged',accept=['original real CPU API returns NX_STATE(-4) and existing firmware exit4','linear hardware completion failure, no successful result publication','no Y AXI AW/W or CPU copy, no W/DOT/FP consumption before first block certification','all accepted R/result/native and CPU writes drain at same post-inspection terminal close'],run_order='after both normal shapes; reuse exact q variant compiled DUT')
  r.manifest.update(scope=base_contract['scope'],parent_candidate_id=parent['candidate_id'],qualification=False,board_execution=False,GO=False);r.flush()
  if args.freeze_only:
   base_contract['images']={shape:inputs(r,repo,tools,shape) for shape in ('q','down')};base_contract['images']['q_sw_nan']=fault_input(r,base_contract['images']['q']);base_contract['intervention_identity']='PENDING_BEFORE_ANY_DUT_EXECUTION';write_json(r.path/'contract.json',base_contract)
   for shape in base_contract['images']:shutil.copytree(Path(base_contract['images'][shape]['path']),r.path/'images'/shape)
   r.check('checker-inputs-after',all(sha256(ROOT/n)==h for n,h in frozen.items()),len(frozen));code=0
  else:
   prior=json.loads(args.frozen_contract.read_text());r.check('frozen-input-contract',prior['checker']==frozen and prior['parent_candidate_id']==parent['candidate_id'] and prior['common_guard_sha256']==sha256(VARIANT),sha256(args.frozen_contract))
   for shape,image in prior['images'].items():r.check('frozen-image-'+shape,all(sha256(Path(image['path'])/n)==h for n,h in image['files'].items()),image['files']['linear.elf'])
   variant=args.variant.resolve();identity=args.identity or next((variant/n for n in ('experimental-identity.json','identity.json') if (variant/n).exists()),None)
   if identity is None:raise ValueError('frozen variant identity required before compilation')
   overlay={str(f.relative_to(variant)):sha256(f) for f in (variant/'rtl').rglob('*') if f.is_file()}
   r.check('RTL-only-experiment-intervention',bool(overlay) and (GUARD not in overlay or overlay[GUARD]==sha256(VARIANT)),overlay)
   base_contract.update(images=prior['images'],frozen_input_contract_path=str(args.frozen_contract.resolve()),frozen_input_contract_sha256=sha256(args.frozen_contract),variant=str(variant),variant_identity_sha256=sha256(identity),overlay=overlay)
   write_json(r.path/'contract.json',base_contract);shutil.copy2(identity,r.path/'variant-identity.json');results={};all_compiled={};q_variant_sim=None
   sys.path.insert(0,str(TEST));from check_consumers import review as review_consumers
   for shape in ('q','down'):
    image_info=prior['images'][shape];image=Path(image_info['path']);results[shape]={};raw={};all_compiled[shape]={}
    for name in ('baseline','variant'):
     arm=Arm(r,shape+'-'+name);tb=arm.build/'tb_body.svh';body=(ROOT/'tests/ce64_soc/tb_body.svh').read_text().replace('soc.compute.ce.control.','soc.compute.ce.control.linear_control.').replace("cpu_bus.araddr<32'hac200000","cpu_bus.araddr<32'hb0000000")
     body=body.replace(".model_sealed(1'b1)",".model_sealed(1'b1),.startup_authorized(1'b0)");body=body.replace('backend.awlen!=0||backend.awburst!=1',"backend.awlen>31||backend.awburst!=1||(backend.awlen!=0&&backend.awsize!=4)")
     tb.write_text(body+'\n'+(TEST/'monitor.svh').read_text());overrides={str(f.relative_to(repo)):f for f in (repo/'rtl').rglob('*') if f.is_file()};overrides['tests/ce64_soc/tb_body.svh']=tb;overrides[GUARD]=VARIANT
     if name=='variant':overrides.update({n:variant/n for n in overlay})
     extra=[n for n in overlay if n.endswith('.sv') and not (repo/n).exists()] if name=='variant' else []
     sim=build(arm,tools,Path(lock['files']['vpi']['path']),board_memory=True,wave_window=100,source_overrides=overrides,additional_sources=[str(f.relative_to(repo)) for f in sorted((repo/'rtl/sfu').glob('*.sv'))]+extra,defines=['OPT11_LANES=2']+(['API_W_SW_VARIANT'] if name=='variant' else []))
     if shape=='q' and name=='variant':q_variant_sim=sim
     compiled={str(f.relative_to(arm.build/'sources')):sha256(f) for f in (arm.build/'sources/rtl').rglob('*') if f.is_file()};expected=dict(sources);expected[GUARD]=sha256(VARIANT)
     if name=='variant':expected.update(overlay)
     r.check(shape+'-'+name+'-compiled-source-closure',all(h==expected.get(n) for n,h in compiled.items()),len(compiled));all_compiled[shape][name]=compiled
     case=arm.build/'case';case.mkdir()
     for f in sim.parent.glob('*.bin'):shutil.copy2(f,case/f.name)
     cfg=dict(run_id=r.run_id,shape=shape,K=image_info['K'],arm=name,max_cycles=limits['max_CPU_cycles'],wall_seconds=limits['simulation_wall_seconds'],image_plan=str(image/'load.plan'),ce_rom=str(image/'ce-rom.hex'),golden=str(image/'golden.bin'),expected_aq=str(image/'expected-aq.bin'),expected_sa=str(image/'expected-sa.bin'),linear_thresholds=json.loads((ROOT/'configs/t05-thresholds.json').read_text())['operators']['linear']);write_json(case/'case.json',cfg)
     r.execute(shape+'-'+name+'-real-cpu-api',[sys.executable,Path(__file__).resolve(),'--case',case/'case.json','--sim',sim],cfg['wall_seconds']+60,cwd=case)
     obs=json.loads((case/'actual-results.json').read_text());raw[name]=transport(case/'api-transport.csv',obs['terminal_close']);obs['workload']=read_budget(case/'api-transport.csv',image_info);obs['consumer_review']=review_consumers(case/'consumer.csv',image_info,obs['terminal_close'],variant=name=='variant');obs['API_other_residual_cycles']=obs['CPU_API_cycles']-obs['counts']['linear_backend_cycles']-obs['counts']['quantize_backend_cycles'];results[shape][name]=obs;write_json(r.path/(shape+'-'+name+'-transport-review.json'),raw[name])
     r.check(shape+'-'+name+'-state-total-original-counter',obs['consumer_review']['state_residence_sum']==obs['counts']['linear_backend_cycles'],dict(residence=obs['consumer_review']['state_residence_sum'],original_counter=obs['counts']['linear_backend_cycles']))
     r.check(shape+'-'+name+'-original-Y-publisher',obs['workload']['Y_writes']==[dict(address=0xac010000,beats=32,size=4),dict(address=0xac010200,beats=1,size=2)],obs['workload']['Y_writes'])
     if name=='variant':
      for kind,want in prior['expected_variant_workload'][shape].items():r.check(shape+'-variant-'+kind+'-workload',obs['workload']['reads'][kind]==want,obs['workload']['reads'][kind])
    for kind in ('AW','W','B'):r.check(shape+'-unchanged-complete-'+kind,raw['baseline'][kind]==raw['variant'][kind],len(raw['baseline'][kind]))
    r.check(shape+'-complete-Y-bits-identical',results[shape]['baseline']['numeric']['output_bits']==results[shape]['variant']['numeric']['output_bits'],129)
    delta=results[shape]['baseline']['CPU_API_cycles']-results[shape]['variant']['CPU_API_cycles'];r.check(shape+'-actual-net-API-saving',delta>0,delta);results[shape]['CPU_API_saving_cycles']=delta
    for name in ('baseline','variant'):results[shape][name]['numeric'].pop('output_bits')
   fault_info=prior['images']['q_sw_nan'];fault_image=Path(fault_info['path']);fault_case=r.build/'q-sw-nan-case';fault_case.mkdir()
   for f in q_variant_sim.parent.glob('*.bin'):shutil.copy2(f,fault_case/f.name)
   cfg=dict(run_id=r.run_id,shape='q_sw_nan',K=896,arm='variant',expected_fault=True,max_cycles=limits['max_CPU_cycles'],wall_seconds=limits['simulation_wall_seconds'],image_plan=str(fault_image/'load.plan'),ce_rom=str(fault_image/'ce-rom.hex'));write_json(fault_case/'case.json',cfg)
   r.execute('q-bad-sw-real-cpu-api',[sys.executable,Path(__file__).resolve(),'--case',fault_case/'case.json','--sim',q_variant_sim],cfg['wall_seconds']+60,cwd=fault_case)
   fault=json.loads((fault_case/'actual-results.json').read_text());fault_raw=transport(fault_case/'api-transport.csv',fault['terminal_close']);fault['consumer_review']=review_consumers(fault_case/'consumer.csv',fault_info,fault['terminal_close'],variant=True,fault=True)
   r.check('bad-Sw-never-writes-Y',not any(0xac010000<=v[0]<0xac010000+516 for v in fault_raw['AW']),fault_raw['counts']);write_json(r.path/'q-bad-sw-transport-review.json',fault_raw)
   write_json(r.path/'results.json',dict(shapes=results,bad_first_Sw_fault=fault,scope=base_contract['scope'],fullgraph_cycles=None,TTFT_seconds=None,frequency_signoff_hz=None,GO=False));write_json(r.path/'compiled-source-closures.json',all_compiled)
   r.check('overlay-after',all(sha256(variant/n)==h for n,h in overlay.items()),overlay);r.check('checker-inputs-after',all(sha256(ROOT/n)==h for n,h in frozen.items()),len(frozen));code=0
  r.check('parent54-after',all(sha256(repo/n)==h for n,h in sources.items()),parent['candidate_id'])
 except BaseException:(r.path/'failure.txt').write_text(traceback.format_exc());print(traceback.format_exc(),flush=True)
 finally:
  for shape in ('q','down'):
   for arm in ('baseline','variant'):
    for sub in ('case','sources'):
     f=r.build/(shape+'-'+arm)/sub
     if f.exists():shutil.copytree(f,r.path/(shape+'-'+arm)/sub)
  if (r.build/'q-sw-nan-case').exists():shutil.copytree(r.build/'q-sw-nan-case',r.path/'q-sw-nan-case')
  for f in (Path(__file__),TEST/'firmware.c',TEST/'observer.py',TEST/'fault_observer.py',TEST/'check_consumers.py',TEST/'monitor.svh'):
   out=r.path/'inputs'/f.relative_to(ROOT);out.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(f,out)
  r.manifest['artifacts']={str(f.relative_to(r.path)):sha256(f) for f in r.path.rglob('*') if f.is_file() and not(f.parent==r.path and f.name in ('manifest.json','commands.json','checks.json','exit-status.txt'))};code=r.finish(code)
 print(r.manifest['status'],r.path,flush=True);return code
if __name__=='__main__':raise SystemExit(main())
