#!/usr/bin/env python3
"""T19 real CPU/Coral model graph qualification and immutable archive checks."""
import argparse,hashlib,json,shutil,sys,tarfile,traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from evidence import EvidenceRun,StepFailure,sha256,content_id,write_json
from run_cocotb import environment
from run_t07 import simulate_batch
import run_t16
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tests/end_to_end'),str(ROOT/'tests/models'),str(ROOT/'tests/cocotb')]
from model_prepare import prepare
from prepare_image import parse_elf
from model_scoreboard import score
from cocotb_case import validate
from waveform import check_waveform

def inputs():
    files=run_t16.inputs()
    names=['scripts/run_t19.py','configs/t19-model-integration.json','docs/spec/model-integration-t19.md','scripts/complete_t19.py']
    for directory in ('tests/end_to_end','firmware/runtime/reference','firmware/runtime/port'):
        names += [str(p.relative_to(ROOT)) for p in (ROOT/directory).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc']
    names += ['tests/cocotb/test_model_integration.py','tests/reference/fixture_io.py','tests/reference/oracle.py','model_tools/numeric_v1.py','software/reference/runtime.py']
    files.update({n:sha256(ROOT/n) for n in names});return dict(sorted(files.items()))

def firmware(run,config,tools,profile,fw):
    out=run.build/'images'/profile;prepare(out,config,profile);src=ROOT/'firmware/drivers/accel';port=ROOT/'firmware/runtime/port';ref=ROOT/'firmware/runtime/reference';elf=out/'firmware.elf'
    flags=['-march=rv32imf_zicsr_zifencei','-mabi=ilp32f','-DHARD_FLOAT','-DNX_PORTABLE','-DNX_T19_BLOCK' if profile=='block' else '-DNX_T19_MINI',
        '-O2','-g','-ffp-contract=off','-fno-fast-math','-ffreestanding','-fno-builtin','-fno-pic','-fno-strict-aliasing','-ffunction-sections','-fdata-sections',
        '-nostdlib','-nostartfiles','-msmall-data-limit=0','-Wall','-Wextra','-Werror','-Wno-unknown-pragmas','-Wl,--build-id=none','-Wl,--gc-sections',f'-ffile-prefix-map={ROOT}=.']
    if profile=='smoke':flags+=['-DT19_SMOKE']
    run.execute('firmware-'+profile,[tools['rv32_gcc'],*flags,*sum((['-I',p] for p in [src,port,ref,ROOT/'software/include',fw,out]),[]),
        '-T',ROOT/'tests/soc_accel/link.ld',f'-Wl,-Map={out}/firmware.map',ROOT/'firmware/cpu/start.S',ROOT/'tests/end_to_end/firmware.c',
        ref/'nx_reference.c',port/'coral_backend.c',src/'accel.c',src/'target.c',src/'linear_api.c',src/'coral_linear.c','-lm','-lc','-lnosys','-lgcc','-o',elf],120)
    entry,segs,flags=parse_elf(elf.read_bytes(),base=0x10000,capacity=0xb8000000-0x10000)
    run.check('elf-'+profile,entry==0x10000 and flags==2 and all(0x10000<=s.address<s.address+s.memory_size<=0x20000 or 0xb4000000<=s.address<s.address+s.memory_size<=0xb4050000 for s in segs),'real RV32IMF, same source C graph, no golden linked')
    fixture=json.loads((out/'fixture.json').read_text());plan=(out/'data.plan').read_text()
    for i,s in enumerate(segs):
        p=out/f'cpu-segment-{i}.bin';p.write_bytes(s.data);fixture['regions'].append(dict(name=p.stem,address=s.address,bytes=len(s.data),path=str(p.resolve()),sha256=sha256(p),kind='firmware'))
        if s.data:plan+=f'B {s.address:x} {len(s.data):x} {p.resolve()}\n'
    fixture.update(elf_sha256=sha256(elf),coral_program_sha256=sha256(fw/'coral.elf'));write_json(out/'fixture.json',fixture);(out/'load.plan').write_text(plan);return out

def case(run,tools,config,name,images,sim,negative=None,launch=True):
    params=config['cases'].get(name,config['cases']['smoke-seed1']);d=run.build/'cocotb'/name;d.mkdir(parents=True)
    for p in sim.parent.glob('*.bin'):shutil.copy2(p,d/p.name)
    cfg=dict(task='T19',case_id=name,run_id=run.run_id,**params,python_prefix=sys.prefix,cocotb_version=config['cocotb_version'],test_mode='PRELOAD',negative=negative,
        max_cycles=2000 if negative=='held-reset' else config['max_cycles'],fixture=str(images/'fixture.json'),golden=str(images/'golden.json'),image_plan=str(images/'load.plan'),
        fixture_sha256=sha256(images/'fixture.json'),golden_sha256=sha256(images/'golden.json'),simulator_sha256=sha256(sim),effective_seeds={'vcs':params['seed'],'cocotb':params['seed'],'cpu_i':params['seed']^0x49,'cpu_d':params['seed']^0x44,'backend':params['seed']^0x4e})
    write_json(d/'case.json',cfg);job=dict(name='case-'+name,case=d,argv=[tools['python'],ROOT/'scripts/cocotb_case.py','--case',d/'case.json','--sim',sim],cost=10 if params['profile']=='block' else 5 if params['profile']=='continuous' else 1)
    if not launch:return job
    return run.execute(job['name'],job['argv'],config['timeouts_seconds']['simulation'],cwd=d)

def archive(run):
    if (run.build/'desktop').exists():shutil.copytree(run.build/'desktop',run.path/'artifacts/desktop',dirs_exist_ok=True)
    run_t16.archive(run)

def verify_archive(path):
    path=Path(path).resolve();m=json.loads((path/'manifest.json').read_text())
    if m.get('task_id')!='T19' or m.get('status')!='PASS' or m.get('exit_code')!=0 or (path/'exit-status.txt').read_text().strip()!='0':raise ValueError('not a completed T19 PASS')
    for n,h in m['artifacts'].items():
        p=(path/n).resolve()
        if not p.is_relative_to(path) or not p.is_file() or sha256(p)!=h:raise ValueError('artifact identity '+n)
    for name,key in [('commands.json',None),('checks.json','checks')]:
        rows=json.loads((path/name).read_text());rows=rows[key] if key else rows
        if not rows or any(r['status']!='PASS' for r in rows):raise ValueError('failed root results')
    files=m['source']['files']
    if content_id(files)!=m['source']['sha256']:raise ValueError('source digest')
    with tarfile.open(path/'source.tar.gz') as tar:
        if set(tar.getnames())!=set(files):raise ValueError('source inventory')
        for n,h in files.items():
            if hashlib.sha256(tar.extractfile(n).read()).hexdigest()!=h:raise ValueError('source content '+n)
        registered=json.load(tar.extractfile('configs/t19-model-integration.json'))
    cfg=json.loads((path/'config.json').read_text());suite=cfg['suite']
    if sha256(path/'config.json')!=m['config']['sha256'] or suite not in registered['suites'] or cfg!={**registered,'suite':suite,'selected_cases':registered['suites'][suite]} or set(m['cases'])!=set(cfg['selected_cases']):raise ValueError('registered matrix')
    count=0
    for name in cfg['selected_cases']:
        d=path/'artifacts/cocotb'/name;c=json.loads((d/'case.json').read_text());checks=validate(d,c)
        if c['task']!='T19' or c['run_id']!=m['run_id'] or c['negative'] is not None or any(c[k]!=v for k,v in cfg['cases'][name].items()):raise ValueError('case identity')
        folder=path/'artifacts/images'/c['profile']
        for key in ('fixture','golden'):
            if sha256(folder/(key+'.json'))!=c[key+'_sha256']:raise ValueError('fixture identity')
        got,_=score(d,json.loads((folder/'fixture.json').read_text()),json.loads((folder/'golden.json').read_text()),folder)
        if any(checks['result'].get(k)!=v for k,v in got.items()) or sha256(d/'transactions.csv')!=m['cases'][name]['sequence_sha256']:raise ValueError('independent score or trace identity')
        check_waveform(d);count+=checks['check_count']
    if suite!='smoke':
        if set(m.get('negatives',{}))!=set(cfg['negative_cases']):raise ValueError('negative matrix')
        if m['cases']['smoke-seed1']['sequence_sha256']!=m['cases']['smoke-seed1-replay']['sequence_sha256']:raise ValueError('deterministic replay')
        for name,r in m['negatives'].items():
            nd=Path(r['path']);nm=json.loads((nd/'manifest.json').read_text())
            if nm['status']!='FAIL' or nm['exit_code']!=1 or nm['negative']!=name:raise ValueError('negative raw failure')
            for rel,h in nm['artifacts'].items():
                if sha256(nd/rel)!=h:raise ValueError('negative artifact')
    if suite=='full':
        desktop=json.loads((path/'artifacts/desktop/result.json').read_text())
        if desktop['status']!='PASS' or desktop['cases']!=99 or desktop['contexts']!=[1,4,8,512] or desktop['actual_context_640_overflow_and_reset']!='PASS':raise ValueError('complete desktop model missing')
    return dict(status='PASS',suite=suite,cases=len(m['cases']),independent_checks=count)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--suite',choices=['smoke','regression','full'],default='full');p.add_argument('--run-id');p.add_argument('--verify-archive',type=Path);a=p.parse_args()
    if a.verify_archive:
        try:print(json.dumps(verify_archive(a.verify_archive),indent=2));return 0
        except Exception:traceback.print_exc();return 1
    run=EvidenceRun(ROOT,'T19',a.run_id);print('T19 evidence: '+str(run.path),flush=True);code=1
    try:
        files=inputs();run.manifest['source']=dict(files=files,sha256=content_id(files))
        with tarfile.open(run.path/'source.tar.gz','w:gz') as tar:
            for n in files:tar.add(ROOT/n,arcname=n,recursive=False)
        cfg=json.loads((ROOT/'configs/t19-model-integration.json').read_text());cfg.update(suite=a.suite,selected_cases=cfg['suites'][a.suite]);write_json(run.path/'config.json',cfg)
        run.manifest.update(config={'sha256':sha256(run.path/'config.json')},qualification=cfg['scope'],invocation=[sys.executable,*sys.argv])
        tools={k:v['path'] for k,v in json.loads((ROOT/'docs/spec/toolchain-lock.json').read_text())['tools'].items()};vpi=environment(run,cfg,tools)
        fw,sim=run_t16.build(run,cfg,tools,vpi);images={}
        for profile in dict.fromkeys([cfg['cases'][n]['profile'] for n in cfg['selected_cases']]+['smoke']):images[profile]=firmware(run,cfg,tools,profile,fw)
        if a.suite=='full':run.execute('desktop-full-model',[tools['python'],ROOT/'tests/end_to_end/desktop.py',run.build/'desktop'],3600,cwd=ROOT)
        jobs=[case(run,tools,cfg,n,images[cfg['cases'][n]['profile']],sim,launch=False) for n in cfg['selected_cases']];simulate_batch(run,jobs,cfg['timeouts_seconds']['simulation'],cfg['simulation_workers'])
        for name in cfg['selected_cases']:
            r=json.loads((run.build/'cocotb'/name/'checks.json').read_text());run.manifest.setdefault('cases',{})[name]=dict(status=r['status'],checks=r['check_count'],sequence_sha256=r['sequence_sha256'],result=r['result']);run.flush()
        if a.suite!='smoke':
            run.check('replay',run.manifest['cases']['smoke-seed1']['sequence_sha256']==run.manifest['cases']['smoke-seed1-replay']['sequence_sha256'],'complete actual CPU/backend handshake sequence')
            def negative(name):
                neg=EvidenceRun(ROOT,'T19_NEGATIVE',run.run_id+'-'+name);neg.manifest.update(parent=str(run.path),negative=name,expected='FAIL');rc=0
                try:case(neg,tools,cfg,name,images['smoke'],sim,name)
                except StepFailure as e:rc=e.exit_code
                finally:archive(neg);neg.finish(rc)
                d=neg.build/'cocotb'/name;status=json.loads((d/'case-status.json').read_text());needle={'empty':'required testcase identity/count mismatch','missing-xml':'missing/stale results.xml'}.get(name,'XML failure/error/skip')
                detected=rc==1 and needle in status.get('reason','')
                if name in ('held-reset','bad-golden','bad-kv'):detected &= json.loads((d/'checks.json').read_text())['first_failure']['category']=={'held-reset':'completion','bad-golden':'data','bad-kv':'kv'}[name]
                return name,detected,status,str(neg.path)
            with ThreadPoolExecutor(max_workers=cfg['simulation_workers']) as pool:
                for name,detected,status,path in pool.map(negative,cfg['negative_cases']):
                    run.check('negative-'+name,detected,status);run.manifest.setdefault('negatives',{})[name]=dict(path=path,reason=status.get('reason'));run.flush()
            run.execute('project-tests',[tools['make'],'test'],600,cwd=ROOT)
        run.check('source-unchanged',inputs()==files,'acceptance execution inputs stable');code=0
    except StepFailure as e:code=e.exit_code;(run.path/'failure.txt').write_text(str(e)+'\n')
    except KeyboardInterrupt:code=130
    except Exception:(run.path/'failure.txt').write_text(traceback.format_exc())
    finally:archive(run);code=run.finish(code)
    print('T19 '+run.manifest['status']+': '+str(run.path),flush=True);return code
if __name__=='__main__':sys.exit(main())
