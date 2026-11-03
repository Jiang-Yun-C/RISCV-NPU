#!/usr/bin/env python3
"""Export exact editable experiment source and bounded evidence; never runs EDA or changes qualification."""
import ast,difflib,hashlib,json,os,shutil,subprocess,sys,zipfile
from collections import deque
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from evidence import sha256,content_id
KEY='OPT10-R1-Pro-code-handoff-20261021-v2'
OUT=ROOT/'exports'/KEY
PKG=OUT/KEY
COMBO=ROOT/'variants/opt10_r1_w_sw_rope_combo_v1'
STOP='evidence/OPT10_R1_GUARD_REVIEW/opt10-r1-model3-gate-raw-independent-20261021-v1'
TEXT={'.py','.sv','.svh','.v','.vh','.c','.h','.S','.s','.ld','.tcl','.json','.md','.txt','.xml','.rpt','.snr','.rtr','.log','.diff','.patch','.csv','.ys','.cfg','.f','.sgdc','.fdc','.sdc','.xdc','.yaml','.yml','.sh','.toml','.prj'}
SKIP={'__pycache__','.pytest_cache','.git','compiled','csrc','vendor','sources','inputs','images','image','production','__MACOSX'}
FILES={};MAP={};COVER={};OMIT=[]
def emit(name,data,origin=None,expected=None,kind='GENERATED_HANDOFF'):
 p=PKG/name;digest=hashlib.sha256(data).hexdigest()
 if expected and digest!=expected:raise ValueError('source hash differs '+str(origin))
 if name in FILES:
  if FILES[name]['sha256']!=digest:raise ValueError('conflicting destination '+name)
  return
 p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
 FILES[name]={'sha256':digest,'bytes':len(data),'origin':origin,'kind':kind}
 if origin:MAP.setdefault(origin,[]).append(name)
def copy(src,dst,expected=None,kind='VERBATIM'):
 src=Path(src);b=src.stat();data=src.read_bytes();a=src.stat()
 if (b.st_mtime_ns,b.st_size)!=(a.st_mtime_ns,a.st_size):raise ValueError('source changed while packaging '+str(src))
 origin=str(src.relative_to(ROOT)) if ROOT in src.parents else str(src)
 emit(dst,data,origin,expected,kind)
def js(name,obj):emit(name,(json.dumps(obj,ensure_ascii=False,indent=2)+'\n').encode())
def txt(name,value):emit(name,value.encode())
def walk_source(src,dst):
 for f in sorted(src.rglob('*')):
  if f.is_file() and '__pycache__' not in f.parts and '.pytest_cache' not in f.parts and f.suffix in TEXT and f.stat().st_size<8*1024*1024:copy(f,str(Path(dst)/f.relative_to(src)))
def receipt(rel):
 p=ROOT/rel
 if not p.exists():raise ValueError('missing receipt '+rel)
 chosen=[]
 for f in sorted(p.iterdir()):
  if f.is_file() and f.suffix in TEXT and f.stat().st_size<=8*1024*1024:copy(f,rel+'/'+f.name);chosen.append(f)
 for n in ('logs','cocotb/seed1'):
  d=p/n
  if d.exists():
   for f in sorted(d.iterdir()):
    if f.is_file() and f.suffix in TEXT and f.stat().st_size<=1024*1024 and f.suffix!='.csv':copy(f,rel+'/'+str(f.relative_to(p)));chosen.append(f)
 mpath=p/'manifest.json';m=json.loads(mpath.read_text()) if mpath.exists() else {}
 missing=[]
 for n,h in m.get('artifacts',{}).items():
  dst=rel+'/'+n
  if dst in FILES:
   if FILES[dst]['sha256']!=h:raise ValueError('included original artifact differs '+dst)
  else:
   missing.append(n);src=p/n
   OMIT.append({'path':dst,'bytes':src.stat().st_size if src.is_file() else None,'original_manifest_sha256':h,'included':False,'verified_bytes_in_package':False,'reason':'Bounded review package omits large raw, binaries, generated builds or duplicated per-run source; original manifest hash is provenance only.'})
 COVER[rel]={'original_status':m.get('status'),'original_manifest_sha256':sha256(mpath) if mpath.exists() else None,'included_files':len(chosen),'original_artifacts':len(m.get('artifacts',{})),'omitted_original_artifacts':len(missing),'own_manifest_artifact_bytes_complete':bool(mpath.exists()) and not missing,'transitive_dependency_closure_complete':False,'full_receipt_replayable':False,'replay_limitation':'Complete transitive raw/tool/environment closure is not included or verified; complete own-manifest artifact bytes alone do not make a receipt replayable.','qualification_transfer':False}
def main():
 OUT.mkdir(parents=True,exist_ok=False);PKG.mkdir()
 state=json.loads((ROOT/'configs/opt10-r1-status.json').read_text());identity=json.loads((COMBO/'identity.json').read_text());gate=json.loads((ROOT/STOP/'final169-gate.json').read_text())
 assert state['status']=='ACTIVE_INCOMPLETE' and gate['allow_full169'] is False and gate['GO'] is False
 identities={};base54={};base_repo=None
 for v in (41,53,54):
  d=ROOT/f'evidence/OPT16_CANDIDATE/opt10-r1-candidate-20261020-v{v}';m=json.loads((d/'manifest.json').read_text());inventory=json.loads((d/'candidate-sources.json').read_text());repo=Path(m['candidate_repo'])
  assert content_id(inventory)==m['candidate_id']
  for n,h in inventory.items():copy(repo/n,f'frozen/v{v}/source/'+n,h)
  for name in ('manifest.json','candidate-sources.json','contract.json'):
   if(d/name).exists():copy(d/name,f'frozen/v{v}/metadata/'+name)
  copy(d/'production/full_weights.h',f'frozen/v{v}/production/full_weights.h',m['artifacts']['production/full_weights.h'])
  identities['v'+str(v)]={'candidate_id':m['candidate_id'],'files':len(inventory),'source_root':f'frozen/v{v}/source','source_manifest':f'frozen/v{v}/metadata/candidate-sources.json'}
  if v==54:base54=inventory;base_repo=repo
 composed=dict(base54);composed.update(identity['overlay'])
 for n,h in composed.items():copy(COMBO/n if n in identity['overlay'] else base_repo/n,'source/'+n,h)
 copy(ROOT/'Makefile','source/Makefile');copy(ROOT/'Makefile','protected/Makefile')
 assert sha256(ROOT/'Makefile')=='7513d21860df4bd822b0133a68d8bf6c7fd02afb2e0924d5d45dca32fca0e5eb'
 for variant in ('opt10_r1_w_sw_rope_combo_v1','opt10_r1_w_sw_integrated_v2','opt10_r1_guard_refill_v1','opt10_r1_rope_store_elision_v2','opt10_r1_linear_stream_capture_v1','opt10_r1_static54_mmio_v1','opt10_r1_startup_ready_decode_v1'):
  walk_source(ROOT/'variants'/variant,'context/variants/'+variant)
 js('SOURCE_IDENTITIES.json',{'mainline':41,'active_experiment':identity,'composed_source_content_id':content_id(composed),'composed_source_inventory':composed,'composed_source_files':len(composed),'composed_source_root':'source','frozen':identities,'protected_root_Makefile_sha256':sha256(ROOT/'Makefile'),'note':'Composed full-source content ID is distinct from overlay experimental content ID. Extra tests/scripts/Makefile in source/ are outside the 233-design-source inventory. Frozen historical variants are references, never auto-merged.'})
 patch=[]
 for n in sorted(identity['overlay']):
  old=(base_repo/n).read_text().splitlines(True) if(base_repo/n).exists() else []
  patch.extend(difflib.unified_diff(old,(COMBO/n).read_text().splitlines(True),fromfile='a/'+n if old else '/dev/null',tofile='b/'+n))
 txt('patches/exact54-to-tested-a74.patch',''.join(patch))
 # Related tests/models are source only. Large model payload and compiled images stay out.
 for src,dst in [('tests','source/tests'),('model_tools','source/model_tools'),('docs/spec','source/docs/spec')]:walk_source(ROOT/src,dst)
 # Start from directly relevant entrypoints, then close statically visible local imports.
 names=['run_opt10_r1_guard_ab','run_opt10_r1_guard_cpu_ab','run_opt10_r1_w_sw_api','run_opt10_r1_fulln_combo_api','run_opt10_r1_fulln_combo_api_v2','run_opt10_r1_fulln_combo_model3','run_opt10_r1_fulln_combo_model3_v2','run_opt10_r1_head_combo_api','prepare_opt10_r1_combo_fullgraph','run_opt10_r1_combo_fullgraph','run_opt10_r1_combo_fullgraph_v2','run_opt10_r1_sw_capture','audit_opt10_r1_sw_capture_raw','implement_opt10_r1_w_sw_stream','implement_opt10_r1_w_sw_decl_order_v2','opt10_r1_measurement','opt10_r1_measurement_cocotb','evidence','stop_opt10_r1_head_budget','build_opt10_r1_pro_code_handoff','build_opt10_r1_pro_code_handoff_v2']
 q=deque(ROOT/'scripts'/(n+'.py') for n in names);seen=set()
 while q:
  f=q.popleft()
  if f in seen or not f.is_file():continue
  seen.add(f);copy(f,'source/'+str(f.relative_to(ROOT)))
  tree=ast.parse(f.read_text())
  for node in ast.walk(tree):
   mods=[]
   if isinstance(node,ast.Import):mods=[n.name for n in node.names]
   elif isinstance(node,ast.ImportFrom) and node.module:mods=[node.module]+[node.module+'.'+n.name for n in node.names]
   for mod in mods:
    rel=Path(*mod.split('.'))
    for cand in (ROOT/(str(rel)+'.py'),ROOT/'scripts'/(str(rel)+'.py'),ROOT/'scripts'/rel/'__init__.py'):
     if cand.is_file() and ROOT/'scripts' in cand.parents:q.append(cand)
 prep=json.loads((ROOT/'evidence/OPT10_R1_COMBO_FULLGRAPH_PREP/opt10-r1-combo-fullgraph-offline-prep-20261021-v1/contract.json').read_text())
 needed=set(prep['measurement_inputs'])|{'configs/opt10-r1-status.json','configs/opt05-budgets.json','configs/opt12-vector.json','configs/opt16-integration.json','configs/t05-thresholds.json','configs/cocotb-toolchain-lock.json'}
 for n in sorted(needed):
  f=ROOT/n
  if f.is_file() and f.suffix in TEXT:copy(f,'source/'+n)
 # Frozen CPU Verilog and tiny generated initialization payload, no tool binaries.
 cpu=ROOT/'evidence/T16/acceptance-20261007-v3';copy(cpu/'manifest.json','context/T09_CPU/manifest.json')
 for f in sorted((cpu/'artifacts/generated/hard').iterdir()):
  if f.is_file() and (f.suffix in {'.v','.sv','.bin'}) and f.stat().st_size<2*1024*1024:copy(f,'context/T09_CPU/'+f.name)
 # Small real-model N129 data permit Pro to write meaningful local short checks.
 cpath=ROOT/'evidence/OPT10_R1_W_SW_API/opt10-r1-w-sw-api-input-contract-20261021-v3/contract.json';fixtures=json.loads(cpath.read_text())['images']
 for shape in ('q','down'):
  x=fixtures[shape];data={}
  for n,h in x['files'].items():
   if n.endswith('.bin') and not n.startswith('elf-'):copy(Path(x['path'])/n,'fixtures/n129/'+shape+'/'+n,h,'REAL_MODEL_SHORT_INPUT_OR_INDEPENDENT_GOLDEN');data[n]=h
  js('fixtures/n129/'+shape+'/fixture-data.json',dict(original_input_contract=str(cpath.relative_to(ROOT)),original_input_contract_sha256=sha256(cpath),shape=x['shape'],M=x['M'],N=x['N'],K=x['K'],W=x['W'],Sw=x['Sw'],bias=x['bias'],input_address=x['input_address'],Y=x['Y'],model_pack_sha256=x['model_pack_sha256'],files=data,ELF_included=False,scope='REAL_SHORT_MODEL_BYTES_ONLY_NOT_DUT_EXECUTION_OR_COMPLETE_MODEL'))
 refs=[
 'OPT10_R1_GUARD_AB/opt10-r1-guard-refill-ab-20261021-v1','OPT10_R1_GUARD_CPU_AB/opt10-r1-guard-cpu-api-ab-20261021-v6',
 'OPT10_R1_GUARD_REVIEW/opt10-r1-guard-refill-independent-review-20261021-v3','OPT10_R1_GUARD_MAP/opt10-r1-guard-refill-finite-map-20261021-v3',
 'OPT10_R1_SW_CAPTURE/opt10-r1-sw-capture-native-module-20261021-v2','OPT10_R1_W_SW_API/opt10-r1-w-sw-api-ab-20261021-v2','OPT10_R1_W_SW_API/opt10-r1-w-sw-api-ab-20261021-v1',
 'OPT10_R1_W_SW_API/opt10-r1-w-sw-api-input-contract-20261021-v3','OPT10_R1_GUARD_REVIEW/opt10-r1-w-sw-api-and-budget-independent-20261021-v1',
 'OPT10_R1_FULLN_COMBO_API/opt10-r1-fulln-combo-gate-down-20261021-v2','OPT10_R1_FULLN_COMBO_API/opt10-r1-fulln-combo-down-20261021-v1',
 'OPT10_R1_FULLN_COMBO_API/opt10-r1-fulln-gate-phase-reconcile-20261021-v1','OPT10_R1_FULLN_COMBO_API/opt10-r1-fulln-down-phase-reconcile-20261021-v1',
 'OPT10_R1_GUARD_REVIEW/opt10-r1-fulln-tier1-calibration-independent-20261021-v3','OPT10_R1_FULLN_COMBO_API/opt10-r1-fulln-model3-gate-ab-20261021-v1',
 'OPT10_R1_FULLN_COMBO_API/opt10-r1-fulln-model3-input-contract-20261021-v2','OPT10_R1_GUARD_REVIEW/opt10-r1-model3-gate-source-independent-20261021-v1',
 'OPT10_R1_GUARD_REVIEW/opt10-r1-model3-gate-raw-independent-20261021-v1','OPT10_R1_GUARD_NONLINEAR_CREDIT/opt10-r1-v41-nonlinear-guard-ceiling-20261021-v1',
 'OPT10_R1_EXECUTION_STOP/opt10-r1-native3-budget-stop-20261021-v1','OPT10_R1_HEAD_COMBO_API/opt10-r1-head-combo-api-ab-20261021-v1',
 'OPT10_R1_GUARD_REVIEW/opt10-r1-head-reviewer-cancelled-closure-20261021-v1','OPT10_R1_COMBO_FULLGRAPH_PREP/opt10-r1-combo-fullgraph-offline-prep-20261021-v1',
 'OPT10_R1_COMBO_FULLGRAPH_V2_OFFLINE/opt10-r1-combo-fullgraph-v2-boundary-offline-20261021-v2','OPT10_R1_FULLGRAPH/opt10-r1-fullgraph-v41-token0-20261020-v1',
 'OPT10_R1_COST_LEDGER/opt10-r1-current-cost-ledger-20261021-v2','OPT10_R1_LINEAR_CAPTURE_BUDGET/opt10-r1-linear-stream-cadence-budget-20261021-v2',
 'OPT10_R1_STATIC54_CLEANUP/opt10-r1-static54-cleanup-20261021-mmio-sealed15-v1','OPT10_R1_STARTUP_READY/opt10-r1-startup-ready-induction-20261021-v1',
 'OPT10_R1_EXTERNAL_MATERIAL_AUDIT/opt10-r1-primary-materials-20261021-v1','OPT16_PDS/opt10-r1-lint53-soc-20261020-v1','OPT16_STATIC/opt10-r1-lint54-static-20261020-v1']
 for n in refs:receipt('evidence/'+n)
 for n in ('docs/reports/OPT10-R1-GUARD-W-SW-20261021.md','docs/reports/OPT10-R1-CONTINUATION-20261021.md','docs/plan/cards/OPT10-R1.md','docs/plan/cards/OPT17.md','configs/opt10-r1-status.json'):
  copy(ROOT/n,'context/'+n)
 # Authoritative documents are current snapshots; the long execution journal preserves historical then-pending wording.
 notes=Path('/tmp/opt10_r1_pro_code_notes_20261021.txt')
 txt('CODE_GUIDE.txt','包内路径映射：下文rtl/firmware等设计路径均对应source/；原variants/*在context/variants/*；原evidence/*在包内evidence/*（只包含清单中的字节）。先读README_先读.md与CURRENT_STATE.md。\n\n'+notes.read_text())
 js('CURRENT_STATE.json',{'created_utc':datetime.now(timezone.utc).isoformat(),'status':state['status'],'mainline':41,'new_OPT16_GO':False,'OPT17':'DEFERRED','active_experiment':state['guard_w_sw_execution_20261021'],'final169_decision':gate,'all_new_unmeasured':{'head_API_cycles':None,'complete169_API_cycles':None,'actual_RoPE_complete_graph_saving':None,'visible_TTFT':None,'frequency_signoff_hz':None,'physical_resources':None}})
 write_documents(identity,gate)
 js('RECEIPT_COVERAGE.json',COVER)
 js('OMISSIONS.json',{'scope':'Missing bytes are not validated by original receipt hashes. This is an editable source handoff, not a complete replay environment.','global_exclusions':['Full536731456-byte model pack and fullN/head model input images','Original application/loader/test ELF, bitstreams, EDA executables and licenses','GB complete/cancelled raw, VCD and generated compiled directories','Most archived per-run source duplicates and large transport expansion JSON','No CDC/RDC legal environment, V1.4 DDR AC/PCB timing package or locked postroute DRC method can be supplied here'],'small_real_N129_model_slices_included':True,'omitted_receipt_artifacts':OMIT})
 txt('verify_package.py',VERIFY)
 js('PATH_MAP.json',MAP)
 js('FILE_MANIFEST.json',{'scope':'PACKAGE_BYTES_AND_EXACT_DESIGN_SOURCE_IDENTITY_ONLY_NOT_FULL_ORIGINAL_RECEIPT_OR_OPT16','files':FILES})
 sums={n:v['sha256'] for n,v in FILES.items()};sums['FILE_MANIFEST.json']=sha256(PKG/'FILE_MANIFEST.json')
 # FILE_MANIFEST intentionally excludes itself. SHA256SUMS covers it and every payload file.
 sums.pop('SHA256SUMS.txt',None)
 (PKG/'SHA256SUMS.txt').write_text(''.join(h+'  '+n+'\n' for n,h in sorted(sums.items())))
 result=subprocess.run([sys.executable,str(PKG/'verify_package.py')],capture_output=True,text=True,check=True)
 archive=OUT/(KEY+'.zip')
 with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
  for f in sorted(PKG.rglob('*')):
   if f.is_file():z.write(f,KEY+'/'+str(f.relative_to(PKG)))
 (OUT/(archive.name+'.sha256')).write_text(sha256(archive)+'  '+archive.name+'\n')
 shutil.copy2(PKG/'PROMPT_给Pro.txt',OUT/'PROMPT_给Pro.txt')
 report={'status':'PASS_PACKAGE_CHECK_ONLY','archive':str(archive),'archive_sha256':sha256(archive),'archive_bytes':archive.stat().st_size,'payload_files':len(FILES),'design_files':len(composed),'overlay_files':len(identity['overlay']),'script_import_closure_files':len(seen),'verifier':json.loads(result.stdout),'GO':False,'board_execution':False}
 (OUT/'BUILD_REPORT.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps(report,ensure_ascii=False))

def write_documents(identity,gate):
 txt('README_先读.md',f'''# OPT10-R1 当前源码交接给 Pro（2026-10-21）

这份包用于让 Pro **亲自修改代码并返回补丁**。它包含精确设计源码和有界证据，不是完整仿真环境，也不是新 OPT16 GO。

## 按此顺序读取

1. `CURRENT_STATE.md`：当前结果、完整API预算、STOP范围和仍缺的资格。
2. `PROMPT_给Pro.txt`：可直接粘贴到Pro的任务，要求交付代码而非只建议。
3. `CODE_GUIDE.txt`：七文件职责、真实行号、buffer/lease/publisher及计量边界。
4. `source/rtl/ce64/nx_ce64_control.sv`、`source/rtl/ce64/nx_ce64_dma.sv`、`source/rtl/ce64/nx_ce64_sw_capture.sv`、`source/rtl/ce64/common/nx_ce64_guard.sv`；其余入口见导读。
5. `{STOP}/final169-gate.json`、`conditional-screen.json`、`screen.py`、`review.json`。

## 从哪份代码开始改

`source/`已按**精确54的232个设计源＋七文件overlay**合成，设计闭包233文件。另附相关runner/checker/tests/configs和原根Makefile。它对应实验EID `{identity['experimental_content_id']}`，尚未晋级。

`frozen/v54/source/`是精确54，`frozen/v41/`是主线历史，`frozen/v53/`只用于最新已执行物理报告的源身份参照。`context/variants/`保留未自动合入的实验/私有静态与startup改动；它们不属于当前七文件组合。

不要取用户工作区根RTL/FW作为基线。交接时已核实它们与54/a74不同。所有设计源SHA在`SOURCE_IDENTITIES.json`，每个包内文件在`FILE_MANIFEST.json`；`patches/exact54-to-tested-a74.patch`可将54重建为本次已测组合。

先运行 `python3 verify_package.py`，再复制`source/`作新编辑目录。保留原包及frozen目录，返回新源码/补丁与新身份清单。修改后不要重写旧清单使旧证据看起来仍适用。

## 有哪些实际输入

`fixtures/n129/q/`与`down/`含真实前129行W/Sw、激活、bias（q）、独立Aq/Sa、DOT/FP/最终Y参考；总量约1.1MB。它们来自既有冻结输入合同，逐字节hash已核对。未包含完整536,731,456B模型包、完整N/head输入、ELF、bitstream或工具/许可。

原机复现入口在`REPRODUCE.md`。现有runner保留原绝对路径/精确收据引用，并非解压即能跑完整VCS/PDS的便携脚手架；完整原机环境在`/home/Jiang/RISCV+NPU`。不要删掉身份/预算门来让外部包“能跑”。小规模本地检查可使用随包源码/短输入；不能运行的项目标为NOT_RUN。

## 如何理解收据

`evidence/`只打包有界文本/JSON及部分短raw。`RECEIPT_COVERAGE.json`逐收据说明本manifest的artifact是否齐全；全部完整重放标记为false，因为未验证传递依赖/raw/工具环境闭包。`OMISSIONS.json`列出未打包的原artifact及原manifest引用hash。**原manifest不能验证缺失字节**，也不能用包校验代替原raw独审。`context/docs/reports/...`是完整过程日志，早期“运行中”描述已由顶部最新STOP取代；以`CURRENT_STATE.md`和最终门为准。

所有新旧FAIL保留。head0是预算取消，原父receipt FAIL、partial raw未完整封口；不是数值/协议故障证明。Pro可以重新设计新的隔离修订，但不得直接继续被拒绝的旧head/169或操作板卡。
''')
 txt('CURRENT_STATE.md','''# 当前状态与代码结论

OPT10-R1 ACTIVE/未完成；主线41未变，OPT17 DEFERRED。没有新的有效独立OPT16 GO，没有编程、SD/Flash写入或板端测速。全部新DUT/审计运行已结束。

## 身份

- 主线41 CID：5d8e5ca3c53193e1113ab13f69dab8b162ed25ca606a6a0b7555f2f8c0c17e9d。
- 精确54 CID：30baf1ecc6d83c130a126e508d461f917b69c997e283d1b82c1afec31cc17046。
- 当前七file组合EID：a74c87ae4e8b0290abd825bfe8d1708323f95a2fc7619ada0638a010ea6c27bc。
- 七file为guard、DMA、control、CE top、Sw capture、dispatch、RoPE C。完整233设计源在source/，元数据和overlay hash见SOURCE_IDENTITIES.json。
- 七file组合没合入私有15file静态修复或startup镜像；这些分支不能拼成当前资格。

## 已实际实现

正常guard单槽寄存器支持consume/refill；数据仍寄存、单在途、LAST退休才释放、denied流不变。512B原write_buffer拆两个256B W bank，证书后直接给DOT。1216B四行Sw私有缓存从真实DMA R捕获并在完整认证/运输排空后可见。真实descriptor完整owner/session/sequence与epoch/generation绑定；真实消费后归还bank；每行原bias先读，128列publisher之前归还W，原native1024 drain/readback保留。

Aq/Sa继续原路径；没有Aq缓存、N2双行上下文或第二scratch。逐G64仍两次独立FP32乘法、逐行原序累加。RoPE只省略精确单位系数情况下逐位相同的普通RAM写；完整N linear测试只是编译该文件，没有实际执行RoPE。

## 实测API cycles（每行独立A/B，不相加）

| A/B范围 | native数字模型 | 基线 | 改版 | 净省 |
|---|---:|---:|---:|---:|
| guard only，N129/K4864 | delay0 | 795825 | 744382 | 51443 |
| W+Sw q N129/K896，共同refill基线 | delay0 | 277659 | 257523 | 20136 |
| W+Sw down N129/K4864，共同refill基线 | delay0 | 744382 | 620039 | 124343 |
| 七file完整gate N4864/K896，对原54 | delay0 | 2268805 | 1186869 | 1081936 |
| 七file完整down N896/K4864，对原54 | delay0 | 2379710 | 1187194 | 1192516 |
| 七file完整gate，对原54，两臂均匹配旧169模型 | delay3 | 2410630 | 1310354 | 1100276 |

完整gate/down各68096组、分别38/7个原512B publisher，数值/owner/tag/credit/原序FP/native排空独审PASS。匹配delay3的gate改版CE=1081178；同delay0为958931，多122247，其中W_WAIT多112840、Sw_WAIT多8281、其他load多26、write多1100。首次Sw NaN真实CPU故障用例hardware−9/API−4，零W/DOT/FP/Y、接受运输排空PASS，但未授完整fault/warm矩阵。

guard协议13例、capture链26例、Sw独立24例943检查等只是各自闭包证据。256B无stallprimitive间隔46→31，不可将31替代共享fabric/API成本。adapter仍先接完整native量子再返回AXI R。

## 为什么触发STOP

原41完整169图终态数值PASS，但API413554211>250M；CE243187285，API−CE170366926（含其他backend，非纯CPU）。完整线性+head API289845608。若其他API实际节省S，CE预算=79633074+S。

新组合完整169从未运行。RoPE25173404的历史调用投影未在组合完整图兑现，不能当已省；整25M仍为情景假设。backend属于API内部；restore和运输/计算交集不得重复计账。

最初delay0条件均值CE102239991，S25M余2393083。后发现旧169使用max_delay3，作用于每个native beat，而非一次命令延迟。进行了上表匹配gate补证后，按真实169地址/行/page/量子/Sw块/publisher事件替换系数，未用N129比例放大。只将已测无bias K896角色换成3，其余bias/K4864仍乐观保留0。

| 匹配原模型的条件角色账 | CE cycles | S25M剩余 |
|---|---:|---:|
| 观测pattern min | 104189519 | +443555 |
| 观测pattern mean | 112466641 | −7833567 |
| 观测逐事件max | 121540430 | −16907356 |

旧41完整48533086条raw另枚举：非linear/SFU最多613552个内部guard返回泡泡（633344 R−19792 AR），这是机会数上界，不是新API实省，也不含CPU/native。即使给满该额外信用，均值还差7220015；条件算式为257220015，**并非新完整图实测周期**。按事前均值规则拒绝扩大到169/新增head0 arm。min仍可行，因此未证明250M数学绝对不可能。

已启动的head0基线在未完成时按预算停止，variant未启动；精确进程/取消收据与partial raw hash保留。head API、完整169 API、实际整图RoPE节省均null，不归因为DUT数值或协议FAIL。

## 还有哪些资格没完成

同一最终冻结候选的完整head/169、生产service、冷启动/长上下文/全部可见TTFT、最终质量、完整fault/暖恢复、资源/125MHz/零warning均未闭合。私有15file静态补丁26→1仍FAIL；reset v2/v3/v4迁移告警已拒绝合并。startup镜像有源绑定关系/归纳证明但无新PDS；最新有效物理仍53 setup WNS−0.294ns，非新组合签核。

三项外部硬缺项：合法可执行CDC/RDC环境/许可；匹配V1.4 DDR AC/核心PCB/外设时序资料；锁定PDS支持的postroute DRC方法。责任人/时间未知，输入未变不重复许可/help探针。

## 新修改不可放宽的合同

125MHz、完整API250M、全部原TTFT，以及LUT76500/FF73800/DRM36K140/APM57不改。attention150M、完整图验证600M、生产保护900M分开。当前54 SoC实际native STALL_LIMIT=65536，独立capture为125000000，二者不改也不能混称125M生产timeout已测。原128列publisher、native1024排空、单scratch、owner/tag/credit、失败不成功发布、接受事务排空与两MUL/原序ADD保持。
''')
 txt('PROMPT_给Pro.txt','''请基于附件亲自修改OPT10-R1代码并返回可应用补丁/修改文件；不要只重新总结或列计划。

先读 README_先读.md、CURRENT_STATE.md、CODE_GUIDE.txt、SOURCE_IDENTITIES.json，以及 evidence/OPT10_R1_GUARD_REVIEW/opt10-r1-model3-gate-raw-independent-20261021-v1/{final169-gate.json,conditional-screen.json,review.json,screen.py}。再读 source/rtl/ce64/{nx_ce64_control.sv,nx_ce64_dma.sv,nx_ce64_sw_capture.sv}、common/nx_ce64_guard.sv、common/nx_ce64_ddr_adapter.sv、source/rtl/sfu/nx_opt11_dispatch.sv 和source/firmware/runtime/reference/nx_reference.c。

准确起点是精确54+七文件已测组合a74c87ae4e8b0290abd825bfe8d1708323f95a2fc7619ada0638a010ea6c27bc，已合成在source/；不是原工作区根RTL/FW。先运行python3 verify_package.py，然后复制source/建立新工作副本。frozen/、context/里的旧变体、原收据和根Makefile不可修改。

当前事实：guard refill与W直捕获+四行Sw已经真实接入CPU/控制器/FP/原128列publisher。完整gate/down delay0 API各从2268805/2379710降到1186869/1187194，位级/credit/native排空独审PASS。匹配旧完整169的native max_delay3后，完整gate API2410630→1310354也PASS，但CE1081178比delay0多122247，其中W_WAIT多112840、Sw_WAIT多8281。原native模型对每个beat施加LFSR cap3等待；不能把delay0视为旧169或真实DDR模型。

按169实际事件回填，匹配角色条件mean CE112466641；整25M假设下还缺7833567。即使给满非CE guard泡泡最大机会613552，仍缺7220015，按事前mean规则STOP。min情景余443555，尚未证明数学绝对不可能。257220015是条件算式，不是新完整169实测。只有无bias K896角色已换为匹配3，其他仍乐观保留0，不得把模型当保守实板预测。RoPE25173404历史投影未兑现、其他API170366926不是纯CPU；backend嵌套API、restore/peek/运输计算重叠不能重复记账。

请做以下工作并真正交付代码：
1. 找出本次实现仍可兑现的主导未隐藏成本，用真实state/owner/port/AR/R/native/FP/publisher事件说明；不要预设改guard、加Aq/N2或加存储必然正确。当前已消除guard隔拍，但adapter仍先收全native量子。Sw认证、W bank交接和FP/原Y发布必须在账中。
2. 选择最有判别力且边界可审的下一修订。先写新合同：全API预算、修改文件、数据/端口/状态、输入/模型(seed1/max_delay3为匹配参照)、checker/deadline及接受/拒绝/停止条件。历史Aq/N2是暂缓/未实现项，若要改变本轮边界须显式解释新合同与预算，不能把未做功能视为已有，也不能临时堆组件抵账。
3. 在新的工作副本实际改RTL/FW。保留每G64两次独立FP32乘法、每行原序累加、原数值/错误语义、单scratch互斥、完整owner/tag/credit、真实消费后释放bank、已接受事务排空、失败不成功发布、原128列硬件publisher与1024 native drain/readback。Sw不能塞进旧0x5800区覆盖0x5c00 bias；held W时不能全局拿physical_idle替代dma_idle。
4. 使用包内真实N129 q/down数据及现有checker设计/执行有判别力的短验证；有工具就实际跑并给完整命令/日志/退出码，没有工具就明确NOT_RUN，提供可在原机执行的测试/脚本，不得伪称RTL/EDA/完整API PASS。先syntax/短测，再真实CPU完整API净差和事件预算；失败保留。结果无净收益或预算仍不成立就停止扩大，不投数小时head/169碰运气。
5. 返回：可应用的changes.patch（相对随包source/的设计源码）、全部修改/新增文件、源hash/新身份说明、合同、预算前后账、实际验证与未测项。单独说明对接口/时序/资源/复位的影响和还缺的资格。不要只给伪代码或建议。新的RTL/FW不得沿用a74身份；不要改旧收据或用代码相同叶模块自动移授集成资格。

原125MHz、完整API250M、全部TTFT及资源76500LUT/73800FF/140DRM36K/57APM不变；150M attention、600M整图验证、900M生产保护不混用。当前54 SoC实际native timeout65536与旧独立capture125M合同不同，不能偷改或混称已测。没有新的独立OPT16 GO，禁止OPT17/编程/写SD或Flash/板端测速。

完整模型/ELF/EDA工具/许可和GB raw不在附件；小N129真实模型slice和独立golden已包含。附件verify只验证已有字节，不复验被省略原artifact。当前CDC/RDC合法环境、V1.4 DDR AC/PCB资料、锁定PDS postroute DRC方法缺失，责任人/时间未知；不要重跑没变输入的许可/help探针。最新有效物理53 setup WNS−0.294ns，私有静态15file补丁26→1仍FAIL，startup证明无新PDS，均不能自动合并或当新组合签核。

本轮head0已因预算取消并保留partial raw/FAIL，variant和169未运行，完整性能指标null。不要直接重启被拒绝的旧run-id或绕过新执行版的合同/预算门；请先交付新的可测代码。
''')
 txt('REPRODUCE.md','''# 复现与证据入口

## 外部Pro可立即做的事

`python3 verify_package.py`用标准库核对包内SHA、三个精确候选设计闭包、233源合成及七文件overlay身份，并核对关键预算算式；它不执行RTL/EDA或复验缺失raw。`fixtures/n129/{q,down}`可用于新独立短checker；`source/tests/opt10_r1_w_sw_api`等为原数值/消费checker源码。

`patches/exact54-to-tested-a74.patch`相对frozen/v54/source；在临时副本运行`patch -p1`后，所有233个设计源应逐文件等于source/。Pro修改应相对这个已测a74快照，输出新的补丁，而非再把54→a74补丁当新成果。

## 原机入口（依赖原机工具、模型及全部冻结收据）

工作目录为 `/home/Jiang/RISCV+NPU`。以下是已执行命令的结构，不授权重用旧run-id或重跑。原run的精确argv、输入、期限见对应`commands.json`和`contract.json`。

```text
/home/Jiang/.local/opt/nexusrv-python/bin/python scripts/run_opt10_r1_fulln_combo_model3_v2.py \
 --run-id <新的隔离run-id> --shape gate \
 --frozen-contract evidence/OPT10_R1_FULLN_COMBO_API/opt10-r1-fulln-model3-input-contract-20261021-v2/contract.json \
 --variant <新变体目录> --budget-acceptance <新独立匹配模型接受文件>
```

这是旧a74测量runner的接口说明；它强制旧a74身份，不能直接给新的RTL使用。新修订须生成自己的合同/runner/身份，明确继承与重新验证闭包。禁止删除检查来运行。原已执行run-id为`opt10-r1-fulln-model3-gate-ab-20261021-v1`，该原收据必须保留。

| 范围 | 源入口 | 最新实测/审查 |
|---|---|---|
| guard协议/native A/B | source/scripts/run_opt10_r1_guard_ab.py | evidence/OPT10_R1_GUARD_AB/opt10-r1-guard-refill-ab-20261021-v1 |
| guard真实CPU | source/scripts/run_opt10_r1_guard_cpu_ab.py | evidence/OPT10_R1_GUARD_CPU_AB/opt10-r1-guard-cpu-api-ab-20261021-v6 |
| W+Sw N129正常/坏Sw | source/scripts/run_opt10_r1_w_sw_api.py | evidence/OPT10_R1_W_SW_API/opt10-r1-w-sw-api-ab-20261021-v2 |
| 完整gate/down delay0 | source/scripts/run_opt10_r1_fulln_combo_api_v2.py | evidence/OPT10_R1_FULLN_COMBO_API/opt10-r1-fulln-combo-gate-down-20261021-v2 与 opt10-r1-fulln-combo-down-20261021-v1 |
| 完整gate匹配delay3 | source/scripts/run_opt10_r1_fulln_combo_model3_v2.py | evidence/OPT10_R1_FULLN_COMBO_API/opt10-r1-fulln-model3-gate-ab-20261021-v1 |
| 独立raw审查及条件角色预算 | evidence/OPT10_R1_GUARD_REVIEW/opt10-r1-model3-gate-raw-independent-20261021-v1/raw_audit.py 与 screen.py | 同目录review.json/conditional-screen.json/final169-gate.json |
| head流式checker | source/tests/opt10_r1_head_combo_api/check_consumers_streaming.py | 原head0取消，无完整性能资格 |
| 169离线准备/严格执行边界 | source/scripts/prepare_opt10_r1_combo_fullgraph.py 与 run_opt10_r1_combo_fullgraph_v2.py | 原准备与offline验证PASS，无执行许可/无169 DUT |

VCS/RV32/PDS版本及位置见随包`source/docs/spec/toolchain-lock.json`和`source/configs/cocotb-toolchain-lock.json`。这些位置是原机记录，不表示外部Pro具有同样工具或许可。原数字native模型在`source/tests/ce64_soc/native_memory_model.sv`，delay3配置在`source/configs/opt12-vector.json`。

## 长异步任务

原用户合同：空write_stdin轮询yield_time_ms≥180000，优先300000；functions.wait≥180000；functions.exec外层比最长嵌套等待至少长30000ms。非空交互输入不套长等待，不为报告仍运行而唤醒。新实验先冻结checker/input/deadline，保留FAIL，未测指标null；不得修改根Makefile。
''')

VERIFY=r'''#!/usr/bin/env python3
"""Verify handoff bytes and design identities only; never grants qualification."""
import hashlib,json,sys
from pathlib import Path
R=Path(__file__).resolve().parent
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
load=lambda p:json.loads(p.read_text())
def need(x,m):
 if not x:raise ValueError(m)
def cid(x):return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def main():
 m=load(R/'FILE_MANIFEST.json');expected=set(m['files'])|{'FILE_MANIFEST.json','SHA256SUMS.txt'}
 for n,x in m['files'].items():
  p=(R/n).resolve();need(R in p.parents and p.is_file(),'missing/unsafe '+n);need(p.stat().st_size==x['bytes'] and sha(p)==x['sha256'],'changed '+n)
 actual={str(p.relative_to(R)) for p in R.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
 need(actual==expected,'inventory extras/missing')
 sums={n:h for h,n in (line.split('  ',1) for line in (R/'SHA256SUMS.txt').read_text().splitlines())}
 need(set(sums)==set(m['files'])|{'FILE_MANIFEST.json'},'sum inventory')
 for n,h in sums.items():need(sha(R/n)==h,'sum changed '+n)
 ids=load(R/'SOURCE_IDENTITIES.json')
 for v,x in ids['frozen'].items():
  inv=load(R/x['source_manifest']);need(cid(inv)==x['candidate_id'],'candidate ID '+v)
  for n,h in inv.items():need(sha(R/x['source_root']/n)==h,'candidate source '+v+'/'+n)
 base=load(R/ids['frozen']['v54']['source_manifest']);base.update(ids['active_experiment']['overlay'])
 need(base==ids['composed_source_inventory'] and cid(base)==ids['composed_source_content_id'] and len(base)==233,'composed source identity')
 for n,h in base.items():need(sha(R/'source'/n)==h,'composed source '+n)
 need(sha(R/'source/Makefile')==sha(R/'protected/Makefile')==ids['protected_root_Makefile_sha256'],'protected Makefile')
 g=load(R/'evidence/OPT10_R1_GUARD_REVIEW/opt10-r1-model3-gate-raw-independent-20261021-v1/final169-gate.json')
 need(g['allow_full169'] is False and g['GO'] is False,'STOP scope')
 need(104633074-112466641==-7833567 and -7833567+613552==-7220015,'conditional budget arithmetic')
 need(g['unconditional_250M_impossibility_proved'] is False and g['complete_API_cycles'] is None,'unmeasured/conditional scope')
 print(json.dumps({'status':'PASS','package_files':len(m['files']),'design_source_files':233,'overlay_files':7,'scope':'INCLUDED_BYTES_IDENTITY_AND_CONDITIONAL_ARITHMETIC_ONLY_NOT_RAW_REPLAY_OR_OPT16'},ensure_ascii=False))
if __name__=='__main__':
 try:main()
 except Exception as e:print('FAIL',str(e));sys.exit(1)
'''
if __name__=='__main__':main()
