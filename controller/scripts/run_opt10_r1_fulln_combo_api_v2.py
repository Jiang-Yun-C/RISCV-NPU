#!/usr/bin/env python3
"""Draft tier1 full-N gate/down direct combo A/B; execution requires a frozen budget acceptance receipt."""
import argparse,csv,json,os,shutil,subprocess,sys,traceback,xml.etree.ElementTree as ET
from collections import Counter,deque
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from evidence import EvidenceRun,sha256,write_json,content_id
from scripts.opt10_r1_measurement import seal_cpu_trace
PARENT=ROOT/'evidence/OPT16_CANDIDATE/opt10-r1-candidate-20261020-v54'
TEST=ROOT/'tests/opt10_r1_fulln_combo_api'
GUARD='rtl/ce64/common/nx_ce64_guard.sv'
VARIANT=ROOT/'variants/opt10_r1_guard_refill_v1'/GUARD
ROPE=ROOT/'variants/opt10_r1_w_sw_rope_combo_v1/firmware/runtime/reference/nx_reference.c'
ROPE_SHA='a28800f0b9f169c920e7fa4a5bec17504da2a091ecb659cca0a9ab91fe57abc8'

class Arm:
 def __init__(self,r,name):self.parent=r;self.build=r.build/name;self.build.mkdir();self.manifest={};self.name=name
 def check(self,n,c,d):return self.parent.check(self.name+'-'+n,c,d)
 def execute(self,n,a,t,cwd=None):return self.parent.execute(self.name+'-'+n,a,t,cwd or self.build)

def inputs(r,repo,tools,shape,arm):
 from model_tools.verify_pack import verify
 from model_tools import numeric_v1 as num
 from tests.models.prepare_image import parse_elf
 image=r.build/('image-'+shape+'-'+arm);image.mkdir();manifest=json.loads((ROOT/'docs/spec/model-pack-v1-manifest.json').read_text());pack=verify(ROOT/manifest['pack_path'],expected_sha256=manifest['sha256'])
 def a(n):return pack.rows(n).copy()
 stem='model.layers.0.'
 def lin(x,name):
  name=stem+name+'.weight';aq,sa=num.quantize(x);bias=pack.entries.get(name.replace('.weight','.bias'))
  return num.linear_quantized(aq,sa,a(name),a(name+'.scale'),a(name.replace('.weight','.bias')) if bias else None)[0]
 x=num.dequantize(a('model.embed_tokens.weight')[:1],a('model.embed_tokens.weight.scale')[:1]);z=num.rmsnorm(x,a(stem+'input_layernorm.weight'))
 # Independently derive the actual layer0 norm2 and activation from token0.
 v=lin(z,'self_attn.v_proj').reshape(1,2,64);attention=np.repeat(v,7,axis=1).reshape(1,896)
 res=num.residual(x,lin(attention,'self_attn.o_proj'));norm=num.rmsnorm(res,a(stem+'post_attention_layernorm.weight'))
 if shape=='gate':
  n,k=4864,896;name=stem+'mlp.gate_proj.weight';act=norm.astype('<f4');waddr=0x88bd0200;swaddr=0x88ff8200
 else:
  n,k=896,4864;name=stem+'mlp.down_proj.weight';waddr=0x894a5200;swaddr=0x898cd200
  gate=lin(norm,'mlp.gate_proj');up=lin(norm,'mlp.up_proj')
  # Exact tests/reference/oracle.py Oracle.swiglu exp-rounding rule.
  e=np.exp(-np.abs(gate).astype('f8')).astype('f4');sig=np.where(gate>=0,np.float32(1)/(np.float32(1)+e),e/(np.float32(1)+e));act=((gate*sig)*up).astype('<f4')
 biasaddr=0;bias=None;w=a(name);sw=a(name+'.scale')
 physical_header=(PARENT/'production/full_weights.h').read_text()
 expected_line=f'w->layer[0].{shape}=(nx_matrix){{(const int8_t *)(uintptr_t)0x{waddr:08x}u,(const float *)(uintptr_t)0x{swaddr:08x}u,NULL,{n},{k}}};'
 r.check('exact-production-matrix-'+shape+'-'+arm,expected_line in physical_header and tuple(w.shape)==(n,k) and tuple(sw.shape)==(n,k//64) and pack.entries[name]['soc_address']==waddr and pack.entries[name+'.scale']['soc_address']==swaddr,expected_line)
 aq,sa=num.quantize(act);golden,dots=num.linear_quantized(aq,sa,w,sw)
 regions=[]
 def add(n,address,data,kind):
  f=image/(n+'.bin');f.write_bytes(data);regions.append(dict(name=n,address=address,bytes=len(data),path=str(f),sha256=sha256(f),kind=kind))
 add('layer0-'+shape+'-token0-input',0xac000000,act.tobytes(),'independent_real_model_activation');add('W-full',waddr,w.tobytes(),'immutable_model_slice');add('Sw-full',swaddr,sw.tobytes(),'immutable_model_slice')
 if bias is not None:add('bias-first129',biasaddr,bias.astype('<f4').tobytes(),'immutable_model_slice')
 golden.tofile(image/'golden.bin');aq.tofile(image/'expected-aq.bin');sa.tofile(image/'expected-sa.bin');dots.tofile(image/'expected-dots.bin')
 products=(dots[:,0,:].T.astype('<f4')*sa[0]).astype('<f4');values=(products*sw).astype('<f4');partials=np.empty_like(values);total=np.zeros(n,dtype='<f4')
 for group in range(k//64):total=(total+values[:,group]).astype('<f4');partials[:,group]=total
 np.stack((products,values,partials),axis=-1).astype('<f4').tofile(image/'expected-fp.bin')
 elf=image/'linear.elf';src=repo/'firmware/drivers/accel';port=repo/'firmware/runtime/port';ref=repo/'firmware/runtime/reference'
 flags=['-march=rv32imf_zicsr_zifencei','-mabi=ilp32f','-DHARD_FLOAT','-DNX_PORTABLE','-DCASE_Q='+str(int(shape=='gate')),'-O2','-g','-ffp-contract=off','-fno-fast-math','-fno-strict-aliasing','-ffreestanding','-fno-builtin','-fno-pic','-nostdlib','-nostartfiles','-msmall-data-limit=0','-ffunction-sections','-fdata-sections','-Wall','-Wextra','-Werror','-Wno-unknown-pragmas','-Wl,--gc-sections','-Wl,--build-id=none']
 reference_source=ROPE if arm=='variant' else ref/'nx_reference.c'
 r.execute('rv32-firmware-'+shape+'-'+arm,[tools['rv32_gcc'],*flags,'-I',src,'-I',port,'-I',ref,'-I',repo/'software/include','-T',ROOT/'tests/opt12/link.ld',f'-Wl,-Map={image}/linear.map',repo/'firmware/cpu/start.S',TEST/'firmware.c',port/'ce64_backend.c',reference_source,*[src/n for n in ('accel.c','target.c','linear_api.c','ce64_linear.c','opt12.c')],'-lm','-lc','-lgcc','-o',elf],120)
 entry,segments,abi=parse_elf(elf.read_bytes(),base=0x10000,capacity=0xb8000000-0x10000);r.check('actual-RV32-ABI-'+shape+'-'+arm,entry==0x10000 and abi==2,'frozen hard-FPU RV32 production API/transport; no stubs')
 rom=bytearray(65536)
 for i,s in enumerate(segments):
  add('elf-'+str(i),s.address,s.data,'firmware')
  if 0x10000<=s.address<0x20000:rom[s.address-0x10000:s.address-0x10000+len(s.data)]=s.data
 ordered=sorted(regions,key=lambda v:v['address']);r.check('shared-fixture-nonoverlap-'+shape+'-'+arm,all(a['address']+a['bytes']<=b['address'] for a,b in zip(ordered,ordered[1:])),len(regions))
 write_json(image/'fixture.json',dict(regions=regions,model_pack_sha256=manifest['sha256'],scope='REAL_MODEL_POSTLOAD_SLICE_NOT_AUTHENTICATED_LOADER'))
 (image/'load.plan').write_text(''.join(f"B {x['address']:x} {x['bytes']:x} {x['path']}\n" for x in regions));(image/'ce-rom.hex').write_text(''.join(f'{int.from_bytes(rom[i:i+4],"little"):08x}\n' for i in range(0,65536,4)))
 c_inputs=[repo/'firmware/cpu/start.S',TEST/'firmware.c',port/'ce64_backend.c',reference_source]+[src/name for name in ('accel.c','target.c','linear_api.c','ce64_linear.c','opt12.c')]
 frozen=dict(shape=shape,M=1,N=n,K=k,W=waddr,Sw=swaddr,bias=biasaddr,input_address=0xac000000,Y=(0xac011800 if shape=='gate' else 0xac00e000),path=str(image),model_pack_sha256=manifest['sha256'],files={f.name:sha256(f) for f in image.iterdir() if f.is_file()},arm=arm,reference_source=str(reference_source),reference_source_sha256=sha256(reference_source),actual_gcc_source_inputs={str(f):sha256(f) for f in c_inputs},activation_provenance='gate: actual token0 layer0 norm2; down: actual token0 layer0 act; independent numeric-v1 primitives, exact context1 attention identity and tests/reference/oracle.py Oracle.swiglu binary64 exp rounded to binary32; no candidate outputs',RoPE_executed=False)
 return frozen

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
 expected_test='fulln_combo_cpu_api'
 if producer.returncode or len(tests)!=1 or tests[0].get('name')!=expected_test or any(x.tag in ('failure','error','skipped') for x in xml.iter()):raise ValueError('actual real-RV32 API failed; preserve raw')
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

def read_budget(path,shape):
 rows=list(csv.reader(path.open()));commit=[row for row in rows if row[1]=='COMMIT'];totals={};k=shape['K'];matrix_n=shape['N'];y_base=shape['Y'];w=shape['W'];sw=shape['Sw'];bias=shape['bias']
 for row in rows:
  if row[1]!='AR':continue
  address,burst_len,size=[int(v,16) for v in row[2:5]];beats=burst_len+1;length=beats*(1<<size)
  name='W' if w<=address<w+matrix_n*k else 'Sw' if sw<=address<sw+matrix_n*(k//64)*4 else 'bias' if bias and bias<=address<bias+matrix_n*4 else 'Aq' if 0xba1c0000<=address<0xba1c0000+k else 'Sa' if 0xba1c5000<=address<0xba1c5000+k//64*4 else 'quantize_input' if 0xac000000<=address<0xac000000+k*4 else 'other'
  v=totals.setdefault(name,dict(AR=0,R=0,logical_bytes=0));v['AR']+=1;v['R']+=beats;v['logical_bytes']+=length
 y_writes=[]
 for row in rows:
  if row[1]=='AW' and y_base<=int(row[2],16)<y_base+matrix_n*4:y_writes.append(dict(address=int(row[2],16),beats=int(row[3],16)+1,size=int(row[4],16)))
 values=[int(n,16) for n in commit[-1][2:]]
 return dict(reads=totals,Y_writes=y_writes,linear_counters=dict(zip(('total','load','compute','write','restore_overlap'),values)),commit_count=len(commit))

def enumerate_supply(image):
 n,k=image['N'],image['K'];groups=k//64;out={v:dict(AR=0,R=0,logical_bytes=0) for v in ('W','Sw')}
 for row in range(n):
  group=0
  while group<groups:
   address=image['W']+row*k+group*64;take=min(4,groups-group,(4096-(address&4095))//64)
   out['W']['AR']+=1;out['W']['R']+=4*take;out['W']['logical_bytes']+=64*take;group+=take
 for row in range(0,n,4):
  address=image['Sw']+row*groups*4;left=min(4,n-row)*groups
  while left:
   if address&15:size=2;beats=min(left,(16-(address&15))//4);words=beats
   elif left>=4:size=4;beats=min(left//4,32,(4096-(address&4095))//16);words=beats*4
   else:size=2;beats=left;words=left
   out['Sw']['AR']+=1;out['Sw']['R']+=beats;out['Sw']['logical_bytes']+=beats*(1<<size);address+=words*4;left-=words
 return out

def main():
 p=argparse.ArgumentParser();p.add_argument('--run-id');p.add_argument('--freeze-only',action='store_true');p.add_argument('--frozen-contract',type=Path);p.add_argument('--variant',type=Path);p.add_argument('--identity',type=Path);p.add_argument('--budget-acceptance',type=Path);p.add_argument('--shape',choices=('gate','down','all'),default='all');p.add_argument('--case',type=Path);p.add_argument('--sim',type=Path);args=p.parse_args()
 if args.case:execute_case(args.case,args.sim);return 0
 if not args.run_id:p.error('--run-id required')
 if not args.freeze_only and (not args.frozen_contract or not args.variant or not args.budget_acceptance):p.error('DUT execution requires frozen inputs, combo variant and explicit frozen tier1 budget acceptance receipt')
 r=EvidenceRun(ROOT,'OPT10_R1_FULLN_COMBO_API',args.run_id);code=1
 try:
  from run_ce64_soc import build
  parent=json.loads((PARENT/'manifest.json').read_text());repo=Path(parent['candidate_repo']);sources=json.loads((PARENT/'candidate-sources.json').read_text())
  r.check('exact-parent54-before',all(sha256(repo/n)==h for n,h in sources.items()),parent['candidate_id']);r.check('exact-RoPE-source',sha256(ROPE)==ROPE_SHA,ROPE_SHA)
  lock=json.loads((ROOT/'configs/cocotb-toolchain-lock.json').read_text());r.check('locked-VPI',all(sha256(v['path'])==v['sha256'] for v in lock['files'].values()),lock)
  tools={k:v['path'] for k,v in json.loads((ROOT/'docs/spec/toolchain-lock.json').read_text())['tools'].items()}
  names=[Path(__file__),TEST/'firmware.c',TEST/'observer.py',TEST/'check_consumers.py',TEST/'monitor.svh',ROPE,ROOT/'scripts/opt10_r1_measurement.py',ROOT/'scripts/opt10_r1_measurement_cocotb.py',ROOT/'scripts/run_ce64_soc.py',ROOT/'tests/ce64_soc/tb_body.svh',ROOT/'tests/ce64_soc/native_memory_model.sv',ROOT/'tests/reference/oracle.py',ROOT/'model_tools/numeric_v1.py',ROOT/'configs/t05-thresholds.json']
  frozen={str(f.relative_to(ROOT)):sha256(f) for f in names};write_json(r.path/'frozen-checker-inputs.json',frozen)
  limits=dict(compile_wall_seconds=600,simulation_wall_seconds=1800,max_CPU_cycles=20000000,production_call_deadline=900000000,effective_native_STALL_LIMIT=65536,WRITE_DRAIN_CYCLES=1024)
  contract=dict(scope='EXPERIMENT3_TIER1_FULL_N_GATE_DOWN_DIRECT_COMBO_API_AB_NOT_HEAD_OR_169',parent_candidate_id=parent['candidate_id'],parent_source_manifest_sha256=sha256(PARENT/'candidate-sources.json'),baseline='exact parent54 original guard, DMA, controller and reference C',variant='frozen guard plus W/Sw integration and exact RoPE C unit compiled as a real gcc input',RoPE_source=str(ROPE),RoPE_source_sha256=ROPE_SHA,RoPE_executed=False,RoPE_saving_claim=None,limits=limits,checker=frozen,api_boundary='original nxr_ce64_linear_private entry-to-return including validation, real quantize, descriptor, wait, original all128-column hardware Y publishers and original native drain; no CPU Y copy',input_layout='actual full original physical matrix W/Sw addresses and shapes; no matrix repacking or page relocation',native_model='unchanged digital model max_delay0, not production DDR calibration',startup_boundary='original RV32 start.S and BSS zeroing; postload startup_authorized0 only; no authenticated boot or service claim',accept=['both complete fullN APIs improve versus exact54 original guard directly','all actual Aq/W/DOT and independent FP32 p/v/partial bits match reference','all Sw and W owner/tag/credit and real consumer/publisher/native drain identities close','state-residence sum equals original CE total, restore only an overlap','original complete250M budget remains supported by measured exclusive costs and actual software saving before head/169 enlargement'],stop=['any original numeric/protocol/publication failure','no complete API benefit','measured unavoidable costs fail S0 and explicit S25M scenario','unsupported unmeasured future software saving is required'],qualification=False,GO=False,fullgraph_cycles=None,TTFT_seconds=None,frequency_signoff_hz=None)
  r.manifest.update(scope=contract['scope'],parent_candidate_id=parent['candidate_id'],qualification=False,board_execution=False,GO=False);r.flush()
  if args.freeze_only:
   images={}
   if args.frozen_contract:
    previous=json.loads(args.frozen_contract.read_text());images=previous['images'];contract['prepared_input_reuse_contract_sha256']=sha256(args.frozen_contract);contract['prepared_input_reuse_contract_path']=str(args.frozen_contract.resolve());contract['postprocess_fix_only']='Distinct matrix_N/ARLEN and Ybase/Y_write_list names; same DUT, tensor, ELF, observer, consumer checker, deadlines and tool argv. --shape only selects an already frozen gate/down case.'
    for key,image in images.items():
     r.check('reuse-complete-image-'+key,all(sha256(Path(image['path'])/name)==h for name,h in image['files'].items()),image['files']['linear.elf'])
     r.check('reuse-actual-FW-source-'+key,all(sha256(name)==h for name,h in image['actual_gcc_source_inputs'].items()),image['reference_source_sha256'])
   else:
    for shape in ('gate','down'):
     for arm in ('baseline','variant'):images[shape+'_'+arm]=inputs(r,repo,tools,shape,arm)
     for name in ('layer0-'+shape+'-token0-input.bin','W-full.bin','Sw-full.bin','golden.bin','expected-aq.bin','expected-sa.bin','expected-dots.bin','expected-fp.bin'):r.check(shape+'-same-tensor-'+name,images[shape+'_baseline']['files'][name]==images[shape+'_variant']['files'][name],name)
   contract['images']=images;contract['expected_variant_workload']={shape:enumerate_supply(images[shape+'_variant']) for shape in ('gate','down')};contract['intervention_identity']='PENDING_COMBO_IDENTITY_AND_BUDGET_ACCEPTANCE_BEFORE_DUT';write_json(r.path/'contract.json',contract)
   for key,image in images.items():shutil.copytree(Path(image['path']),r.path/'images'/key)
   code=0
  else:
   prior=json.loads(args.frozen_contract.read_text());r.check('frozen-input-contract',prior['checker']==frozen and prior['parent_candidate_id']==parent['candidate_id'],sha256(args.frozen_contract))
   budget=json.loads(args.budget_acceptance.read_text());r.check('explicit-budget-tier1-acceptance',budget.get('allows_fullN_tier1') is True,sha256(args.budget_acceptance));shutil.copy2(args.budget_acceptance,r.path/'budget-acceptance.json')
   for key,image in prior['images'].items():r.check('frozen-image-'+key,all(sha256(Path(image['path'])/n)==h for n,h in image['files'].items()),image['files']['linear.elf'])
   variant=args.variant.resolve();identity=args.identity or variant/'identity.json';overlay={str(f.relative_to(variant)):sha256(f) for f in (variant/'rtl').rglob('*') if f.is_file()}
   r.check('frozen-combo-reference',sha256(variant/'firmware/runtime/reference/nx_reference.c')==ROPE_SHA,ROPE_SHA)
   r.check('budget-bound-combo-identity',sha256(identity)==budget['combo_identity_sha256'],budget['combo_experimental_content_id'])
   contract.update(images=prior['images'],frozen_input_contract_sha256=sha256(args.frozen_contract),variant=str(variant),variant_identity_sha256=sha256(identity),overlay=overlay,budget_acceptance_sha256=sha256(args.budget_acceptance));write_json(r.path/'contract.json',contract);shutil.copy2(identity,r.path/'variant-identity.json')
   sys.path.insert(0,str(TEST));from check_consumers import review as review_consumers
   results={};compiled_all={}
   selected_shapes=('gate','down') if args.shape=='all' else (args.shape,)
   contract['selected_shapes']=list(selected_shapes);write_json(r.path/'contract.json',contract)
   for shape in selected_shapes:
    results[shape]={};raw={};compiled_all[shape]={}
    for armname in ('baseline','variant'):
     image_info=prior['images'][shape+'_'+armname];image=Path(image_info['path']);arm=Arm(r,shape+'-'+armname);tb=arm.build/'tb_body.svh'
     body=(ROOT/'tests/ce64_soc/tb_body.svh').read_text().replace('soc.compute.ce.control.','soc.compute.ce.control.linear_control.').replace("cpu_bus.araddr<32'hac200000","cpu_bus.araddr<32'hb0000000").replace(".model_sealed(1'b1)",".model_sealed(1'b1),.startup_authorized(1'b0)").replace('backend.awlen!=0||backend.awburst!=1',"backend.awlen>31||backend.awburst!=1||(backend.awlen!=0&&backend.awsize!=4)")
     tb.write_text(body+'\n'+(TEST/'monitor.svh').read_text());overrides={str(f.relative_to(repo)):f for f in (repo/'rtl').rglob('*') if f.is_file()};overrides['tests/ce64_soc/tb_body.svh']=tb
     if armname=='variant':overrides.update({n:variant/n for n in overlay})
     extra=[n for n in overlay if n.endswith('.sv') and not(repo/n).exists()] if armname=='variant' else []
     sim=build(arm,tools,Path(lock['files']['vpi']['path']),board_memory=True,wave_window=100,source_overrides=overrides,additional_sources=[str(f.relative_to(repo)) for f in sorted((repo/'rtl/sfu').glob('*.sv'))]+extra,defines=['OPT11_LANES=2']+(['API_W_SW_VARIANT'] if armname=='variant' else []))
     compiled={str(f.relative_to(arm.build/'sources')):sha256(f) for f in (arm.build/'sources/rtl').rglob('*') if f.is_file()};expected=dict(sources)
     if armname=='variant':expected.update(overlay)
     r.check(shape+'-'+armname+'-exact-compiled-RTL',all(expected.get(n)==h for n,h in compiled.items()),len(compiled));compiled_all[shape][armname]=compiled
     case=arm.build/'case';case.mkdir()
     for f in sim.parent.glob('*.bin'):shutil.copy2(f,case/f.name)
     cfg=dict(run_id=r.run_id,shape=shape,K=image_info['K'],N=image_info['N'],Y=image_info['Y'],arm=armname,max_cycles=limits['max_CPU_cycles'],wall_seconds=limits['simulation_wall_seconds'],image_plan=str(image/'load.plan'),ce_rom=str(image/'ce-rom.hex'),golden=str(image/'golden.bin'),expected_aq=str(image/'expected-aq.bin'),expected_sa=str(image/'expected-sa.bin'),linear_thresholds=json.loads((ROOT/'configs/t05-thresholds.json').read_text())['operators']['linear']);write_json(case/'case.json',cfg)
     r.execute(shape+'-'+armname+'-real-cpu-api',[sys.executable,Path(__file__).resolve(),'--case',case/'case.json','--sim',sim],cfg['wall_seconds']+60,cwd=case)
     obs=json.loads((case/'actual-results.json').read_text());raw[armname]=transport(case/'api-transport.csv',obs['terminal_close']);obs['workload']=read_budget(case/'api-transport.csv',image_info);obs['consumer_review']=review_consumers(case/'consumer.csv',image_info,obs['terminal_close'],variant=armname=='variant');obs['API_other_residual_cycles']=obs['CPU_API_cycles']-obs['counts']['linear_backend_cycles']-obs['counts']['quantize_backend_cycles'];results[shape][armname]=obs
     r.check(shape+'-'+armname+'-state-sum',obs['consumer_review']['state_residence_sum']==obs['counts']['linear_backend_cycles'],obs['consumer_review']['state_residence_sum'])
     expectedY=[dict(address=image_info['Y']+offset,beats=32,size=4) for offset in range(0,image_info['N']*4,512)];r.check(shape+'-'+armname+'-all-original-Y-publishers',obs['workload']['Y_writes']==expectedY,obs['workload']['Y_writes'])
     if armname=='variant':
      for kind,want in prior['expected_variant_workload'][shape].items():r.check(shape+'-'+kind+'-exact-address-workload',obs['workload']['reads'][kind]==want,obs['workload']['reads'][kind])
     write_json(r.path/(shape+'-'+armname+'-transport-review.json'),raw[armname])
    for kind in ('AW','W','B'):r.check(shape+'-same-complete-'+kind,raw['baseline'][kind]==raw['variant'][kind],len(raw['baseline'][kind]))
    r.check(shape+'-same-complete-Y-object-bits',results[shape]['baseline']['numeric']['output_bits']==results[shape]['variant']['numeric']['output_bits'],prior['images'][shape+'_baseline']['N'])
    delta=results[shape]['baseline']['CPU_API_cycles']-results[shape]['variant']['CPU_API_cycles'];r.check(shape+'-net-complete-combo-API-saving',delta>0,delta);results[shape]['CPU_API_saving_cycles']=delta
    for armname in ('baseline','variant'):results[shape][armname]['numeric'].pop('output_bits')
   write_json(r.path/'results.json',dict(shapes=results,scope=contract['scope'],RoPE_executed=False,RoPE_saving_cycles=None,fullgraph_cycles=None,TTFT_seconds=None,frequency_signoff_hz=None,GO=False));write_json(r.path/'compiled-source-closures.json',compiled_all);code=0
  r.check('checker-and-RoPE-after',all(sha256(ROOT/n)==h for n,h in frozen.items()),len(frozen));r.check('parent54-after',all(sha256(repo/n)==h for n,h in sources.items()),parent['candidate_id'])
 except BaseException:(r.path/'failure.txt').write_text(traceback.format_exc());print(traceback.format_exc(),flush=True)
 finally:
  for shape in ('gate','down'):
   for armname in ('baseline','variant'):
    for sub in ('case','sources'):
     f=r.build/(shape+'-'+armname)/sub
     if f.exists():shutil.copytree(f,r.path/(shape+'-'+armname)/sub)
  for f in (Path(__file__),TEST/'firmware.c',TEST/'observer.py',TEST/'check_consumers.py',TEST/'monitor.svh'):
   out=r.path/'inputs'/f.relative_to(ROOT);out.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(f,out)
  r.manifest['artifacts']={str(f.relative_to(r.path)):sha256(f) for f in r.path.rglob('*') if f.is_file() and not(f.parent==r.path and f.name in ('manifest.json','commands.json','checks.json','exit-status.txt'))};code=r.finish(code)
 print(r.manifest['status'],r.path,flush=True);return code
if __name__=='__main__':raise SystemExit(main())
