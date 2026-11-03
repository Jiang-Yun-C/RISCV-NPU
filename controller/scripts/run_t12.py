#!/usr/bin/env python3
"""Rebuild T12 host + real RV32 runtime; preserve all acceptance evidence."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tarfile
import traceback
import threading
from concurrent.futures import ThreadPoolExecutor
from evidence import EvidenceRun,StepFailure,sha256,content_id,write_json
from run_cocotb import environment,generate
from elftools.elf.elffile import ELFFile
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tests/models'),str(ROOT/'tests/runtime'),str(ROOT/'tests/cocotb')]
from prepare_image import parse_elf

class RuntimeEvidence(EvidenceRun):
    """Independent simulator processes share only a serialized evidence index."""
    def __init__(self,*args,**kwargs):
        self._index_lock=threading.RLock();super().__init__(*args,**kwargs)
    def flush(self):
        with self._index_lock:super().flush()

def inputs():
    names=['Makefile','scripts/run_t12.py','scripts/run_cocotb.py','scripts/cocotb_case.py','scripts/evidence.py','scripts/probe_tools.py',
        'model_tools/export_tokenizer.py','model_tools/runtime_weights.py','model_tools/numeric_v1.py','model_tools/verify_pack.py',
        'software/runtime/run_cpu.py','software/reference/runtime.py','docs/spec/runtime-v1.md','configs/t12-runtime.json','configs/cocotb-toolchain-lock.json',
        'docs/spec/model-pack-v1-manifest.json','docs/spec/model-pack-v1-budget.json','docs/spec/application-v2-model-lock.json',
        'docs/spec/toolchain-lock.json','docs/spec/memory-map-v1.json','configs/t05-thresholds.json','configs/t11-reference.json',
        'firmware/cpu/start.S','third_party/lock.json','rtl/interfaces/axi4_if.sv','tests/models/prepare_image.py',
        'tests/models/axi_sparse_mem.sv','tests/models/sparse_memory_pkg.sv']
    for folder in ('firmware/runtime','tests/runtime','tests/cocotb','cpu_gen'):
        names += [str(p.relative_to(ROOT)) for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc']
    return {n:sha256(ROOT/n) for n in sorted(set(names))}

def cflags(run,fixtures,small=False):
    return ['-std=c11','-DNX_PORTABLE','-O2','-ffp-contract=off','-fno-fast-math','-fno-strict-aliasing',
        '-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-Wno-unknown-pragmas','-Wno-unused-function',
        '-I',ROOT/'firmware/runtime/port','-I',ROOT/'firmware/runtime/reference','-I',fixtures]+(['-DNX_SMALL'] if small else [])
def sources():
    return [ROOT/p for p in ('tests/runtime/firmware.c','firmware/runtime/port/tokenizer.c','firmware/runtime/port/runtime.c','firmware/runtime/port/model.c','firmware/runtime/reference/nx_reference.c')]

def build_full(run,tools,tokenizer):
    dest=run.build/'firmware/full';dest.mkdir(parents=True)
    run.execute('full-weight-views',[tools['python'],ROOT/'model_tools/runtime_weights.py',dest],60)
    run.execute('firmware-full',[tools['rv32_gcc'],*cflags(run,dest),f'-DTOKENIZER_BYTES={(tokenizer/"tokenizer.nxt").stat().st_size}',
        '-march=rv32im_zicsr_zifencei','-mabi=ilp32','-ffreestanding','-fno-pic','-fno-builtin','-nostdlib','-nostartfiles',
        '-msmall-data-limit=0','-ffunction-sections','-fdata-sections','-fstack-usage','-Wl,--gc-sections','-Wl,--build-id=none',
        f'-ffile-prefix-map={ROOT}=.',f'-Wl,-Map={dest}/firmware.map','-T',ROOT/'firmware/runtime/port/link.ld',
        ROOT/'firmware/cpu/start.S',ROOT/'firmware/runtime/main.c',*sources()[1:],'-lm','-lc','-lgcc','-o',dest/'firmware.elf'],120,cwd=dest)
    with (dest/'firmware.elf').open('rb') as stream:
        elf=ELFFile(stream);symbols={s.name:s['st_value'] for s in elf.get_section_by_name('.symtab').iter_symbols()}
    run.check('full-image-static',elf['e_flags']==0 and symbols['__bss_end']<=0xb4800000 and '__muldf3' in symbols and
        not any(n in symbols for n in ('malloc','calloc','_sbrk','clock_gettime')),{'bss_end':symbols['__bss_end'],'stack':65536,'abi':'ILP32'})
    write_json(dest/'footprint.json',{'text_data_bss_bytes':symbols['__bss_end']-0xb4000000,'stack_capacity':65536,
        'heap_capacity':8388608,'heap_used':0,'kv_bytes':15728640,'work_bytes':664576,'logits_bytes':607744,
        'tokenizer_index_bytes':(tokenizer/'tokenizer.nxt').stat().st_size,'qualification':'FULL RV32 LINK; numerical full graph verified on host; real reduced graph in RTL'})
    return dest

def build_firmware(run,tools,profile,fixtures,tokenizer):
    out=run.build/'firmware'/profile;out.mkdir(parents=True)
    size=(tokenizer/'tokenizer.nxt').stat().st_size
    elf=out/'firmware.elf';march='rv32im_zicsr_zifencei'
    cmd=[tools['rv32_gcc'],*cflags(run,fixtures,profile=='small'),f'-DTOKENIZER_BYTES={size}',f'-march={march}','-mabi=ilp32',
         '-g','-ffreestanding','-fno-pic','-fno-builtin','-nostdlib','-nostartfiles','-msmall-data-limit=0',
         '-ffunction-sections','-fdata-sections','-fstack-usage',f'-ffile-prefix-map={ROOT}=.',
         '-Wl,--build-id=none','-Wl,--gc-sections',f'-Wl,-Map={out}/firmware.map',
         '-T',ROOT/'firmware/runtime/port/link.ld',ROOT/'firmware/cpu/start.S',*sources(),'-lm','-lc','-lnosys','-lgcc','-o',elf]
    run.execute('firmware-'+profile,cmd,300,cwd=out)
    log=run.execute('disassemble-'+profile,[tools['rv32_objdump'],'-d',elf],30);shutil.copy2(log,out/'firmware.dis')
    with elf.open('rb') as stream:
        obj=ELFFile(stream);symbols={s.name:s['st_value'] for s in obj.get_section_by_name('.symtab').iter_symbols()}
    entry,segments,flags=parse_elf(elf.read_bytes(),base=0x10000,capacity=0xb8000000-0x10000)
    run.check('abi-'+profile,entry==0x10000 and flags==0 and '__mulsf3' in symbols and (profile=='control' or '__muldf3' in symbols) and
              not any(s in symbols for s in ('malloc','calloc','_sbrk','omp_set_num_threads','clock_gettime')),
              {'entry':entry,'flags':flags,'abi':'ILP32 soft-float, libm and libgcc, no heap/POSIX/OpenMP'})
    run.check('image-bound-'+profile,all((0x10000<=s.address and s.address+s.memory_size<=0x20000) or
              (0xb4000000<=s.address and s.address+s.memory_size<=0xb4800000) for s in segments),symbols['__bss_end'])
    images=[]
    def image(name,address,data):
        path=out/name;path.write_bytes(data);images.append({'path':str(path),'address':address,'bytes':len(data),'sha256':sha256(path)})
    for i,s in enumerate(segments):image(f'segment-{i}.bin',s.address,s.data)
    image('bss-poison.bin',symbols['__bss_start'],b'\xcc'*(symbols['__bss_end']-symbols['__bss_start']))
    image('stack-poison.bin',0xb7ff0000,b'\xa5'*65536)
    for name,address in [('tokenizer.nxt',0xb8af4d00),('small.bin' if profile=='small' else 't11-tile.bin',0x80000000)]:
        path=tokenizer/name if name=='tokenizer.nxt' else fixtures/name
        images.append({'path':str(path),'address':address,'bytes':path.stat().st_size,'sha256':sha256(path)})
    guards=[0xb7ff0000,0xb7ff0004,0xb7ff0008,0xb7ff000c,0xb5000000,0xa8000000+327680,0xac000800]
    for i,address in enumerate(guards[4:]):image(f'guard-{i}.bin',address,b'\xa5'*16)
    fixture={'producer':'T12','profile':profile,'test_mode':'PRELOAD','isa':march,'abi':'ilp32','entry':entry,
         'elf_sha256':sha256(elf),'symbols':symbols,'images':images,'guard_addresses':guards,
         'logical_view':'actual CPU UART-MMIO observations, readonly weights/tokenizer, guarded arenas',
         'source_fixtures_sha256':sha256(fixtures/'manifest.json')}
    write_json(out/'fixture.json',fixture)
    (out/'image-plan.txt').write_text(''.join(f"B {r['address']:x} {r['bytes']:x} {r['path']}\n" for r in images if r['bytes']))
    return out

def compile_simulator(run,tools,generated,vpi):
    dest=run.build/'compiled';dest.mkdir()
    rtl=generated/'soft/T09Cpu.v'
    for p in rtl.parent.glob('*.bin'):shutil.copy2(p,dest/p.name)
    ports=re.findall(r'(input|output)\s+wire\s*(\[[^]]+\])?\s*(\w+)\s*[,\n]',rtl.read_text().split(');',1)[0])
    wrapper='`timescale 1ns/1ps\nmodule tb_cpu;\n'
    wrapper+=''.join(f"  {'logic' if d=='input' else 'wire'} {w} {n};\n" for d,w,n in ports)
    wrapper+='T09Cpu cpu(.*);\n'+(ROOT/'tests/runtime/tb_body.svh').read_text()+'\nendmodule\n'
    (dest/'tb_cpu.sv').write_text(wrapper)
    run.execute('vcs-build',[tools['vcs'],'-full64','-sverilog','-timescale=1ns/1ps','-debug_access+all','+acc+3',
        '-cc',tools['vcs_host_cc'],'-cpp',tools['vcs_host_cxx'],'-LDFLAGS','-Wl,--no-as-needed','-load',vpi,
        '-top','tb_cpu',ROOT/'rtl/interfaces/axi4_if.sv',ROOT/'tests/models/sparse_memory_pkg.sv',
        ROOT/'tests/models/axi_sparse_mem.sv',rtl,dest/'tb_cpu.sv','-o',dest/'simv'],300,cwd=dest)
    return dest/'simv'

def case(run,tools,config,name,fw,sim,golden,negative=None):
    dest=run.build/'cocotb'/name;dest.mkdir(parents=True)
    for p in sim.parent.glob('*.bin'):shutil.copy2(p,dest/p.name)
    seed=int(re.search(r'seed(\d+)',name)[1]) if 'seed' in name else 1
    cfg={'task':'T12','case_id':name,'run_id':run.run_id,'profile':fw.name,'seed':seed,
         'python_prefix':sys.prefix,'cocotb_version':config['cocotb_version'],'test_mode':'PRELOAD',
         'max_cycles':2000 if negative=='held-reset' else config['max_cycles'],'max_delay':config['max_delay'],
         'negative':negative,'fixture':str(fw/'fixture.json'),'golden':str(golden),
         'fixture_sha256':sha256(fw/'fixture.json'),'golden_sha256':sha256(golden),
         'image_plan':str(fw/'image-plan.txt'),'simulator_sha256':sha256(sim)}
    write_json(dest/'case.json',cfg)
    try:
        run.execute('case-'+name,[tools['python'],ROOT/'scripts/cocotb_case.py','--case',dest/'case.json','--sim',sim],
                    config['timeouts_seconds']['simulation'],cwd=dest)
    finally:
        shutil.copytree(dest,run.path/'artifacts/cocotb'/name)
    return json.loads((dest/'checks.json').read_text())

def archive(run):
    dest=run.path/'artifacts';dest.mkdir(exist_ok=True)
    for name in ('firmware','fixtures','tokenizer','generated'):
        p=run.build/name
        if p.exists() and not (dest/name).exists():shutil.copytree(p,dest/name)
    for p in run.build.glob('host-*'):
        if p.is_file():shutil.copy2(p,dest/p.name)
    if (run.build/'compiled/tb_cpu.sv').exists():shutil.copy2(run.build/'compiled/tb_cpu.sv',dest/'tb_cpu.sv')
    run.manifest['artifacts']={str(p.relative_to(run.path)):sha256(p) for p in sorted(run.path.rglob('*'))
        if p.is_file() and not(p.parent==run.path and p.name in ('manifest.json','checks.json','commands.json','exit-status.txt'))}

def verify_archive(path):
    from cocotb_case import validate
    from common.runtime_waveform import check_waveform
    path=Path(path).resolve();m=json.loads((path/'manifest.json').read_text())
    if m.get('status')!='PASS' or m.get('exit_code')!=0 or (path/'exit-status.txt').read_text().strip()!='0':raise ValueError('not PASS')
    for file,key in [('commands.json','commands'),('checks.json','checks')]:
        values=json.loads((path/file).read_text());values=values if isinstance(values,list) else values['checks']
        if not values or any(v['status']!='PASS' for v in values):raise ValueError('missing/failed '+key)
    for name,h in m['artifacts'].items():
        p=(path/name).resolve()
        if not p.is_relative_to(path) or not p.is_file() or sha256(p)!=h:raise ValueError('modified artifact '+name)
    source=m['source']
    if content_id(source['files'])!=source['sha256']:raise ValueError('source identity')
    import hashlib
    with tarfile.open(path/'source.tar.gz') as tar:
        if set(tar.getnames())!=set(source['files']):raise ValueError('source inventory')
        for name,h in source['files'].items():
            if hashlib.sha256(tar.extractfile(name).read()).hexdigest()!=h:raise ValueError('source content')
        registered=json.load(tar.extractfile('configs/t12-runtime.json'))
    config=json.loads((path/'config.json').read_text())
    if sha256(path/'config.json')!=m['config_sha256'] or sorted(m['cases'])!=sorted(config['selected_cases']):raise ValueError('required matrix')
    suite=config.get('suite');selected=registered['suites'].get(suite,[])
    if not selected or len(set(selected))!=len(selected) or config['selected_cases']!=selected:
        raise ValueError('registered matrix missing, duplicated or changed')
    expected=dict(registered,suite=suite,selected_cases=selected)
    if config!=expected:raise ValueError('registered configuration changed')
    for name,record in m['cases'].items():
        d=path/'artifacts/cocotb'/name;cfg=json.loads((d/'case.json').read_text())
        if cfg['case_id']!=name or cfg['run_id']!=m['run_id']:raise ValueError('case identity')
        if sha256(path/'artifacts/firmware'/cfg['profile']/'fixture.json')!=cfg['fixture_sha256'] or sha256(path/'artifacts/fixtures/golden.json')!=cfg['golden_sha256']:raise ValueError('fixture identity')
        checks=validate(d,cfg);check_waveform(d)
        if checks['sequence_sha256']!=record['sequence_sha256'] or checks['check_count']!=record['checks'] or checks['result']!=record['result']:raise ValueError('observation identity')
    if config['suite']!='smoke':
        if len(m.get('negative_evidence',[]))!=len(config['negative_cases']):raise ValueError('negative matrix missing')
        for name in m['negative_evidence']:
            p=Path(name);n=json.loads((p/'manifest.json').read_text())
            if n['status']!='FAIL' or n['exit_code']!=1:raise ValueError('negative raw FAIL missing')
            for rel,h in n['artifacts'].items():
                if sha256(p/rel)!=h:raise ValueError('negative artifact identity')
    return {'status':'PASS','cases':len(m['cases']),'negative_cases':len(m.get('negative_evidence',[])),'source_sha256':source['sha256']}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--suite',choices=['smoke','regression','full'],default='regression');p.add_argument('--run-id');p.add_argument('--verify-archive',type=Path)
    a=p.parse_args()
    if a.verify_archive:
        try:print(json.dumps(verify_archive(a.verify_archive),indent=2));return 0
        except Exception as e:print('ARCHIVE_REJECT: '+str(e),file=sys.stderr);return 1
    run=RuntimeEvidence(ROOT,'T12',a.run_id);print('T12 evidence: '+str(run.path),flush=True);code=1
    try:
        files=inputs();run.manifest['source']={'files':files,'sha256':content_id(files)}
        with tarfile.open(run.path/'source.tar.gz','w:gz') as tar:
            for n in files:tar.add(ROOT/n,arcname=n,recursive=False)
        config=json.loads((ROOT/'configs/t12-runtime.json').read_text());config.update(suite=a.suite,selected_cases=config['suites'][a.suite]);write_json(run.path/'config.json',config)
        run.manifest.update(config_sha256=sha256(run.path/'config.json'),invocation=[sys.executable,*sys.argv],test_mode='PRELOAD')
        registry={t['id']:t for t in json.loads((ROOT/'docs/plan/tasks.json').read_text())['tasks']}
        prerequisites={}
        for task in ('T03','T09','T11'):
            record=registry[task];paths=record['evidence'] if isinstance(record['evidence'],list) else [record['evidence']]
            run.check('prerequisite-'+task,record['status']=='DONE' and all(json.loads((ROOT/p).read_text())['status']=='PASS' for p in paths),paths)
            prerequisites[task]={p:sha256(ROOT/p) for p in paths}
        run.manifest['prerequisites']=prerequisites
        tools={k:v['path'] for k,v in json.loads((ROOT/'docs/spec/toolchain-lock.json').read_text())['tools'].items()}
        vpi=environment(run,config,tools)
        fixtures=run.build/'fixtures';tokenizer=run.build/'tokenizer'
        run.execute('tokenizer-export',[tools['python'],ROOT/'model_tools/export_tokenizer.py',tokenizer],180)
        run.execute('independent-fixtures',[tools['python'],ROOT/'tests/runtime/fixtures.py',fixtures],120)
        published=ROOT/'tests/cocotb/fixtures/runtime'
        run.check('tokenizer-reproduction',sha256(tokenizer/'tokenizer.nxt')==sha256(published/'tokenizer/tokenizer.nxt'),
                  'full original-tokenizer compiled tables reproduced byte for byte')
        run.check('fixture-reproduction',all(sha256(p)==sha256(published/'inputs'/p.name) for p in fixtures.iterdir() if p.is_file()),
                  'independent fixed text, model, T11 tile and golden artifacts reproduced byte for byte')
        run.execute('host-tokenizer-build',['gcc','-std=c11','-O2','-shared','-fPIC',ROOT/'firmware/runtime/port/tokenizer.c','-o',run.build/'host-tokenizer.so'],60)
        run.execute('official-tokenizer-differential',[tools['python'],ROOT/'tests/runtime/tokenizer_reference.py',run.build/'host-tokenizer.so',tokenizer/'tokenizer.nxt'],180)
        run.execute('portable-full-model',[tools['python'],ROOT/'software/runtime/run_cpu.py','--verify-full',
            '--library',run.build/'host-full.so','--tokenizer',tokenizer/'tokenizer.nxt','--output',run.build/'host-full-checks.json'],180)
        for profile in ('control','small'):
            binary=run.build/('host-'+profile)
            run.execute('host-build-'+profile,['gcc',*cflags(run,fixtures,profile=='small'),'-D_POSIX_C_SOURCE=200809L','-DHOST_TEST',*sources(),'-lm','-o',binary],120)
            output=run.execute('host-run-'+profile,[binary,tokenizer/'tokenizer.nxt',fixtures/('small.bin' if profile=='small' else 't11-tile.bin')],120)
            run.execute('host-score-'+profile,[tools['python'],ROOT/'tests/runtime/check.py',output,fixtures/'golden.json',profile,'--report',run.build/('host-'+profile+'-checks.json')],60)
        generated=generate(run,tools,['soft'],600)
        fws={profile:build_firmware(run,tools,profile,fixtures,tokenizer) for profile in ('control','small')}
        build_full(run,tools,tokenizer)
        sim=compile_simulator(run,tools,generated,vpi);results={}
        with ThreadPoolExecutor(max_workers=config.get('parallel_simulations',4)) as pool:
            pending={name:pool.submit(case,run,tools,config,name,fws[name.split('-')[0]],sim,fixtures/'golden.json') for name in config['selected_cases']}
            results={name:future.result() for name,future in pending.items()}
        for name,r in results.items():
            if name.endswith('-replay'):
                old=results[name.removesuffix('-replay')]
                run.check('replay-'+name,r['sequence_sha256']==old['sequence_sha256'] and r['result']['cycles']==old['result']['cycles'],'same seed exact CPU record stream and clock count')
        run.manifest['cases']={n:{'sequence_sha256':r['sequence_sha256'],'result':r['result'],'checks':r['check_count']} for n,r in results.items()}
        if a.suite!='smoke':
            def negative(name):
                neg=EvidenceRun(ROOT,'T12_NEGATIVE',run.run_id+'-'+name);neg.manifest.update(expected='FAIL',parent=str(run.path));rc=0
                try:case(neg,tools,config,name,fws['control'],sim,fixtures/'golden.json',name)
                except StepFailure as e:rc=e.exit_code
                finally:archive(neg);neg.finish(rc)
                status=json.loads((neg.build/'cocotb'/name/'case-status.json').read_text())
                reason={'empty':'required testcase identity/count mismatch','missing-xml':'missing/stale results.xml','held-reset':'XML failure/error/skip','bad-golden':'XML failure/error/skip'}[name]
                detected=rc==1 and reason in status.get('reason','')
                if name in ('held-reset','bad-golden'):
                    failure=json.loads((neg.build/'cocotb'/name/'checks.json').read_text())['first_failure']
                    detected &= failure['category']==('completion' if name=='held-reset' else 'tokenizer')
                run.check('negative-'+name,detected,status);return str(neg.path)
            with ThreadPoolExecutor(max_workers=config.get('parallel_simulations',4)) as pool:
                negatives=list(pool.map(negative,config['negative_cases']))
            run.manifest['negative_evidence']=negatives
            run.execute('project-regression',[tools['make'],'test'],300,cwd=ROOT)
        run.check('source-unchanged',inputs()==files,'source/config/checker unchanged throughout qualification')
        code=0
    except StepFailure as e:code=e.exit_code;(run.path/'failure.txt').write_text(str(e)+'\n')
    except KeyboardInterrupt:code=130;(run.path/'failure.txt').write_text('Interrupted\n')
    except Exception:(run.path/'failure.txt').write_text(traceback.format_exc())
    finally:archive(run);code=run.finish(code)
    print(f'T12 {run.manifest["status"]}: {run.path}',flush=True);return code
if __name__=='__main__':sys.exit(main())
