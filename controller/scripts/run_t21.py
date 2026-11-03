#!/usr/bin/env python3
"""Unified smoke/regression/full entry and immutable sim-v1 acceptance bundle."""
import argparse,csv,io,json,os,re,shutil,sys,tarfile,time,traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from evidence import StepFailure,sha256,content_id,write_json
from run_t12 import RuntimeEvidence
from sim_v1 import read,receipt,current_sources,case_inventory,checked_path
ROOT=Path(__file__).resolve().parents[1]
CONFIG='configs/t21-sim-v1.json'

def sources():
    names=['Makefile','README.md','TOOLS.md','third_party/lock.json','third_party/coralnpu/hdl/chisel/src/bus/SpiMaster.scala','docs/reports/sim-v1-static-review.md','docs/reports/sim-v1-lint-sites.json','docs/reports/sim-v1-rebuild.md','evidence/T05/20261003T123546.536147Z-cfa58369/artifacts/vectors/index.json']
    for folder in ('scripts','configs','cpu_gen','firmware','rtl','software','model_tools','tests','docs/spec','third_party/coremark'):
        names += [str(p.relative_to(ROOT)) for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix not in ('.pyc','.tmp')]
    return {n:sha256(ROOT/n) for n in sorted(set(names))}

def audit(run,record,label,key):
    p=ROOT/record['path'];out=run.path/'audits'/(key+'.json');out.parent.mkdir(exist_ok=True)
    if record.get('manifest_sha256'):run.check('pin-'+key,sha256(p/'manifest.json')==record['manifest_sha256'],'original registered manifest unchanged')
    args=[sys.executable,ROOT/'scripts/t21_audit.py','--path',p,'--task',record['task'],'--classification',label,'--output',out]
    if record.get('expected')=='FAIL':args+=['--raw-fail']
    run.execute('audit-'+key,args,172800,cwd=ROOT);result=read(out)
    run.check('audit-result-'+key,result['status']=='PASS','semantic and source/XML/input identity audit')
    return result

def verify_archive(path):
    path=Path(path).resolve();m=receipt(path)
    if m.get('task_id')!='T21':raise ValueError('not T21')
    cfg=read(path/'config.json');frozen=read(path/'source-index.json')['files']
    if sha256(path/'config.json')!=m['config_sha256'] or frozen!=m['source']['files']:raise ValueError('frozen identity')
    if cfg['suite'] not in cfg['suites']:raise ValueError('suite')
    selected=cfg['suites'][cfg['suite']]['fresh']
    if set(m['current'])!=set(selected):raise ValueError('missing/extra current mandatory jobs')
    rows=read(path/'coverage.json')['cases']
    if not rows or not any(r['classification']=='CURRENT_EXECUTION' for r in rows):raise ValueError('empty coverage')
    for task,record in m['current'].items():
        if sha256(ROOT/record['path']/'manifest.json')!=record['manifest_sha256']:raise ValueError('current receipt changed '+task)
        cm=receipt(ROOT/record['path'])
        if cm['status']!='PASS' or cm['exit_code']!=0:raise ValueError('current failure')
        for n,h in cm.get('source',{}).get('files',{}).items():
            if frozen.get(n)!=h:raise ValueError('current source does not match frozen source '+n)
        if task!='T04':case_inventory(ROOT/record['path'],cm,'CURRENT_EXECUTION')
    if cfg['suite']=='full':
        if set(m['auxiliary'])!=set(cfg['required_auxiliary']):raise ValueError('missing auxiliary')
        for task,rec in m['auxiliary'].items():
            if sha256(ROOT/rec['path']/'manifest.json')!=rec['manifest_sha256']:raise ValueError('auxiliary identity')
            am=receipt(ROOT/rec['path'])
            for n,h in am.get('source',{}).get('files',{}).items():
                if frozen.get(n)!=h:raise ValueError('auxiliary source does not match frozen source '+n)
        for rec in read(path/'exploratory-failures.json'):
            receipt(ROOT/rec['path'],'FAIL',rec['manifest_sha256'],expected_exit=rec['exit_code'])
        expected={(r['task'],r['manifest_sha256']) for r in cfg['history']+cfg['supplementary']}
        actual={(r['task'],r['manifest_sha256']) for r in m['historical']}
        if expected!=actual:raise ValueError('missing historical evidence')
        for rec in m['historical']:
            if sha256(ROOT/rec['path']/'manifest.json')!=rec['manifest_sha256']:raise ValueError('historical manifest changed')
        for name,rec in read(path/'dependency-index.json')['records'].items():
            base=ROOT/name
            for artifact,h in rec['artifacts'].items():
                if sha256(checked_path(base,artifact))!=h:raise ValueError('dependency artifact changed '+name+'/'+artifact)
            for artifact,h in rec['receipt_files'].items():
                if sha256(checked_path(base,artifact))!=h:raise ValueError('dependency execution receipt changed '+name+'/'+artifact)
        non=read(path/'coverage-non-cocotb.json')
        if non['T04']['status']!='PASS' or len(non['T04']['cases'])!=9:raise ValueError('memory coverage missing')
        fresh_tasks={task:[r for r in rows if r['task']==task and r['classification']=='CURRENT_EXECUTION'] for task in selected}
        for task,records in fresh_tasks.items():
            if task=='T04':continue
            suite=selected[task];actual_names=[r['case_id'] for r in records];child_cfg=read(ROOT/m['current'][task]['path']/'config.json')
            if set(actual_names)!=set(child_cfg['suites'][suite]) or len(actual_names)!=len(set(actual_names)):raise ValueError('current coverage matrix '+task)
        controls=read(path/'archive-controls.json')
        if controls['status']!='PASS' or controls['detected']<6:raise ValueError('negative gate controls')
    for r in rows:
        if r['checks']<=0 or r['exit_code']!=0:raise ValueError('invalid case')
        if sha256(r['xml'])!=r['xml_sha256']:raise ValueError('changed XML')
        if sha256(Path(r['xml']).parent/'checks.json')!=r['checks_sha256']:raise ValueError('changed case checks')
    return dict(status='PASS',suite=cfg['suite'],closes_milestone=cfg['suite']=='full',current_tasks=len(m['current']),cases=len(rows),independent_checks=sum(r['checks'] for r in rows),source_sha256=m['source']['sha256'])

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--suite',choices=['smoke','regression','full'],default='full');p.add_argument('--run-id');p.add_argument('--verify-archive',type=Path);p.add_argument('--receive-current',type=Path,help='explicit paths to independently executed current-source runs; never relabel or overwrite them');a=p.parse_args(argv)
    if a.verify_archive:
        try:print(json.dumps(verify_archive(a.verify_archive),indent=2));return 0
        except Exception:traceback.print_exc();return 1
    r=RuntimeEvidence(ROOT,'T21',a.run_id);start=time.monotonic();code=1;print('T21 evidence '+str(r.path),flush=True)
    try:
        cfg=read(ROOT/CONFIG);cfg['suite']=a.suite;write_json(r.path/'config.json',cfg);r.manifest['config_sha256']=sha256(r.path/'config.json')
        files=sources();r.manifest['source']=dict(files=files,sha256=content_id(files));write_json(r.path/'source-index.json',dict(files=files,sha256=content_id(files)))
        # Exclusive creation plus a new EvidenceRun directory; Git is unnecessary.
        with (r.path/'source.tar.gz').open('xb') as stream:
            with tarfile.open(fileobj=stream,mode='w:gz') as tar:
                for n in files:tar.add(ROOT/n,arcname=n,recursive=False)
        (r.path/'source.tar.gz').chmod(0o444)
        shutil.copy2(ROOT/'docs/plan/tasks.json',r.path/'input-task-register.json')
        resources=dict(affinity=sorted(os.sched_getaffinity(0)),logical_cpus=os.cpu_count(),load=os.getloadavg(),meminfo=Path('/proc/meminfo').read_text(),cgroup=Path('/proc/self/cgroup').read_text(),cpu_max=Path('/sys/fs/cgroup/cpu.max').read_text() if Path('/sys/fs/cgroup/cpu.max').exists() else 'root cgroup: no cpu.max limit',memory_max=Path('/sys/fs/cgroup/memory.max').read_text() if Path('/sys/fs/cgroup/memory.max').exists() else 'root cgroup: no memory.max limit')
        write_json(r.path/'resources.json',resources);r.check('resources',len(resources['affinity'])>=2,'record CPU quota, memory and load before scheduling')
        log=r.execute('license',['lmutil','lmstat','-a','-c',os.environ['SNPSLMD_LICENSE_FILE']],90)
        license_text=log.read_text();seats=re.findall(r'Users of (VCS\S*):.*?Total of (\d+) licenses? issued;\s+Total of (\d+) licenses? in use',license_text)
        r.check('license-ready','license server UP' in license_text and 'snpslmd: UP' in license_text and any(int(n)>int(u) for _,n,u in seats),dict(features=seats))
        received=read(a.receive_current) if a.receive_current else {};current={};aux={};rows=[];history=[];non_cocotb={}
        write_json(r.path/'received-runs.json',received)
        history_pool=ThreadPoolExecutor(max_workers=2)
        historical_futures=[]
        if a.suite=='full':
            for i,rec in enumerate(cfg['history']+cfg['supplementary']):historical_futures.append(history_pool.submit(audit,r,rec,'HISTORICAL_INPUT' if i<len(cfg['history']) else 'SUPPLEMENTARY','history-'+str(i)))
        def execute_job(item):
            task,suite=item;job=next(j for j in cfg['fresh_jobs'] if j['task']==task);rid=r.run_id+'-'+task.lower();path=received.get(task)
            if path is None:
                args=[sys.executable,ROOT/job['runner'],'--run-id',rid]
                if task=='T09':args+=['--task',task]
                if suite:args+=['--suite',suite]
                r.execute('execute-'+task.lower(),args,604800,cwd=ROOT);path='evidence/'+task+'/'+rid
            m=read(ROOT/path/'manifest.json')
            if m['status']=='RUNNING':r.execute('await-'+task.lower(),[sys.executable,ROOT/'scripts/t21_wait_receipt.py',ROOT/path],604800,cwd=ROOT);m=read(ROOT/path/'manifest.json')
            r.check('current-status-'+task.lower(),m['task_id']==task and m['status']=='PASS' and m['exit_code']==0,path)
            r.check('current-source-'+task.lower(),not current_sources(ROOT,m),'every actual execution input matches frozen current bytes')
            r.check('current-frozen-source-'+task.lower(),all(files.get(n)==h for n,h in m.get('source',{}).get('files',{}).items()),'all actual inputs are present in the frozen snapshot')
            if suite:
                config=read(ROOT/path/'config.json');r.check('current-suite-'+task.lower(),config['suite']==suite,'exact registered suite, no filtered partial matrix')
            record=dict(task=task,path=path,manifest_sha256=sha256(ROOT/path/'manifest.json'))
            result=audit(r,record,'CURRENT_EXECUTION','current-'+task.lower());return task,record,result
        # Task lanes contain independent build/output paths. Each task internally
        # reuses only its own compiled image. Long directed cases run once.
        with ThreadPoolExecutor(max_workers=cfg['task_workers']) as pool:
            for task,record,result in pool.map(execute_job,cfg['suites'][a.suite]['fresh'].items()):
                current[task]=record;rows+=result['cases'];r.manifest['current']=current;r.flush()
                if result.get('non_cocotb'):non_cocotb[task]=result['non_cocotb']
        if a.suite=='full':
            for future in historical_futures:
                result=future.result();history.append(result);rows+=result['cases']
            history_pool.shutdown()
            for task in cfg['required_auxiliary']:
                path=received.get(task);rid=r.run_id+'-'+task.lower()
                if path is None:
                    args={'T21_COREMARK':[ROOT/'scripts/run_coremark.py'], 'T21_STATIC':[ROOT/'scripts/t21_static.py','--cpu-build',ROOT/current['T19']['path'].replace('evidence/','build/',1),'--cpu-variants-build',ROOT/current['T09']['path'].replace('evidence/','build/',1)],'T21_HEAD_IDENTITY':[ROOT/'scripts/t21_head_identity.py','--current-build',ROOT/current['T16']['path'].replace('evidence/','build/',1)],'T21_PERFORMANCE':[ROOT/'scripts/t21_performance.py','--current-build',ROOT/current['T20']['path'].replace('evidence/','build/',1)],'T21_CORAL_PERFORMANCE':[ROOT/'scripts/t21_coral_perf.py','--current-build',ROOT/current['T19']['path'].replace('evidence/','build/',1)]}[task]
                    r.execute('execute-'+task.lower(),[sys.executable,*args,'--run-id',rid],7200,cwd=ROOT);path='evidence/'+task+'/'+rid
                if read(ROOT/path/'manifest.json')['status']=='RUNNING':r.execute('await-'+task.lower(),[sys.executable,ROOT/'scripts/t21_wait_receipt.py',ROOT/path],604800,cwd=ROOT)
                record=dict(task=task,path=path,manifest_sha256=sha256(ROOT/path/'manifest.json'));result=audit(r,record,'SUPPLEMENTARY','aux-'+task.lower());aux[task]=record
                m=read(ROOT/path/'manifest.json')
                r.check('aux-source-'+task.lower(),not current_sources(ROOT,m),'auxiliary source inputs unchanged')
                if task=='T21_STATIC':
                    r.check('static-input-identities',all(Path(n).is_file() and sha256(n)==h for n,h in m['inputs'].items()),'actual lint/inventory inputs')
                    dest=r.path/'frozen-static-inputs';dest.mkdir();index={}
                    for i,(name,h) in enumerate(m['inputs'].items()):
                        target=dest/(str(i)+'-'+Path(name).name);shutil.copy2(name,target);index[name]=dict(sha256=h,snapshot=str(target.relative_to(r.path)))
                    write_json(r.path/'static-input-index.json',index)
            r.execute('gate-unit-tests',[sys.executable,'-m','unittest','discover','-s',ROOT/'tests/sim_v1','-v'],120,cwd=ROOT)
            r.execute('project-tests',['make','test'],600,cwd=ROOT)
            # Six material rejection tests are executed by the unit suite.
            testlog=(r.path/'logs/gate-unit-tests.stderr.log').read_text();n=int(re.search(r'Ran (\d+) tests',testlog).group(1));r.check('nonempty-gate-tests',n>=6,'archive corruption and coverage rejection')
            write_json(r.path/'archive-controls.json',dict(status='PASS',tests=n,detected=n-1,log='logs/gate-unit-tests.stderr.log'))
            # Pin failed exploratory probes separately; these are never functional PASS.
            failures=[]
            perf=read(ROOT/aux['T21_PERFORMANCE']['path']/'performance.json')
            for record in perf['internal']:
                if record.get('raw_exit_code'):
                    receipt(ROOT/record['evidence'],'FAIL',record['manifest_sha256'],expected_exit=record['raw_exit_code'])
                    failures.append(dict(path=record['evidence'],manifest_sha256=record['manifest_sha256'],exit_code=record['raw_exit_code'],scope='EXPLORATORY_FGP_ONLY'))
            write_json(r.path/'exploratory-failures.json',failures)
            # Freeze the actual reusable dependencies, independently of root Git.
            depdir=r.path/'frozen-dependencies';depdir.mkdir();external={}
            build=ROOT/current['T19']['path'].replace('evidence/','build/',1)
            pack=read(ROOT/'docs/spec/model-pack-v1-manifest.json')
            inputs={'vexriscv-source.tar':ROOT/current['T19']['path']/'vexriscv-source.tar','coral-rtl.zip':ROOT/current['T19']['path']/'coral-rtl.zip','coral-source.tar.gz':ROOT/current['T19']['path']/'coral-source.tar.gz','model.nxpack':ROOT/pack['pack_path']}
            for name,original in inputs.items():
                shutil.copy2(original,depdir/name);(depdir/name).chmod(0o444);external[name]=dict(original_path=str(original),sha256=sha256(depdir/name),bytes=(depdir/name).stat().st_size)
            r.check('managed-model-identity',external['model.nxpack']['sha256']==pack['sha256'],'complete W8 model format and payload')
            vex=read(ROOT/'third_party/lock.json')['dependencies']['VexRiscv'];r.execute('upstream-bundle',['git','-C',vex['path'],'bundle','create',depdir/'vexriscv.bundle','--all'],120)
            r.execute('upstream-bundle-verify',['git','-C',vex['path'],'bundle','verify',depdir/'vexriscv.bundle'],60)
            external['vexriscv.bundle']=dict(original_path=vex['path'],commit=vex['commit'],sha256=sha256(depdir/'vexriscv.bundle'),bytes=(depdir/'vexriscv.bundle').stat().st_size);write_json(r.path/'external-inputs.json',external)
        r.manifest.update(current=current,auxiliary=aux,historical=[{k:v for k,v in x.items() if k!='cases'} for x in history],qualification=dict(milestone='sim-v1' if a.suite=='full' else 'DAILY_'+a.suite.upper(),board='NOT_TESTED',dedicated_cdc_rdc='NOT_SIGNED_OFF'))
        write_json(r.path/'coverage.json',dict(status='PASS',cases=rows,current_cases=sum(x['classification']=='CURRENT_EXECUTION' for x in rows),historical_cases=sum(x['classification']=='HISTORICAL_INPUT' for x in rows),independent_checks=sum(x['checks'] for x in rows),note='Counts distinguish current execution from original historical inputs; never a count of unique logical properties.'))
        write_json(r.path/'coverage-non-cocotb.json',non_cocotb)
        with (r.path/'coverage.csv').open('w') as stream:
            fields=['task','case_id','classification','original_run_id','seed','test_mode','checks','exit_code','xml','xml_sha256','source_sha256','simulator_sha256'];w=csv.DictWriter(stream,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(rows)
        # Record every source transition; current affected regression is above.
        write_json(r.path/'source-transitions.json',[dict(task=x['task'],path=x['path'],source_sha256=x.get('source_sha256'),changes=x.get('source_drift',{})) for x in history])
        mapping={}
        for record in list(current.values())+list(aux.values()):
            m=read(ROOT/record['path']/'manifest.json');mapping[record['task']]=dict(record,source=m.get('source'),firmware={n:h for n,h in m.get('artifacts',{}).items() if n.endswith(('.elf','.bin','.v'))},vpi=m.get('vpi'),compiler=m.get('compiler'))
        write_json(r.path/'version-map.json',dict(version='sim-v1',source_sha256=content_id(files),model=read(ROOT/'docs/spec/model-pack-v1-manifest.json'),numeric=sha256(ROOT/'docs/spec/numeric-v1.md'),backend_api=sha256(ROOT/'docs/spec/backend-contract-v1.md'),runtime_api=sha256(ROOT/'docs/spec/runtime-v1.md'),mapping=mapping))
        dependencies={}
        upstream=[dict(path='evidence/T05/20261003T123546.536147Z-cfa58369'),dict(path=read(ROOT/'configs/t19-model-integration.json')['input_t06'])] if a.suite=='full' else []
        for rec in cfg['history']+cfg['supplementary']+list(current.values())+list(aux.values())+upstream:
            p=ROOT/rec['path'];m=read(p/'manifest.json');dependencies[str(p.relative_to(ROOT))]=dict(manifest_sha256=sha256(p/'manifest.json'),artifacts=m.get('artifacts',{}),receipt_files={n:sha256(p/n) for n in ('commands.json','checks.json','exit-status.txt') if (p/n).is_file()},managed_artifacts=m.get('managed_artifacts',{}),prerequisites=m.get('prerequisites',{}))
        write_json(r.path/'dependency-index.json',dict(scope='Original evidence and managed model files are inputs, not new T21 executions or compile caches',records=dependencies,external_toolchain='docs/spec/toolchain-lock.json',upstream_lock='third_party/lock.json'))
        r.check('source-unchanged',sources()==files,'all frozen execution inputs remain unchanged');r.manifest['wall_seconds']=round(time.monotonic()-start,3);code=0
    except Exception:(r.path/'failure.txt').write_text(traceback.format_exc());traceback.print_exc()
    finally:
        r.manifest['artifacts']={str(p.relative_to(r.path)):sha256(p) for p in r.path.rglob('*') if p.is_file() and str(p.relative_to(r.path)) not in ('manifest.json','checks.json','commands.json','exit-status.txt')};code=r.finish(code)
    print('T21 '+r.manifest['status']+' '+str(r.path),flush=True);return code
if __name__=='__main__':sys.exit(main())
