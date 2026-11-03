#!/usr/bin/env python3
"""Offline OPT07: isolated B, VCS CPU cycles, independent full-model quality."""
import argparse,json,re,shutil,sys,traceback,threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from evidence import EvidenceRun,StepFailure,sha256,write_json,content_id,utc_now
from run_cocotb import environment,generate
from tests.models.prepare_image import prepare,parse_elf
from tests.opt07.fixture import generate as fixture

class Run(EvidenceRun):
    def __init__(self,*a,**kw):self._lock=threading.RLock();super().__init__(*a,**kw)
    def flush(self):
        with self._lock:super().flush()

def inputs():
    names=['scripts/run_opt07.py','scripts/verify_opt07.py','scripts/cocotb_case.py','scripts/run_cocotb.py','scripts/evidence.py','docs/spec/opt07-swiglu.md',
           'scripts/probe_tools.py','tests/cocotb/test_opt07.py','tests/cocotb/common/checks.py','tests/cocotb/common/runtime_waveform.py',
           'tests/runtime/tb_body.svh','tests/runtime/check.py','tests/models/prepare_image.py','tests/models/axi_sparse_mem.sv',
           'tests/models/sparse_memory_pkg.sv','rtl/interfaces/axi4_if.sv','configs/opt07-swiglu.json','configs/t05-thresholds.json',
           'configs/t11-reference.json','docs/spec/toolchain-lock.json','configs/cocotb-toolchain-lock.json','third_party/lock.json',
           'docs/spec/model-pack-v1-manifest.json','model_tools/numeric_v1.py','model_tools/verify_pack.py',
           'software/reference/runtime.py','tests/reference/validate.py','tests/reference/oracle.py','tests/vectors/check_v1.py',
           'scripts/evaluate_t11.py','scripts/application_v2/common.py','software/application_v2/program.py',
           'configs/application_v2/release.json','configs/application_v2/prompt.txt','tests/application/v2/dev.jsonl','tests/application/v2/heldout.jsonl']
    for folder in ('variants/opt07','tests/opt07','cpu_gen'):
        names += [str(p.relative_to(ROOT)) for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and 'target' not in p.parts]
    return {n:sha256(ROOT/n) for n in sorted(set(names))}

def build_firmware(r,repo,tools,label,long=False,mode=None):
    fx=fixture(r.build/('fixture-'+label),long,mode);out=r.build/('firmware-'+label);out.mkdir()
    port=repo/'firmware/runtime/port';ref=repo/'firmware/runtime/reference'
    flags=['-std=c11','-DNX_PORTABLE','-DHARD_FLOAT','-march=rv32imf_zicsr_zifencei','-mabi=ilp32f','-O2','-ffp-contract=off','-fno-fast-math',
           '-fno-strict-aliasing','-ffreestanding','-fno-builtin','-fno-pic','-nostdlib','-nostartfiles','-msmall-data-limit=0',
           '-ffunction-sections','-fdata-sections','-fstack-usage','-Wl,--gc-sections','-Wl,--build-id=none','-Wall','-Wextra','-Werror',
           '-Wno-unknown-pragmas','-I',ref,'-I',fx]
    r.execute('firmware-'+label,[tools['rv32_gcc'],*flags,'-T',port/'link.ld',repo/'firmware/cpu/start.S',ROOT/'tests/opt07/main.c',ref/'nx_reference.c','-lm','-lc','-lgcc','-o',out/'kernel.elf'],90)
    log=r.execute('disassemble-'+label,[tools['rv32_objdump'],'-d',out/'kernel.elf'],30)
    shutil.copy2(log,out/'kernel.dis')
    entry,segments,abi=parse_elf((out/'kernel.elf').read_bytes(),base=0x10000,capacity=0xb8000000-0x10000)
    r.check('abi-'+label,entry==0x10000 and abi==2,'RV32IMF ILP32F production flags')
    prepare(out/'image','PRELOAD',out/'kernel.elf','elf',base=0x10000,capacity=0xb8000000-0x10000)
    return fx,out

def compile_sim(r,tools,generated,vpi,access="r"):
    dest=r.build/'compiled';dest.mkdir();rtl=generated/'hard/T09Cpu.v'
    for f in rtl.parent.glob('*.bin'):shutil.copy2(f,dest/f.name)
    ports=re.findall(r'(input|output)\s+wire\s*(\[[^]]+\])?\s*(\w+)\s*[,\n]',rtl.read_text().split(');',1)[0])
    wrapper='`timescale 1ns/1ps\nmodule tb_cpu;\n'+''.join(f"{'logic' if d=='input' else 'wire'} {w} {n};\n" for d,w,n in ports)+'T09Cpu cpu(.*);\n'+(ROOT/'tests/runtime/tb_body.svh').read_text()+'\nendmodule\n'
    (dest/'tb_cpu.sv').write_text(wrapper)
    r.execute('vcs-build',[tools['vcs'],'-full64','-sverilog','-timescale=1ns/1ps','-debug_access+'+access,'-cc',tools['vcs_host_cc'],'-cpp',tools['vcs_host_cxx'],
        '-LDFLAGS','-Wl,--no-as-needed','-load',vpi,'-top','tb_cpu',*[ROOT/n for n in ['rtl/interfaces/axi4_if.sv','tests/models/sparse_memory_pkg.sv','tests/models/axi_sparse_mem.sv']],rtl,dest/'tb_cpu.sv','-o',dest/'simv'],300,cwd=dest)
    return dest/'simv'

def case(r,cfg,label,seed,fx,sim,long=False,negative=None):
    fixture_dir,out=fx;dest=r.build/'cocotb'/label;dest.mkdir(parents=True)
    for f in sim.parent.glob('*.bin'):shutil.copy2(f,dest/f.name)
    c=dict(cfg,task='OPT07',case_id=label,run_id=r.run_id,seed=seed,negative=negative,profile='long' if long else 'short',python_prefix=sys.prefix,
           max_cycles=cfg['max_cycles_long'] if long else cfg['max_cycles_short'],image_plan=str(out/'image/load.plan'),
           fixture=str(fixture_dir/'inputs.h'),golden=str(fixture_dir/'golden.json'),fixture_sha256=sha256(fixture_dir/'inputs.h'),golden_sha256=sha256(fixture_dir/'golden.json'),
           simulator_sha256=sha256(sim),effective_seeds=dict(python=seed,cocotb=seed,vcs=seed,i_memory=seed^0x49,d_memory=seed^0x44))
    if negative=='held-reset':c['max_cycles']=10000
    write_json(dest/'case.json',c)
    try:r.execute('case-'+label,[sys.executable,ROOT/'scripts/cocotb_case.py','--case',dest/'case.json','--sim',sim],cfg['timeouts_seconds']['simulation_long' if long else 'simulation_short'],cwd=dest)
    finally:shutil.copytree(dest,r.path/'cocotb'/label)
    result=json.loads((dest/'observations.json').read_text());print('PASS RTL '+label+' '+str(result['cycles']),flush=True);return result

def numerical(parent,repo,mode):
    r=Run(ROOT,'OPT07_NUMERIC',parent.run_id+'-mode'+str(mode));code=1
    lib=r.build/'kernel.so'
    try:
        r.execute('compile',['gcc','-std=c11','-O3','-march=native','-fno-fast-math','-ffp-contract=off','-fopenmp','-Wall','-Wextra','-Werror','-shared','-fPIC',
            '-I',repo/'firmware/runtime/reference',f'-DNX_OPT07_DEFAULT={mode}',repo/'firmware/runtime/reference/nx_reference.c','-lm','-o',lib],60)
        r.execute('numerical',[sys.executable,ROOT/'tests/reference/validate.py','--lib',lib,'--output',r.build/'numeric'],1800,cwd=ROOT)
        code=0
    except StepFailure as exc:code=exc.exit_code
    finally:
        shutil.copy2(lib,r.path/'kernel.so')
        if (r.build/'numeric').exists():shutil.copytree(r.build/'numeric',r.path/'numeric')
        r.manifest['artifacts']={str(p.relative_to(r.path)):sha256(p) for p in r.path.rglob('*') if p.is_file() and not(p.parent==r.path and p.name in ('manifest.json','commands.json','checks.json','exit-status.txt'))}
        code=r.finish(code)
    print('NUMERIC mode='+str(mode)+' '+r.manifest['status'],flush=True)
    return dict(mode=mode,path=str(r.path.relative_to(ROOT)),lib=str(lib),status=r.manifest['status'],manifest_sha256=sha256(r.path/'manifest.json'))

def negative(parent,cfg,name,fx,sim):
    r=Run(ROOT,'OPT07_NEGATIVE',parent.run_id+'-'+name);code=1
    try:case(r,cfg,'negative',1,fx,sim,negative=name)
    except StepFailure as exc:code=exc.exit_code
    finally:code=r.finish(code)
    parent.check('negative-'+name,code!=0 and json.loads((r.path/'cocotb/negative/case-status.json').read_text())['status']=='FAIL',str(r.path))
    return str(r.path.relative_to(ROOT))

def production(r,repo,parent,mode):
    commands=json.loads((parent/'build-commands.json').read_text());cmd=next(x for x in commands if x['name']=='application-link')
    original=ROOT/'build/OPT01/opt01-integration-20261018-v2/repo';oldout=original/'build/T25_PREPARE/opt02-full-20261018-v2/application'
    prod=r.build/'production';shutil.copytree(original/'evidence/T25_PREPARE/opt02-full-20261018-v2/application',prod)
    for n in ('tokenizer.S','tokenizer.nxt'):
        if (oldout/n).exists():shutil.copy2(oldout/n,prod/n)
    argv=[x.replace(str(oldout),str(prod)).replace(str(original),str(repo)) for x in cmd['argv']]
    argv.insert(1,f'-DNX_OPT07_DEFAULT={mode}')
    r.execute('production-link',argv,180,cwd=prod)
    entry,segments,abi=parse_elf((prod/'application.elf').read_bytes(),base=0xb4000000,capacity=8*1024*1024)
    r.check('production-rebuilt',entry==0xb4000000 and abi==2 and len(segments)==1,'B CE64 full application, selected default, ILP32F')
    write_json(r.path/'production-identity.json',dict(mode=mode,entry=entry,abi='ILP32F',elf_sha256=sha256(prod/'application.elf'),bytes=len(segments[0].data),memory_bytes=segments[0].memory_size,programmed=False))

def main():
    p=argparse.ArgumentParser();p.add_argument('--run-id');a=p.parse_args();r=Run(ROOT,'OPT07',a.run_id);code=1;print(r.path,flush=True)
    try:
        cfg=json.loads((ROOT/'configs/opt07-swiglu.json').read_text());write_json(r.path/'config.json',cfg)
        r.manifest.update(scope=cfg['scope'],board_gate=cfg['board_gate'],programming_performed=False,physical_qualification=False)
        files=inputs();write_json(r.path/'inputs.json',files)
        for name in files:
            dst=r.path/'sources'/name;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/name,dst)
        parent=ROOT/cfg['parent'];b=ROOT/cfg['base'];baseline=json.loads((parent/'source-B.json').read_text())
        r.check('baseline-identity',all(sha256(b/n)==h for n,h in baseline.items()),len(baseline))
        protected={n:sha256(ROOT/n) for n in json.loads((parent/'protected-before.json').read_text())}
        write_json(r.path/'protected-before.json',protected)
        repo=r.build/'repo';shutil.copytree(b,repo)
        for name in json.loads((parent/'dependency-relocations.json').read_text()):
            dst=repo/name;dst.write_text(dst.read_text().replace(str(b),str(repo)))
        shutil.copytree(ROOT/cfg['overlay'],repo,dirs_exist_ok=True)
        write_json(r.path/'candidate-sources.json',{str(p.relative_to(repo)):sha256(p) for p in (repo/'firmware').rglob('*') if p.is_file()})
        r.manifest.update(candidate_repo=str(repo),source_id=content_id(files))
        tools={k:v['path'] for k,v in json.loads((ROOT/'docs/spec/toolchain-lock.json').read_text())['tools'].items()};vpi=environment(r,cfg,tools)
        r.execute('host-tests',[sys.executable,'-m','unittest','tests.opt07.test_host','tests.opt07.test_gate','-v'],180,cwd=ROOT)
        # Full-model independent reference and actual CPU run concurrently;
        # each process owns its result directory and bounded subprocess group.
        with ThreadPoolExecutor(max_workers=10) as pool:
            nums={m:pool.submit(numerical,r,repo,m) for m in range(4)}
            short=build_firmware(r,repo,tools,'short')
            long={m:build_firmware(r,repo,tools,'width4864-mode'+str(m),True,m) for m in range(4)}
            gen=generate(r,tools,['hard'],cfg['timeouts_seconds']['generate']);sim=compile_sim(r,tools,gen,vpi)
            matrix=[('seed1',1),('seed7',7),('seed19',19),('seed1-repeat',1)]
            jobs={name:pool.submit(case,r,cfg,name,seed,short,sim) for name,seed in matrix}
            jobs.update({'width4864-mode'+str(m):pool.submit(case,r,cfg,'width4864-mode'+str(m),1,long[m],sim,True) for m in range(4)})
            numeric={str(m):f.result() for m,f in nums.items()};write_json(r.path/'numeric-candidates.json',numeric)
            r.check('original-full-model-pass',numeric['0']['status']=='PASS',numeric['0'])
            r.execute('operators',[sys.executable,ROOT/'tests/opt07/host.py','--lib',numeric['3']['lib'],'--output',r.path/'operators.json'],180,cwd=ROOT)
            # Both dev evaluations precede final algorithm selection. Quality
            # heldout is opened only after measured cycles select the candidate.
            for mode in (0,3):
                if numeric[str(mode)]['status']=='PASS':
                    r.execute('quality-dev-mode'+str(mode),[sys.executable,ROOT/'scripts/evaluate_t11.py','--lib',numeric[str(mode)]['lib'],'--split','dev','--output',r.path/('dev-mode'+str(mode)),'--workers','4','--threads','8'],1800,cwd=ROOT)
            if numeric['3']['status']=='PASS':
                a=json.loads((ROOT/numeric['0']['path']/'numeric/result.json').read_text())
                guarded_metrics=json.loads((ROOT/numeric['3']['path']/'numeric/result.json').read_text())
                r.check('cumulative-metrics-identical',a['metrics']==guarded_metrics['metrics'],'all independent block/KV/logits error records')
                rows=lambda mode:[json.loads(x) for x in (r.path/('dev-mode'+str(mode))/'results.jsonl').read_text().splitlines()]
                r.check('dev-generation-identical',[(x['id'],x['output_ids'],x['stop_reason']) for x in rows(0)]==[(x['id'],x['output_ids'],x['stop_reason']) for x in rows(3)],'all development generated IDs and stop reasons')
            results={name:f.result() for name,f in jobs.items()}
        write_json(r.path/'rtl-results.json',results)
        r.check('deterministic-replay',(r.path/'cocotb/seed1/cpu-output.txt').read_bytes()==(r.path/'cocotb/seed1-repeat/cpu-output.txt').read_bytes(),'CPU MMIO records including all mcycle values')
        baseline_out=results['width4864-mode0']['metrics']['0']['output_sha256']
        r.check('guarded-full-width-bit-exact',results['width4864-mode3']['metrics']['3']['output_sha256']==baseline_out,'4864 actual RV32 outputs')
        ops=json.loads((r.path/'operators.json').read_text())
        eligible=[m for m in (0,3) if numeric[str(m)]['status']=='PASS' and ops[str(m)]['status']=='PASS' and json.loads((r.path/('dev-mode'+str(m))/'summary.json').read_text())['status']=='PASS']
        mode=min(eligible,key=lambda m:results['width4864-mode'+str(m)]['metrics'][str(m)]['cycles'])
        freeze=dict(frozen_at=utc_now(),mode=mode,source_id=content_id(files),library_sha256=sha256(numeric[str(mode)]['lib']),criteria=cfg['selection_policy'],eligible=eligible,heldout_used_for_selection=False)
        write_json(r.path/'selection-freeze.json',freeze)
        r.execute('quality-heldout',[sys.executable,ROOT/'scripts/evaluate_t11.py','--lib',numeric[str(mode)]['lib'],'--split','heldout','--output',r.path/'heldout','--workers','4','--threads','8'],1800,cwd=ROOT)
        production(r,repo,parent,mode)
        r.manifest['negative_evidence']={n:negative(r,cfg,n,short,sim) for n in ('bad-golden','held-reset','empty','missing-xml')}
        r.check('sources-unchanged',inputs()==files,content_id(files))
        r.check('baseline-preserved',all(sha256(b/n)==h for n,h in baseline.items()),'Frozen B')
        after={n:sha256(ROOT/n) for n in protected};write_json(r.path/'protected-after.json',after);r.check('root-A-release-preserved',after==protected,len(after))
        r.manifest.update(selected_mode=mode,numeric_candidates=numeric,rtl_cases=len(results),candidate_software_speed_measured=True)
        code=0
    except Exception:(r.path/'failure.txt').write_text(traceback.format_exc());print(traceback.format_exc(),flush=True)
    finally:
        for folder in ('firmware-short','fixture-short','production','generated'):
            if (r.build/folder).exists():shutil.copytree(r.build/folder,r.path/folder)
        for folder in r.build.glob('*width4864*'):
            if folder.is_dir():shutil.copytree(folder,r.path/folder.name)
        r.manifest['artifacts']={str(p.relative_to(r.path)):sha256(p) for p in r.path.rglob('*') if p.is_file() and not(p.parent==r.path and p.name in ('manifest.json','commands.json','checks.json','exit-status.txt'))}
        code=r.finish(code)
    print(r.manifest['status']+' '+str(r.path),flush=True);return code
if __name__=='__main__':sys.exit(main())
