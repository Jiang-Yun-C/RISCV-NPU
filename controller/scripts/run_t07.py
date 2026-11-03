#!/usr/bin/env python3
"""T07: freshly compile accepted RVV RTL, qualify AXI128/ID6 and stream T05 data."""
import argparse
import csv
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import time
import traceback
import zipfile
from coral_rtl import apply_patches, input_paths as coral_patch_inputs
from evidence import EvidenceRun, StepFailure, content_id, sha256, write_json, utc_now

ROOT=Path(__file__).resolve().parents[1]
CHECK=ROOT/'tests/coral_external/check.py'
RTL=['rtl/interfaces/axi4_if.sv','tests/models/sparse_memory_pkg.sv','tests/models/axi_sparse_mem.sv']

def inputs():
    names=['Makefile','scripts/run_t07.py','scripts/evidence.py','scripts/probe_tools.py','configs/t07-external.json',
        'docs/spec/toolchain-lock.json','docs/spec/numeric-v1.md','configs/t05-thresholds.json',
        'docs/spec/application-v2-model-lock.json','docs/spec/coral-t06-contract.md','docs/spec/backend-t07-probe.md','third_party/lock.json',
        'tests/coral/start.S','tests/coral/link.ld','tests/models/prepare_image.py','tests/soc/soc_memory_env.sv',
        'tests/axi/tb_axi.sv','tests/axi/make_workload.py','tests/axi/check_axi.py']+RTL
    names += [str(p.relative_to(ROOT)) for p in (ROOT/'tests/coral_external').rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    names += coral_patch_inputs()
    return {n:sha256(ROOT/n) for n in sorted(set(names))}

def preserve(run):
    out=run.path/'artifacts';out.mkdir(exist_ok=True)
    for p in run.build.iterdir():
        if p.is_dir() and p.name.startswith(('case-','image-','stimulus-')):shutil.copytree(p,out/p.name,dirs_exist_ok=True)
        elif p.is_file() and p.suffix in ('.elf','.dis','.json','.zip','.h'):shutil.copy2(p,out/p.name)
    run.manifest['artifacts']={str(p.relative_to(run.path)):sha256(p) for p in run.path.rglob('*')
        if p.is_file() and p.name not in ('manifest.json','checks.json','commands.json','exit-status.txt')}

def negative(parent, good, image, mutation, needle, py):
    child=EvidenceRun(ROOT,'T07_NEGATIVE',parent.run_id+'-'+mutation)
    child.manifest.update(source=parent.manifest['source'],config=parent.manifest['config'],checker=parent.manifest['checker'],
        parent=str(parent.path.relative_to(ROOT)),seed=1,test_mode='EXPECTED_FAILURE',qualification='NEGATIVE_CONTROL_ONLY')
    for name in ('source.tar.gz','config.json'):shutil.copy2(parent.path/name,child.path/name)
    case=child.build/'case-corrupt';shutil.copytree(good,case);(case/'check.json').unlink(missing_ok=True)
    code=1;rejected=False
    try:
        if mutation=='done':
            meta=json.loads((image/'image.json').read_text());row=(meta['symbols']['done']['address']-0x10000)//16
            p=case/'dtcm.hex';rows=p.read_text().splitlines();rows[row]='0'*32;p.write_text('\n'.join(rows)+'\n')
        else:
            p=case/'external.csv'
            with p.open() as f:r=csv.DictReader(f);fields=r.fieldnames;rows=list(r)
            if mutation=='truncated':rows=rows[:-1]
            elif mutation=='read-data':
                row=next(r for r in rows if r['ch']=='R');row['data']=f'{int(row["data"],16)^1:x}'
            else:
                target='a1000000' if mutation=='integer' else 'a0000000';pending=[];changed=False
                for row in rows:
                    if row['ch']=='AW':pending.append(row['addr'])
                    elif row['ch']=='W':
                        addr=pending.pop(0)
                        if addr==target:
                            row['data']='7f800000' if mutation=='float' else f'{int(row["data"],16)^1:x}'
                            changed=True;break
                if not changed:raise ValueError('negative mutation target not reached')
            with p.open('w') as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
        child.execute('check-corrupt',[py,CHECK,case,image,parent.build/'linear.dis'],120)
        code=0
    except StepFailure as e:
        code=e.exit_code;logs=''.join(p.read_text(errors='replace') for p in (child.path/'logs').glob('*.log'));rejected=needle in logs
        (child.path/'failure.txt').write_text(str(e)+'\n')
    finally:preserve(child);child.finish(code)
    parent.manifest.setdefault('negative_runs',[]).append(str(child.path.relative_to(ROOT)))
    parent.check('reject-'+mutation,rejected and child.manifest['status']=='FAIL' and not (case/'check.json').exists(),needle)

def simulate_batch(run,jobs,timeout,workers):
    """Independent simulator processes; all evidence metadata has one writer."""
    pending=iter(sorted(jobs,key=lambda j:j['cost'],reverse=True));active=[];exhausted=False;failed=[]
    try:
        while active or not exhausted:
            while len(active)<workers and not exhausted:
                job=next(pending,None)
                if job is None:exhausted=True;break
                name=job['name'];record=dict(name=name,argv=[str(a) for a in job['argv']],cwd=str(job['case']),
                    timeout_seconds=timeout,started_at=utc_now(),status='RUNNING',stdout=f'logs/{name}.stdout.log',stderr=f'logs/{name}.stderr.log')
                out=(run.path/record['stdout']).open('w');err=(run.path/record['stderr']).open('w')
                proc=subprocess.Popen(record['argv'],cwd=job['case'],stdout=out,stderr=err,start_new_session=True)
                run.steps.append(record);active.append((proc,record,time.monotonic(),out,err));run.flush()
            for item in active[:]:
                proc,rec,start,out,err=item;code=proc.poll()
                if code is None and time.monotonic()-start>timeout:
                    EvidenceRun._kill_group(proc);code=124;err.write('TIMEOUT; process group killed\n')
                if code is None:continue
                out.close();err.close();rec.update(exit_code=code,process_returncode=proc.returncode,finished_at=utc_now(),
                    duration_seconds=round(time.monotonic()-start,3),status='PASS' if code==0 else 'FAIL')
                run.checks.append(dict(name=rec['name'],status=rec['status'],detail=dict(exit_code=code)))
                if code:failed.append((rec['name'],code))
                active.remove(item);run.flush();print(rec['name']+' '+rec['status'],flush=True)
            if active:time.sleep(0.2)
    finally:
        for proc,rec,start,out,err in active:
            EvidenceRun._kill_group(proc);out.close();err.close()
            rec.update(exit_code=130,status='FAIL',finished_at=utc_now());run.flush()
    if failed:raise StepFailure(*failed[0])

def execute(run,cfg,probe):
    tools=json.loads((ROOT/'docs/spec/toolchain-lock.json').read_text())['tools'];py=tools['python']['path']
    source=ROOT/cfg['input_t06'];t05=ROOT/cfg['input_t05'];t06=json.loads((source/'manifest.json').read_text())
    run.check('prerequisite-status',t06['status']=='PASS' and json.loads((t05/'manifest.json').read_text())['status']=='PASS','accepted T05/T06 runs')
    run.manifest['prerequisites']={str(p.relative_to(ROOT)):sha256(p/'manifest.json') for p in (source,t05)}
    run.execute('tool-probe',[py,ROOT/'scripts/probe_tools.py','--root',ROOT,'--output',run.build/'tool-report.json'],60)
    top=cfg['top'];z=source/'artifacts'/(top+'.zip')
    for p in (z,source/'coral-source.tar.gz'):
        run.check('input-'+p.name.replace('.','-'),sha256(p)==t06['artifacts'][str(p.relative_to(source))],'accepted T06 artifact identity')
    shutil.copy2(source/'coral-source.tar.gz',run.path/'coral-source.tar.gz')
    shutil.copy2(z,run.build/z.name)
    rtl=run.build/'rtl';rtl.mkdir()
    with zipfile.ZipFile(z) as archive:
        run.check('safe-rtl-archive',all(not Path(n).is_absolute() and '..' not in Path(n).parts for n in archive.namelist()),'relative members')
        archive.extractall(rtl)
    apply_patches(run, rtl)
    commands=json.loads((source/'commands.json').read_text());gcc=Path(next(s['argv'][0] for s in commands if s['name']=='compile-vector'))
    objdump=gcc.with_name('riscv64-unknown-elf-objdump')
    run.check('compiler-identity',sha256(gcc)==t06['compiler']['sha256'] and sha256(objdump)==t06['compiler']['objdump_sha256'],t06['compiler'])
    run.manifest['compiler']=t06['compiler'];run.manifest['coral']=t06['coral'];run.flush()
    # The only DPI code is the same SRAM byte storage model accepted by T06.
    sram=ROOT/'third_party/coralnpu/hdl/verilog/sram_backdoor.cc'
    with tarfile.open(source/'coral-source.tar.gz') as tar:
        raw=tar.extractfile('hdl/verilog/sram_backdoor.cc').read()
        (rtl/'sram_backdoor.h').write_bytes(tar.extractfile('hdl/verilog/sram_backdoor.h').read())
    (rtl/'sram_backdoor.cc').write_bytes(raw)
    run.execute('compile-firmware',[gcc,f'-march={cfg["march"]}',f'-mabi={cfg["mabi"]}','-O2','-fno-tree-vectorize',
        '-ffp-contract=off','-fno-fast-math','-msmall-data-limit=0','-ffreestanding','-nostdlib','-Wl,--no-relax',
        '-T',ROOT/'tests/coral/link.ld',ROOT/'tests/coral/start.S',ROOT/'tests/coral_external/linear.c','-o',run.build/'linear.elf'],60)
    log=run.execute('disassemble',[objdump,'-d',run.build/'linear.elf'],30);shutil.copy2(log,run.build/'linear.dis')
    vcs=[tools['vcs']['path'],'-full64','-sverilog','-timescale=1ns/1ps','-debug_access+all',
         '-cc',tools['vcs_host_cc']['path'],'-cpp',tools['vcs_host_cxx']['path']]
    mem_build=run.build/'memory';mem_build.mkdir()
    run.execute('compile-axi128',vcs+['+define+AXI_DATA_W=128','+define+AXI_ID_W=6','-top','tb_axi',
        *[ROOT/p for p in RTL],ROOT/'tests/soc/soc_memory_env.sv',ROOT/'tests/axi/tb_axi.sv','-o',mem_build/'simv'],cfg['timeouts_seconds']['compile'],cwd=mem_build)
    stimulus=run.build/'stimulus-axi128'
    run.execute('prepare-axi128',[py,ROOT/'tests/axi/make_workload.py',stimulus,'--width',128,'--id-bits',6],60)
    work=json.loads((stimulus/'workload.json').read_text());run.manifest['memory_cases']=[]
    for seed in (1,7):
        case=run.build/f'case-axi128-seed{seed}';case.mkdir()
        log=run.execute(f'axi128-{seed}',[mem_build/'simv','-no_save',f'+seed={seed}',f'+ntb_random_seed={seed}',
            '+random_delays=1',f'+stimulus={stimulus}',f'+image_plan={stimulus}/image/load.plan','+mode=PRELOAD',
            f'+writes={len(work["writes"])}',f'+reads={len(work["reads"])}'],60,cwd=case)
        run.check(f'axi128-complete-{seed}','T04_AXI_PASS' in log.read_text(),'explicit complete marker')
        run.execute(f'check-axi128-{seed}',[py,ROOT/'tests/axi/check_axi.py',case,stimulus/'workload.json'],60)
        run.manifest['memory_cases'].append(dict(name=case.name,result=json.loads((case/'axi-check.json').read_text())))
    # Explicit TB dumps/monitors remain; avoid retaining writable debug access
    # to every internal RVV net in multi-million-cycle performance runs.
    log=run.execute('compile-rvv',[v for v in vcs if v!='-debug_access+all']+['-CFLAGS','-std=c++17','+define+VCS',f'+define+CORAL_TOP={top}',
        '-top','tb_external','-f','filelist.f',*[ROOT/p for p in RTL],ROOT/'tests/coral_external/tb_external.sv',rtl/'sram_backdoor.cc',
        '-o',run.build/'simv'],cfg['timeouts_seconds']['compile'],cwd=rtl)
    run.check('vcs-version',tools['vcs']['expected_version'] in log.read_text(),'locked VCS')
    vectors=t05/'artifacts/vectors';cases=[];images={};jobs=[]
    matrix=[('k',1,0,None,'ideal',1,1,1)]
    if not probe:
        for fam,n in [('q',896),('k',128),('gate',4864),('down',896)]:
            for m in (1,4):
                if (fam,m)==('k',1):continue
                for row in range(0,n,cfg['output_tile_rows']):
                    matrix.append((fam,m,row,min(cfg['output_tile_rows'],n-row),'ideal',1,1,1))
        matrix += [('head',m,t['row'],t['rows'],'ideal',1,1,1) for t in cfg['head_tiles'] for m in (1,4)]
        matrix += [('k',m,0,None,p,1,1,1) for p in ('latency20','bandwidth16','contended') for m in (1,4)]
        matrix += [('k',1,0,None,'contended',1,1,s) for s in (1,7)]
        matrix += [('k',m,0,None,'ideal',0,1,1) for m in (1,4)]
        matrix += [('k',1,0,None,'ideal',1,0,1)]
    for fam,m,row,rows,profile,audit,restore,seed in matrix:
        key=f'{fam}-m{m}-row{row}-rows{rows if rows is not None else "all"}-audit{audit}-restore{restore}'
        if key not in images:
            im=run.build/('image-'+key)
            args=[py,ROOT/'tests/coral_external/prepare.py',run.build/'linear.elf',vectors,im,'--family',fam,'--m',m,'--row',row,'--audit',audit,'--restore',restore]
            if rows is not None:args+=['--rows',rows]
            run.execute('prepare-'+key,args,60);images[key]=im
        im=images[key];meta=json.loads((im/'image.json').read_text());timing=cfg['profiles'][profile]
        name=f'case-{len(jobs):03d}-{key}-{profile}-seed{seed}';case=run.build/name;case.mkdir()
        args=[run.build/'simv','-no_save',f'+image={im}/load.hex',f'+image_plan={im}/load.plan',f'+entry={meta["entry"]:x}',
            '+mode=PRELOAD',f'+seed={seed}',f'+ntb_random_seed={seed}',f'+mem_latency={timing["latency"]}',
            f'+mem_interval={timing["interval"]}',f'+mem_ready_period={timing["ready_period"]}',
            f'+random_delays={timing["random_delays"]}',f'+max_delay={timing["max_delay"]}']
        jobs.append(dict(name=name,case=case,image=im,profile=profile,seed=seed,timing=timing,argv=args,
            cost=meta['n']*meta['k']*(meta['m']+4)))
    simulate_batch(run,jobs,cfg['timeouts_seconds']['run'],1 if probe else cfg['simulation_workers'])
    for job in jobs:
        name=job['name'];case=job['case'];im=job['image'];log=run.path/f'logs/{name}.stdout.log'
        run.check(name+'-complete','T07_EXECUTED' in log.read_text() and 'Fatal:' not in log.read_text(),'real RTL halted without fault')
        run.execute(name+'-check',[py,CHECK,case,im,run.build/'linear.dis'],cfg['timeouts_seconds']['check'])
        cases.append(dict(name=name,image=im.name,profile=job['profile'],seed=job['seed'],timing=job['timing'],result=json.loads((case/'check.json').read_text())))
        run.manifest['cases']=cases;run.flush()
    if not probe:
        same=[c for c in cases if c['profile']=='contended' and c['result']['shape_MKN'][0]==1]
        run.check('deterministic-replay',same[0]['result']['trace_sha256']==same[1]['result']['trace_sha256'],'identical seed complete event trace')
        run.check('different-timing-same-result',same[0]['result']['trace_sha256']!=same[2]['result']['trace_sha256'] and len({c['result']['result_sha256'] for c in same})==1,'seed 7 changes timing only')
        for mutation,needle in [('integer','integer dot mismatch'),('float','FP32 tolerance failure'),
            ('read-data','external read data mismatch'),('truncated','missing completion'),('done','firmware completion marker')]:
            negative(run,run.build/cases[0]['name'],run.build/cases[0]['image'],mutation,needle,py)
        run.execute('t04-regression',['make','t04'],600,cwd=ROOT)
        run.execute('project-regression',['make','test'],120,cwd=ROOT)
    run.manifest['coverage']='SINGLE_PROBE' if probe else 'FULL_T07_MATRIX'

def main():
    p=argparse.ArgumentParser();p.add_argument('--run-id');p.add_argument('--probe',action='store_true');a=p.parse_args()
    run=EvidenceRun(ROOT,'T07_PROBE' if a.probe else 'T07',a.run_id);print(run.path,flush=True);code=1
    try:
        cfg=json.loads((ROOT/'configs/t07-external.json').read_text());files=inputs();write_json(run.path/'config.json',cfg)
        run.manifest.update(source=dict(files=files,sha256=content_id(files),snapshot='source.tar.gz'),config=dict(sha256=sha256(run.path/'config.json')),
            checker=dict(sha256=sha256(CHECK)),seed=cfg['seed'],test_mode='AXI_SUBORDINATE_LOAD_PLUS_EXTERNAL_PRELOAD',qualification=cfg['qualification'],conclusion='NOT_EVALUATED')
        with tarfile.open(run.path/'source.tar.gz','w:gz') as tar:
            for name in files:tar.add(ROOT/name,arcname=name)
        run.flush();execute(run,cfg,a.probe)
        run.check('source-stable',inputs()==files,'source unchanged during acceptance')
        code=0;run.manifest['conclusion']='PROBE_PASS' if a.probe else 'PASS_RVV_EXTERNAL_OPERATORS'
    except StepFailure as e:code=e.exit_code;(run.path/'failure.txt').write_text(str(e)+'\n')
    except KeyboardInterrupt:code=130
    except Exception:(run.path/'failure.txt').write_text(traceback.format_exc())
    finally:preserve(run);code=run.finish(code)
    print(json.dumps(dict(status=run.manifest['status'],evidence=str(run.path),exit_code=code)),flush=True);return code

if __name__=='__main__':raise SystemExit(main())
