#!/usr/bin/env python3
"""Rebuild real RTL tests; no proprietary simulator or frozen generated model.

Results describe digital component/CE tests with an explicitly behavioral
external memory environment. They are not board, DDR timing, PDS, or full
production-model performance evidence.
"""
import argparse
import difflib
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from lower_fp_pipeline import lower

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
VENDOR=['cf_math_pkg.sv','fpnew_pkg.sv','lzc.sv','fpnew_classifier.sv','fpnew_rounding.sv','fpnew_fma.sv']

def sources(kind):
    if kind=='argmax':
        return ['rtl/interfaces/axi4_if.sv','rtl/ce64/nx_ce64.sv']
    files=['rtl/ce64/vendor/registers.svh']
    files+=['rtl/ce64/vendor/'+name for name in VENDOR]
    if kind=='metadata':
        return files+['rtl/ce64/nx_ce64_fma_retimed.sv','rtl/ce64/nx_ce64_fp32_op.sv',
            'tests/competition_memory/metadata_component.sv']
    if kind=='pv':
        return files+['rtl/ce64/nx_ce64_fma_retimed.sv','rtl/sfu/nx_opt11_fp.sv',
            'rtl/sfu/nx_opt11_dispatch.sv','tests/competition_memory/pv_component.sv']
    files+=['rtl/interfaces/axi4_if.sv','rtl/soc/nx_accel_map.sv','rtl/ce64/nx_ce64_math_pkg.sv']
    files+=['rtl/ce64/'+name for name in [
        'nx_ce64_dot16.sv','nx_ce64_fma_retimed.sv','nx_ce64_fp32_op.sv',
        'nx_ce64_fp32_ordered_s0.sv','nx_ce64_scratch.sv','nx_ce64_dma.sv',
        'nx_ce64_desc.sv','nx_ce64_fault.sv','nx_ce64_regs.sv','nx_ce64_control.sv',
        'nx_ce64_sw_capture.sv','nx_ce64.sv']]
    files += [str(p.relative_to(ROOT)) for p in sorted((ROOT/'rtl/sfu').glob('*.sv'))]
    return files+['tests/competition_memory/ce_component.sv']

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--verilator',default=shutil.which('verilator'))
    p.add_argument('--verilator-root',default=os.getenv('VERILATOR_ROOT'))
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--jobs',type=int,default=2)
    p.add_argument('--only',choices=['pv','argmax','metadata','ce','ce-baseline'])
    p.add_argument('--split-fp-registers','--unpack-fp-metadata',dest='unpack_fp_metadata',action='store_true',help='Simulation-only old-Verilator compatibility: split each original packed FP pipeline flop output into an exactly typed element register')
    p.add_argument('--metadata-fixed-ready',action='store_true',help='Limit standalone FP metadata test to source gaps and an always-ready output; no general FP backpressure claim')
    a=p.parse_args()
    if not a.verilator:p.error('Set --verilator or put Verilator on PATH')
    out=a.out.resolve();out.mkdir(parents=True,exist_ok=True)
    env=dict(os.environ)
    if a.verilator_root:env['VERILATOR_ROOT']=a.verilator_root
    version=subprocess.check_output([a.verilator,'--version'],env=env,text=True).strip()
    receipt={'tool':version,'scope':__doc__.strip(),'cases':{},'source_sha256':{}}
    for case in [a.only] if a.only else ['pv','argmax','ce','ce-baseline']:
        kind='ce' if case=='ce-baseline' else case
        top={'pv':'pv_component','argmax':'nx_ce64_head_argmax','metadata':'metadata_component','ce':'ce_component'}[kind]
        files=sources(kind);cpp=HERE/(kind+'_sim.cpp');build=out/(case+'-obj')
        for name in files+[str(cpp.relative_to(ROOT)),'tests/competition_memory/run_rtl.py']:
            receipt['source_sha256'][name]=hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
        cmd=[a.verilator,'--cc','--exe','--build','-j',str(a.jobs),'--top-module',top,
            '-DOPT11_LANES=2','-Wno-fatal','-Wno-BLKANDNBLK','-I'+str(ROOT/'rtl/ce64/vendor'),
            '--Mdir',str(build),'-CFLAGS','-O2 -ffp-contract=off -frounding-math']
        # Verilator 5.006 diagnoses continuous array[0] plus sequential
        # array[i+1] in the unchanged FP implementation as BLKANDNBLK.
        # The waiver is for disjoint elements, not changed numeric RTL.
        if case=='ce-baseline':cmd+=['-GENHANCED=0']
        input_files=[str(ROOT/name) for name in files]
        if a.unpack_fp_metadata and kind in ('ce','metadata','pv'):
            path=ROOT/'rtl/ce64/nx_ce64_fma_retimed.sv'
            original=path.read_text()
            converted,counts=lower(original)
            copied=out/'compat-fp-metadata.sv'
            if not copied.exists() or copied.read_text()!=converted:copied.write_text(converted)
            (out/'original-fp.sv').write_text(original)
            patch=''.join(difflib.unified_diff(original.splitlines(True),converted.splitlines(True),
                fromfile='original-fp.sv',tofile='compat-fp-metadata.sv'))
            (out/'compat-fp.patch').write_text(patch)
            input_files=[str(copied) if x==str(path) else x for x in input_files]
            cmd.remove('-Wno-BLKANDNBLK')
            receipt['source_sha256']['tests/competition_memory/lower_fp_pipeline.py']=hashlib.sha256((HERE/'lower_fp_pipeline.py').read_bytes()).hexdigest()
            receipt['simulation_compatibility']={**counts,
                'input_sha256':hashlib.sha256(original.encode()).hexdigest(),
                'generated_sha256':hashlib.sha256(converted.encode()).hexdigest(),
                'patch_sha256':hashlib.sha256(patch.encode()).hexdigest(),
                'scope':'Each packed pipeline flop output is represented by an exactly typed element register and a continuous connection to its original array index. Same expressions, indexing, FF macros, enables/resets and latency. Production source untouched; no BLKANDNBLK waiver.'}
        cmd += input_files+[str(cpp)]
        started=time.monotonic()
        print('Building '+case,flush=True)
        with (out/(case+'-build.log')).open('w') as log:
            built=subprocess.run(cmd,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
        record={'build_command':cmd,'build_returncode':built.returncode,'result':'FAIL'}
        receipt['cases'][case]=record
        if not built.returncode:
            print('Running '+case,flush=True)
            with (out/(case+'-results.txt')).open('w') as log,(out/(case+'-stderr.txt')).open('w') as err:
                run_command=[str(build/('V'+top))]
                if kind=='metadata' and a.metadata_fixed_ready:run_command+=['--fixed-ready']
                ran=subprocess.run(run_command,cwd=ROOT,env=env,stdout=log,stderr=err,timeout=600)
            record['run_command']=run_command
            record['run_returncode']=ran.returncode
            record['result']='PASS' if not ran.returncode else 'FAIL'
        record['elapsed_seconds']=time.monotonic()-started
        (out/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
        if record['result']!='PASS':raise SystemExit(case+' failed; see '+str(out))
        print(case+' PASS',flush=True)
    return 0

if __name__=='__main__':sys.exit(main())
