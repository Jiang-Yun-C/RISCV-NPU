#!/usr/bin/env python3
"""T20 real CPU / virtual pin peripherals, fail-closed evidence qualification."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
import hashlib
import json
import io
import os
from pathlib import Path
import re
import shutil
import sys
import tarfile
import time
import traceback
from evidence import StepFailure,content_id,sha256,write_json
from run_cocotb import environment,generate
from run_t12 import RuntimeEvidence
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tests/application/t20'))
from prepare import prepare,verify_model
from prepare_image import parse_elf
from cocotb_case import validate
from common.runtime_waveform import check_waveform

def inputs():
    names=['Makefile','scripts/run_t20.py','scripts/t20_model.py','scripts/run_cocotb.py','scripts/cocotb_case.py',
        'scripts/run_t12.py','scripts/evidence.py','scripts/probe_tools.py','scripts/complete_t20.py','scripts/t20_multi_model.py','docs/spec/application-t20.md',
        'configs/t20-application.json','configs/t20-prompt.txt','configs/t20-completion-prompt.txt','configs/cocotb-toolchain-lock.json','docs/spec/toolchain-lock.json',
        'docs/spec/python-requirements.lock.txt','third_party/lock.json','docs/spec/memory-map-v1.json',
        'rtl/interfaces/axi4_if.sv','rtl/soc/t03_uart_tx.sv','rtl/soc/t17_uart.sv','rtl/soc/t17_uart_router.sv',
        'tests/models/axi_sparse_mem.sv','tests/models/sparse_memory_pkg.sv','tests/models/prepare_image.py',
        'tests/application/v2/dev.jsonl','software/application_v2/program.py','software/application_v2/compiler.py','software/application_v2/serial_control.py','docs/spec/application-t20.schema.json','tests/cocotb/test_application.py',
        'tests/cocotb/test_empty.py','tests/cocotb/common/checks.py','tests/cocotb/common/runtime_waveform.py',
        'firmware/cpu/start.S','firmware/runtime/port/link.ld']
    for folder in ('firmware/application','tests/application/t20','cpu_gen'):
        names += [str(f.relative_to(ROOT)) for f in (ROOT/folder).rglob('*') if f.is_file() and '__pycache__' not in f.parts and f.suffix!='.pyc']
    return {n:sha256(ROOT/n) for n in sorted(set(names))}

def firmware(run,tools):
    out=run.build/'images';out.mkdir();elf=out/'firmware.elf'
    run.execute('firmware',[tools['rv32_gcc'],'-march=rv32im_zicsr_zifencei','-mabi=ilp32','-O2','-g','-ffreestanding','-fno-builtin','-nostdlib','-nostartfiles','-msmall-data-limit=0',
        '-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-ffunction-sections','-fdata-sections','-fstack-usage','-Wl,--gc-sections','-Wl,--build-id=none',f'-ffile-prefix-map={ROOT}=.',
        '-T',ROOT/'firmware/runtime/port/link.ld',ROOT/'firmware/cpu/start.S',ROOT/'firmware/application/application.c',ROOT/'firmware/application/main.c','-lc','-lgcc','-o',elf],120)
    entry,segments,flags=parse_elf(elf.read_bytes(),base=0x10000,capacity=0xb8000000-0x10000)
    run.check('elf',entry==0x10000 and flags==0 and all(0x10000<=s.address<s.address+s.memory_size<=0x20000 or 0xb4000000<=s.address<s.address+s.memory_size<=0xb4800000 for s in segments),'RV32IM/ILP32, no expected actions linked')
    images=[]
    for i,s in enumerate(segments):
        p=out/f'segment-{i}.bin';p.write_bytes(s.data);images.append(dict(path=str(p.resolve()),address=s.address,bytes=len(s.data),sha256=sha256(p)))
    write_json(out/'fixture.json',dict(producer='T20',schema_version=1,test_mode='PRELOAD',elf_sha256=sha256(elf),entry=entry,images=images))
    (out/'load.plan').write_text(''.join(f"B {r['address']:x} {r['bytes']:x} {r['path']}\n" for r in images if r['bytes']))
    return out

def compile_sim(run,tools,generated,vpi,fgp=False):
    out=run.build/('fgp' if fgp else 'compiled');out.mkdir();rtl=generated/'soft/T09Cpu.v'
    for p in rtl.parent.glob('*.bin'):shutil.copy2(p,out/p.name)
    ports=re.findall(r'(input|output)\s+wire\s*(\[[^]]+\])?\s*(\w+)\s*[,\n]',rtl.read_text().split(');',1)[0])
    wrapper='`timescale 1ns/1ps\nmodule tb_cpu;\n'+''.join(f"{'logic' if d=='input' else 'wire'} {w} {n};\n" for d,w,n in ports)
    (out/'tb_cpu.sv').write_text(wrapper+'T09Cpu cpu(.*);\n'+(ROOT/'tests/application/t20/tb_body.svh').read_text()+'\nendmodule\n')
    run.execute('vcs-fgp' if fgp else 'vcs-build',[tools['vcs'],*(['-fgp'] if fgp else []),'-j32','-full64','-sverilog','-timescale=1ns/1ps','-debug_access+all','+acc+3',
        '-cc',tools['vcs_host_cc'],'-cpp',tools['vcs_host_cxx'],'-LDFLAGS','-Wl,--no-as-needed','-load',vpi,'-top','tb_cpu',
        *[ROOT/n for n in ('rtl/interfaces/axi4_if.sv','tests/models/sparse_memory_pkg.sv','tests/models/axi_sparse_mem.sv','rtl/soc/t03_uart_tx.sv','rtl/soc/t17_uart.sv','rtl/soc/t17_uart_router.sv')],rtl,out/'tb_cpu.sv','-o',out/'simv'],300,cwd=out)
    return out/'simv'

def case(run,tools,cfg,name,sim,images,golden,negative=None,profile=None,cores=None):
    out=run.build/'cocotb'/name;out.mkdir(parents=True)
    for p in sim.parent.glob('*.bin'):shutil.copy2(p,out/p.name)
    params=cfg['cases'].get(name,dict(profile=profile or 'short',seed=1))
    config=dict(task='T20',case_id=name,run_id=run.run_id,**params,python_prefix=sys.prefix,cocotb_version=cfg['cocotb_version'],
        test_mode='PRELOAD',max_cycles=2000 if negative=='held-reset' else cfg['max_cycles'],max_delay=cfg['max_delay'],negative=negative,
        fgp_cores=cores or cfg['fgp_cores'],fixture=str(images/'fixture.json'),golden=str(golden),image_plan=str(images/'load.plan'),
        fixture_sha256=sha256(images/'fixture.json'),golden_sha256=sha256(golden),simulator_sha256=sha256(sim),
        effective_seeds=dict(vcs=params['seed'],cocotb=params['seed'],cpu_i=params['seed']^0x49,cpu_d=params['seed']^0x44))
    write_json(out/'case.json',config);start=time.monotonic()
    run.execute('case-'+name,[tools['python'],ROOT/'scripts/cocotb_case.py','--case',out/'case.json','--sim',sim],cfg['timeouts_seconds']['simulation'],cwd=out)
    return json.loads((out/'checks.json').read_text()),time.monotonic()-start

def archive(run):
    for name in ('images','generated','cocotb'):
        if (run.build/name).exists():shutil.copytree(run.build/name,run.path/'artifacts'/name,dirs_exist_ok=True)
    for n in ('compiled','fgp'):
        if (run.build/n/'tb_cpu.sv').exists():
            (run.path/'artifacts'/n).mkdir(parents=True,exist_ok=True)
            shutil.copy2(run.build/n/'tb_cpu.sv',run.path/'artifacts'/n/'tb_cpu.sv')
    run.manifest['artifacts']={str(p.relative_to(run.path)):sha256(p) for p in run.path.rglob('*') if p.is_file() and not(p.parent==run.path and p.name in ('manifest.json','commands.json','checks.json','exit-status.txt'))}

def verify_archive(path):
    path=Path(path).resolve();m=json.loads((path/'manifest.json').read_text())
    if m.get('task_id')!='T20' or m.get('status')!='PASS' or m.get('exit_code')!=0 or (path/'exit-status.txt').read_text().strip()!='0':raise ValueError('not a T20 PASS')
    for n,h in m['artifacts'].items():
        p=(path/n).resolve()
        if not p.is_relative_to(path) or not p.is_file() or sha256(p)!=h:raise ValueError('artifact '+n)
    if content_id(m['source']['files'])!=m['source']['sha256']:raise ValueError('source digest')
    with tarfile.open(path/'source.tar.gz') as tar:
        if set(tar.getnames())!=set(m['source']['files']):raise ValueError('source inventory')
        for n,h in m['source']['files'].items():
            if hashlib.sha256(tar.extractfile(n).read()).hexdigest()!=h:raise ValueError('source '+n)
        registered=json.load(tar.extractfile('configs/t20-application.json'))
    cfg=json.loads((path/'config.json').read_text());suite=cfg['suite']
    if suite not in registered['suites'] or not registered['suites'][suite] or len(set(cfg['selected_cases']))!=len(cfg['selected_cases']) or cfg!={**registered,'suite':suite,'selected_cases':registered['suites'][suite]} or sha256(path/'config.json')!=m['config_sha256'] or set(m['cases'])!=set(cfg['selected_cases']):raise ValueError('registered matrix')
    for filename in ('commands.json','checks.json'):
        data=json.loads((path/filename).read_text());data=data['checks'] if filename=='checks.json' else data
        if not data or any(row['status']!='PASS' for row in data):raise ValueError('missing/failed root results')
    required={'source.tar.gz','config.json','golden.json','model/manifest.json','model/results.jsonl','model/summary.json','performance.json','artifacts/images/fixture.json'}
    for n in cfg['selected_cases']:
        required |= {f'artifacts/cocotb/{n}/{file}' for file in ('case.json','checks.json','results.xml','observations.json','events.csv','cpu.vcd','peripherals.vcd','simulation.log','case-status.json','waveform-check.json')}
    if suite!='smoke':required |= {'terminal.jsonl','terminal-snapshot.json','logs/terminal-dry-run.stdout.log','logs/terminal-dry-run.stderr.log'}
    if not required.issubset(m['artifacts']):raise ValueError('required artifact inventory')
    verify_model(path/'model')
    golden=json.loads((path/'golden.json').read_text());count=0
    if sha256(path/'model/manifest.json')!=golden['model_manifest_sha256']:raise ValueError('model identity')
    for n in cfg['selected_cases']:
        d=path/'artifacts/cocotb'/n;c=json.loads((d/'case.json').read_text());r=validate(d,c);check_waveform(d)
        from pin_wave import check as check_pins
        check_pins(d/'peripherals.vcd')
        if c['run_id']!=m['run_id'] or c['task']!='T20' or c['negative'] is not None or c['fgp_cores']!=cfg['fgp_cores'] or c['max_cycles']!=cfg['max_cycles'] or c['max_delay']!=cfg['max_delay'] or any(c[k]!=v for k,v in cfg['cases'][n].items()):raise ValueError('case identity')
        if sha256(path/'golden.json')!=c['golden_sha256'] or sha256(path/'artifacts/images/fixture.json')!=c['fixture_sha256']:raise ValueError('fixture identity')
        obs=json.loads((d/'observations.json').read_text());rows=golden['groups'][c['profile']]
        if len(obs['responses'])!=len(rows):raise ValueError('request inventory')
        events=list(csv.DictReader(io.StringIO((d/'events.csv').read_text())));positions=[i for i,e in enumerate(events) if e['kind']=='R']
        if len(positions)!=len(rows):raise ValueError('passive request inventory')
        for i,(row,response,pins) in enumerate(zip(rows,obs['responses'],obs['pins'])):
            expected=row['expected'];status=expected['error'] or 'OK'
            if response['validation']!=status or response['id']!=row['id'] or response['intent']!=row['intent'] or response['actions']!=expected['actions'] or response['readings']!=expected['readings']:raise ValueError('independent replay mismatch')
            segment=events[positions[i]+1:positions[i+1] if i+1<len(positions) else len(events)]
            actions=[['led' if e['kind']=='G' else 'pwm',int(e['value'])] for e in segment if e['kind'] in ('G','P')]
            if actions!=expected['actions'] or pins['pwm_high']!=pins['pwm_duty']:raise ValueError('independent device replay')
        from common.checks import digest
        sequence=digest(dict(responses=obs['responses'],pins=obs['pins'],sensors=obs['sensors'],events=(d/'events.csv').read_text()))
        if sequence!=r['sequence_sha256'] or sequence!=m['cases'][n]['sequence_sha256'] or r['check_count']!=m['cases'][n]['checks']:raise ValueError('sequence identity')
        count+=r['check_count']
    if suite!='smoke':
        terminal=json.loads((path/'terminal.jsonl').read_text())
        first=json.loads((path/'model/results.jsonl').read_text().splitlines()[0])
        if terminal['text']!=first['input'] or terminal['snapshot']['state']!=first['state'] or any(terminal['model'][k]!=first[k] for k in ('text','output_ids','stop','candidates','selected_route','selected_prompt')):raise ValueError('terminal full-model identity')
        packet=(path/'logs/terminal-dry-run.stdout.log').read_bytes()
        if hashlib.sha256(packet).hexdigest()!=terminal['frame_sha256']:raise ValueError('terminal UART frame')
        if m['cases']['short-seed1']['sequence_sha256']!=m['cases']['short-seed1-replay']['sequence_sha256']:raise ValueError('seed replay')
        if set(m.get('negatives',{}))!=set(cfg['negative_cases']):raise ValueError('negative matrix')
        for n,record in m['negatives'].items():
            nd=Path(record['path']);nm=json.loads((nd/'manifest.json').read_text())
            if nm['status']!='FAIL' or nm['exit_code']!=1:raise ValueError('negative raw failure')
            for rel,h in nm['artifacts'].items():
                if sha256(nd/rel)!=h:raise ValueError('negative artifact')
            if n in ('held-reset','bad-golden','dropped-action'):
                first=json.loads((nd/'artifacts/cocotb'/n/'checks.json').read_text())['first_failure']
                if first['category']!={'held-reset':'completion','bad-golden':'validation','dropped-action':'gpio'}[n]:raise ValueError('negative expected reason')
    return dict(status='PASS',suite=suite,cases=len(m['cases']),independent_checks=count)

def main():
    p=argparse.ArgumentParser();p.add_argument('--suite',choices=['smoke','regression','full'],default='full');p.add_argument('--run-id');p.add_argument('--verify-archive',type=Path);p.add_argument('--benchmark',action='store_true');p.add_argument('--reuse-build',type=Path);a=p.parse_args()
    if a.verify_archive:
        try:print(json.dumps(verify_archive(a.verify_archive),indent=2));return 0
        except Exception:traceback.print_exc();return 1
    run=RuntimeEvidence(ROOT,'T20_PERFORMANCE' if a.benchmark else 'T20',a.run_id);print('T20 evidence '+str(run.path),flush=True);code=1
    try:
        files=inputs();run.manifest['source']=dict(files=files,sha256=content_id(files))
        with tarfile.open(run.path/'source.tar.gz','w:gz') as tar:
            for n in files:tar.add(ROOT/n,arcname=n,recursive=False)
        cfg=json.loads((ROOT/'configs/t20-application.json').read_text());cfg.update(suite=a.suite,selected_cases=cfg['suites'][a.suite]);write_json(run.path/'config.json',cfg)
        run.manifest.update(config_sha256=sha256(run.path/'config.json'),scope=cfg['scope'],invocation=[sys.executable,*sys.argv])
        tools={k:v['path'] for k,v in json.loads((ROOT/'docs/spec/toolchain-lock.json').read_text())['tools'].items()}
        run.execute('resources',['bash','-c','nproc; lscpu; free -h; uptime; cat /proc/self/status | head -25'],30)
        run.execute('license',['lmutil','lmstat','-a','-c',os.environ['SNPSLMD_LICENSE_FILE']],90)
        vpi=environment(run,cfg,tools)
        if a.reuse_build:
            previous=a.reuse_build.resolve();receipt=json.loads((ROOT/'evidence/T20'/previous.name/'manifest.json').read_text())
            compile_names=[n for n in files if n.startswith(('cpu_gen/','rtl/','firmware/','tests/models/')) or n=='tests/application/t20/tb_body.svh']
            run.check('reuse-inputs',all(receipt['source']['files'].get(n)==files[n] for n in compile_names),'all CPU/RTL/firmware/adapter/memory inputs identical')
            steps=json.loads((ROOT/'evidence/T20'/previous.name/'commands.json').read_text())
            run.check('reuse-build-complete',all(any(s['name']==n and s['status']=='PASS' for s in steps) for n in ('cpu-generate','firmware','vcs-build')),'successful compile receipts, regardless of later test failure')
            generated=run.build/'generated';shutil.copytree(previous/'generated',generated)
            images=run.build/'images';shutil.copytree(previous/'images',images)
            old_case=json.loads((previous/'cocotb/short-seed1/case.json').read_text());sim=previous/'compiled/simv'
            run.check('reuse-simulator',sha256(sim)==old_case['simulator_sha256'],'compiled binary identity')
            run.manifest['compile_reuse']=dict(build=str(previous),simulator_sha256=sha256(sim),inputs={n:files[n] for n in compile_names})
        else:
            generated=generate(run,tools,['soft'],600);images=firmware(run,tools)
            sim=compile_sim(run,tools,generated,vpi,fgp=cfg['fgp_cores']>1)
        golden=run.path/'golden.json';write_json(golden,prepare(ROOT/cfg['model_evidence']))
        shutil.copytree(ROOT/cfg['model_evidence'],run.path/'model')
        mm=json.loads((run.path/'model/manifest.json').read_text())
        run.check('model-consumer-source',mm.get('compiler') is True and mm['workers']==cfg['desktop_workers'] and all(sha256(ROOT/n)==h for n,h in mm['source']['files'].items()),'actual full-model C, tokenizer wrapper, compiler, prompts and dev inputs match the recorded model run')
        perf=ROOT/'evidence/T20_PERFORMANCE/concurrency-20261008-v1'
        if not a.benchmark:
            pm=json.loads((perf/'manifest.json').read_text())
            run.check('performance-source',pm['status']=='PASS' and all(pm['source']['files'].get(n)==h for n,h in files.items() if n.startswith(('firmware/','rtl/','cpu_gen/')) or n in ('tests/application/t20/tb_body.svh','tests/models/axi_sparse_mem.sv','tests/models/sparse_memory_pkg.sv')),'performance and acceptance CPU/RTL/firmware/virtual-MMIO sources identical; final checker additionally archives passive pin VCD')
            shutil.copy2(perf/'performance.json',run.path/'performance.json');run.manifest['performance_evidence']=dict(path=str(perf),manifest_sha256=sha256(perf/'manifest.json'))
        if a.benchmark:
            fgp=compile_sim(run,tools,generated,vpi,fgp=True);bench=[]
            for cores in [1,4,8,16,32]:
                r,wall=case(run,tools,cfg,'cores'+str(cores),sim if cores==1 else fgp,images,golden,profile='short',cores=cores)
                bench.append(dict(cores=cores,wall_seconds=wall,sequence_sha256=r['sequence_sha256'],cycles=r['result']['cycles'],checks=r['check_count']))
                print('benchmark',cores,round(wall,3),flush=True)
            run.check('benchmark-equivalence',len({r['sequence_sha256'] for r in bench})==1,'values, UART, I2C, output pins and cycles identical')
            throughput=[]
            for workers in [8,16,32]:
                start=time.monotonic()
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    def throughput_case(i):return case(run,tools,cfg,f'workers{workers}-job{i}',sim,images,golden,profile='throughput',cores=1)[0]
                    reports=list(pool.map(throughput_case,range(32)))
                seconds=time.monotonic()-start
                run.check(f'throughput-{workers}',len({r['sequence_sha256'] for r in reports})==1,'32 identical independent one-request cases')
                throughput.append(dict(simulation_workers=workers,jobs=32,cores_per_simulation=1,wall_seconds=seconds,checks=sum(r['check_count'] for r in reports)))
                print('throughput',workers,round(seconds,3),flush=True)
            write_json(run.path/'performance.json',dict(scope='representative CPU/UART/I2C/GPIO/PWM windows; no FPGA speed claim',compile_jobs=32,benchmarks=bench,best=min(bench,key=lambda r:r['wall_seconds']),throughput=throughput,best_throughput=min(throughput,key=lambda r:r['wall_seconds'])))
        else:
            start=time.monotonic()
            with ThreadPoolExecutor(max_workers=cfg['simulation_workers']) as pool:
                if a.suite!='smoke':
                    first=json.loads((run.path/'model/results.jsonl').read_text().splitlines()[0])
                    write_json(run.path/'terminal-snapshot.json',dict(epoch=1,state=first['state']))
                    terminal=pool.submit(run.execute,'terminal-dry-run',[tools['python'],ROOT/'software/application_v2/serial_control.py','--snapshot',run.path/'terminal-snapshot.json','--text',first['input'],'--dry-run','--log',run.path/'terminal.jsonl'],180,ROOT)
                def execute_case(n):return n,case(run,tools,cfg,n,sim,images,golden)[0]
                for n,r in pool.map(execute_case,cfg['selected_cases']):
                    run.manifest.setdefault('cases',{})[n]=dict(checks=r['check_count'],sequence_sha256=r['sequence_sha256'],result=r['result']);run.flush();print(n,r['status'],flush=True)
                matrix_wall=time.monotonic()-start
                if a.suite!='smoke':
                    terminal.result();record=json.loads((run.path/'terminal.jsonl').read_text())
                    run.check('terminal-model-replay',all(record['model'][k]==first[k] for k in ('text','output_ids','stop','candidates','selected_route','selected_prompt')) and record['library_sha256']==mm['result']['library_sha256'],'actual terminal CLI reproduces recorded full-model output and exact C-library identity; no physical port opened')
            run.manifest['matrix_wall_seconds']=matrix_wall
            if a.suite!='smoke':
                run.check('seed-replay',run.manifest['cases']['short-seed1']['sequence_sha256']==run.manifest['cases']['short-seed1-replay']['sequence_sha256'],'full deterministic UART/I2C/actions/pins stream')
                def negative(name):
                    neg=RuntimeEvidence(ROOT,'T20_NEGATIVE',run.run_id+'-'+name);neg.manifest.update(negative=name,parent=str(run.path));rc=0
                    try:case(neg,tools,cfg,name,sim,images,golden,negative=name,profile='short')
                    except StepFailure as e:rc=e.exit_code
                    finally:archive(neg);neg.finish(rc)
                    status=json.loads((neg.build/'cocotb'/name/'case-status.json').read_text());needle={'empty':'required testcase identity/count mismatch','missing-xml':'missing/stale results.xml'}.get(name,'XML failure/error/skip')
                    ok=rc==1 and needle in status.get('reason','')
                    if name in ('held-reset','bad-golden','dropped-action'):
                        first=json.loads((neg.build/'cocotb'/name/'checks.json').read_text())['first_failure']
                        ok &= first['category']=={'held-reset':'completion','bad-golden':'validation','dropped-action':'gpio'}[name]
                    return name,ok,str(neg.path),status
                with ThreadPoolExecutor(max_workers=cfg['simulation_workers']) as pool:
                    for name,ok,path,status in pool.map(negative,cfg['negative_cases']):
                        run.check('negative-'+name,ok,status);run.manifest.setdefault('negatives',{})[name]=dict(path=path,reason=status.get('reason'));run.flush()
                run.execute('project-tests',[tools['make'],'test'],600,cwd=ROOT)
            run.execute('application-tests',[tools['python'],'-m','unittest','discover','-s',ROOT/'tests/application/t20','-p','test_*.py','-v'],120,cwd=ROOT)
        run.check('source-unchanged',inputs()==files,'all executed sources frozen');code=0
    except StepFailure as e:code=e.exit_code;(run.path/'failure.txt').write_text(str(e)+'\n')
    except Exception:(run.path/'failure.txt').write_text(traceback.format_exc());traceback.print_exc()
    finally:archive(run);code=run.finish(code)
    print('T20 '+run.manifest['status']+' '+str(run.path),flush=True);return code
if __name__=='__main__':sys.exit(main())
