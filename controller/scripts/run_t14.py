#!/usr/bin/env python3
"""Fresh Coral microprogram/RTL build and the registered T14 VCS+cocotb matrix."""
import argparse,hashlib,json,re,shutil,sys,tarfile,traceback,zipfile
from pathlib import Path
from coral_rtl import apply_patches, input_paths as coral_patch_inputs
from evidence import EvidenceRun,StepFailure,sha256,content_id,write_json
from run_cocotb import environment
from run_t07 import simulate_batch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tests/streaming'),str(ROOT/'tests/cocotb'),str(ROOT/'tests/models')]
from prepare import prepare
from streaming_check import score
from waveform import check_waveform
from cocotb_case import validate
from elftools.elf.elffile import ELFFile

def inputs():
    names=['Makefile','scripts/run_t14.py','scripts/run_t07.py','scripts/run_cocotb.py','scripts/cocotb_case.py','scripts/evidence.py','scripts/probe_tools.py',
           'configs/t14-streaming.json','configs/cocotb-toolchain-lock.json','docs/spec/toolchain-lock.json','docs/spec/memory-map-v1.json',
           'configs/t05-thresholds.json','docs/spec/application-v2-model-lock.json','docs/spec/backend-contract-v1.md','docs/spec/accel-t13-contract.md','docs/spec/streaming-t14-contract.md',
           'third_party/lock.json','tests/coral/start.S','tests/models/prepare_image.py','rtl/interfaces/axi4_if.sv',
           'rtl/soc/nx_accel_map.sv','rtl/soc/nx_accel_guard.sv','rtl/soc/nx_stream_counters.sv',
           'tests/models/sparse_memory_pkg.sv','tests/models/axi_sparse_mem.sv','tests/cocotb/common/checks.py','tests/cocotb/test_streaming.py',
           'tests/cocotb/test_empty.py','model_tools/verify_pack.py']
    for directory in ('tests/streaming','tests/cocotb/fixtures/model_pack'):
        names += [str(p.relative_to(ROOT)) for p in (ROOT/directory).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc']
    names += [str(p.relative_to(ROOT)) for p in (ROOT/'firmware/drivers/accel').glob('stream.*')]
    names += coral_patch_inputs()
    return {n:sha256(ROOT/n) for n in sorted(set(names))}

def build(run,config,tools,vpi):
    source=ROOT/config['input_t06'];m=json.loads((source/'manifest.json').read_text());top=config['top'];zip_path=source/'artifacts'/(top+'.zip')
    run.check('t06-status',m['status']=='PASS' and sha256(zip_path)==m['artifacts'][str(zip_path.relative_to(source))],'accepted real RVV RTL')
    run.check('t06-source',sha256(source/'coral-source.tar.gz')==m['artifacts']['coral-source.tar.gz'],'accepted SRAM-only DPI storage')
    for task,path in config['prerequisites'].items():
        p=ROOT/path;manifest=json.loads((p/'manifest.json').read_text());run.check('prerequisite-'+task.lower(),manifest['status']=='PASS' and manifest['exit_code']==0,path)
        run.manifest.setdefault('prerequisites',{})[task]={'path':path,'manifest_sha256':sha256(p/'manifest.json')}
    t10=json.loads((ROOT/config['prerequisites']['T10']/'manifest.json').read_text())
    run.check('t10-published-fixtures',sha256(ROOT/'tests/cocotb/fixtures/model_pack/manifest.json')==t10['artifacts']['fixtures/manifest.json'],'unchanged accepted producer fixture manifest')
    shutil.copy2(source/'coral-source.tar.gz',run.path/'coral-source.tar.gz');shutil.copy2(zip_path,run.path/'coral-rtl.zip')
    dest=run.build/'compiled';dest.mkdir();rtl=dest/'rtl';rtl.mkdir()
    with zipfile.ZipFile(zip_path) as z:
        run.check('rtl-archive-safe',all(not Path(n).is_absolute() and '..' not in Path(n).parts for n in z.namelist()),'relative members')
        z.extractall(rtl)
    apply_patches(run, rtl)
    with tarfile.open(source/'coral-source.tar.gz') as tar:
        for name in ('sram_backdoor.cc','sram_backdoor.h'):(rtl/name).write_bytes(tar.extractfile('hdl/verilog/'+name).read())
    gcc=Path(next(s['argv'][0] for s in json.loads((source/'commands.json').read_text()) if s['name']=='compile-vector'));objdump=gcc.with_name('riscv64-unknown-elf-objdump')
    run.check('compiler-lock',sha256(gcc)==m['compiler']['sha256'] and sha256(objdump)==m['compiler']['objdump_sha256'],m['compiler'])
    run.manifest.update(compiler=m['compiler'],coral=m['coral'],rtl_sha256=sha256(zip_path))
    fw=run.build/'firmware';fw.mkdir();src=ROOT/'firmware/drivers/accel'
    run.execute('firmware',[gcc,f'-march={config["march"]}',f'-mabi={config["mabi"]}','-O2','-g','-fno-tree-vectorize','-ffp-contract=off','-fno-fast-math',
        '-ffreestanding','-fno-builtin','-msmall-data-limit=0','-nostdlib','-Wl,--no-relax','-Wl,--build-id=none','-Wall','-Wextra','-Werror',
        f'-ffile-prefix-map={ROOT}=.', '-T',src/'stream.ld',f'-Wl,-Map={fw}/stream.map',ROOT/'tests/coral/start.S',src/'stream.c','-lgcc','-o',fw/'stream.elf'],60)
    log=run.execute('disassemble',[objdump,'-d',fw/'stream.elf'],30);shutil.copy2(log,fw/'stream.dis')
    with (fw/'stream.elf').open('rb') as f:
        elf=ELFFile(f);symbols={s.name:int(s['st_value']) for s in elf.get_section_by_name('.symtab').iter_symbols() if s.name};text=elf.get_section_by_name('.text')['sh_size']
    layout={'itcm_bytes':int(text),'request_address':symbols['request'],'result_address':symbols['result'],'dtcm_static_bytes':symbols['__data_end']-0x10000,
            'stack_bottom':symbols['__stack_bottom'],'stack_top':symbols['__stack_top'],'guard_bytes':16,'activation_bytes':19456,'activation_scale_bytes':1216,'scratch_bytes':64,
            'staging_mode':'serial; weight rows remain external; no external DMA; double buffering disabled until dependency-safe overlap is measured'}
    run.check('tcm-footprint',text<=8192 and symbols['request']==0x10000 and symbols['result']==0x10100 and symbols['__data_end']<=0x16ff0,layout)
    run.check('rvv-actual-instructions',all(x in log.read_text() for x in ('vle8.v','vse8.v','vwmul.vv','vwredsum.vs','0x08000073')), 'real generated RVV load/store/dot and halt')
    write_json(fw/'allocation.json',layout);run.manifest['allocation']=layout
    sources=[ROOT/n for n in ('rtl/interfaces/axi4_if.sv','rtl/soc/nx_accel_map.sv','rtl/soc/nx_accel_guard.sv','rtl/soc/nx_stream_counters.sv',
        'tests/models/sparse_memory_pkg.sv','tests/models/axi_sparse_mem.sv','tests/streaming/tb_streaming.sv')]
    run.execute('vcs-build',[tools['vcs'],'-full64','-sverilog','-timescale=1ns/1ps','-debug_access+all','+acc+3','-cc',tools['vcs_host_cc'],'-cpp',tools['vcs_host_cxx'],
        '-CFLAGS','-std=c++17','-LDFLAGS','-Wl,--no-as-needed','-load',vpi,'+define+VCS',f'+define+CORAL_TOP={top}','-top','tb_cpu','-f','filelist.f',*sources,rtl/'sram_backdoor.cc','-o',dest/'simv'],config['timeouts_seconds']['compile'],cwd=rtl)
    return fw,dest/'simv'

def case(run,tools,config,name,fw,sim,negative=None,launch=True):
    params=config['cases'].get(name,config['cases']['short-seed1']);profile=params['profile']
    images=run.build/'images'/profile
    if not images.exists():prepare(fw/'stream.elf',images,profile)
    dest=run.build/'cocotb'/name;dest.mkdir(parents=True)
    cfg=dict(task='T14',case_id=name,run_id=run.run_id,**params,python_prefix=sys.prefix,cocotb_version=config['cocotb_version'],test_mode='PRELOAD',
        max_cycles=config['max_cycles'],job_max_cycles=config['job_max_cycles'],max_delay=config['max_delay'],negative=negative,
        fixture=str(images/'fixture.json'),golden=str(images/'golden.json'),image_plan=str(images/'load.plan'),image=str(images/'load.hex'),
        fixture_sha256=sha256(images/'fixture.json'),golden_sha256=sha256(images/'golden.json'),simulator_sha256=sha256(sim),
        effective_seeds={'vcs':params['seed'],'cocotb':params['seed'],'memory':params['seed']^0x9e3779b9,'native_port':params['seed']})
    write_json(dest/'case.json',cfg)
    if not launch:
        return dict(name='case-'+name,case=dest,argv=[tools['python'],ROOT/'scripts/cocotb_case.py','--case',dest/'case.json','--sim',sim],cost=1000000 if profile=='pack' else 100000,case_id=name)
    try:run.execute('case-'+name,[tools['python'],ROOT/'scripts/cocotb_case.py','--case',dest/'case.json','--sim',sim],config['timeouts_seconds']['simulation'],cwd=dest)
    finally:shutil.copytree(dest,run.path/'artifacts/cocotb'/name)
    return json.loads((dest/'checks.json').read_text())

def archive(run):
    out=run.path/'artifacts';out.mkdir(exist_ok=True)
    for name in ('firmware','images','cocotb'):
        if (run.build/name).exists():shutil.copytree(run.build/name,out/name,dirs_exist_ok=True)
    if (run.build/'tool-report.json').exists():shutil.copy2(run.build/'tool-report.json',out/'tool-report.json')
    run.manifest['artifacts']={str(p.relative_to(run.path)):sha256(p) for p in sorted(run.path.rglob('*')) if p.is_file() and not (p.parent==run.path and p.name in ('manifest.json','checks.json','commands.json','exit-status.txt'))}

def verify_archive(path):
    path=Path(path).resolve();m=json.loads((path/'manifest.json').read_text())
    if m.get('status')!='PASS' or m.get('exit_code')!=0 or (path/'exit-status.txt').read_text().strip()!='0':raise ValueError('not a completed PASS')
    for rel,h in m['artifacts'].items():
        p=(path/rel).resolve()
        if not p.is_relative_to(path) or not p.is_file() or sha256(p)!=h:raise ValueError('artifact changed: '+rel)
    if not m['artifacts'] or sha256(path/'config.json')!=m['config']['sha256']:raise ValueError('config identity')
    for name,key in [('commands.json',None),('checks.json','checks')]:
        rows=json.loads((path/name).read_text());rows=rows[key] if key else rows
        if not rows or any(r['status']!='PASS' for r in rows):raise ValueError('failed root result')
    files=m['source']['files']
    if content_id(files)!=m['source']['sha256']:raise ValueError('source inventory digest')
    with tarfile.open(path/'source.tar.gz') as tar:
        if set(tar.getnames())!=set(files):raise ValueError('source inventory')
        for name,h in files.items():
            if hashlib.sha256(tar.extractfile(name).read()).hexdigest()!=h:raise ValueError('source content')
        registered=json.load(tar.extractfile('configs/t14-streaming.json'))
    config=json.loads((path/'config.json').read_text());suite=config['suite']
    if config!={**registered,'suite':suite,'selected_cases':registered['suites'][suite]} or set(m['cases'])!=set(config['selected_cases']):raise ValueError('registered matrix')
    checks=0
    for name in config['selected_cases']:
        dest=path/'artifacts/cocotb'/name;cfg=json.loads((dest/'case.json').read_text());r=validate(dest,cfg);expected=config['cases'][name]
        if any(cfg[k]!=v for k,v in expected.items()) or cfg['task']!='T14' or cfg['negative'] is not None or cfg['case_id']!=name or cfg['run_id']!=m['run_id']:raise ValueError('case configuration/identity')
        folder=path/'artifacts/images'/cfg['profile']
        for key in ('fixture','golden'):
            if sha256(folder/(key+'.json'))!=cfg[key+'_sha256']:raise ValueError('fixture/golden identity')
        if sha256(dest/'transactions.csv')!=r['sequence_sha256'] or r['sequence_sha256']!=m['cases'][name]['sequence_sha256']:raise ValueError('trace identity')
        check_waveform(dest);score(dest,json.loads((folder/'fixture.json').read_text()),json.loads((folder/'golden.json').read_text()),json.loads((dest/'observations.json').read_text()),folder)
        checks+=r['check_count']
    if suite!='smoke':
        if set(m.get('negatives',{}))!=set(config['negative_cases']):raise ValueError('missing negative matrix')
        for name,rec in m['negatives'].items():
            nd=Path(rec['path']);nm=json.loads((nd/'manifest.json').read_text())
            if nm['status']!='FAIL' or nm['exit_code']!=1 or nm.get('negative')!=name:raise ValueError('negative raw FAIL')
            for rel,h in nm['artifacts'].items():
                if sha256(nd/rel)!=h:raise ValueError('negative artifact')
        if m['cases']['short-seed1']['sequence_sha256']!=m['cases']['short-seed1-replay']['sequence_sha256']:raise ValueError('replay trace')
    return dict(status='PASS',cases=len(m['cases']),independent_checks=checks,source_sha256=m['source']['sha256'])

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--suite',choices=['smoke','regression','full'],default='regression');p.add_argument('--run-id');p.add_argument('--verify-archive',type=Path);a=p.parse_args()
    if a.verify_archive:
        try:print(json.dumps(verify_archive(a.verify_archive),indent=2));return 0
        except Exception as error:print('ARCHIVE_REJECT: '+str(error),file=sys.stderr);return 1
    run=EvidenceRun(ROOT,'T14',a.run_id);print('T14 evidence: '+str(run.path),flush=True);code=1
    try:
        files=inputs();run.manifest['source']={'files':files,'sha256':content_id(files)}
        with tarfile.open(run.path/'source.tar.gz','w:gz') as tar:
            for name in files:tar.add(ROOT/name,arcname=name,recursive=False)
        config=json.loads((ROOT/'configs/t14-streaming.json').read_text());config.update(suite=a.suite,selected_cases=config['suites'][a.suite]);write_json(run.path/'config.json',config)
        run.manifest.update(config={'sha256':sha256(run.path/'config.json')},qualification=config['scope'],invocation=[sys.executable,*sys.argv])
        tools={k:v['path'] for k,v in json.loads((ROOT/'docs/spec/toolchain-lock.json').read_text())['tools'].items()}
        vpi=environment(run,config,tools);fw,sim=build(run,config,tools,vpi);results={}
        jobs=[case(run,tools,config,name,fw,sim,launch=False) for name in config['selected_cases']]
        simulate_batch(run,jobs,config['timeouts_seconds']['simulation'],config['simulation_workers'])
        for name in config['selected_cases']:
            dest=run.build/'cocotb'/name;r=json.loads((dest/'checks.json').read_text());results[name]=r
            if name.endswith('-replay'):run.check('deterministic-replay',r['sequence_sha256']==results[name.removesuffix('-replay')]['sequence_sha256'],'complete AXI payload/response/timing trace')
        run.manifest['cases']={k:{'status':v['status'],'checks':v['check_count'],'sequence_sha256':v['sequence_sha256'],'result':v['result']} for k,v in results.items()}
        if a.suite!='smoke':
            for name in config['negative_cases']:
                neg=EvidenceRun(ROOT,'T14_NEGATIVE',run.run_id+'-'+name);neg.manifest.update(negative=name,parent=str(run.path),expected='FAIL');rc=0
                try:case(neg,tools,config,name,fw,sim,name)
                except StepFailure as error:rc=error.exit_code
                finally:archive(neg);neg.finish(rc)
                status=json.loads((neg.build/'cocotb'/name/'case-status.json').read_text());needle={'empty':'required testcase identity/count mismatch','missing-xml':'missing/stale results.xml'}.get(name,'XML failure/error/skip')
                detected=rc==1 and needle in status.get('reason','')
                if name in ('held-reset','bad-golden'):
                    failure=json.loads((neg.build/'cocotb'/name/'checks.json').read_text())['first_failure'];detected&=failure['category']=={'held-reset':'completion','bad-golden':'data'}[name]
                run.check('negative-'+name,detected,status);run.manifest.setdefault('negatives',{})[name]={'path':str(neg.path),'reason':status.get('reason')}
            run.execute('project-tests',[tools['make'],'test'],300,cwd=ROOT)
        run.check('source-unchanged',inputs()==files,'all acceptance inputs stable');code=0
    except StepFailure as error:code=error.exit_code;(run.path/'failure.txt').write_text(str(error)+'\n')
    except KeyboardInterrupt:code=130
    except Exception:(run.path/'failure.txt').write_text(traceback.format_exc())
    finally:archive(run);code=run.finish(code)
    print(f'T14 {run.manifest["status"]}: {run.path}',flush=True);return code
if __name__=='__main__':sys.exit(main())
