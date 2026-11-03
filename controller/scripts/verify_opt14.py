#!/usr/bin/env python3
"""Replay baseline CPU observations and fail closed on incomplete evidence."""
import argparse,json,sys,xml.etree.ElementTree as ET
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'scripts'),str(ROOT/'tests/cocotb')]
from evidence import sha256,content_id
from common.checks import Checks
from tests.opt14.score import score
from cocotb_case import validate

MATRIX=[['seed1',1],['seed7',7],['seed19',19],['seed1-repeat',1]]


def receipt(path,task):
    path=Path(path);m=json.loads((path/'manifest.json').read_text())
    if m['task_id']!=task or m['status']!='PASS' or m['exit_code']!=0 or (path/'exit-status.txt').read_text().strip()!='0':
        raise ValueError('failed receipt '+str(path))
    artifacts=m.get('artifacts',{})
    if not artifacts or any(not (path/n).is_file() or sha256(path/n)!=h for n,h in artifacts.items()):
        raise ValueError('changed/missing receipt artifact '+str(path))
    commands=json.loads((path/'commands.json').read_text());checks=json.loads((path/'checks.json').read_text())['checks']
    if not checks or any(c['status']!='PASS' for c in checks) or any(c['status']!='PASS' or c['exit_code']!=0 for c in commands):
        raise ValueError('receipt command/check failure')
    return m


def verify_baseline(path):
    path=Path(path).resolve();m=receipt(path,'OPT14_BASELINE')
    if m.get('full_matrix') is not True or m.get('argmax_rtl_implemented') is not False:
        raise ValueError('baseline measurement scope')
    if json.loads((path/'matrix.json').read_text())!=MATRIX:raise ValueError('required seed matrix')
    inputs=json.loads((path/'inputs.json').read_text())
    if content_id(inputs)!=m['source_id'] or any(sha256(ROOT/n)!=h or sha256(path/'sources'/n)!=h for n,h in inputs.items()):
        raise ValueError('current/source snapshot identity')
    if sha256(path/'cpu.v')!=m['cpu_rtl_sha256']:raise ValueError('CPU RTL identity')
    results={};total=0
    for name,seed in MATRIX:
        d=path/'cocotb'/name;cfg=json.loads((d/'case.json').read_text())
        status=json.loads((d/'case-status.json').read_text())
        checks=validate(d,cfg,status['started_ns'])
        if cfg['task']!='OPT14_BASELINE' or cfg['seed']!=seed or cfg['run_id']!=m['run_id']:
            raise ValueError('case identity')
        if status['status']!='PASS' or status['exit_code']!=0 or status['checks']!=checks['check_count']:
            raise ValueError('case execution status')
        for key in ('fixture','golden'):
            if sha256(cfg[key])!=cfg[key+'_sha256']:raise ValueError('fixture/golden identity')
        c=Checks();observed=score(d/'cpu-output.txt',json.loads(Path(cfg['golden']).read_text()),c)
        if c.first_failure or any(checks['categories'].get(k,0)<v for k,v in c.counts.items()):raise ValueError('replay checks')
        if observed!=json.loads((d/'observations.json').read_text()):raise ValueError('observations differ from raw CPU records')
        wave=json.loads((d/'waveform-check.json').read_text())
        if wave['status']!='PASS' or wave['clock_rises']<1000 or wave['retire_rises']<100:raise ValueError('bounded waveform')
        results[name]=dict(observed=observed,checks=checks['check_count'],sequence_sha256=sha256(d/'cpu-output.txt'))
        total+=checks['check_count']
    if results['seed1']!=results['seed1-repeat']:raise ValueError('same-seed replay')
    if json.loads((path/'results.json').read_text())!={n:d['observed'] for n,d in results.items()}:
        raise ValueError('summary differs from replay')
    return dict(status='PASS',baseline=str(path.relative_to(ROOT)),checks=total,cases=results,
                scope='BASELINE_CPU_COSTS_ONLY_NO_STREAMING_ARGMAX_RTL_QUALIFICATION')


def verify_assessment(path):
    from opt14_model import assess
    path=Path(path).resolve();m=receipt(path,'OPT14')
    baseline=ROOT/m['baseline'];review=verify_baseline(baseline)
    inputs=json.loads((path/'inputs.json').read_text())
    if any(sha256(ROOT/n)!=h for n,h in inputs.items()):raise ValueError('assessment input identity')
    result=assess(ROOT,review)
    if result!=json.loads((path/'assessment.json').read_text()):raise ValueError('assessment recomputation')
    negatives=json.loads((path/'negative-tests.json').read_text())
    if len(negatives)<6 or any(x['detected'] is not True or x['exit_code']==0 for x in negatives):
        raise ValueError('negative gate verification')
    for record in negatives:
        d=path/'negative'/record['name']
        if int((d/'exit-status.txt').read_text())!=record['exit_code']:
            raise ValueError('negative raw exit status')
        if record['expected_diagnostic'] not in (d/'replay.stdout.log').read_text()+(d/'replay.stderr.log').read_text():
            raise ValueError('negative failure provenance')
    for n,h in json.loads((path/'parents.json').read_text()).items():
        if sha256(ROOT/n/'manifest.json')!=h:raise ValueError('parent identity '+n)
    for n,h in json.loads((path/'protected-before.json').read_text()).items():
        if sha256(ROOT/n)!=h:raise ValueError('protected baseline '+n)
    return dict(status='PASS',assessment=str(path.relative_to(ROOT)),decision=result['decision'],
                baseline_checks=review['checks'],selected_for_OPT16=False)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('path',type=Path);a=p.parse_args()
    task=json.loads((a.path/'manifest.json').read_text())['task_id']
    result=verify_baseline(a.path) if task=='OPT14_BASELINE' else verify_assessment(a.path)
    print(json.dumps({k:v for k,v in result.items() if k!='cases'},indent=2))

if __name__=='__main__':main()
