#!/usr/bin/env python3
"""Execute accepted T16 firmware/payloads through the T24 digital DDR fabric."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import tarfile
import traceback
from evidence import EvidenceRun, StepFailure, content_id, sha256, write_json
from run_cocotb import environment
import run_t16
from run_t07 import simulate_batch
from cocotb_case import validate

ROOT=Path(__file__).resolve().parents[1]
EXTRA=['rtl/soc/nx_soc_test_response.sv','rtl/soc/nx_soc_core.sv','rtl/soc/nx_axi_ddr_route.sv','rtl/soc/nx_axi_ddr_mux.sv',
       'rtl/soc/nx_soc_ddr_fabric.sv','rtl/soc/nx_ddr_adapter.sv',
       'tests/board_soc/native_memory_model.sv']
OWN=['configs/t24-soc-board.json','scripts/run_t24.py','tests/board_soc/tb_core_body.svh',
     'tests/cocotb/test_board_soc.py','rtl/coral/pango/Sram.v']

def inputs():
    return {**run_t16.inputs(),**{n:sha256(ROOT/n) for n in EXTRA+OWN}}

def import_images(run,config,profile):
    parent=ROOT/config['input_t16'];m=json.loads((parent/'manifest.json').read_text())
    src=parent/'artifacts/images'/profile;dest=run.build/'images'/profile
    for p in src.rglob('*'):
        if p.is_file() and sha256(p)!=m['artifacts'][str(p.relative_to(parent))]:
            raise ValueError('accepted T16 image changed: '+str(p))
    shutil.copytree(src,dest)
    fixture=json.loads((dest/'fixture.json').read_text());golden=json.loads((dest/'golden.json').read_text())
    for region in fixture['regions']: region['path']=str(dest/Path(region['path']).name)
    for job in golden['jobs']: job['expected_path']=str(dest/Path(job['expected_path']).name)
    write_json(dest/'fixture.json',fixture);write_json(dest/'golden.json',golden)
    (dest/'load.plan').write_text(''.join('B %x %x %s\n'%(r['address'],r['bytes'],r['path']) for r in fixture['regions']))
    identity={n:sha256(dest/n) for n in ('firmware.elf','fixture_jobs.h')}
    run.check('same-firmware-'+profile,all(identity[n]==sha256(src/n) for n in identity),'byte-identical accepted T16 ELF/header and memory region payloads')
    run.manifest.setdefault('t16_images',{})[profile]=dict(parent=str(src.relative_to(ROOT)),
        parent_fixture_sha256=sha256(src/'fixture.json'),parent_golden_sha256=sha256(src/'golden.json'),
        firmware_sha256=identity['firmware.elf'],payloads={r['name']:r['sha256'] for r in fixture['regions']})
    return dest

def case(run,tools,config,images,sim,name,negative=None):
    params=config['cases'].get(name,config['cases']['smoke-seed1'])
    dest=run.build/'cocotb'/name;dest.mkdir(parents=True)
    for p in sim.parent.glob('*.bin'):shutil.copy2(p,dest/p.name)
    cfg=dict(task='T24',case_id=name,run_id=run.run_id,**params,python_prefix=sys.prefix,
        cocotb_version=config['cocotb_version'],test_mode='PRELOAD',negative=negative,
        max_cycles=2000 if negative=='held-reset' else config['head_max_cycles'] if params['profile']=='head' else config['max_cycles'],
        fixture=str(images/'fixture.json'),golden=str(images/'golden.json'),image_plan=str(images/'load.plan'),
        fixture_sha256=sha256(images/'fixture.json'),golden_sha256=sha256(images/'golden.json'),simulator_sha256=sha256(sim),
        effective_seeds={'vcs':params['seed'],'cocotb':params['seed'],'cpu_i':params['seed']^0x49,'cpu_d':params['seed']^0x44,'backend':params['seed']^0x4e})
    write_json(dest/'case.json',cfg)
    return dict(name='case-'+name,case=dest,argv=[tools['python'],ROOT/'scripts/cocotb_case.py','--case',dest/'case.json','--sim',sim],cost=151936 if params['profile']=='head' else 1)

def verify_archive(path):
    from scoreboard import score
    from waveform import check_waveform
    path=Path(path).resolve();m=json.loads((path/'manifest.json').read_text())
    if m['task_id']!='T24' or m['status']!='PASS' or m['exit_code']!=0 or (path/'exit-status.txt').read_text().strip()!='0':raise ValueError('not a completed T24 PASS')
    for n,h in m['artifacts'].items():
        p=(path/n).resolve()
        if not p.is_relative_to(path) or sha256(p)!=h:raise ValueError('artifact identity: '+n)
    if content_id(m['source']['files'])!=m['source']['sha256']:raise ValueError('source inventory')
    with tarfile.open(path/'source.tar.gz') as tar:
        if set(tar.getnames())!=set(m['source']['files']):raise ValueError('source snapshot inventory')
        for n,h in m['source']['files'].items():
            if hashlib.sha256(tar.extractfile(n).read()).hexdigest()!=h:raise ValueError('source snapshot content')
        registered=json.load(tar.extractfile('configs/t24-soc-board.json'))
    cfg=json.loads((path/'config.json').read_text());selected=registered['suites'][cfg['suite']]
    if sha256(path/'config.json')!=m['config']['sha256'] or cfg!={**registered,'suite':cfg['suite'],'selected_cases':selected} or set(m['cases'])!=set(selected):raise ValueError('frozen matrix')
    if any(x['status']!='PASS' for x in json.loads((path/'commands.json').read_text())+json.loads((path/'checks.json').read_text())['checks']):raise ValueError('failed root check')
    total=0
    parent=ROOT/cfg['input_t16']
    for profile,identity in m['t16_images'].items():
        d=path/'artifacts/images'/profile;src=parent/'artifacts/images'/profile
        if sha256(d/'firmware.elf')!=identity['firmware_sha256'] or sha256(d/'firmware.elf')!=sha256(src/'firmware.elf'):raise ValueError('same accepted firmware')
        f=json.loads((d/'fixture.json').read_text());old=json.loads((src/'fixture.json').read_text())
        norm=lambda value:{**value,'regions':[{k:v for k,v in r.items() if k!='path'} for r in value['regions']]}
        if norm(f)!=norm(old):raise ValueError('same accepted T16 fixture')
        for region in f['regions']:
            if sha256(d/Path(region['path']).name)!=region['sha256']:raise ValueError('same fixture payload')
    for n in selected:
        d=path/'artifacts/cocotb'/n;c=json.loads((d/'case.json').read_text());r=validate(d,c)
        if c['task']!='T24' or c['run_id']!=m['run_id'] or c['negative'] is not None or any(c[k]!=v for k,v in cfg['cases'][n].items()):raise ValueError('case identity')
        images=path/'artifacts/images'/c['profile']
        for key in ('fixture','golden'):
            if sha256(images/(key+'.json'))!=c[key+'_sha256']:raise ValueError('case input identity')
        got,_=score(d,json.loads((images/'fixture.json').read_text()),json.loads((images/'golden.json').read_text()),images)
        if any(r['result'].get(k)!=v for k,v in got.items()):raise ValueError('independent score')
        check_waveform(d)
        if sha256(d/'transactions.csv')!=r['sequence_sha256'] or r['sequence_sha256']!=m['cases'][n]['sequence_sha256']:raise ValueError('trace identity')
        total+=r['check_count']
    if cfg['suite']!='smoke':
        if set(m.get('negatives',{}))!=set(cfg['negative_cases']):raise ValueError('negative coverage')
        for n,record in m['negatives'].items():
            d=Path(record['path']);nm=json.loads((d/'manifest.json').read_text())
            if nm['status']!='FAIL' or nm['exit_code']!=1 or nm['negative']!=n:raise ValueError('negative raw FAIL')
            for rel,h in nm['artifacts'].items():
                if sha256(d/rel)!=h:raise ValueError('negative artifact identity')
        if m['cases']['control-seed1']['sequence_sha256']!=m['cases']['control-seed1-replay']['sequence_sha256']:raise ValueError('same-seed replay')
    if cfg['suite']=='full' and m['cases']['head-seed1']['result']['full_head_rows']!=151936:raise ValueError('full head incomplete')
    return dict(status='PASS',suite=cfg['suite'],cases=len(selected),independent_checks=total,board_qualified=False)

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id');parser.add_argument('--suite',choices=['smoke','regression','full'],default='full')
    parser.add_argument('--verify-archive',type=Path)
    args=parser.parse_args(argv)
    if args.verify_archive:
        try: print(json.dumps(verify_archive(args.verify_archive),indent=2));return 0
        except Exception:traceback.print_exc();return 1
    run=EvidenceRun(ROOT,'T24',args.run_id);code=1
    print('T24 evidence: '+str(run.path),flush=True)
    try:
        files=inputs();run.manifest['source']=dict(files=files,sha256=content_id(files))
        with tarfile.open(run.path/'source.tar.gz','w:gz') as tar:
            for n in files:tar.add(ROOT/n,arcname=n,recursive=False)
        config=json.loads((ROOT/'configs/t24-soc-board.json').read_text())
        config.update(suite=args.suite,selected_cases=config['suites'][args.suite]);write_json(run.path/'config.json',config)
        parent=ROOT/config['input_t16'];pm=json.loads((parent/'manifest.json').read_text())
        run.check('accepted-t16',pm['status']=='PASS' and pm['exit_code']==0,str(parent))
        parents=[str((parent/'manifest.json').relative_to(ROOT)),
                 'evidence/T23/adapter-acceptance-20261011-v5/manifest.json',
                 'evidence/T22_NATIVE_IMPL/rc3-native110-20261010-v7-full1g/manifest.json',
                 'evidence/T22_HANDOFF/deferred-board-debug-20261011-v1/handoff.json']
        run.manifest.update(parents={n:sha256(ROOT/n) for n in parents},config={'sha256':sha256(run.path/'config.json')},
            scope=config['scope'],invocation=[sys.executable,*sys.argv],board_qualified=False,physical_calibration=False)
        write_json(run.path/'baseline-differences.json',dict(parents=run.manifest['parents'],
            unchanged='T16 accepted firmware ELF, Coral microprogram, all payload/golden arrays and addresses',
            changes=['Digital DDR route/mux and T23 adapter','Coral generic synthesis SRAM in VCS and PDS',
                     'Native digital memory model; delayed commit; 8-cycle candidate drain; physical qualification still open',
                     'T16 errors injected at AXI response seam; no physical DDR fault claim'],
            board_operations=False,historical_board_results_reused=False))
        tools={k:v['path'] for k,v in json.loads((ROOT/'docs/spec/toolchain-lock.json').read_text())['tools'].items()}
        vpi=environment(run,config,tools)
        _,sim=run_t16.build(run,config,tools,vpi,EXTRA,ROOT/'rtl/coral/pango/Sram.v')
        run.check('fpga-sram',sha256(sim.parent/'rtl/Sram.v')==files['rtl/coral/pango/Sram.v'],'same SRAM implementation for simulation/synthesis')
        profiles=list(dict.fromkeys(config['cases'][n]['profile'] for n in config['selected_cases']))
        if args.suite!='smoke' and 'smoke' not in profiles:profiles.append('smoke')
        images={p:import_images(run,config,p) for p in profiles}
        jobs=[case(run,tools,config,images[config['cases'][n]['profile']],sim,n) for n in config['selected_cases']]
        simulate_batch(run,jobs,config['timeouts_seconds']['simulation'],config['simulation_workers'])
        for n in config['selected_cases']:
            r=json.loads((run.build/'cocotb'/n/'checks.json').read_text())
            run.manifest.setdefault('cases',{})[n]=dict(status=r['status'],checks=r['check_count'],sequence_sha256=r['sequence_sha256'],result=r['result']);run.flush()
        if args.suite!='smoke':
            run.check('same-seed-replay',run.manifest['cases']['control-seed1']['sequence_sha256']==run.manifest['cases']['control-seed1-replay']['sequence_sha256'],'all CPU/backend events')
            for n in config['negative_cases']:
                child=EvidenceRun(ROOT,'T24_NEGATIVE',run.run_id+'-'+n);child.manifest.update(parent=str(run.path),negative=n,expected='FAIL');rc=0
                job=case(child,tools,config,images['smoke'],sim,n,n)
                try:child.execute(job['name'],job['argv'],config['timeouts_seconds']['simulation'],cwd=job['case'])
                except StepFailure as e:rc=e.exit_code
                finally:run_t16.archive(child);child.finish(rc)
                d=job['case'];status=json.loads((d/'case-status.json').read_text());reason={'empty':'required testcase identity/count mismatch','missing-xml':'missing/stale results.xml'}.get(n,'XML failure/error/skip')
                detected=rc==1 and reason in status.get('reason','')
                if n in ('held-reset','bad-golden','stale-data'):
                    failure=json.loads((d/'checks.json').read_text())['first_failure']
                    detected &= failure['category']=={'held-reset':'completion','bad-golden':'data','stale-data':'completion'}[n]
                run.check('negative-'+n,detected,status)
                run.manifest.setdefault('negatives',{})[n]=dict(path=str(child.path),reason=status.get('reason'))
        run.check('source-unchanged',inputs()==files,'all execution inputs stable');code=0
    except StepFailure as e:code=e.exit_code;(run.path/'failure.txt').write_text(str(e)+'\n')
    except KeyboardInterrupt:code=130
    except Exception:(run.path/'failure.txt').write_text(traceback.format_exc())
    finally:run_t16.archive(run);code=run.finish(code)
    print('T24 DIGITAL '+run.manifest['status']+': '+str(run.path),flush=True)
    return code

if __name__=='__main__':sys.exit(main())
