#!/usr/bin/env python3
"""Build, execute and re-score immutable real CPU/SPI SD boot evidence."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import tarfile
import traceback
from evidence import EvidenceRun,StepFailure,sha256,content_id,write_json
from run_cocotb import environment,generate
from run_t17 import UartEvidence,archive
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tests/boot/sd'),str(ROOT/'tests/models'),str(ROOT/'software/boot'),str(ROOT/'model_tools')]
from prepare import prepare,trust_header,PROFILES
from prepare_image import parse_elf
from sd_image import build as build_card
from verify_pack import verify
from importlib.util import spec_from_file_location,module_from_spec
_wave_spec=spec_from_file_location('t18_sd_waveform',ROOT/'tests/boot/sd/waveform.py')
_wave_module=module_from_spec(_wave_spec);_wave_spec.loader.exec_module(_wave_module)
check_waveform=_wave_module.check_waveform

def inputs():
    names=['Makefile','scripts/run_t18.py','scripts/complete_t18.py','scripts/check_t18_archive_controls.py','scripts/run_t17.py','scripts/run_cocotb.py','scripts/cocotb_case.py','scripts/evidence.py','scripts/probe_tools.py',
      'configs/t18-sd-boot.json','configs/cocotb-toolchain-lock.json','docs/spec/toolchain-lock.json','docs/spec/python-requirements.lock.txt',
      'docs/spec/memory-map-v1.json','docs/spec/model-pack-v1-manifest.json','docs/spec/sd-boot-v1.md','third_party/lock.json',
      'third_party/coralnpu/hdl/chisel/src/bus/SpiMaster.scala','rtl/interfaces/axi4_if.sv','rtl/soc/t03_uart_tx.sv',
      'rtl/soc/t17_uart.sv','rtl/soc/t17_uart_router.sv','rtl/soc/t18_spi.sv','tests/models/axi_sparse_mem.sv',
      'tests/models/sparse_memory_pkg.sv','tests/models/prepare_image.py','tests/boot/uart/application.S','tests/boot/uart/app.ld',
      'firmware/runtime/port/runtime.c','firmware/runtime/port/runtime.h','firmware/runtime/port/tokenizer.h','model_tools/verify_pack.py']
    for folder in ('cpu_gen','firmware/boot/sd_loader','tests/boot/sd','software/boot','tests/cocotb'):
        names += [str(p.relative_to(ROOT)) for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc']
    return {n:sha256(ROOT/n) for n in sorted(set(names))}

def build_firmware(run,tools):
    out=run.build/'firmware';out.mkdir();folder=ROOT/'firmware/boot/sd_loader'
    flags=['-march=rv32im_zicsr_zifencei','-mabi=ilp32','-O2','-g','-ffreestanding','-fno-builtin','-fno-pic','-fno-strict-aliasing',
      '-nostdlib','-nostartfiles','-msmall-data-limit=0','-ffunction-sections','-fdata-sections','-Wl,--gc-sections','-Wall','-Wextra','-Werror',
      '-Wl,--build-id=none',f'-ffile-prefix-map={ROOT}=.']
    apps={}
    for name,signature in dict(A=0xa1700001,B=0xb1700002).items():
        elf=out/('app-'+name+'.elf');binary=out/('app-'+name+'.bin')
        run.execute('firmware-app-'+name.lower(),[tools['rv32_gcc'],*flags,f'-DAPP_SIGNATURE={signature}',f'-DAPP_MESSAGE="APP {name} PASS\\n"',
          '-T',ROOT/'tests/boot/uart/app.ld',ROOT/'tests/boot/uart/application.S','-o',elf],60)
        _,segments,abi=parse_elf(elf.read_bytes(),base=0xb4000000,capacity=65536)
        run.check('application-'+name,abi==0 and len(segments)==1,'real RV32 machine code application');binary.write_bytes(segments[0].data);apps[name]=binary
    trust_header(apps,out/'trusted.h')
    elf=out/'boot.elf';run.execute('firmware-boot',[tools['rv32_gcc'],*flags,'-I',out,'-I',ROOT/'firmware/runtime/port',
      f'-Wl,-Map={out}/boot.map','-T',folder/'link.ld',folder/'start.S',folder/'main.c',folder/'sha256.c',ROOT/'firmware/runtime/port/runtime.c','-lgcc','-o',elf],60)
    _,segments,abi=parse_elf(elf.read_bytes(),base=0x10000,capacity=0x20000);rom=[s for s in segments if s.data]
    run.check('boot-rom',abi==0 and len(rom)==1 and rom[0].address==0x10000 and len(rom[0].data)<65536,'ROM only; SRAM BSS cleared by CPU')
    (out/'boot.bin').write_bytes(rom[0].data)
    log=run.execute('disassemble-boot',[tools['rv32_objdump'],'-d',elf],30);shutil.copy2(log,out/'boot.dis')
    run.check('visibility-code','fence.i' in log.read_text(),'instruction invalidation before DDR application entry')
    from elftools.elf.elffile import ELFFile
    with elf.open('rb') as f:
        parsed=ELFFile(f);bss=parsed.get_section_by_name('.bss')['sh_size'];scratch=parsed.get_section_by_name('.sd_scratch')['sh_size']
    write_json(out/'memory-budget.json',dict(rom_bytes=len(rom[0].data),sram_bss_bytes=bss,stack_reserved_bytes=32768,
      directory_limit_bytes=4096*256,full_directory_bytes=467*256,model_extra_copy_bytes=0,sector_buffer_bytes=512,cacheable_scratch_bytes=scratch,cacheable_scratch_limit_bytes=4096,cacheable_scratch_address='0xb7ff0000'))
    return out,apps

def compile_simulator(run,tools,generated,vpi):
    out=run.build/'compiled';out.mkdir();rtl=generated/'soft/T09Cpu.v'
    for p in rtl.parent.glob('*.bin'):shutil.copy2(p,out/p.name)
    ports=re.findall(r'(input|output)\s+wire\s*(\[[^]]+\])?\s*(\w+)\s*[,\n]',rtl.read_text().split(');',1)[0])
    wrapper='`timescale 1ns/1ps\nmodule tb_cpu;\n'+''.join(f"  {'logic' if d=='input' else 'wire'} {w} {n};\n" for d,w,n in ports)
    wrapper+='T09Cpu cpu(.*);\n'+(ROOT/'tests/boot/sd/tb_body.svh').read_text()+'\nendmodule\n';(out/'tb_cpu.sv').write_text(wrapper)
    run.execute('vcs-build',[tools['vcs'],'-full64','-sverilog','-timescale=1ns/1ps','-debug_access+all','+acc+3','-cc',tools['vcs_host_cc'],
      '-cpp',tools['vcs_host_cxx'],'-LDFLAGS','-Wl,--no-as-needed','-load',vpi,'-top','tb_cpu',
      *[ROOT/p for p in ('rtl/interfaces/axi4_if.sv','tests/models/sparse_memory_pkg.sv','tests/models/axi_sparse_mem.sv',
         'rtl/soc/t03_uart_tx.sv','rtl/soc/t17_uart.sv','rtl/soc/t17_uart_router.sv','rtl/soc/t18_spi.sv')],rtl,out/'tb_cpu.sv','-o',out/'simv'],300,cwd=out)
    return out/'simv'

def case(run,tools,config,name,profile,seed,fw,fixture,sim,negative=None):
    dest=run.build/'cocotb'/name;dest.mkdir(parents=True)
    for p in sim.parent.glob('*.bin'):shutil.copy2(p,dest/p.name)
    cfg=dict(task='T18',case_id=name,run_id=run.run_id,profile=profile,seed=seed,negative=negative,
      effective_seeds=dict(python=seed,cocotb=seed,vcs=seed,i_memory=seed^0x49,d_memory=seed^0x44,sd=seed^0x53),
      python_prefix=sys.prefix,cocotb_version=config['cocotb_version'],max_cycles=10000 if negative=='held-reset' else config['max_cycles'],
      max_delay=config['max_delay'],test_mode='PROTOCOL_BOOT',boot=str(fw/'boot.bin'),boot_bytes=(fw/'boot.bin').stat().st_size,
      boot_sha256=sha256(fw/'boot.bin'),fixture=str(fixture/'fixture.json'),golden=str(fixture/'golden.json'),
      fixture_sha256=sha256(fixture/'fixture.json'),golden_sha256=sha256(fixture/'golden.json'),simulator_sha256=sha256(sim))
    write_json(dest/'case.json',cfg)
    try:run.execute('case-'+name,[tools['python'],ROOT/'scripts/cocotb_case.py','--case',dest/'case.json','--sim',sim],config['timeouts_seconds']['simulation'],cwd=dest)
    finally:shutil.copytree(dest,run.path/'artifacts/cocotb'/name)
    return json.loads((dest/'checks.json').read_text())

def negative_case(parent,tools,config,name,fw,fixture,sim):
    run=EvidenceRun(ROOT,'T18_NEGATIVE',parent.run_id+'-'+name);run.manifest.update(parent=str(parent.path),expected='FAIL',negative=name,source=parent.manifest['source']);code=1
    try:case(run,tools,config,name,'smoke',1,fw,fixture,sim,name)
    except StepFailure as e:code=e.exit_code
    finally:archive(run);code=run.finish(code)
    status=json.loads((run.build/'cocotb'/name/'case-status.json').read_text())
    report=json.loads((run.build/'cocotb'/name/'checks.json').read_text()) if (run.build/'cocotb'/name/'checks.json').exists() else {}
    if name in ('held-reset','bad-golden'):detected=report.get('status')=='FAIL' and (report.get('first_failure') or {}).get('category')==('completion' if name=='held-reset' else 'selftest')
    else:detected=('required testcase identity/count mismatch' if name=='empty' else 'missing/stale results.xml') in status['reason']
    parent.check('negative-'+name,code==1 and status['status']=='FAIL' and detected,dict(evidence=str(run.path),reason=status.get('reason')));return str(run.path)

def verify_archive(path):
    from cocotb_case import validate
    from scoreboard import revalidate
    path=Path(path).resolve();m=json.loads((path/'manifest.json').read_text())
    if m.get('status')!='PASS' or m.get('exit_code')!=0 or (path/'exit-status.txt').read_text().strip()!='0':raise ValueError('archive not completed PASS')
    for name in ('commands.json','checks.json'):
        data=json.loads((path/name).read_text());rows=data if isinstance(data,list) else data['checks']
        if not rows or any(r['status']!='PASS' for r in rows):raise ValueError('root command/check failure')
    for name,h in m['artifacts'].items():
        p=(path/name).resolve()
        if not p.is_relative_to(path) or not p.is_file() or sha256(p)!=h:raise ValueError('modified/missing artifact '+name)
    source=m['source'];required={'scripts/run_t18.py','tests/cocotb/test_sd_boot.py','tests/boot/sd/scoreboard.py','tests/boot/sd/card.py','firmware/boot/sd_loader/main.c','firmware/boot/sd_loader/sha256.c','rtl/soc/t18_spi.sv','cpu_gen/src/main/scala/nexusrv/GenT09.scala'}
    if not required.issubset(source['files']) or content_id(source['files'])!=source['sha256']:raise ValueError('source identity/inventory')
    with tarfile.open(path/'source.tar.gz') as tar:
        if set(tar.getnames())!=set(source['files']):raise ValueError('source archive inventory')
        for n,h in source['files'].items():
            if hashlib.sha256(tar.extractfile(n).read()).hexdigest()!=h:raise ValueError('source content '+n)
        registered=json.load(tar.extractfile('configs/t18-sd-boot.json'))
    cfg=json.loads((path/'config.json').read_text());suite=cfg['suite'];selected=registered['suites'][suite]
    if cfg!=dict(registered,suite=suite,selected_cases=selected) or sha256(path/'config.json')!=m['config_sha256']:raise ValueError('changed registered config')
    if set(m['cases'])!=set(selected) or len(selected)!=len(set(selected)):raise ValueError('required case matrix')
    count=0;consumed=set()
    for name,record in m['cases'].items():
        d=path/'artifacts/cocotb'/name;case_cfg=json.loads((d/'case.json').read_text());profile=name.split('-')[0];seed=int(re.search(r'seed(\d+)',name)[1]);fx=path/'artifacts/fixtures'/profile
        if case_cfg['case_id']!=name or case_cfg['run_id']!=m['run_id'] or case_cfg['negative'] is not None or case_cfg['profile']!=profile or case_cfg['seed']!=seed or case_cfg['test_mode']!='PROTOCOL_BOOT':raise ValueError('case identity')
        for key in ('max_cycles','max_delay'):
            if case_cfg[key]!=registered[key]:raise ValueError('changed case '+key)
        if sha256(path/'artifacts/firmware/boot.bin')!=case_cfg['boot_sha256']:raise ValueError('boot identity')
        for key in ('fixture','golden'):
            if sha256(fx/(key+'.json'))!=case_cfg[key+'_sha256']:raise ValueError('input identity')
        fixture=json.loads((fx/'fixture.json').read_text());golden=json.loads((fx/'golden.json').read_text())
        for action in fixture['actions']:
            stored=fx/Path(action['image']).name
            if sha256(stored)!=action['image_sha256']:raise ValueError('card image identity')
            action['image']=str(stored)
        report=validate(d,case_cfg);check_waveform(d);summary=revalidate(d,fixture,golden,case_cfg)
        if report['sequence_sha256']!=record['sequence_sha256'] or report['check_count']!=record['checks']:raise ValueError('case record')
        count+=report['check_count'];consumed.update(summary['t10_cases'])
    if suite!='smoke':
        if len(m.get('negative_evidence',[]))!=len(registered['negative_cases']):raise ValueError('negative coverage')
        for n,pathstr in zip(registered['negative_cases'],m['negative_evidence']):
            d=Path(pathstr);nm=json.loads((d/'manifest.json').read_text())
            if nm['negative']!=n or nm['status']!='FAIL' or nm['exit_code']!=1:raise ValueError('raw negative FAIL missing')
            for f,h in nm['artifacts'].items():
                if sha256(d/f)!=h:raise ValueError('changed negative artifact')
        if m['cases']['control-seed1']['sequence_sha256']!=m['cases']['control-seed1-replay']['sequence_sha256']:raise ValueError('deterministic replay')
        expected={x[0] for p in PROFILES.values() for x in p}
        if consumed!=expected:raise ValueError('T10 consumption matrix')
        if json.loads((path/'full-file-check.json').read_text()).get('status')!='PASS':raise ValueError('full file coverage')
    return dict(status='PASS',cases=len(selected),independent_checks=count,t10_cases=len(consumed),negative_cases=len(m.get('negative_evidence',[])),source_sha256=source['sha256'])

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--suite',choices=['smoke','regression','full'],default='full');p.add_argument('--run-id');p.add_argument('--verify-archive',type=Path);args=p.parse_args()
    if args.verify_archive:
        try:print(json.dumps(verify_archive(args.verify_archive),indent=2));return 0
        except Exception as e:print('ARCHIVE_REJECT: '+str(e),file=sys.stderr);return 1
    run=UartEvidence(ROOT,'T18',args.run_id);print('T18 evidence: '+str(run.path),flush=True);code=1
    try:
        files=inputs();run.manifest['source']=dict(files=files,sha256=content_id(files),snapshot='source.tar.gz')
        with tarfile.open(run.path/'source.tar.gz','w:gz') as tar:
            for n in files:tar.add(ROOT/n,arcname=n,recursive=False)
        config=json.loads((ROOT/'configs/t18-sd-boot.json').read_text());selected=config['suites'][args.suite];config.update(suite=args.suite,selected_cases=selected);write_json(run.path/'config.json',config)
        run.manifest.update(config_sha256=sha256(run.path/'config.json'),invocation=[sys.executable,*sys.argv],qualification=dict(protocol_boot='REAL_SPI_PINS',cpu='REAL_T09_CACHE_ENABLED',full_model='FILE_LEVEL_ONLY',board='NOT_TESTED_NOT_REQUIRED'))
        tools={k:v['path'] for k,v in json.loads((ROOT/'docs/spec/toolchain-lock.json').read_text())['tools'].items()}
        vpi=environment(run,config,tools);generated=generate(run,tools,['soft'],config['timeouts_seconds']['generate']);fw,apps=build_firmware(run,tools)
        sim=compile_simulator(run,tools,generated,vpi)
        router=run.build/'router-test';router.mkdir()
        run.execute('router-build',[tools['vcs'],'-full64','-sverilog','-timescale=1ns/1ps','-cc',tools['vcs_host_cc'],'-cpp',tools['vcs_host_cxx'],
          '-top','router_adversarial',ROOT/'rtl/interfaces/axi4_if.sv',ROOT/'rtl/soc/t17_uart_router.sv',
          ROOT/'tests/boot/sd/router_adversarial.sv','-o',router/'simv'],120,cwd=router)
        log=run.execute('router-adversarial',[router/'simv','-no_save'],30,cwd=router)
        run.check('router-cross-target','ROUTER_ADVERSARIAL_PASS' in log.read_text(),'W before next AW cannot leak across targets after WLAST')
        profiles=set(n.split('-')[0] for n in selected)|({'smoke'} if args.suite!='smoke' else set());fxs={p:prepare(run.build/'fixtures'/p,apps,p) for p in sorted(profiles)}
        def execute(name):
            profile=name.split('-')[0];seed=int(re.search(r'seed(\d+)',name)[1]);r=case(run,tools,config,name,profile,seed,fw,fxs[profile],sim)
            print('T18 PASS '+name,flush=True);return r
        with ThreadPoolExecutor(max_workers=config['parallel_processes']) as pool:results=dict(zip(selected,pool.map(execute,selected)))
        run.manifest['cases']={n:dict(checks=r['check_count'],sequence_sha256=r['sequence_sha256'],result=r['result']) for n,r in results.items()}
        if args.suite!='smoke':
            run.check('deterministic-replay',results['control-seed1']['sequence_sha256']==results['control-seed1-replay']['sequence_sha256'],'complete SPI/event sequence')
            with ThreadPoolExecutor(max_workers=config['parallel_processes']) as pool:run.manifest['negative_evidence']=list(pool.map(lambda n:negative_case(run,tools,config,n,fw,fxs['smoke'],sim),config['negative_cases']))
            full=json.loads((ROOT/'docs/spec/model-pack-v1-manifest.json').read_text());pack=ROOT/full['pack_path'];v=verify(pack,expected_sha256=full['sha256'])
            check=build_card(apps['A'],pack,run.build/'full-card.img');write_json(run.path/'full-file-check.json',dict(status='PASS',model=v.summary,media=check,scope='entire full package and every tensor/file/media offset; no full-size serial RTL transfer'))
            run.check('full-file-size',v.summary['bytes']==536731456 and check['bytes']%512==0,'complete frozen model; bounded host streaming')
            run.execute('project-tests',[tools['make'],'test'],180,cwd=ROOT)
        run.check('source-unchanged',inputs()==files,'complete implementation and checker identity');code=0
    except StepFailure as e:code=e.exit_code;(run.path/'failure.txt').write_text(str(e)+'\n')
    except Exception:(run.path/'failure.txt').write_text(traceback.format_exc())
    finally:archive(run);code=run.finish(code)
    print(f'T18 {run.manifest["status"]} (exit {code}): {run.path}',flush=True);return code
if __name__=='__main__':sys.exit(main())
