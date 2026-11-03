"""Fail-closed sim-v1 provenance and per-case inventory (no RTL arithmetic)."""
import hashlib,json,tarfile
from pathlib import Path
import xml.etree.ElementTree as ET
from evidence import content_id,sha256

def read(path):return json.loads(Path(path).read_text())

def checked_path(base,name):
    p=(Path(base)/name).resolve()
    if not p.is_relative_to(Path(base).resolve()) or not p.is_file():raise ValueError('missing/unsafe artifact '+str(name))
    return p

def receipt(path,expected='PASS',manifest_hash=None,source_snapshot=None,expected_exit=None,allow_no_commands=False,source_snapshot_extras=None):
    path=Path(path).resolve();m=read(path/'manifest.json')
    if manifest_hash and sha256(path/'manifest.json')!=manifest_hash:raise ValueError('manifest identity '+str(path))
    rc=expected_exit if expected_exit is not None else 0 if expected=='PASS' else 1
    if m['status']!=expected or m['exit_code']!=rc or (path/'exit-status.txt').read_text().strip()!=str(rc):raise ValueError('unfinished/incorrect status '+str(path))
    if m['run_id']!=path.name:
        original=m.get('requalification',{}).get('original_evidence')
        if not original or Path(original).name!=m['run_id'] or not m.get('metadata_finalization'):raise ValueError('relabeled run-id '+str(path))
    commands=read(path/'commands.json');checks=read(path/'checks.json')['checks']
    if (not commands and not allow_no_commands) or not checks:raise ValueError('empty execution '+str(path))
    if expected=='PASS' and any(s['status']!='PASS' or s.get('exit_code',0)!=0 for s in commands+checks):raise ValueError('failed commands/checks '+str(path))
    for n,h in m.get('artifacts',{}).items():
        if sha256(checked_path(path,n))!=h:raise ValueError('artifact hash '+str(path/n))
    source=m.get('source',{})
    if source.get('files'):
        if content_id(source['files'])!=source['sha256']:raise ValueError('source identity')
        with tarfile.open(source_snapshot or path/'source.tar.gz') as tar:
            snapshot_files={**source['files'],**(source_snapshot_extras or {})}
            if set(tar.getnames())!=set(snapshot_files):raise ValueError('source inventory')
            for n,h in snapshot_files.items():
                member=tar.getmember(n)
                if not member.isfile() or hashlib.sha256(tar.extractfile(n).read()).hexdigest()!=h:raise ValueError('source snapshot '+n)
    return m

def case_inventory(path,m,classification):
    path=Path(path).resolve();rows=[]
    for name,record in m.get('cases',{}).items():
        d=path/'artifacts/cocotb'/name;c=read(d/'case.json');r=read(d/'checks.json');s=read(d/'case-status.json')
        acquisition=m.get('capture',{}).get('run_id',m['run_id'])
        if c['case_id']!=name or c['run_id']!=acquisition or c.get('negative') is not None:raise ValueError('case identity')
        revalidation=read(d/'revalidation.json') if m.get('capture') else None
        if (s['status']!='PASS' or s['exit_code']!=0) and not (revalidation and revalidation['status']=='PASS' and s.get('simulator_exit')==0 and 'VCD/AXI' in s.get('reason','')):raise ValueError('case raw/revalidation status')
        if r['status']!='PASS' or r['first_failure'] is not None:raise ValueError('case status')
        if not r['categories'] or any(type(x)!=int or x<=0 for x in r['categories'].values()) or r['check_count']!=sum(r['categories'].values()):raise ValueError('zero/inconsistent checks')
        if record.get('checks',r['check_count'])!=r['check_count']:raise ValueError('check count record')
        for k in ('case_id','run_id','seed','profile','fixture_sha256','golden_sha256'):
            if c[k]!=r[k]:raise ValueError('checks identity '+k)
        xml=d/'results.xml';tree=ET.parse(xml).getroot();tests=tree.findall('.//testcase')
        if len(tests)!=1 or any(x.tag in ('failure','error','skipped') for x in tree.iter()):raise ValueError('empty/failed/skipped XML')
        expected={'T09':('cpu_execution','test_cpu'),'T12':('runtime_execution','test_runtime'),'T13':('accel_control','test_accel_control'),'T14':('streaming','test_streaming'),'T15':('linear','test_linear'),'T16':('soc_accel','test_soc_accel'),'T17':('uart_boot','test_uart_boot'),'T18':('sd_boot','test_sd_boot'),'T19':('model_integration','test_model_integration'),'T20':('application','test_application')}.get(m['task_id'])
        if expected and (tests[0].get('name'),tests[0].get('classname'))!=expected:raise ValueError('unexpected XML testcase identity')
        start=s.get('started_ns',0)
        if not start or xml.stat().st_mtime_ns<start or (d/'checks.json').stat().st_mtime_ns<start:raise ValueError('old XML/checks')
        log=(d/'simulation.log').read_text(errors='replace')
        if any(x in log for x in ('Fatal:','Error-','UVM_FATAL','UVM_ERROR','Cannot open file')):raise ValueError('unexplained simulator error')
        execution_path=Path(m.get('capture',{}).get('path') or m.get('requalification',{}).get('original_evidence') or path)
        cmd=next((x for x in read(execution_path/'commands.json') if x['name']=='case-'+name),None)
        # Some requalified T15/T16 runs deliberately retain the original execution receipt.
        if cmd is None:
            candidates=[x for x in read(path/'commands.json') if name in ' '.join(x['argv'])]
            cmd=candidates[0] if candidates else None
        if cmd is None or not cmd.get('timeout_seconds',0)>0:raise ValueError('missing bounded execution command '+name)
        rows.append(dict(task=m['task_id'],case_id=name,classification=classification,manifest=str(path/'manifest.json'),manifest_sha256=sha256(path/'manifest.json'),original_run_id=c['run_id'],acceptance_record_run_id=m['run_id'],source_sha256=m['source']['sha256'],case_config_sha256=sha256(d/'case.json'),fixture_sha256=c['fixture_sha256'],golden_sha256=c['golden_sha256'],simulator_sha256=c['simulator_sha256'],seed=c['seed'],effective_seeds=c.get('effective_seeds',{'python':c['seed'],'cocotb':c['seed'],'vcs':c['seed']}),test_mode=c['test_mode'],max_cycles=c['max_cycles'],wall_timeout_seconds=cmd.get('timeout_seconds') if cmd else None,execution_commands=str(execution_path/'commands.json'),xml=str(xml),xml_sha256=sha256(xml),test_name=tests[0].get('name'),checks=r['check_count'],checks_sha256=sha256(d/'checks.json'),sequence_sha256=r.get('sequence_sha256'),exit_code=0,original_case_status=s,revalidation=revalidation,result=r.get('result')))
    return rows

def check_replays(rows):
    by={r['case_id']:r for r in rows};replays=[]
    for n,r in by.items():
        if n.endswith('-replay'):
            original=by.get(n.removesuffix('-replay'))
            if not original or not r['sequence_sha256'] or original['sequence_sha256']!=r['sequence_sha256']:raise ValueError('seed replay '+n)
            replays.append(n)
    return replays

def current_sources(root,m):
    return {n:dict(recorded=h,current=sha256(Path(root)/n) if (Path(root)/n).is_file() else None) for n,h in m.get('source',{}).get('files',{}).items() if not (Path(root)/n).is_file() or sha256(Path(root)/n)!=h}
