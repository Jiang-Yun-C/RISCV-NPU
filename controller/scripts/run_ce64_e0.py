#!/usr/bin/env python3
"""Evidence-preserving E0 arithmetic qualification and same-port PDS probes."""
import argparse,json,re,shutil,sys,traceback
from pathlib import Path
from evidence import EvidenceRun,sha256,write_json,content_id
from pds.tool_identity import checked_tool
from pds.resource_report import parse_resources
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tests/ce64'))
from make_vectors import make
SV2V=ROOT/'build/T24_TOOLS/sv2v-20261011-v1/sv2v'
YOSYS=ROOT/'build/T24_TOOLS/yosys-20261011-v1/yosys'
VENDOR=['cf_math_pkg.sv','fpnew_pkg.sv','fpnew_classifier.sv','fpnew_rounding.sv','lzc.sv','fpnew_fma.sv']
LOCAL=['nx_ce64_math_pkg.sv','nx_ce64_dot16.sv','nx_ce64_fma_retimed.sv','nx_ce64_fp32_op.sv','nx_ce64_fp32_restore.sv','nx_ce64_group_probe.sv']

def sources(run):
    src=run.build/'sources';src.mkdir()
    shutil.copytree(ROOT/'rtl/ce64',src/'rtl');shutil.copytree(ROOT/'tests/ce64',src/'tests',ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copy2(__file__,run.path/'runner.py');shutil.copy2(ROOT/'scripts/evidence.py',run.path/'evidence.py')
    files={str(p.relative_to(src)):sha256(p) for p in src.rglob('*') if p.is_file()}
    run.manifest['source_sha256']=content_id(files);run.manifest['source_files']=files
    names=[src/'rtl/vendor'/n for n in VENDOR]+[src/'rtl'/n for n in LOCAL]
    return src,names

def archive(run):
    for d in ['sources','vectors']:
        if (run.build/d).exists():shutil.copytree(run.build/d,run.path/d)
    run.manifest['artifacts']={str(p.relative_to(run.path)):sha256(p) for p in run.path.rglob('*') if p.is_file() and p.name not in ('manifest.json','commands.json','checks.json','exit-status.txt')}

def rtl(run,src,names):
    tools={k:v['path'] for k,v in json.loads((ROOT/'docs/spec/toolchain-lock.json').read_text())['tools'].items()}
    result=make(run.build/'vectors');run.manifest.update(vectors=result,fixture_sha256=result['parents']['fixture'],golden_sha256=result['parents']['golden'],
        threshold_sha256=result['parents']['threshold'],firmware_sha256=result['parents']['ELF'])
    run.manifest['tests']={}
    for test,param in [('dot','PIPE_PRODUCTS'),('restore','PARALLEL'),('group','PARALLEL')]:
        for variant in [0,1]:
            case=f'{test}-{variant}';dest=run.build/case;dest.mkdir()
            sim=dest/'simv'
            run.execute('compile-'+case,[tools['vcs'],'-full64','-sverilog','-timescale=1ns/1ps',
                src/'rtl/vendor/registers.svh',*names,src/'tests'/('tb_'+test+'.sv'),
                '-top','tb_'+test,'-pvalue+tb_'+test+'.'+param+'='+str(variant),'-o',sim],240,cwd=dest)
            log=run.execute('test-'+case,[sim,'-no_save','+vectors='+str(run.build/'vectors'/('restore.txt' if test=='restore' else 'groups.txt'))],300,cwd=dest)
            text=log.read_text();marker='CE64_'+test.upper()+'_PASS'
            run.check('observed-'+case,marker in text and 'Fatal' not in text,text[-1000:])
            run.manifest['tests'][case]={'summary':re.search(marker+r'[^\n]*',text)[0]}
            for csv in dest.glob('*.csv'):shutil.copy2(csv,run.path/(case+'.csv'))
    run.manifest.update(qualification_scope='RTL arithmetic, bit-exact p/v/partial and flags, frozen T16 subset arithmetic, framing/backpressure/local reset. No DMA/SoC/board qualification',
        unproven=['unbounded formal liveness/arithmetic','four-state unknown input policy','complete DMA fault and call-order precedence','full-head and real CPU-driven CE integration'])

def map_component(run,src,names,args):
    contract,identity=checked_tool(ROOT/'docs/spec/pds-toolchain-2024.2-global.json',args.tool_evidence)
    run.manifest.update(tool_identity=identity,device_identity='Logos2/PG2L200H/FBB676/-6',IP_identity=json.loads((src/'rtl/vendor/provenance.json').read_text()))
    rtl_name='nx_ce64_dot16' if args.profile.startswith('D16') else 'nx_ce64_fp32_restore'
    parameter='PIPE_PRODUCTS' if args.profile.startswith('D16') else 'PARALLEL'
    value=int(args.profile in ('D16-P','F32-P'))
    # Derive wrappers by copying exactly the candidate's declaration/ports.
    raw=(src/'rtl'/(rtl_name+'.sv')).read_text()
    decl=re.search(r'module '+rtl_name+r'[\s\S]*?\);',raw)[0]
    top='ce64_'+args.profile.lower().replace('-','_')
    declaration=re.sub(r'module '+rtl_name+r'\s*#\([^)]*\)', 'module '+top,decl)
    # Both variants receive the same elastic input/output registers. This
    # includes cast, multiplier input and finite/status logic in FF-to-FF
    # synthesis timing, instead of leaving them as unconstrained port paths.
    ports=[]
    for direction,chunk in re.findall(r'(input|output)\s+logic\s+([^\n]+)',decl):
        chunk=chunk.rstrip(',');match=re.match(r'(signed\s+)?(\[[^]]+\]\s*)?(.*)',chunk)
        kind=(match[1] or '')+(match[2] or '')
        for name in match[3].split(','):ports.append((direction,kind,name.strip()))
    ins=[(k,n) for d,k,n in ports if d=='input' and n not in ('clock','reset_n','req_valid_i','rsp_ready_i')]
    outs=[(k,n) for d,k,n in ports if d=='output' and n not in ('req_ready_o','rsp_valid_o')]
    code=declaration+'\nlogic iv,dready,ov,sready;\n'
    code+=''.join(f'logic {k} {n}_r;\n' for k,n in ins)+''.join(f'logic {k} {n}_d;\n' for k,n in outs)
    code+='assign req_ready_o=reset_n && (!iv || dready);\nassign sready=reset_n && (!rsp_valid_o || rsp_ready_i);\n'
    code+='always_ff @(posedge clock or negedge reset_n) begin\nif(!reset_n) begin iv<=0;rsp_valid_o<=0;\n'
    code+=''.join(n+'_r<=0;\n' for k,n in ins)+''.join(n+'<=0;\n' for k,n in outs)
    code+='end else begin\nif(req_ready_o) begin iv<=req_valid_i;if(req_valid_i) begin\n'
    code+=''.join(n+'_r<='+n+';\n' for k,n in ins)+'end end\n'
    code+='if(sready) begin rsp_valid_o<=ov;if(ov) begin\n'+''.join(n+'<='+n+'_d;\n' for k,n in outs)+'end end\nend end\n'
    connections=['.clock(clock)','.reset_n(reset_n)','.req_valid_i(iv)','.req_ready_o(dready)','.rsp_valid_o(ov)','.rsp_ready_i(sready)']
    connections+=['.'+n+'('+n+'_r)' for k,n in ins]+['.'+n+'('+n+'_d)' for k,n in outs]
    code+=rtl_name+' #('+'.'+parameter+'('+str(value)+')) dut('+','.join(connections)+');\nendmodule\n'
    wrapper=src/'wrapper.sv';wrapper.write_text(code)
    converted=run.build/'converted.v'
    output=run.execute('convert',[SV2V,'--top='+top,'-DSYNTHESIS','-I'+str(src/'rtl/vendor'),src/'rtl/vendor/registers.svh',*names,wrapper],300)
    converted.write_text(output.read_text());shutil.copy2(converted,run.path/'converted.v')
    script=run.build/'lower.ys';elaborated=run.build/'elaborated.v'
    script.write_text(f'read_verilog -sv -defer {converted}\nhierarchy -check -top {top}\nproc\nopt\ncheck -assert\nwrite_verilog -noattr {elaborated}\n')
    run.execute('elaborate',[YOSYS,'-s',script],300)
    for p in [script,elaborated]:shutil.copy2(p,run.path/p.name)
    run.manifest['conversion']={str(p):sha256(p) for p in [SV2V,YOSYS,converted,elaborated,script]}
    fdc=run.build/'component.fdc';fdc.write_text('create_clock -name core -period 8.000 [get_ports clock]\n')
    flow=run.build/'flow.tcl'
    flow.write_text('set_arch -family Logos2 -device PG2L200H -package FBB676 -speedgrade -6\n'+
        f'add_design {{{elaborated}}}\nadd_constraint {{{fdc}}}\n'+
        f'if {{[catch {{compile -top_module {top} -system_verilog -compiler_directives SYNTHESIS}} e]}} {{puts "CE64_COMPILE_FAILED $e";exit 1}}\n'+
        'if {[catch {synthesize -ads -disable_io_insertion} e]} {puts "CE64_ADS_FAILED $e";exit 1}\nputs CE64_AREA_COMPLETE\nexit\n')
    run.execute('ads',['/usr/local/bin/pds2024-run',sys.executable,ROOT/'scripts/pds/run_interactive.py',flow,
        '--binary',contract['entries']['shell'],'--log',run.path/'pds.log','--cwd',run.build,'--marker','CE64_AREA_COMPLETE'],1800)
    log=(run.path/'pds.log').read_text();snr=run.build/'synthesize'/(top+'.snr');vm=run.build/'synthesize'/(top+'_syn.vm')
    run.check('fresh-netlist',snr.is_file() and vm.is_file() and vm.stat().st_size>0,'ADS artifacts')
    run.check('mapped-clean',not re.search(r'^E:|Program Error Out|unmapped RTL inst',log,re.M),'no unmapped errors')
    resources=parse_resources(snr.read_text());run.manifest['mapped_resources']=resources
    timing=re.search(r'^\s*core\s+([\d.]+) MHz\s+([\d.]+) MHz\s+([\d.]+)\s+([\d.]+)\s+(-?[\d.]+)',snr.read_text(),re.M)
    run.manifest['synthesis_timing']={'scope':'ADS estimate, common registered boundaries, not routed timing',
        'requested_MHz':float(timing[1]),'estimated_MHz':float(timing[2]),'slack_ns':float(timing[5])} if timing else 'UNKNOWN'
    run.manifest['timing_status']='SYNTHESIS_ESTIMATE_MET' if timing and float(timing[5])>=0 else 'TIMING_FAIL' if timing else 'UNKNOWN'
    cap=dict(luts=4000,registers=4000,drm36k=0,apm=16) if args.profile.startswith('D16') else dict(luts=10000,registers=8000,drm36k=4,apm=12)
    okay=resources['latches']==0 and all(resources[k]<=v for k,v in cap.items())
    run.manifest.update(profile=args.profile,top=top,component_budget=cap,resource_status='PASS' if okay else 'RESOURCE_FAIL',
        netlist_sha256=sha256(vm),constraints_sha256=sha256(fdc),qualification_scope='Component ADS only; no whole-board resource qualification',
        unproven=['routed timing/DRC','mapped-netlist numerical replay','whole-board resources','SoC/board behavior'])
    for p in [snr,vm,fdc,flow]:shutil.copy2(p,run.path/p.name)
    run.check('component-budget',okay,dict(resources=resources,cap=cap))

def main():
    p=argparse.ArgumentParser();p.add_argument('--stage',choices=['rtl','map'],required=True);p.add_argument('--run-id',required=True)
    p.add_argument('--profile',choices=['D16-S','D16-P','F32-S','F32-P']);p.add_argument('--tool-evidence',type=Path)
    a=p.parse_args();run=EvidenceRun(ROOT,'CE64_E0_RTL' if a.stage=='rtl' else 'CE64_E0_MAP',a.run_id);code=1
    run.manifest.update(route='C_CE64_PRIMARY',task_status='ACTIVE',physical_qualification=False,
        latency_II='NOT_RUN',payload_bytes='NOT_RUN',native_bytes='NOT_RUN',fault_tests='NOT_RUN')
    try:
        src,names=sources(run)
        if a.stage=='rtl':rtl(run,src,names)
        else:
            if not a.profile or not a.tool_evidence:p.error('map needs --profile and --tool-evidence')
            map_component(run,src,names,a)
        code=0
    except Exception:
        (run.path/'failure.txt').write_text(traceback.format_exc());run.checks.append(dict(name='runner',status='FAIL',detail='failure.txt'))
    finally:
        archive(run);code=run.finish(code)
    print('CE64 E0 '+run.manifest['status']+': '+str(run.path),flush=True);return code

if __name__=='__main__':sys.exit(main())
