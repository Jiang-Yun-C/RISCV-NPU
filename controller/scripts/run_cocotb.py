#!/usr/bin/env python3
"""Rebuild and qualify task-specific real RTL through VCS + locked cocotb."""
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import traceback

from evidence import EvidenceRun, StepFailure, content_id, sha256, write_json

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tests/cocotb'),str(ROOT/'tests/cpu'),str(ROOT/'tests/models')]
from common.cpu_reference import expected
from prepare_image import parse_elf
from elftools.elf.elffile import ELFFile


def inputs():
    names=['Makefile','docs/spec/cpu-feature-matrix.md','configs/cocotb-toolchain-lock.json','configs/cocotb-regression.json','docs/spec/toolchain-lock.json',
           'docs/spec/python-requirements.lock.txt','docs/spec/memory-map-v1.json','third_party/lock.json',
           'scripts/run_cocotb.py','scripts/cocotb_case.py','scripts/evidence.py','scripts/probe_tools.py',
           'tests/cpu/check_cpu.py','tests/models/prepare_image.py']
    for directory in ('cpu_gen','firmware/cpu','tests/cocotb'):
        names += [str(p.relative_to(ROOT)) for p in (ROOT/directory).rglob('*')
                  if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc']
    return {name:sha256(ROOT/name) for name in sorted(set(names))}


def environment(run, config, tools):
    import cocotb
    from cocotb_tools.config import lib_name_path
    run.check('python-environment',sys.prefix==str(Path(tools['python']).parent.parent)
              and cocotb.__version__==config['cocotb_version']
              and importlib.metadata.version('cocotbext-axi')==config['cocotbext_axi_version'],
              {'python':sys.executable,'prefix':sys.prefix,'cocotb':cocotb.__version__})
    lib=Path(lib_name_path('vpi','vcs')).resolve()
    run.check('vpi-environment',lib.is_file() and lib.is_relative_to(Path(sys.prefix)),str(lib))
    lock=json.loads((ROOT/'configs/cocotb-toolchain-lock.json').read_text())
    run.check('cocotb-runtime-lock',all(Path(v['path']).is_file() and sha256(v['path'])==v['sha256']
        for v in lock['files'].values()) and str(lib)==lock['files']['vpi']['path'],lock)
    run.manifest['cocotb_runtime_lock']=lock
    run.manifest['vpi']={'path':str(lib),'sha256':sha256(lib),'python':sys.executable,
                         'cocotb':cocotb.__version__,'cocotbext_axi':importlib.metadata.version('cocotbext-axi')}
    run.execute('tool-probe',[tools['python'],ROOT/'scripts/probe_tools.py','--root',ROOT,
                            '--output',run.build/'tool-report.json'],config['timeouts_seconds']['probe'])
    return lib


def generate(run,tools,profiles,timeout):
    dep=json.loads((ROOT/'third_party/lock.json').read_text())['dependencies']['VexRiscv']
    upstream=run.build/'VexRiscv';upstream.mkdir()
    archive=run.path/'vexriscv-source.tar'
    run.execute('upstream-export',[tools['git'],'-C',dep['path'],'archive','--format=tar','--output',archive,dep['commit']],30)
    run.execute('upstream-extract',['tar','-xf',archive,'-C',upstream],30)
    for patch in sorted((ROOT/'cpu_gen/patches').glob('*.patch')):
        run.execute(patch.stem+'-patch',['patch','-p1','--input',patch],30,cwd=upstream)
    run.manifest['upstream']={**dep,'source_sha256':sha256(archive),'patches':{p.name:sha256(p) for p in sorted((ROOT/'cpu_gen/patches').glob('*.patch'))}}
    project=run.build/'cpu_gen';shutil.copytree(ROOT/'cpu_gen',project)
    generated=run.build/'generated';generated.mkdir()
    commands=[]
    for profile in profiles:
        (generated/profile).mkdir()
        commands.append(f'runMain nexusrv.GenT09 {generated/profile} {profile}')
    log=run.execute('cpu-generate',[tools['sbt'],f'-Dnexusrv.vex.source={upstream}','-J-Xmx2G','-batch',*commands],timeout,cwd=project)
    run.check('cpu-generated',all(f'T09_GENERATED profile={p}' in log.read_text() for p in profiles),profiles)
    return generated


def firmware(run,tools,profile,timeout):
    dest=run.build/'firmware'/profile;dest.mkdir(parents=True)
    hard=profile=='hard'; march='rv32imf_zicsr_zifencei' if hard else 'rv32im_zicsr_zifencei';abi='ilp32f' if hard else 'ilp32'
    source=ROOT/'firmware/cpu'
    cmd=[tools['rv32_gcc'],f'-march={march}',f'-mabi={abi}','-O2','-g','-ffreestanding','-fno-builtin',
         '-fno-pic','-fno-strict-aliasing','-nostdlib','-nostartfiles','-msmall-data-limit=0',
         '-Wall','-Wextra','-Werror','-Wl,--build-id=none',f'-Wl,-Map={dest}/firmware.map',
         f'-ffile-prefix-map={ROOT}=.',f'-fdebug-prefix-map={run.build}=.',f'-T{source}/link.ld',
         source/'start.S',source/'directed.S',source/'main.c']
    if hard: cmd += ['-DHARD_FLOAT',source/'float_abi.c','-lm','-lc','-lnosys']
    run.execute(f'firmware-{profile}',cmd+['-lgcc','-o',dest/'firmware.elf'],timeout)
    log=run.execute(f'disassemble-{profile}',[tools['rv32_objdump'],'-d',dest/'firmware.elf'],30)
    shutil.copy2(log,dest/'firmware.dis')
    binary=(dest/'firmware.elf').read_bytes()
    entry,segments,flags=parse_elf(binary,base=0x10000,capacity=0xb8000000-0x10000)
    run.check(f'elf-{profile}',entry==0x10000 and flags==(2 if hard else 0),{'entry':entry,'flags':flags,'abi':abi})
    memory_map=json.loads((ROOT/'docs/spec/memory-map-v1.json').read_text())
    regions=memory_map['soc_regions']+memory_map['ddr_regions']
    permitted=[r for r in regions if r['name'] in ('boot_rom','cpu_private')]
    run.check(f'image-addresses-{profile}',all(any(int(r['base'],0)<=s.address and
        s.address+s.memory_size<=int(r['base'],0)+r['size_bytes'] for r in permitted) for s in segments),
        'PRELOAD only boot ROM + cpu_private; never weights or result MMIO')
    with (dest/'firmware.elf').open('rb') as f:
        elf=ELFFile(f)
        symbols={s.name:s['st_value'] for s in elf.get_section_by_name('.symtab').iter_symbols()}
    required=['abi_compute','sqrtf'] if hard else ['__mulsf3','__addsf3']
    run.check(f'float-abi-{profile}',all(n in symbols for n in required),required)
    fixture={'schema_version':1,'producer':'T09','test_mode':'PRELOAD','endianness':'little',
             'dtype':'uint8','layout_id':'RV32_ELF_PHYSICAL','group_size':'not_applicable','model':'not_applicable',
             'elf_sha256':sha256(dest/'firmware.elf'),'isa':march,'abi':abi,'symbols':symbols,
             'logical_view':'physical RV32 ELF segments; CPU-produced named MMIO signatures',
             'comparison':{'integers':'bit_exact','fp32_test_patterns':'bit_exact','atol':0,'rtol':0},
             'generator_sha256':sha256(ROOT/'scripts/run_cocotb.py'),
             'checker_sha256':sha256(ROOT/'tests/cocotb/test_cpu.py'),
             'reference_sha256':sha256(ROOT/'tests/cocotb/common/cpu_reference.py'),
             'segments':[{'address':s.address,'hex':s.data.hex(),'memory_size':s.memory_size,
                          'shape':[len(s.data)],'stride':[1],
                          'sha256':__import__('hashlib').sha256(s.data).hexdigest()} for s in segments]}
    write_json(dest/'fixture.json',fixture)
    def instruction_at(a):
        for s in segments:
            if s.address<=a<a+4<=s.address+len(s.data):
                return int.from_bytes(s.data[a-s.address:a-s.address+4],'little')
        raise ValueError('missing expected instruction')
    for seed in (1,7,19):
        write_json(dest/f'golden-{seed}.json',expected(seed,hard,symbols,instruction_at))
    return dest


def compile_cpu(run,tools,generated,profile,vpi,timeout):
    dest=run.build/'compiled'/profile;dest.mkdir(parents=True)
    rtl=generated/profile/'T09Cpu.v'
    for p in (generated/profile).glob('*.bin'): shutil.copy2(p,dest/p.name)
    # Mechanical testbench shell: all driving is external cocotb, all CPU outputs are observations.
    header=rtl.read_text().split(');',1)[0]
    ports=re.findall(r'(input|output)\s+wire\s*(\[[^]]+\])?\s*(\w+)\s*[,\n]',header)
    if not ports: raise ValueError('cannot parse generated CPU ports')
    wrapper='`timescale 1ns/1ps\nmodule tb_cpu;\n'
    wrapper+=''.join(f"  {'reg' if direction=='input' else 'wire'} {width} {name};\n" for direction,width,name in ports)
    wrapper+='  T09Cpu cpu (.*);\n  initial begin $dumpfile("cpu.vcd"); $dumpvars(1,tb_cpu); end\nendmodule\n'
    (dest/'tb_cpu.sv').write_text(wrapper)
    log=run.execute(f'vcs-build-{profile}',[tools['vcs'],'-full64','-sverilog','-timescale=1ns/1ps',
        '-debug_access+all','+acc+3','-cc',tools['vcs_host_cc'],'-cpp',tools['vcs_host_cxx'],
        '-LDFLAGS','-Wl,--no-as-needed','-load',vpi,'-top','tb_cpu',rtl,dest/'tb_cpu.sv','-o',dest/'simv'],timeout,cwd=dest)
    run.check(f'vcs-version-{profile}','X-2025.06' in log.read_text(),'locked VCS compiler')
    return dest/'simv'


def case(run,tools,config,case_id,profile,seed,fw,sim,negative=None):
    dest=run.build/'cocotb'/case_id;dest.mkdir(parents=True)
    for p in sim.parent.glob('*.bin'): shutil.copy2(p,dest/p.name)
    cfg={'schema_version':1,'case_id':case_id,'run_id':run.run_id,'profile':profile,'seed':seed,
         'effective_seeds':{'python':seed,'cocotb':seed,'vcs':seed,'i_memory':seed^0x49,'d_memory':seed^0x44},
         'test_mode':'PRELOAD','python_prefix':sys.prefix,'cocotb_version':config['cocotb_version'],
         'expected_framework_status':'FAIL' if negative else 'PASS','expected_dut_faults':[0,1,2,3,4,5,6,11,0x80000003,0x80000007,0x8000000b],
         'max_cycles':2000 if negative=='held-reset' else config['max_cycles'],
         'max_delay':config['max_delay'],'negative':negative,
         'fixture':str(fw/'fixture.json'),'golden':str(fw/f'golden-{seed}.json'),
         'fixture_sha256':sha256(fw/'fixture.json'),'golden_sha256':sha256(fw/f'golden-{seed}.json'),
         'simulator_sha256':sha256(sim),'rtl_initialization':{p.name:sha256(p) for p in dest.glob('*.bin')}}
    write_json(dest/'case.json',cfg)
    try:
        run.execute('case-'+case_id,[tools['python'],ROOT/'scripts/cocotb_case.py','--case',dest/'case.json','--sim',sim],
                    config['timeouts_seconds']['simulation'],cwd=dest)
    finally:
        archive=run.path/'artifacts'/'cocotb'/case_id
        shutil.copytree(dest,archive)
    report=json.loads((dest/'checks.json').read_text())
    return report


def negative_case(parent,tools,config,name,fw,sim):
    run=EvidenceRun(ROOT,'T09_NEGATIVE',parent.run_id+'-'+name)
    run.manifest.update(parent=str(parent.path),expected='FAIL',negative=name,source=parent.manifest['source'],
                        compiled_simulator={'path':str(sim),'sha256':sha256(sim)})
    code=1
    try:
        case(run,tools,config,name,'soft',1,fw,sim,name)
        run.check('negative-must-fail',False,'negative unexpectedly passed')
    except StepFailure as error:
        code=error.exit_code
    finally:
        shutil.copy2(parent.path/'source.tar.gz',run.path/'source.tar.gz')
        archive(run)
        code=run.finish(code)
    status_path=run.build/'cocotb'/name/'case-status.json'
    status=json.loads(status_path.read_text()) if status_path.exists() else {}
    expected_reason={'held-reset':'XML failure/error/skip','bad-golden':'XML failure/error/skip',
                     'empty':'required testcase identity/count mismatch','missing-xml':'missing/stale results.xml'}[name]
    detected=code==1 and expected_reason in status.get('reason','')
    case_dir=run.build/'cocotb'/name
    if name in ('held-reset','bad-golden'):
        report=json.loads((case_dir/'checks.json').read_text())
        failure=report.get('first_failure') or {}
        category='completion' if name=='held-reset' else 'signature'
        detected &= report['status']=='FAIL' and failure.get('category')==category
        if name=='held-reset': detected &= 'cycle timeout' in str(failure.get('detail'))
        else: detected &= failure.get('detail',{}).get('item')=='2'
    elif name=='missing-xml':
        import xml.etree.ElementTree as ET
        xml=ET.parse(case_dir/'intentionally-removed-results.xml').getroot()
        detected &= not any(n.tag in ('error','failure','skipped') for n in xml.iter())
        detected &= json.loads((case_dir/'checks.json').read_text())['status']=='PASS'
    elif name=='empty':
        import xml.etree.ElementTree as ET
        xml=ET.parse(case_dir/'results.xml').getroot()
        detected &= [n.get('name') for n in xml.findall('.//testcase')]==['empty']
        detected &= not any(n.tag in ('error','failure','skipped') for n in xml.iter())
    parent.check('negative-'+name,detected,{'evidence':str(run.path),'actual_status':status})
    return str(run.path)


def archive(run):
    artifacts=run.path/'artifacts';artifacts.mkdir(exist_ok=True)
    for name in ('generated','firmware'):
        if (run.build/name).is_dir(): shutil.copytree(run.build/name,artifacts/name)
    if (run.build/'tool-report.json').exists(): shutil.copy2(run.build/'tool-report.json',artifacts/'tool-report.json')
    for p in (run.build/'compiled').glob('*/tb_cpu.sv'):
        target=artifacts/'wrappers'/p.parent.name;target.mkdir(parents=True);shutil.copy2(p,target/p.name)
    run.manifest['artifacts']={str(p.relative_to(run.path)):sha256(p) for p in sorted(run.path.rglob('*'))
                               if p.is_file() and not (p.parent==run.path and p.name in ('manifest.json','checks.json','commands.json','exit-status.txt'))}


def verify_archive(path):
    from cocotb_case import validate
    from common.waveform import check_waveform
    path=Path(path).resolve();m=json.loads((path/'manifest.json').read_text())
    if m.get('status')!='PASS' or m.get('exit_code')!=0 or (path/'exit-status.txt').read_text().strip()!='0':
        raise ValueError('archive is not a completed PASS')
    commands=json.loads((path/'commands.json').read_text())
    checks=json.loads((path/'checks.json').read_text())['checks']
    if not commands or not checks or any(x.get('status')!='PASS' for x in commands+checks):
        raise ValueError('missing/failed root commands or checks')
    if sha256(path/'config.json')!=m['config']['sha256']: raise ValueError('config identity mismatch')
    for name,expected_hash in m['artifacts'].items():
        p=(path/name).resolve()
        if not p.is_relative_to(path) or not p.is_file() or sha256(p)!=expected_hash:
            raise ValueError('artifact missing/modified: '+name)
    source=m['source']
    if content_id(source['files'])!=source['sha256']: raise ValueError('source identity mismatch')
    import hashlib
    with tarfile.open(path/'source.tar.gz') as tar:
        if set(tar.getnames())!=set(source['files']): raise ValueError('source archive inventory mismatch')
        for name,h in source['files'].items():
            if hashlib.sha256(tar.extractfile(name).read()).hexdigest()!=h: raise ValueError('source snapshot hash: '+name)
    config=json.loads((path/'config.json').read_text())
    if not config['selected_cases'] or len(config['selected_cases'])!=len(set(config['selected_cases'])) or set(m['cases'])!=set(config['selected_cases']): raise ValueError('required case coverage mismatch')
    checks=0
    for case_id,record in m['cases'].items():
        dest=path/'artifacts/cocotb'/case_id
        cfg=json.loads((dest/'case.json').read_text())
        if cfg['case_id']!=case_id or cfg['run_id']!=m['run_id']: raise ValueError('case/parent identity mismatch')
        firmware=path/'artifacts/firmware'/cfg['profile']
        if sha256(firmware/'fixture.json')!=cfg['fixture_sha256'] or sha256(firmware/f"golden-{cfg['seed']}.json")!=cfg['golden_sha256']:
            raise ValueError('fixture/golden identity mismatch')
        report=validate(dest,cfg)
        if report['sequence_sha256']!=record['sequence_sha256']: raise ValueError('case digest mismatch')
        check_waveform(dest)
        checks+=report['check_count']
    for name in m.get('negative_evidence',[]):
        negative=Path(name);nm=json.loads((negative/'manifest.json').read_text())
        if nm.get('status')!='FAIL' or nm.get('exit_code')!=1: raise ValueError('negative raw FAIL missing')
        for rel,h in nm['artifacts'].items():
            if sha256(negative/rel)!=h: raise ValueError('negative artifact modified')
    return {'status':'PASS','cases':len(m['cases']),'independent_checks':checks,
            'negative_cases':len(m.get('negative_evidence',[])),'source_sha256':source['sha256']}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--task',choices=['T09','T12','T13','T14','T15','T16','T17','T18','T19','T20','T21','T22','T23','T24'],default='T09');p.add_argument('--suite',choices=['smoke','regression','full'],default='regression')
    p.add_argument('--seed',type=int,choices=[1,7,19]);p.add_argument('--run-id')
    p.add_argument('--verify-archive',type=Path)
    args=p.parse_args()
    if args.task=='T24':
        if args.seed is not None:p.error('T24 uses the accepted T16 seed matrix')
        from run_t24 import main as t24_main
        forwarded=['--suite',args.suite]
        if args.run_id:forwarded+=['--run-id',args.run_id]
        if args.verify_archive:forwarded+=['--verify-archive',str(args.verify_archive)]
        return t24_main(forwarded)
    if args.task=='T23':
        if args.seed is not None:p.error('T23 uses the registered width/seed matrix')
        from run_t23 import main as ddr_main
        forwarded=['--suite',args.suite]
        if args.run_id:forwarded+=['--run-id',args.run_id]
        if args.verify_archive:forwarded+=['--verify-archive',str(args.verify_archive)]
        return ddr_main(forwarded)
    if args.task=='T22':
        if args.seed is not None:p.error('T22 uses the registered seed matrix')
        from run_t22 import main as platform_main
        forwarded=['--suite',args.suite]
        if args.run_id:forwarded+=['--run-id',args.run_id]
        if args.verify_archive:forwarded+=['--verify-archive',str(args.verify_archive)]
        return platform_main(forwarded)
    if args.task=='T21':
        if args.seed is not None:p.error('T21 uses the frozen multi-seed matrix')
        from run_t21 import main as milestone_main
        forwarded=['--suite',args.suite]
        if args.run_id:forwarded+=['--run-id',args.run_id]
        if args.verify_archive:forwarded+=['--verify-archive',str(args.verify_archive)]
        return milestone_main(forwarded)
    if args.task in ('T12','T13','T14','T15','T16','T17','T18','T19','T20'):
        if args.seed is not None:p.error('T12 uses the registered seed matrix; use --suite smoke for a short run')
        if args.task=='T20':from run_t20 import main as runtime_main
        elif args.task=='T19':from run_t19 import main as runtime_main
        elif args.task=='T18':from run_t18 import main as runtime_main
        elif args.task=='T17':from run_t17 import main as runtime_main
        elif args.task=='T14':from run_t14 import main as runtime_main
        elif args.task=='T15':from run_t15 import main as runtime_main
        elif args.task=='T16':from run_t16 import main as runtime_main
        elif args.task=='T12':from run_t12 import main as runtime_main
        else:from run_t13 import main as runtime_main
        sys.argv=[sys.argv[0],'--suite',args.suite]
        if args.run_id:sys.argv+=['--run-id',args.run_id]
        if args.verify_archive:sys.argv+=['--verify-archive',str(args.verify_archive)]
        return runtime_main()
    if args.verify_archive:
        try:
            print(json.dumps(verify_archive(args.verify_archive),indent=2));return 0
        except Exception as error:
            print('ARCHIVE_REJECT: '+str(error),file=sys.stderr);return 1
    try: run=EvidenceRun(ROOT,args.task,args.run_id)
    except (ValueError,OSError) as e: print(e,file=sys.stderr);return 2
    print('T09 evidence: '+str(run.path),flush=True)
    code=1
    try:
        files=inputs();run.manifest['source']={'files':files,'sha256':content_id(files),'snapshot':'source.tar.gz'}
        with tarfile.open(run.path/'source.tar.gz','w:gz') as tar:
            for name in files: tar.add(ROOT/name,arcname=name,recursive=False)
        config=json.loads((ROOT/'configs/cocotb-regression.json').read_text())
        case_ids=config['suites'][args.suite]
        if args.seed is not None:
            case_ids=[f'soft-seed{args.seed}'] if args.suite=='smoke' else [x for x in case_ids if f'seed{args.seed}' in x]
        run.check('required-cases',bool(case_ids) and len(case_ids)==len(set(case_ids)),case_ids)
        config.update(suite=args.suite,selected_cases=case_ids)
        write_json(run.path/'config.json',config)
        run.manifest.update(config={'sha256':sha256(run.path/'config.json')},invocation=[sys.executable,*sys.argv],
            test_mode='PRELOAD',qualification={'cpu':'NOT_TESTED','board':'NOT_TESTED_NOT_REQUIRED',
                'privileged_compliance':'PARTIAL_SEE_FEATURE_MATRIX','protocol_boot':'NOT_TESTED_T17_T18'})
        tools={k:v['path'] for k,v in json.loads((ROOT/'docs/spec/toolchain-lock.json').read_text())['tools'].items()}
        vpi=environment(run,config,tools)
        profiles=list(dict.fromkeys(x.split('-')[0] for x in case_ids))
        generated=generate(run,tools,profiles,config['timeouts_seconds']['generate'])
        fws={};sims={}
        for profile in profiles:
            fws[profile]=firmware(run,tools,profile,config['timeouts_seconds']['compile'])
            sims[profile]=compile_cpu(run,tools,generated,profile,vpi,config['timeouts_seconds']['compile'])
        results={}
        for case_id in case_ids:
            profile=case_id.split('-')[0];seed=int(re.search(r'seed(\d+)',case_id)[1])
            results[case_id]=case(run,tools,config,case_id,profile,seed,fws[profile],sims[profile])
            if case_id.endswith('-replay'):
                original=results[case_id.removesuffix('-replay')]
                run.check('repeat-'+case_id,results[case_id]['sequence_sha256']==original['sequence_sha256'],
                          'same-seed complete handshake/retire/branch/interrupt sequence digest')
        run.manifest['cases']={k:{'status':v['status'],'checks':v['check_count'],'result':v['result'],
                                    'sequence_sha256':v['sequence_sha256']} for k,v in results.items()}
        if args.suite!='smoke' and args.seed is None:
            run.manifest['negative_evidence']=[negative_case(run,tools,config,n,fws['soft'],sims['soft']) for n in config['negative_cases']]
            run.execute('framework-tests',[tools['python'],'-m','unittest','discover','-s','tests/cocotb/unit','-v'],90,cwd=ROOT)
            run.execute('project-tests',[tools['make'],'test'],180,cwd=ROOT)
        run.check('source-unchanged',inputs()==files,'all build/checker inputs unchanged')
        run.manifest['qualification']['cpu']='PASS_SUITE_'+args.suite.upper()
        code=0
    except StepFailure as e:
        code=e.exit_code;(run.path/'failure.txt').write_text(str(e)+'\n')
    except KeyboardInterrupt:
        code=130;(run.path/'failure.txt').write_text('Interrupted\n')
    except Exception:
        (run.path/'failure.txt').write_text(traceback.format_exc())
        run.checks.append({'name':'runner-exception','status':'FAIL','detail':'failure.txt'})
    finally:
        archive(run);code=run.finish(code)
    print(f'T09 {run.manifest["status"]} (exit {code}): {run.path}',flush=True)
    return code

if __name__=='__main__': sys.exit(main())
