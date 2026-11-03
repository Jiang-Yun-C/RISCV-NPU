#!/usr/bin/env python3
"""Build and qualify real UART protocol boot; preserve immutable raw evidence."""
import argparse
import hashlib
import json
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
sys.path[:0]=[str(ROOT/'tests/boot/uart'),str(ROOT/'software/boot'),str(ROOT/'tests/models')]
from generate_fixtures import generate as fixtures,SIGNATURES
from prepare_image import parse_elf
from waveform import check_waveform

class UartEvidence(EvidenceRun):
    def __init__(self,*args,**kwargs):
        self._index_lock=threading.RLock();super().__init__(*args,**kwargs)
    def flush(self):
        with self._index_lock:super().flush()

def inputs():
    names=['Makefile','scripts/run_t17.py','scripts/run_cocotb.py','scripts/cocotb_case.py','scripts/evidence.py','scripts/probe_tools.py',
           'configs/t17-uart-boot.json','configs/cocotb-toolchain-lock.json','docs/spec/toolchain-lock.json',
           'docs/spec/python-requirements.lock.txt','docs/spec/memory-map-v1.json','docs/spec/uart-boot-v1.md','third_party/lock.json',
           'rtl/interfaces/axi4_if.sv','rtl/soc/t03_uart_tx.sv','rtl/soc/t17_uart.sv','rtl/soc/t17_uart_router.sv',
           'tests/models/axi_sparse_mem.sv','tests/models/sparse_memory_pkg.sv','tests/models/prepare_image.py']
    for folder in ('cpu_gen','firmware/boot/uart_loader','software/boot','tests/boot/uart','tests/cocotb'):
        names += [str(p.relative_to(ROOT)) for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc']
    return {n:sha256(ROOT/n) for n in sorted(set(names))}

def build_firmware(run,tools):
    folder=ROOT/'firmware/boot/uart_loader';out=run.build/'firmware';out.mkdir()
    flags=['-march=rv32im_zicsr_zifencei','-mabi=ilp32','-O2','-g','-ffreestanding','-fno-builtin','-fno-pic',
           '-nostdlib','-nostartfiles','-msmall-data-limit=0','-Wall','-Wextra','-Werror','-Wl,--build-id=none',
           f'-ffile-prefix-map={ROOT}=.']
    for variant in ('boot','boot-stale-i'):
        elf=out/(variant+'.elf')
        run.execute('firmware-'+variant,[tools['rv32_gcc'],*flags,*(['-DNX_OMIT_FENCE_I'] if variant!='boot' else []),
                    '-T',folder/'link.ld',folder/'start.S',folder/'main.c','-lgcc','-o',elf],60)
        _,segments,abi=parse_elf(elf.read_bytes(),base=0x10000,capacity=0x20000)
        rom=[s for s in segments if s.data]
        run.check('boot-rom-'+variant,abi==0 and len(rom)==1 and rom[0].address==0x10000
                  and len(rom[0].data)<=65536 and all(s.address>=0x20000 or s is rom[0] for s in segments),
                  'only immutable ROM bytes initialized; SRAM BSS cleared by firmware')
        (out/(variant+'.bin')).write_bytes(rom[0].data)
        log=run.execute('disassemble-'+variant,[tools['rv32_objdump'],'-d',elf],30);shutil.copy2(log,out/(variant+'.dis'))
        run.check('instruction-visibility-'+variant,('fence.i' in log.read_text())==(variant=='boot'),'correct/negative I cache maintenance')
    apps={}
    for name,signature in SIGNATURES.items():
        elf=out/('app-'+name+'.elf');binary=out/('app-'+name+'.bin')
        run.execute('firmware-app-'+name.lower(),[tools['rv32_gcc'],*flags,f'-DAPP_SIGNATURE={signature}',
                    f'-DAPP_MESSAGE="APP {name} PASS\\n"','-T',ROOT/'tests/boot/uart/app.ld',
                    ROOT/'tests/boot/uart/application.S','-o',elf],60)
        entry,segments,abi=parse_elf(elf.read_bytes(),base=0xb4000000,capacity=65536)
        run.check('application-'+name,entry==0xb4000000 and abi==0 and len(segments)==1 and len(segments[0].data)>2048,
                  {'entry':entry,'bytes':len(segments[0].data),'signature':signature})
        binary.write_bytes(segments[0].data);apps[name]=binary
        log=run.execute('disassemble-app-'+name.lower(),[tools['rv32_objdump'],'-d',elf],30);shutil.copy2(log,out/('app-'+name+'.dis'))
    return out,apps

def compile_simulator(run,tools,generated,vpi):
    out=run.build/'compiled';out.mkdir();rtl=generated/'soft/T09Cpu.v'
    for p in rtl.parent.glob('*.bin'):shutil.copy2(p,out/p.name)
    ports=re.findall(r'(input|output)\s+wire\s*(\[[^]]+\])?\s*(\w+)\s*[,\n]',rtl.read_text().split(');',1)[0])
    wrapper='`timescale 1ns/1ps\nmodule tb_cpu;\n'
    wrapper+=''.join(f"  {'logic' if d=='input' else 'wire'} {w} {n};\n" for d,w,n in ports)
    wrapper+='T09Cpu cpu(.*);\n'+(ROOT/'tests/boot/uart/tb_body.svh').read_text()+'\nendmodule\n'
    (out/'tb_cpu.sv').write_text(wrapper)
    run.execute('vcs-build',[tools['vcs'],'-full64','-sverilog','-timescale=1ns/1ps','-debug_access+all','+acc+3',
        '-cc',tools['vcs_host_cc'],'-cpp',tools['vcs_host_cxx'],'-LDFLAGS','-Wl,--no-as-needed','-load',vpi,'-top','tb_cpu',
        *[ROOT/p for p in ('rtl/interfaces/axi4_if.sv','tests/models/sparse_memory_pkg.sv','tests/models/axi_sparse_mem.sv',
                           'rtl/soc/t03_uart_tx.sv','rtl/soc/t17_uart.sv','rtl/soc/t17_uart_router.sv')],
        rtl,out/'tb_cpu.sv','-o',out/'simv'],300,cwd=out)
    return out/'simv'

def case(run,tools,config,name,profile,seed,fw,fixture,sim,negative=None):
    dest=run.build/'cocotb'/name;dest.mkdir(parents=True)
    for p in sim.parent.glob('*.bin'):shutil.copy2(p,dest/p.name)
    boot=fw/('boot-stale-i.bin' if negative=='stale-i-cache' else 'boot.bin')
    cfg=dict(task='T17',case_id=name,run_id=run.run_id,profile=profile,seed=seed,negative=negative,
             effective_seeds=dict(python=seed,cocotb=seed,vcs=seed,i_memory=seed^0x49,d_memory=seed^0x44,uart=seed^0x55),
             python_prefix=sys.prefix,cocotb_version=config['cocotb_version'],uart_divisor=config['uart_divisor'],
             max_cycles=10000 if negative=='held-reset' else config['max_cycles'],max_delay=config['max_delay'],
             test_mode='PRELOAD' if profile=='preload' else 'PROTOCOL_BOOT',boot=str(boot),boot_bytes=boot.stat().st_size,
             boot_sha256=sha256(boot),app=str(fw/'app-A.bin'),app_bytes=(fw/'app-A.bin').stat().st_size,
             fixture=str(fixture/'fixture.json'),golden=str(fixture/'golden.json'),
             fixture_sha256=sha256(fixture/'fixture.json'),golden_sha256=sha256(fixture/'golden.json'),simulator_sha256=sha256(sim))
    write_json(dest/'case.json',cfg)
    try:
        run.execute('case-'+name,[tools['python'],ROOT/'scripts/cocotb_case.py','--case',dest/'case.json','--sim',sim],
                    config['timeouts_seconds']['simulation'],cwd=dest)
    finally:shutil.copytree(dest,run.path/'artifacts/cocotb'/name)
    return json.loads((dest/'checks.json').read_text())

def archive(run):
    dest=run.path/'artifacts';dest.mkdir(exist_ok=True)
    for name in ('firmware','fixtures','generated'):
        if (run.build/name).exists():shutil.copytree(run.build/name,dest/name,dirs_exist_ok=True)
    if (run.build/'compiled/tb_cpu.sv').exists():shutil.copy2(run.build/'compiled/tb_cpu.sv',dest/'tb_cpu.sv')
    run.manifest['artifacts']={str(p.relative_to(run.path)):sha256(p) for p in sorted(run.path.rglob('*'))
        if p.is_file() and not(p.parent==run.path and p.name in ('manifest.json','checks.json','commands.json','exit-status.txt','handoff.json'))}

def negative_case(parent,tools,config,name,fw,fixture,sim):
    run=EvidenceRun(ROOT,'T17_NEGATIVE',parent.run_id+'-'+name)
    run.manifest.update(parent=str(parent.path),expected='FAIL',negative=name,source=parent.manifest['source'])
    code=1
    try:case(run,tools,config,name,'control',1,fw,fixture,sim,name)
    except StepFailure as error:code=error.exit_code
    finally:
        shutil.copy2(parent.path/'source.tar.gz',run.path/'source.tar.gz');archive(run);code=run.finish(code)
    d=run.build/'cocotb'/name;status=json.loads((d/'case-status.json').read_text())
    report=json.loads((d/'checks.json').read_text()) if (d/'checks.json').exists() else {}
    if name in ('held-reset','bad-golden','stale-i-cache'):
        category='completion' if name=='held-reset' else 'signature'
        detected=report.get('status')=='FAIL' and (report.get('first_failure') or {}).get('category')==category
    elif name=='empty':detected='required testcase identity/count mismatch' in status['reason']
    else:detected='missing/stale results.xml' in status['reason'] and report.get('status')=='PASS'
    parent.check('negative-'+name,code==1 and status['status']=='FAIL' and detected,dict(evidence=str(run.path),reason=status.get('reason'),failure=report.get('first_failure')))
    return str(run.path)

def verify_archive(path):
    from cocotb_case import validate
    path=Path(path).resolve();m=json.loads((path/'manifest.json').read_text())
    if m.get('status')!='PASS' or m.get('exit_code')!=0 or (path/'exit-status.txt').read_text().strip()!='0':raise ValueError('archive not completed PASS')
    for f in ('commands.json','checks.json'):
        data=json.loads((path/f).read_text());rows=data if isinstance(data,list) else data['checks']
        if not rows or any(r['status']!='PASS' for r in rows):raise ValueError('root command/check failure')
    for name,h in m['artifacts'].items():
        p=(path/name).resolve()
        if not p.is_relative_to(path) or not p.is_file() or sha256(p)!=h:raise ValueError('modified/missing artifact '+name)
    source=m['source']
    if content_id(source['files'])!=source['sha256']:raise ValueError('source identity')
    with tarfile.open(path/'source.tar.gz') as tar:
        if set(tar.getnames())!=set(source['files']):raise ValueError('source archive inventory')
        for n,h in source['files'].items():
            if hashlib.sha256(tar.extractfile(n).read()).hexdigest()!=h:raise ValueError('source content '+n)
        registered=json.load(tar.extractfile('configs/t17-uart-boot.json'))
        required={'scripts/run_t17.py','tests/cocotb/test_uart_boot.py','tests/boot/uart/scoreboard.py',
                  'tests/boot/uart/generate_fixtures.py','rtl/soc/t17_uart.sv','rtl/soc/t17_uart_router.sv',
                  'firmware/boot/uart_loader/main.c','firmware/boot/uart_loader/protocol.h',
                  'tests/models/axi_sparse_mem.sv','cpu_gen/src/main/scala/nexusrv/GenT09.scala'}
        if not required.issubset(source['files']):raise ValueError('trimmed required source inventory')
    cfg=json.loads((path/'config.json').read_text());suite=cfg['suite'];selected=registered['suites'][suite]
    if cfg!=dict(registered,suite=suite,selected_cases=selected) or sha256(path/'config.json')!=m['config_sha256']:
        raise ValueError('changed registered config')
    if not selected or len(selected)!=len(set(selected)) or set(m['cases'])!=set(selected):raise ValueError('required case matrix')
    count=0
    for name,record in m['cases'].items():
        d=path/'artifacts/cocotb'/name;case_cfg=json.loads((d/'case.json').read_text())
        if case_cfg['case_id']!=name or case_cfg['run_id']!=m['run_id'] or case_cfg['negative'] is not None:raise ValueError('case identity')
        profile=name.split('-')[0];seed=int(re.search(r'seed(\d+)',name)[1])
        if case_cfg['profile']!=profile or case_cfg['seed']!=seed or case_cfg['test_mode']!=('PRELOAD' if profile=='preload' else 'PROTOCOL_BOOT'):
            raise ValueError('case mode/seed/profile')
        for key in ('uart_divisor','max_delay','max_cycles'):
            if case_cfg[key]!=registered[key]:raise ValueError('changed case '+key)
        fixture=path/'artifacts/fixtures'/profile
        if sha256(fixture/'fixture.json')!=case_cfg['fixture_sha256'] or sha256(fixture/'golden.json')!=case_cfg['golden_sha256'] or sha256(path/'artifacts/firmware/boot.bin')!=case_cfg['boot_sha256']:
            raise ValueError('input identity')
        report=validate(d,case_cfg);check_waveform(d)
        from scoreboard import revalidate
        revalidate(d,json.loads((fixture/'fixture.json').read_text()),json.loads((fixture/'golden.json').read_text()),case_cfg)
        if report['sequence_sha256']!=record['sequence_sha256'] or report['check_count']!=record['checks']:raise ValueError('case record')
        count+=report['check_count']
    if suite!='smoke':
        if len(m['negative_evidence'])!=len(registered['negative_cases']):raise ValueError('missing negative coverage')
        actual=[]
        for name in m['negative_evidence']:
            d=Path(name);n=json.loads((d/'manifest.json').read_text());actual.append(n['negative'])
            if n['status']!='FAIL' or n['exit_code']!=1 or (d/'exit-status.txt').read_text().strip()!='1':raise ValueError('raw negative FAIL missing')
            for f,h in n['artifacts'].items():
                if sha256(d/f)!=h:raise ValueError('changed negative artifact')
        if actual!=registered['negative_cases']:raise ValueError('negative matrix')
        if m['cases']['control-seed1']['sequence_sha256']!=m['cases']['control-seed1-replay']['sequence_sha256']:raise ValueError('deterministic replay')
    return dict(status='PASS',cases=len(selected),independent_checks=count,negative_cases=len(m.get('negative_evidence',[])),source_sha256=source['sha256'])

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--suite',choices=['smoke','regression','full'],default='full')
    p.add_argument('--run-id');p.add_argument('--verify-archive',type=Path);args=p.parse_args()
    if args.verify_archive:
        try:print(json.dumps(verify_archive(args.verify_archive),indent=2));return 0
        except Exception as error:print('ARCHIVE_REJECT: '+str(error),file=sys.stderr);return 1
    run=UartEvidence(ROOT,'T17',args.run_id);print('T17 evidence: '+str(run.path),flush=True);code=1
    try:
        files=inputs();run.manifest['source']=dict(files=files,sha256=content_id(files),snapshot='source.tar.gz')
        with tarfile.open(run.path/'source.tar.gz','w:gz') as tar:
            for name in files:tar.add(ROOT/name,arcname=name,recursive=False)
        config=json.loads((ROOT/'configs/t17-uart-boot.json').read_text());selected=config['suites'][args.suite]
        config.update(suite=args.suite,selected_cases=selected);write_json(run.path/'config.json',config)
        run.manifest.update(config_sha256=sha256(run.path/'config.json'),invocation=[sys.executable,*sys.argv],
                            qualification=dict(protocol_boot='REAL_RX_TX_PINS',cpu='REAL_T09_CACHE_ENABLED',board='NOT_TESTED_NOT_REQUIRED'))
        tools={k:v['path'] for k,v in json.loads((ROOT/'docs/spec/toolchain-lock.json').read_text())['tools'].items()}
        vpi=environment(run,config,tools);generated=generate(run,tools,['soft'],config['timeouts_seconds']['generate'])
        fw,apps=build_firmware(run,tools);sim=compile_simulator(run,tools,generated,vpi)
        fxs={profile:fixtures(run.build/'fixtures'/profile,apps,profile) for profile in sorted(set(n.split('-')[0] for n in selected))}
        frozen=ROOT/'tests/cocotb/fixtures/uart_boot'
        frozen_manifest=json.loads((frozen/'manifest.json').read_text())
        run.check('frozen-fixtures',all(sha256(frozen/n)==h for n,h in frozen_manifest['files'].items()) and
                  all(sha256(fxs[p]/n)==sha256(frozen/p/n) for p in fxs for n in ('fixture.json','golden.json')) and
                  all(sha256(apps[n])==sha256(frozen/('app-'+n+'.bin')) for n in apps),'fresh compiled applications and all wire/golden fixtures match frozen input')
        def execute_case(name):
            profile=name.split('-')[0];seed=int(re.search(r'seed(\d+)',name)[1])
            result=case(run,tools,config,name,profile,seed,fw,fxs[profile],sim)
            print('T17 PASS '+name,flush=True)
            return result
        with ThreadPoolExecutor(max_workers=config['parallel_processes']) as pool:
            results=dict(zip(selected,pool.map(execute_case,selected)))
        for name in selected:
            if name.endswith('-replay'):run.check('deterministic-replay',results[name]['sequence_sha256']==results[name.removesuffix('-replay')]['sequence_sha256'],'all pin/bus/retirement events including cycles')
        run.manifest['cases']={n:dict(status=r['status'],checks=r['check_count'],result=r['result'],sequence_sha256=r['sequence_sha256']) for n,r in results.items()}
        if args.suite!='smoke':
            with ThreadPoolExecutor(max_workers=config['parallel_processes']) as pool:
                run.manifest['negative_evidence']=list(pool.map(lambda n:negative_case(run,tools,config,n,fw,fxs['control'],sim),config['negative_cases']))
            run.execute('project-tests',[tools['make'],'test'],180,cwd=ROOT)
        run.check('source-unchanged',inputs()==files,'complete implementation/checker identity');code=0
    except StepFailure as error:code=error.exit_code;(run.path/'failure.txt').write_text(str(error)+'\n')
    except Exception:(run.path/'failure.txt').write_text(traceback.format_exc())
    finally:archive(run);code=run.finish(code)
    print(f'T17 {run.manifest["status"]} (exit {code}): {run.path}',flush=True);return code

if __name__=='__main__':sys.exit(main())
