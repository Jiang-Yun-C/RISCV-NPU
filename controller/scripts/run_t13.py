#!/usr/bin/env python3
"""T13: rebuild real cached CPU, driver, native bridge and transaction endpoint."""
import argparse,hashlib,json,re,shutil,sys,tarfile,traceback,zlib
from pathlib import Path
from evidence import EvidenceRun,StepFailure,sha256,content_id,write_json
from run_cocotb import environment,generate
from elftools.elf.elffile import ELFFile
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tests/models'),str(ROOT/'tests/cocotb'),str(ROOT/'tests/accel')]
from prepare_image import parse_elf

def inputs():
    names=['Makefile','scripts/run_t13.py','scripts/run_cocotb.py','scripts/cocotb_case.py','scripts/evidence.py','scripts/probe_tools.py',
        'configs/t13-accel.json','configs/cocotb-toolchain-lock.json','docs/spec/toolchain-lock.json','docs/spec/memory-map-v1.json',
        'docs/spec/accel-t13-contract.md','docs/spec/backend-contract-v1.md','docs/spec/system-contract-v1.md','third_party/lock.json','software/include/backend_v1.h',
        'firmware/cpu/start.S','firmware/cpu/link.ld','tests/coral/start.S','tests/coral/link.ld','rtl/interfaces/axi4_if.sv',
        'tests/models/sparse_memory_pkg.sv','tests/models/axi_sparse_mem.sv','tests/models/prepare_image.py',
        'tests/cocotb/README.md','tests/cocotb/test_accel_control.py','tests/cocotb/test_empty.py','tests/cocotb/common/checks.py','tests/cocotb/common/accel_waveform.py',
        'tests/cocotb/common/cpu_reference.py','tests/cpu/check_cpu.py']
    for directory in ('firmware/drivers/accel','tests/accel','cpu_gen'):
        names += [str(p.relative_to(ROOT)) for p in (ROOT/directory).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc']
    names += [str(p.relative_to(ROOT)) for p in (ROOT/'rtl/soc').glob('nx_accel*.sv')]
    return {n:sha256(ROOT/n) for n in sorted(set(names))}

def firmware(run,tools):
    dest=run.build/'firmware';dest.mkdir()
    flags=['-march=rv32im_zicsr_zifencei','-mabi=ilp32','-O2','-g','-ffreestanding','-fno-builtin','-fno-pic','-fno-strict-aliasing',
           '-nostdlib','-nostartfiles','-msmall-data-limit=0','-Wall','-Wextra','-Werror','-Wl,--build-id=none',f'-ffile-prefix-map={ROOT}=.']
    run.execute('probe-compile',[tools['rv32_gcc'],*flags,'-T',ROOT/'tests/coral/link.ld',ROOT/'tests/coral/start.S',ROOT/'firmware/drivers/accel/probe.c','-o',dest/'probe.elf'],60)
    run.execute('probe-binary',[tools['rv32_objcopy'],'-O','binary',dest/'probe.elf',dest/'probe.bin'],30)
    probe=(dest/'probe.bin').read_bytes();probe+=b'\x00'*(-len(probe)%4)
    run.check('probe-size',0<len(probe)<=8192,len(probe))
    words=[int.from_bytes(probe[i:i+4],'little') for i in range(0,len(probe),4)]
    (dest/'probe_image.h').write_text('#include <stdint.h>\n#define PROBE_CRC 0x%08xu\nstatic const uint32_t probe_words[]={%s};\n'%(zlib.crc32(probe),','.join(hex(w)+'u' for w in words)))
    src=ROOT/'firmware/drivers/accel';elf=dest/'firmware.elf'
    run.execute('firmware',[tools['rv32_gcc'],*flags,'-I',src,'-I',ROOT/'software/include','-I',dest,
        '-T',ROOT/'firmware/cpu/link.ld',f'-Wl,-Map={dest}/firmware.map',ROOT/'firmware/cpu/start.S',ROOT/'tests/accel/firmware.c',
        src/'accel.c',src/'target.c','-lc','-lgcc','-o',elf],60)
    log=run.execute('disassemble',[tools['rv32_objdump'],'-d',elf],30);shutil.copy2(log,dest/'firmware.dis')
    entry,segments,flags=parse_elf(elf.read_bytes(),base=0x10000,capacity=0xb8000000-0x10000)
    run.check('elf-regions',entry==0x10000 and flags==0 and all((0x10000<=s.address and s.address+s.memory_size<=0x20000) or
        (0xb4000000<=s.address and s.address+s.memory_size<=0xb8000000) for s in segments),'T08 ROM/private layout; ILP32')
    images=[]
    for i,s in enumerate(segments):
        path=dest/f'segment-{i}.bin';path.write_bytes(s.data);images.append({'address':s.address,'path':str(path),'bytes':len(s.data),'sha256':sha256(path)})
    guard_values={str(a):0 for a in (0x80000000,0xb8000000,0xbc000000,0xb4000000)}
    for s in segments:
        if s.address<=0xb4000000<s.address+len(s.data):guard_values[str(0xb4000000)]=int.from_bytes(s.data[0xb4000000-s.address:0xb4000004-s.address],'little')
    fixture={'producer':'T13','schema_version':1,'profile':'control','test_mode':'PRELOAD','images':images,'guard_values':guard_values,
             'elf_sha256':sha256(elf),'probe_sha256':sha256(dest/'probe.bin'),'probe_crc32':zlib.crc32(probe),'backend':'CORAL_NATIVE_TRANSACTION_TEST_DOUBLE',
             'model':'not applicable: transport probe','dtype':'U32','shape':[16],'stride':[4],'endianness':'little','group_size':'not applicable',
             'layout_id':'PRIVATE_PROBE_ABI_V1','logical_view':'out[i] = input[i] XOR 0x55aa12ef','input_soc':'0xac000000',
             'output_soc':'0xba000000','coral_local_params':'0x10000','coral_local_result':'0x10100','tolerance':'bit_exact',
             'golden_sha256':sha256(ROOT/'tests/accel/golden.json'),'checker_sha256':sha256(ROOT/'tests/accel/accel_check.py')}
    write_json(dest/'fixture.json',fixture);shutil.copy2(ROOT/'tests/accel/golden.json',dest/'golden.json')
    (dest/'image-plan.txt').write_text(''.join(f"B {r['address']:x} {r['bytes']:x} {r['path']}\n" for r in images if r['bytes']))
    return dest

def compile_sim(run,tools,generated,vpi):
    dest=run.build/'compiled';dest.mkdir();rtl=generated/'soft/T09Cpu.v'
    for p in rtl.parent.glob('*.bin'):shutil.copy2(p,dest/p.name)
    ports=re.findall(r'(input|output)\s+wire\s*(\[[^]]+\])?\s*(\w+)\s*[,\n]',rtl.read_text().split(');',1)[0])
    wrapper='`timescale 1ns/1ps\nmodule tb_cpu;\n'+''.join(f"{'logic' if d=='input' else 'wire'} {w} {n};\n" for d,w,n in ports)
    wrapper+='T09Cpu cpu(.*);\n'+(ROOT/'tests/accel/tb_body.svh').read_text()+'\nendmodule\n';(dest/'tb_cpu.sv').write_text(wrapper)
    sources=[ROOT/p for p in ('rtl/interfaces/axi4_if.sv','rtl/soc/nx_accel_map.sv','rtl/soc/nx_accel_guard.sv','rtl/soc/nx_accel_bridge.sv',
        'tests/models/sparse_memory_pkg.sv','tests/models/axi_sparse_mem.sv','tests/accel/coral_transaction_endpoint.sv')]
    run.execute('vcs-build',[tools['vcs'],'-full64','-sverilog','-timescale=1ns/1ps','-debug_access+all','+acc+3',
        '-cc',tools['vcs_host_cc'],'-cpp',tools['vcs_host_cxx'],'-LDFLAGS','-Wl,--no-as-needed','-load',vpi,
        '-top','tb_cpu',*sources,rtl,dest/'tb_cpu.sv','-o',dest/'simv'],240,cwd=dest)
    return dest/'simv'

def case(run,tools,config,name,fw,sim,negative=None):
    dest=run.build/'cocotb'/name;dest.mkdir(parents=True)
    for p in sim.parent.glob('*.bin'):shutil.copy2(p,dest/p.name)
    seed=int(re.search(r'seed(\d+)',name)[1]) if 'seed' in name else 1
    cfg={'task':'T13','case_id':name,'run_id':run.run_id,'profile':'control','seed':seed,'python_prefix':sys.prefix,
        'cocotb_version':config['cocotb_version'],'test_mode':'PRELOAD','max_cycles':2000 if negative=='held-reset' else config['max_cycles'],
        'max_delay':config['max_delay'],'negative':negative,'fixture':str(fw/'fixture.json'),'golden':str(fw/'golden.json'),
        'fixture_sha256':sha256(fw/'fixture.json'),'golden_sha256':sha256(fw/'golden.json'),'image_plan':str(fw/'image-plan.txt'),
        'simulator_sha256':sha256(sim),'effective_seeds':{'vcs':seed,'cocotb':seed,'cpu_i':seed^0x49,'cpu_d':seed^0x44,'backend':seed^0x4e}}
    write_json(dest/'case.json',cfg)
    try:run.execute('case-'+name,[tools['python'],ROOT/'scripts/cocotb_case.py','--case',dest/'case.json','--sim',sim],config['timeouts_seconds']['simulation'],cwd=dest)
    finally:shutil.copytree(dest,run.path/'artifacts/cocotb'/name)
    return json.loads((dest/'checks.json').read_text())

def archive(run):
    d=run.path/'artifacts';d.mkdir(exist_ok=True)
    for name in ('firmware','generated'):
        if (run.build/name).exists():shutil.copytree(run.build/name,d/name,dirs_exist_ok=True)
    if (run.build/'compiled/tb_cpu.sv').exists():shutil.copy2(run.build/'compiled/tb_cpu.sv',d/'tb_cpu.sv')
    if (run.build/'tool-report.json').exists():shutil.copy2(run.build/'tool-report.json',d/'tool-report.json')
    run.manifest['artifacts']={str(p.relative_to(run.path)):sha256(p) for p in sorted(run.path.rglob('*')) if p.is_file() and
        not (p.parent==run.path and p.name in ('manifest.json','checks.json','commands.json','exit-status.txt'))}

def verify_archive(path):
    from cocotb_case import validate
    from common.accel_waveform import check_waveform
    from accel_check import score
    path=Path(path).resolve();m=json.loads((path/'manifest.json').read_text())
    if m.get('status')!='PASS' or m.get('exit_code')!=0 or (path/'exit-status.txt').read_text().strip()!='0':raise ValueError('not a completed PASS')
    for rel,h in m['artifacts'].items():
        p=(path/rel).resolve()
        if not p.is_relative_to(path) or not p.is_file() or sha256(p)!=h:raise ValueError('modified/missing artifact: '+rel)
    if not m.get('artifacts') or sha256(path/'config.json')!=m['config']['sha256']:raise ValueError('config/artifact identity')
    for name,key in [('commands.json',None),('checks.json','checks')]:
        rows=json.loads((path/name).read_text());rows=rows[key] if key else rows
        if not rows or any(r.get('status')!='PASS' for r in rows):raise ValueError('missing/failed root checks or commands')
    src=m['source']
    if content_id(src['files'])!=src['sha256']:raise ValueError('source identity')
    with tarfile.open(path/'source.tar.gz') as tar:
        if set(tar.getnames())!=set(src['files']):raise ValueError('source inventory')
        for name,h in src['files'].items():
            if hashlib.sha256(tar.extractfile(name).read()).hexdigest()!=h:raise ValueError('source content')
        registered=json.load(tar.extractfile('configs/t13-accel.json'))
    config=json.loads((path/'config.json').read_text());suite=config.get('suite')
    if suite not in registered['suites']:raise ValueError('unknown suite')
    expected={**registered,'suite':suite,'selected_cases':registered['suites'][suite]}
    if config!=expected or set(m.get('cases',{}))!=set(expected['selected_cases']):raise ValueError('registered matrix mismatch')
    count=0
    for name in expected['selected_cases']:
        dest=path/'artifacts/cocotb'/name;cfg=json.loads((dest/'case.json').read_text());r=validate(dest,cfg)
        if cfg.get('task')!='T13' or cfg.get('negative') is not None or cfg.get('profile')!='control' or cfg['seed']!=int(re.search(r'seed(\d+)',name)[1]) or cfg['run_id']!=m['run_id'] or cfg['case_id']!=name or cfg['max_cycles']!=config['max_cycles'] or cfg['max_delay']!=config['max_delay']:raise ValueError('case identity/config')
        for key in ('fixture','golden'):
            if sha256(path/'artifacts/firmware'/f'{key}.json')!=cfg[key+'_sha256']:raise ValueError('fixture/golden identity')
        if sha256(dest/'transactions.csv')!=r['sequence_sha256'] or r['sequence_sha256']!=m['cases'][name]['sequence_sha256']:raise ValueError('trace digest')
        check_waveform(dest);score(dest,json.loads((path/'artifacts/firmware/golden.json').read_text()));count+=r['check_count']
    if suite!='smoke':
        negatives=m.get('negative_evidence',[])
        if len(negatives)!=len(config['negative_cases']):raise ValueError('missing negative matrix')
        for name,record in zip(config['negative_cases'],negatives):
            nd=Path(record);nm=json.loads((nd/'manifest.json').read_text())
            if nm.get('status')!='FAIL' or nm.get('exit_code')!=1 or nm.get('negative')!=name:raise ValueError('negative raw FAIL missing')
            for rel,h in nm['artifacts'].items():
                if sha256(nd/rel)!=h:raise ValueError('negative artifact changed')
    return {'status':'PASS','cases':len(m['cases']),'checks':count,'source_sha256':src['sha256']}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--suite',choices=['smoke','regression','full'],default='regression');p.add_argument('--run-id');p.add_argument('--verify-archive',type=Path);a=p.parse_args()
    if a.verify_archive:
        try:print(json.dumps(verify_archive(a.verify_archive),indent=2));return 0
        except Exception as e:print('ARCHIVE_REJECT: '+str(e),file=sys.stderr);return 1
    run=EvidenceRun(ROOT,'T13',a.run_id);print('T13 evidence: '+str(run.path),flush=True);code=1
    try:
        files=inputs();run.manifest['source']={'files':files,'sha256':content_id(files)}
        with tarfile.open(run.path/'source.tar.gz','w:gz') as tar:
            for name in files:tar.add(ROOT/name,arcname=name,recursive=False)
        config=json.loads((ROOT/'configs/t13-accel.json').read_text());config.update(suite=a.suite,selected_cases=config['suites'][a.suite]);write_json(run.path/'config.json',config)
        run.manifest.update(config={'sha256':sha256(run.path/'config.json')},qualification=config['scope'],invocation=[sys.executable,*sys.argv])
        tools={k:v['path'] for k,v in json.loads((ROOT/'docs/spec/toolchain-lock.json').read_text())['tools'].items()}
        vpi=environment(run,config,tools);generated=generate(run,tools,['soft'],600);fw=firmware(run,tools);sim=compile_sim(run,tools,generated,vpi)
        results={}
        for name in config['selected_cases']:
            r=case(run,tools,config,name,fw,sim);results[name]=r
            if name.endswith('-replay'):run.check('repeat-'+name,r['sequence_sha256']==results[name.removesuffix('-replay')]['sequence_sha256'],'all CPU/native/backend AXI events, same seed')
        run.manifest['cases']={k:{'status':v['status'],'checks':v['check_count'],'sequence_sha256':v['sequence_sha256'],'result':v['result']} for k,v in results.items()}
        if a.suite!='smoke':
            negatives=[]
            for name in config['negative_cases']:
                neg=EvidenceRun(ROOT,'T13_NEGATIVE',run.run_id+'-'+name);neg.manifest.update(parent=str(run.path),negative=name,expected='FAIL');rc=0
                try:case(neg,tools,config,name,fw,sim,name)
                except StepFailure as e:rc=e.exit_code
                finally:archive(neg);neg.finish(rc)
                d=neg.build/'cocotb'/name;status=json.loads((d/'case-status.json').read_text())
                reason={'empty':'required testcase identity/count mismatch','missing-xml':'missing/stale results.xml'}.get(name,'XML failure/error/skip')
                detected=rc==1 and reason in status.get('reason','')
                if name in ('held-reset','stale-data','early-completion'):
                    failure=json.loads((d/'checks.json').read_text())['first_failure'];detected &= failure['category']=={'held-reset':'completion','stale-data':'data','early-completion':'visibility'}[name]
                run.check('negative-'+name,detected,status);negatives.append(str(neg.path))
            run.manifest['negative_evidence']=negatives
            run.execute('project-tests',[tools['make'],'test'],300,cwd=ROOT)
        run.check('source-unchanged',inputs()==files,'all qualification inputs unchanged');code=0
    except StepFailure as e:code=e.exit_code;(run.path/'failure.txt').write_text(str(e)+'\n')
    except KeyboardInterrupt:code=130;(run.path/'failure.txt').write_text('Interrupted\n')
    except Exception:(run.path/'failure.txt').write_text(traceback.format_exc())
    finally:archive(run);code=run.finish(code)
    print(f'T13 {run.manifest["status"]}: {run.path}',flush=True);return code
if __name__=='__main__':sys.exit(main())
