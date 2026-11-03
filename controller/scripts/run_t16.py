#!/usr/bin/env python3
"""Real CPU / native Coral / shared memory end-to-end qualification."""
import argparse,hashlib,json,re,shutil,sys,tarfile,traceback,zipfile,zlib
from pathlib import Path
from coral_rtl import apply_patches, input_paths as coral_patch_inputs
from evidence import EvidenceRun,StepFailure,sha256,content_id,write_json
from run_cocotb import environment,generate
from run_t07 import simulate_batch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tests/soc_accel'),str(ROOT/'tests/cocotb'),str(ROOT/'tests/models')]
from prepare import prepare
from prepare_image import parse_elf
from scoreboard import score
from waveform import check_waveform
from cocotb_case import validate

def inputs():
    names=['Makefile','configs/t16-soc-accel.json','scripts/run_t16.py','scripts/complete_t16.py','scripts/run_t07.py','scripts/run_cocotb.py','scripts/cocotb_case.py','scripts/evidence.py','scripts/probe_tools.py',
        'configs/cocotb-toolchain-lock.json','docs/spec/toolchain-lock.json','docs/spec/memory-map-v1.json','docs/spec/linear-t15-contract.md','docs/spec/linear-t15-support.json',
        'docs/spec/accel-t13-contract.md','docs/spec/soc-accel-t16-contract.md','configs/t05-thresholds.json','third_party/lock.json','software/include/backend_v1.h',
        'tests/models/prepare_image.py','tests/models/sparse_memory_pkg.sv','tests/models/axi_sparse_mem.sv','rtl/interfaces/axi4_if.sv','rtl/soc/nx_shared_memory_arbiter.sv',
        'tests/cocotb/test_soc_accel.py','tests/cocotb/test_empty.py','tests/cocotb/common/checks.py','firmware/cpu/start.S',
        'tests/linear/prepare_linear.py','model_tools/verify_pack.py','docs/spec/model-pack-v1-manifest.json','tests/cocotb/fixtures/golden/manifest.json']
    for directory in ('firmware/drivers/accel','cpu_gen','tests/soc_accel'):
        names += [str(p.relative_to(ROOT)) for p in (ROOT/directory).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc']
    names += [str(p.relative_to(ROOT)) for p in (ROOT/'rtl/soc').glob('nx_accel*.sv')]
    names += coral_patch_inputs()
    return {n:sha256(ROOT/n) for n in sorted(set(names))}

def build(run,config,tools,vpi,extra_sources=(),fpga_sram=None):
    for task,path in config['prerequisites'].items():
        p=ROOT/path;m=json.loads((p/'manifest.json').read_text());run.check('prerequisite-'+task.lower(),m['status']=='PASS' and m['exit_code']==0,path)
        run.manifest.setdefault('prerequisites',{})[task]=dict(path=path,manifest_sha256=sha256(p/'manifest.json'))
    source=ROOT/config['input_t06'];m=json.loads((source/'manifest.json').read_text());zip_path=source/'artifacts'/(config['top']+'.zip')
    run.check('coral-rtl-identity',m['status']=='PASS' and sha256(zip_path)==m['artifacts'][str(zip_path.relative_to(source))],'accepted actual RVV top')
    run.check('coral-sram-source',sha256(source/'coral-source.tar.gz')==m['artifacts']['coral-source.tar.gz'],'DPI SRAM storage only')
    generated=generate(run,tools,['hard'],config['timeouts_seconds']['generate'])
    dest=run.build/'compiled';dest.mkdir();rtl=dest/'rtl';rtl.mkdir()
    shutil.copy2(zip_path,run.path/'coral-rtl.zip');shutil.copy2(source/'coral-source.tar.gz',run.path/'coral-source.tar.gz')
    with zipfile.ZipFile(zip_path) as z:
        if any(Path(n).is_absolute() or '..' in Path(n).parts for n in z.namelist()):raise ValueError('unsafe RTL zip')
        z.extractall(rtl)
    apply_patches(run, rtl)
    if fpga_sram:
        shutil.copy2(fpga_sram,rtl/'Sram.v')
    with tarfile.open(source/'coral-source.tar.gz') as tar:
        for name in ('sram_backdoor.cc','sram_backdoor.h'):(rtl/name).write_bytes(tar.extractfile('hdl/verilog/'+name).read())
    micro=ROOT/config['prerequisites']['T15'];tm=json.loads((micro/'manifest.json').read_text())
    fw=run.build/'firmware';fw.mkdir();elf=micro/'artifacts/firmware/stream.elf'
    run.check('microprogram-identity',sha256(elf)==tm['artifacts']['artifacts/firmware/stream.elf'] and
        sha256(ROOT/'firmware/drivers/accel/linear.c')==tm['source']['files']['firmware/drivers/accel/linear.c'],'byte-identical accepted T15 ELF, no replacement backend')
    shutil.copy2(elf,fw/'coral.elf');entry,segments,_=parse_elf(elf.read_bytes(),base=0,capacity=0x18000);mem=bytearray(0x18000)
    for s in segments:mem[s.address:s.address+len(s.data)]=s.data
    mem[0x16ff0:]=b'\xa5'*(0x18000-0x16ff0)
    image=bytes(mem[:8192]);data=bytes(mem[0x10000:0x18000])
    header='#include <stdint.h>\n#define LINEAR_CRC %du\n'%zlib.crc32(image)
    for name,raw in [('linear_words',image),('linear_data',data)]:header+='static const uint32_t %s[]={%s};\n'%(name,','.join('%du'%w for w in __import__('struct').unpack('<%dI'%(len(raw)//4),raw)))
    (fw/'linear_image.h').write_text(header)
    cpu=generated/'hard/T09Cpu.v'
    for p in cpu.parent.glob('*.bin'):shutil.copy2(p,dest/p.name)
    ports=re.findall(r'(input|output)\s+wire\s*(\[[^]]+\])?\s*(\w+)\s*[,\n]',cpu.read_text().split(');',1)[0])
    wrapper='`timescale 1ns/1ps\nmodule tb_cpu;\n'+''.join("%s %s %s;\n"%('logic' if d=='input' else 'wire',w,n) for d,w,n in ports)
    wrapper+=config.get('cpu_instance','T09Cpu cpu(.*);\n')+(ROOT/config.get('tb_body','tests/soc_accel/tb_body.svh')).read_text()+'\nendmodule\n';(dest/'tb_cpu.sv').write_text(wrapper)
    sources=[ROOT/n for n in ('rtl/interfaces/axi4_if.sv','rtl/soc/nx_shared_memory_arbiter.sv','rtl/soc/nx_accel_map.sv','rtl/soc/nx_accel_guard.sv','rtl/soc/nx_accel_bridge.sv','tests/models/sparse_memory_pkg.sv','tests/models/axi_sparse_mem.sv')]
    sources += [ROOT/n for n in extra_sources]
    run.execute('vcs-build',[tools['vcs'],'-j32',*(['-fgp'] if config.get('fgp_compile') else []),'-full64','-sverilog','-timescale=1ns/1ps','+vpi','-P',ROOT/'tests/soc_accel/pli.tab','-cc',tools['vcs_host_cc'],'-cpp',tools['vcs_host_cxx'],
        '-CFLAGS','-std=c++17','-LDFLAGS','-Wl,--no-as-needed','-load',vpi,'+define+VCS',f'+define+CORAL_TOP={config["top"]}','-top','tb_cpu','-f','filelist.f',*sources,cpu,dest/'tb_cpu.sv',rtl/'sram_backdoor.cc','-o',dest/'simv'],config['timeouts_seconds']['compile'],cwd=rtl)
    run.manifest.update(coral_rtl_sha256=sha256(zip_path),coral_program_sha256=sha256(elf),cpu_rtl_sha256=sha256(cpu))
    return fw,dest/'simv'

def firmware(run,config,tools,profile,fw):
    out=run.build/'images'/profile;prepare(out,config,profile)
    src=ROOT/'firmware/drivers/accel';elf=out/'firmware.elf'
    flags=['-march=rv32imf_zicsr_zifencei','-mabi=ilp32f','-DHARD_FLOAT','-O2','-g','-ffp-contract=off','-fno-fast-math','-ffreestanding','-fno-builtin','-fno-pic','-fno-strict-aliasing',
           '-nostdlib','-nostartfiles','-msmall-data-limit=0','-Wall','-Wextra','-Werror','-Wl,--build-id=none',f'-ffile-prefix-map={ROOT}=.']
    run.execute('firmware-'+profile,[tools['rv32_gcc'],*flags,'-I',src,'-I',ROOT/'software/include','-I',fw,'-I',out,'-T',ROOT/'tests/soc_accel/link.ld',f'-Wl,-Map={out}/firmware.map',ROOT/'firmware/cpu/start.S',ROOT/'tests/soc_accel/firmware.c',src/'accel.c',src/'target.c',src/'linear_api.c',src/'coral_linear.c','-lc','-lgcc','-o',elf],60)
    log=run.execute('disassemble-'+profile,[tools['rv32_objdump'],'-d',elf],30);shutil.copy2(log,out/'firmware.dis')
    entry,segs,flags=parse_elf(elf.read_bytes(),base=0x10000,capacity=0xb8000000-0x10000)
    run.check('elf-'+profile,entry==0x10000 and flags==2 and all(0x10000<=s.address<s.address+s.memory_size<=0x20000 or 0xb4000000<=s.address<s.address+s.memory_size<=0xb4100000 for s in segs),'actual T09 FPU / ILP32F; ROM entry and CPU-private code')
    fixture=json.loads((out/'fixture.json').read_text());plan=(out/'data.plan').read_text()
    for i,s in enumerate(segs):
        p=out/f'cpu-segment-{i}.bin';p.write_bytes(s.data);fixture['regions'].append(dict(name=p.stem,address=s.address,bytes=len(s.data),path=str(p.resolve()),sha256=sha256(p),kind='firmware'))
        if s.data:plan+=f'B {s.address:x} {len(s.data):x} {p.resolve()}\n'
    fixture.update(elf_sha256=sha256(elf),coral_program_sha256=sha256(fw/'coral.elf'));write_json(out/'fixture.json',fixture);(out/'load.plan').write_text(plan)
    return out

def case(run,tools,config,name,images,sim,negative=None,launch=True):
    params=config['cases'].get(name,config['cases']['smoke-seed1']);dest=run.build/'cocotb'/name;dest.mkdir(parents=True)
    for p in sim.parent.glob('*.bin'):shutil.copy2(p,dest/p.name)
    cfg=dict(task='T16',case_id=name,run_id=run.run_id,**params,python_prefix=sys.prefix,cocotb_version=config['cocotb_version'],test_mode='PRELOAD',negative=negative,
        max_cycles=2000 if negative=='held-reset' else config['head_max_cycles'] if params['profile']=='head' else config['max_cycles'],
        fixture=str(images/'fixture.json'),golden=str(images/'golden.json'),image_plan=str(images/'load.plan'),fixture_sha256=sha256(images/'fixture.json'),golden_sha256=sha256(images/'golden.json'),simulator_sha256=sha256(sim),
        effective_seeds={'vcs':params['seed'],'cocotb':params['seed'],'cpu_i':params['seed']^0x49,'cpu_d':params['seed']^0x44,'backend':params['seed']^0x4e})
    write_json(dest/'case.json',cfg)
    if not launch:
        return dict(name='case-'+name,case=dest,argv=[tools['python'],ROOT/'scripts/cocotb_case.py','--case',dest/'case.json','--sim',sim],cost=151936 if params['profile']=='head' else 1)
    try:run.execute('case-'+name,[tools['python'],ROOT/'scripts/cocotb_case.py','--case',dest/'case.json','--sim',sim],config['timeouts_seconds']['simulation'],cwd=dest)
    finally:shutil.copytree(dest,run.path/'artifacts/cocotb'/name)
    return json.loads((dest/'checks.json').read_text())

def archive(run):
    dest=run.path/'artifacts';dest.mkdir(exist_ok=True)
    for name in ('firmware','images','generated','cocotb'):
        if (run.build/name).exists():shutil.copytree(run.build/name,dest/name,dirs_exist_ok=True)
    if (run.build/'compiled/tb_cpu.sv').exists():shutil.copy2(run.build/'compiled/tb_cpu.sv',dest/'tb_cpu.sv')
    if (run.build/'tool-report.json').exists():shutil.copy2(run.build/'tool-report.json',dest/'tool-report.json')
    run.manifest['artifacts']={str(p.relative_to(run.path)):sha256(p) for p in sorted(run.path.rglob('*')) if p.is_file() and not (p.parent==run.path and p.name in ('manifest.json','checks.json','commands.json','exit-status.txt'))}

# A post-processing correction can revalidate immutable captures. This list
# deliberately excludes RTL, firmware, fixture generation, cocotb and numeric
# scoring: a change to any execution or numerical input requires a fresh run.
RECHECK_ONLY={'scripts/run_t16.py','scripts/complete_t16.py','tests/soc_accel/waveform.py',
              'tests/soc_accel/test_waveform.py','tests/soc_accel/test_archive.py'}
RAW_CASE_FILES=('case.json','checks.json','observations.json','cpu.vcd','transactions.csv',
                'results.xml','simulation.log','cpu-output.txt')

def capture_changes(original,current):
    changed=sorted(n for n in set(original)|set(current) if original.get(n)!=current.get(n))
    if set(changed)-RECHECK_ONLY:raise ValueError('capture execution or numerical source changed')
    return changed

def verify_capture(path,current):
    path=Path(path).resolve();m=json.loads((path/'manifest.json').read_text())
    if m.get('task_id')!='T16' or not m.get('finished_at') or m['status'] not in ('PASS','FAIL'):
        raise ValueError('capture must be a finished T16 run')
    if int((path/'exit-status.txt').read_text())!=m['exit_code']:raise ValueError('capture exit identity')
    for name,h in m['artifacts'].items():
        p=(path/name).resolve()
        if not p.is_relative_to(path) or not p.is_file() or sha256(p)!=h:raise ValueError('capture artifact changed: '+name)
    old=m['source']['files']
    if content_id(old)!=m['source']['sha256']:raise ValueError('capture source digest')
    with tarfile.open(path/'source.tar.gz') as tar:
        if set(tar.getnames())!=set(old):raise ValueError('capture source inventory')
        for name,h in old.items():
            if hashlib.sha256(tar.extractfile(name).read()).hexdigest()!=h:raise ValueError('capture source content')
        registered=json.load(tar.extractfile('configs/t16-soc-accel.json'))
    config=json.loads((path/'config.json').read_text());selected=registered['suites']['full']
    if config!={**registered,'suite':'full','selected_cases':selected}:raise ValueError('capture full matrix')
    failed=[s for s in json.loads((path/'commands.json').read_text()) if s['status']!='PASS']
    if m['status']=='FAIL':
        d=path/'artifacts/cocotb/head-seed1';status=json.loads((d/'case-status.json').read_text())
        if len(failed)!=1 or failed[0]['name']!='case-head-seed1' or status.get('simulator_exit')!=0 or status.get('reason')!='VCD/AXI window correlation 0/0':
            raise ValueError('capture failure was not the empty backend waveform window')
    for name in selected:
        d=path/'artifacts/cocotb'/name;cfg=json.loads((d/'case.json').read_text());validate(d,cfg)
        if cfg['run_id']!=m['run_id'] or cfg['negative'] is not None or any(cfg[k]!=v for k,v in config['cases'][name].items()):raise ValueError('capture case identity')
        for f in RAW_CASE_FILES:
            if str((d/f).relative_to(path)) not in m['artifacts']:raise ValueError('capture missing raw artifact')
    return dict(path=str(path),manifest_sha256=sha256(path/'manifest.json'),run_id=m['run_id'],
                original_status=m['status'],source_sha256=m['source']['sha256'],allowed_changes=capture_changes(old,current))

def recheck_case(directory):
    d=Path(directory).resolve();cfg=json.loads((d/'case.json').read_text());r=validate(d,cfg)
    waveform=check_waveform(d)
    got,_=score(d,json.loads(Path(cfg['fixture']).read_text()),json.loads(Path(cfg['golden']).read_text()),Path(cfg['fixture']).parent)
    if any(r['result'].get(k)!=v for k,v in got.items()):raise ValueError('independent capture score aggregation')
    record=dict(status='PASS',capture_run_id=cfg['run_id'],raw_files={n:sha256(d/n) for n in RAW_CASE_FILES},
                waveform=waveform,numeric_checks=r['check_count'],waveform_checker_sha256=sha256(ROOT/'tests/soc_accel/waveform.py'))
    write_json(d/'revalidation.json',record);print(json.dumps(record,indent=2));return record

def import_capture(run,config,tools,path):
    capture=verify_capture(path,run.manifest['source']['files']);path=Path(capture['path']);old=json.loads((path/'manifest.json').read_text())
    run.manifest.update(capture=capture,**{k:old[k] for k in ('prerequisites','cpu_rtl_sha256','coral_rtl_sha256','coral_program_sha256')})
    write_json(run.path/'raw-capture.json',capture);run.check('immutable-capture',True,capture)
    for name in ('firmware','images','generated','cocotb'):shutil.copytree(path/'artifacts'/name,run.build/name)
    for name in ('coral-rtl.zip','coral-source.tar.gz','vexriscv-source.tar'):shutil.copy2(path/name,run.path/name)
    compiled=run.build/'compiled';compiled.mkdir();shutil.copy2(path/'artifacts/tb_cpu.sv',compiled/'tb_cpu.sv')
    sim=ROOT/'build/T16'/capture['run_id']/'compiled/simv'
    run.check('captured-simulator',sim.is_file() and all(sha256(sim)==json.loads((run.build/'cocotb'/name/'case.json').read_text())['simulator_sha256'] for name in config['selected_cases']),'unchanged actual CPU/Coral simulator')
    jobs=[dict(name='recheck-'+name,case=run.build/'cocotb'/name,
        argv=[tools['python'],ROOT/'scripts/run_t16.py','--recheck-case',run.build/'cocotb'/name],
        cost=151936 if config['cases'][name]['profile']=='head' else 1) for name in config['selected_cases']]
    simulate_batch(run,jobs,600,config['simulation_workers'])
    return sim,{p.name:p for p in (run.build/'images').iterdir() if p.is_dir()}

def verify_archive(path):
    path=Path(path).resolve();m=json.loads((path/'manifest.json').read_text())
    if m.get('status')!='PASS' or m.get('exit_code')!=0 or (path/'exit-status.txt').read_text().strip()!='0':raise ValueError('not a completed PASS')
    for name,h in m['artifacts'].items():
        p=(path/name).resolve()
        if not p.is_relative_to(path) or not p.is_file() or sha256(p)!=h:raise ValueError('artifact changed: '+name)
    if not m['artifacts'] or sha256(path/'config.json')!=m['config']['sha256']:raise ValueError('config identity')
    for name,key in [('commands.json',None),('checks.json','checks')]:
        rows=json.loads((path/name).read_text());rows=rows[key] if key else rows
        if not rows or any(r['status']!='PASS' for r in rows):raise ValueError('failed root results')
    files=m['source']['files']
    if content_id(files)!=m['source']['sha256']:raise ValueError('source digest')
    with tarfile.open(path/'source.tar.gz') as tar:
        if set(tar.getnames())!=set(files):raise ValueError('source inventory')
        for n,h in files.items():
            if hashlib.sha256(tar.extractfile(n).read()).hexdigest()!=h:raise ValueError('source content '+n)
        registered=json.load(tar.extractfile('configs/t16-soc-accel.json'))
    config=json.loads((path/'config.json').read_text());suite=config['suite']
    if config!={**registered,'suite':suite,'selected_cases':registered['suites'][suite]} or set(m['cases'])!=set(config['selected_cases']):raise ValueError('registered case matrix')
    capture=m.get('capture')
    if capture and verify_capture(capture['path'],files)!=capture:raise ValueError('capture provenance changed')
    checks=0;outputs=0
    for name in config['selected_cases']:
        d=path/'artifacts/cocotb'/name;cfg=json.loads((d/'case.json').read_text());r=validate(d,cfg)
        runtime_run_id=capture['run_id'] if capture else m['run_id']
        if any(cfg[k]!=v for k,v in config['cases'][name].items()) or cfg['task']!='T16' or cfg['run_id']!=runtime_run_id or cfg['negative'] is not None:raise ValueError('case identity')
        if capture:
            original=Path(capture['path'])/'artifacts/cocotb'/name;rec=json.loads((d/'revalidation.json').read_text())
            if rec['status']!='PASS' or rec['waveform_checker_sha256']!=files['tests/soc_accel/waveform.py'] or any(sha256(d/f)!=sha256(original/f) or rec['raw_files'][f]!=sha256(d/f) for f in RAW_CASE_FILES):raise ValueError('raw capture changed')
        folder=path/'artifacts/images'/cfg['profile']
        for key in ('fixture','golden'):
            if sha256(folder/(key+'.json'))!=cfg[key+'_sha256']:raise ValueError('fixture identity')
        if sha256(d/'transactions.csv')!=r['sequence_sha256'] or r['sequence_sha256']!=m['cases'][name]['sequence_sha256']:raise ValueError('trace identity')
        check_waveform(d);got,_=score(d,json.loads((folder/'fixture.json').read_text()),json.loads((folder/'golden.json').read_text()),folder)
        if any(r['result'].get(k)!=v for k,v in got.items()):raise ValueError('independent score aggregation')
        checks+=r['check_count'];outputs+=got['output_elements']
    if suite!='smoke':
        if set(m.get('negatives',{}))!=set(config['negative_cases']):raise ValueError('negative matrix')
        for name,rec in m['negatives'].items():
            nd=Path(rec['path']);nm=json.loads((nd/'manifest.json').read_text())
            if nm['status']!='FAIL' or nm['exit_code']!=1 or nm.get('negative')!=name:raise ValueError('negative raw FAIL')
            for rel,h in nm['artifacts'].items():
                if sha256(nd/rel)!=h:raise ValueError('negative artifact')
        if m['cases']['control-seed1']['sequence_sha256']!=m['cases']['control-seed1-replay']['sequence_sha256']:raise ValueError('deterministic trace')
    if suite=='full' and m['cases']['head-seed1']['result']['full_head_rows']!=151936:raise ValueError('continuous full head missing')
    return dict(status='PASS',suite=suite,cases=len(m['cases']),independent_checks=checks,output_elements=outputs,source_sha256=m['source']['sha256'])

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--suite',choices=['smoke','regression','full'],default='full');p.add_argument('--run-id');p.add_argument('--verify-archive',type=Path);p.add_argument('--recheck',type=Path);p.add_argument('--recheck-case',type=Path);a=p.parse_args()
    if a.recheck_case:
        try:recheck_case(a.recheck_case);return 0
        except Exception:traceback.print_exc();return 1
    if a.verify_archive:
        try:print(json.dumps(verify_archive(a.verify_archive),indent=2));return 0
        except Exception as e:print('ARCHIVE_REJECT: '+str(e),file=sys.stderr);return 1
    run=EvidenceRun(ROOT,'T16',a.run_id);print('T16 evidence: '+str(run.path),flush=True);code=1
    try:
        files=inputs();run.manifest['source']=dict(files=files,sha256=content_id(files))
        with tarfile.open(run.path/'source.tar.gz','w:gz') as tar:
            for name in files:tar.add(ROOT/name,arcname=name,recursive=False)
        config=json.loads((ROOT/'configs/t16-soc-accel.json').read_text());config.update(suite=a.suite,selected_cases=config['suites'][a.suite]);write_json(run.path/'config.json',config)
        run.manifest.update(config={'sha256':sha256(run.path/'config.json')},qualification=config['scope'],invocation=[sys.executable,*sys.argv])
        tools={k:v['path'] for k,v in json.loads((ROOT/'docs/spec/toolchain-lock.json').read_text())['tools'].items()}
        vpi=environment(run,config,tools);results={}
        if a.recheck:
            if a.suite!='full':raise ValueError('capture recheck requires the full suite')
            sim,images=import_capture(run,config,tools,a.recheck)
        else:
            fw,sim=build(run,config,tools,vpi);images={}
            for profile in list(dict.fromkeys(config['cases'][n]['profile'] for n in config['selected_cases']))+(['smoke'] if a.suite!='smoke' else []):
                if profile not in images:images[profile]=firmware(run,config,tools,profile,fw)
            jobs=[case(run,tools,config,n,images[config['cases'][n]['profile']],sim,launch=False) for n in config['selected_cases']]
            simulate_batch(run,jobs,config['timeouts_seconds']['simulation'],config['simulation_workers'])
        for name in config['selected_cases']:
            r=json.loads((run.build/'cocotb'/name/'checks.json').read_text());results[name]=r
            run.manifest.setdefault('cases',{})[name]=dict(status=r['status'],checks=r['check_count'],sequence_sha256=r['sequence_sha256'],result=r['result']);run.flush()
            if name.endswith('-replay'):run.check('replay',r['sequence_sha256']==results[name.removesuffix('-replay')]['sequence_sha256'],'complete CPU/native/backend events and response payloads')
        if a.suite!='smoke':
            for name in config['negative_cases']:
                neg=EvidenceRun(ROOT,'T16_NEGATIVE',run.run_id+'-'+name);neg.manifest.update(parent=str(run.path),negative=name,expected='FAIL');rc=0
                try:case(neg,tools,config,name,images['smoke'],sim,name)
                except StepFailure as e:rc=e.exit_code
                finally:archive(neg);neg.finish(rc)
                d=neg.build/'cocotb'/name;status=json.loads((d/'case-status.json').read_text());needle={'empty':'required testcase identity/count mismatch','missing-xml':'missing/stale results.xml'}.get(name,'XML failure/error/skip')
                detected=rc==1 and needle in status.get('reason','')
                if name in ('held-reset','bad-golden','stale-data'):
                    failure=json.loads((d/'checks.json').read_text())['first_failure'];detected&=failure['category']=={'held-reset':'completion','bad-golden':'data','stale-data':'completion'}[name]
                run.check('negative-'+name,detected,status);run.manifest.setdefault('negatives',{})[name]=dict(path=str(neg.path),reason=status.get('reason'))
            run.execute('project-tests',[tools['make'],'test'],300,cwd=ROOT)
        run.check('source-unchanged',inputs()==files,'all acceptance inputs stable');code=0
    except StepFailure as e:code=e.exit_code;(run.path/'failure.txt').write_text(str(e)+'\n')
    except KeyboardInterrupt:code=130
    except Exception:(run.path/'failure.txt').write_text(traceback.format_exc())
    finally:archive(run);code=run.finish(code)
    print('T16 '+run.manifest['status']+': '+str(run.path),flush=True);return code
if __name__=='__main__':sys.exit(main())
