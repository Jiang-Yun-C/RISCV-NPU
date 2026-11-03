#!/usr/bin/env python3
"""Launch one isolated VCS/VPI process and reject incomplete cocotb evidence."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from evidence import sha256, write_json


def validate(directory, cfg, started_ns=0):
    directory=Path(directory)
    xml=directory/'results.xml'; report=directory/'checks.json'
    if not xml.is_file() or xml.stat().st_mtime_ns < started_ns:
        raise ValueError('missing/stale results.xml')
    root=ET.parse(xml).getroot()
    cases=root.findall('.//testcase')
    runtime_task=cfg.get('task')=='T12'
    accel_task=cfg.get('task')=='T13'
    name,module=('runtime_execution','test_runtime') if runtime_task else ('cpu_execution','test_cpu')
    if accel_task:name,module='accel_control','test_accel_control'
    if cfg.get('task')=='T14':name,module='streaming','test_streaming'
    if cfg.get('task')=='T15':name,module='linear','test_linear'
    if cfg.get('task')=='T16':name,module='soc_accel','test_soc_accel'
    if cfg.get('task')=='T24':name,module='board_soc','test_board_soc'
    if cfg.get('task')=='T17':name,module='uart_boot','test_uart_boot'
    if cfg.get('task')=='T18':name,module='sd_boot','test_sd_boot'
    if cfg.get('task')=='T19':name,module='model_integration','test_model_integration'
    if cfg.get('task')=='T20':name,module='application','test_application'
    if cfg.get('task')=='T22':name,module='platform_adapter','test_platform_adapter'
    if cfg.get('task')=='T23':name,module='ddr_adapter','test_ddr_adapter'
    if cfg.get('task')=='OPT06':name,module='opt06_stream','test_opt06'
    if cfg.get('task')=='OPT07':name,module='opt07_swiglu','test_opt07'
    if cfg.get('task')=='OPT08_COPY':name,module='opt08_copy','test_opt08_copy'
    if cfg.get('task')=='OPT14_BASELINE':name,module='opt14_baseline','test_opt14_baseline'
    if cfg.get('task')=='OPT09':name,module='opt09_prefix','test_opt09'
    if len(cases)!=1 or cases[0].get('name')!=name or cases[0].get('classname')!=module:
        raise ValueError('required testcase identity/count mismatch (empty or unexpected test)')
    if any(node.tag in ('failure','error','skipped') for node in root.iter()):
        raise ValueError('XML failure/error/skip')
    if not report.is_file() or report.stat().st_mtime_ns < started_ns:
        raise ValueError('missing/stale checks.json')
    checks=json.loads(report.read_text())
    if checks.get('status')!='PASS' or checks.get('first_failure') is not None:
        raise ValueError('independent scoreboard failed')
    for key in ('case_id','run_id','seed','profile','fixture_sha256','golden_sha256'):
        if checks.get(key)!=cfg[key]: raise ValueError('stale/mismatched checks identity: '+key)
    runtime=checks.get('runtime',{})
    if runtime.get('prefix')!=cfg.get('python_prefix') or runtime.get('cocotb')!=cfg.get('cocotb_version'):
        raise ValueError('embedded Python/cocotb environment mismatch')
    cats=checks.get('categories',{})
    required={'axi_request','axi_response','axi_stability','axi_write','signature','trap','interrupt',
              'mret','cache','branch','fault','uart','execution','completion','counters'}
    if runtime_task:
        required={'input_identity','output_set','execution','completion','memory_protection','axi','timing'}
        required|= {'tokenizer','utf8','template','session','t11','t11_integer','tokenizer_errors'} if cfg['profile']=='control' else {'model','kv','dispatch','session','reset'}
    if accel_task:required={'input_identity','output_set','execution','completion','lane','reject','ownership','visibility','sequence','axi','cache','data','recovery','fault','protection','interrupt','state','component_axi','component_data','component_protection','component_isolation'}
    if cfg.get('task')=='T14':
        required={'input_identity','output_set','execution','completion','axi_request','axi_response','axi_write','axi_stability','memory_protection','read_data','data','counters','tiling','timing'}
        if cfg['profile']=='errors':required|={'fault','recovery','reject'}
    if cfg.get('task')=='T15':
        required={'input_identity','output_set','execution','completion','axi_request','axi_response','axi_write','axi_stability','memory_protection','read_data','data','counters','tiling','timing'}
        required|={'production'} if cfg.get('full_projection') else {'integer','restoration'}
        if cfg['profile']=='errors':required|={'fault','recovery','reject'}
    if cfg.get('task') in ('T16','T24'):
        required={'input_identity','output_set','execution','completion','submission','quantization','upload','ownership','visibility','sequence','axi','cache','data','read_data','timing','protection','interrupt','reject','recovery'}
        if cfg['profile']=='control':required.add('fault')
        if cfg['task']=='T24':required|={'ddr_fault','ddr_payload','native_protocol'}
    if cfg.get('task')=='T17':
        required={'input_identity','initial_memory','source','protocol','signature','uart_framing','uart_bytes',
                  'loading','rejection','execution','completion','axi_request','axi_response','axi_write','protection','cache','visibility'}
    if cfg.get('task')=='T18':
        required={'input_identity','initial_memory','protocol','pins','axi_request','axi_response','axi_write','protection','loading','rejection','seal','execution','completion','alias'}
        if cfg['profile'] in ('smoke','control','rvv','down','errors'):required|={'selftest','signature','cache','visibility'}
    if cfg.get('task')=='T19':
        required={'input_identity','output_set','execution','completion','session','dispatch','timing','data','kv','gqa','protection','ownership','visibility','submission','quantization','axi','read_data','cache'}
        if cfg['profile']=='continuous':required|={'boundary','reset'}
    if cfg.get('task')=='T20':
        required={'input_identity','execution','completion','axi','protection','uart','request','provenance','validation','actions','sensor','display','side_effects','pwm','i2c','freshness','pins'}
    if cfg.get('task')=='T22':
        required={'input_identity','ram_data','ram_latency','ram_enable','reset','uart','calibration_gate',
                  'address','write_data','byte_enable','read_data','stability','completion','fault','recovery'}
    if cfg.get('task')=='T23':
        required={'input_identity','completion','recovery','calibration_gate','native_protocol','id','address','stability','write_data','read_data','byte_enable','burst','visibility','counters','t04','t14','arbitration','reject','fault'}
    if cfg.get('task')=='OPT06':required={'input_identity','completion','uart_framing','uart_bytes','state','tokenizer','recovery','tokens','utf8','timing','execution'}
    if cfg.get('task')=='OPT06' and cfg.get('profile')=='nominal':required.discard('recovery')
    if cfg.get('task')=='OPT07':
        required={'input_identity','output_set','completion','numeric','quantization','integer','scale','timing','execution','axi','memory_protection'}
        if cfg['profile']=='short':required|={'exact_candidate','fallback','call_overhead','reject'}
    if cfg.get('task')=='OPT08_COPY':required={'input_identity','completion','output_set','data','timing','execution','protection'}
    if cfg.get('task')=='OPT14_BASELINE':required={'input_identity','completion','output_set','data','timing','execution','protection','semantics','golden'}
    if cfg.get('task')=='OPT09':required={'input_identity','completion','output_set','invalidation','identity','boundary','ids','kv','logits','cold_hot_exact','request','timing','execution','axi','memory_protection','no_kv_copy'}
    if not required.issubset(cats) or any(type(v) is not int or v<=0 for v in cats.values()):
        raise ValueError('missing/zero independent check category')
    if checks.get('check_count')!=sum(cats.values()): raise ValueError('inconsistent actual check count')
    for name in ('observations.json','cpu.vcd'):
        path=directory/name
        if not path.is_file() or path.stat().st_size<100 or path.stat().st_mtime_ns<started_ns:
            raise ValueError('missing/stale observation artifact: '+name)
    log=(directory/'simulation.log').read_text()
    if 'cocotb v2.1.0' not in log or 'Running on Icarus' in log or 'VCS' not in log:
        raise ValueError('VCS/cocotb execution banner missing')
    if any(x in log for x in ('Fatal:', 'Error-', 'UVM_FATAL', 'UVM_ERROR', 'Cannot open file')):
        raise ValueError('unexplained simulator fatal/error')
    return checks


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--case',type=Path,required=True);p.add_argument('--sim',type=Path,required=True)
    args=p.parse_args();cfg=json.loads(args.case.read_text());root=Path(__file__).resolve().parents[1]
    if any(Path(n).exists() for n in ('results.xml','checks.json','simulation.log')):
        raise SystemExit('case directory contains old results')
    libpython_path=subprocess.check_output([sys.executable,"-m","cocotb_tools.config","--libpython"],text=True).strip()
    env=os.environ.copy()
    env.update(PYGPI_PYTHON_BIN=sys.executable,LIBPYTHON_LOC=libpython_path,
               COCOTB_TEST_MODULES='test_empty' if cfg.get('negative')=='empty' else ('test_opt06' if cfg.get('task')=='OPT06' else 'test_ddr_adapter' if cfg.get('task')=='T23' else 'test_board_soc' if cfg.get('task')=='T24' else 'test_platform_adapter' if cfg.get('task')=='T22' else 'test_application' if cfg.get('task')=='T20' else 'test_model_integration' if cfg.get('task')=='T19' else 'test_sd_boot' if cfg.get('task')=='T18' else 'test_uart_boot' if cfg.get('task')=='T17' else 'test_soc_accel' if cfg.get('task')=='T16' else 'test_runtime' if cfg.get('task')=='T12' else 'test_accel_control' if cfg.get('task')=='T13' else 'test_streaming' if cfg.get('task')=='T14' else 'test_linear' if cfg.get('task')=='T15' else 'test_cpu'),
               COCOTB_TOPLEVEL='tb_cpu',COCOTB_TOPLEVEL_LANG='verilog',COCOTB_RANDOM_SEED=str(cfg['seed']),
               COCOTB_RESULTS_FILE=str(Path('results.xml').resolve()),
               NEXUSRV_CASE=str(args.case.resolve()),
               PYTHONPATH=os.pathsep.join(str(root/n) for n in ('tests/cocotb','tests/application/t20','tests/cpu','tests/models','tests/runtime','tests/accel','tests/streaming','tests/linear','tests/soc_accel','tests/end_to_end')))
    # Never inherit a user's test filter or alternate Python bootstrap into qualification.
    for key in ('COCOTB_TEST_FILTER','COCOTB_TESTCASE','MODULE','TESTCASE','GPI_EXTRA','GPI_USERS','PYGPI_USERS','COCOTB_RESOLVE_X','COCOTB_TRUST_INERTIAL_WRITES'):
        env.pop(key,None)
    env["GPI_USERS"]=libpython_path+";"+subprocess.check_output([sys.executable,"-m","cocotb_tools.config","--pygpi-entry-point"],text=True).strip()
    if cfg.get('task')=='OPT07':env['COCOTB_TEST_MODULES']='test_empty' if cfg.get('negative')=='empty' else 'test_opt07'
    if cfg.get('task')=='OPT08_COPY':env['COCOTB_TEST_MODULES']='test_opt08_copy'
    if cfg.get('task')=='OPT14_BASELINE':env['COCOTB_TEST_MODULES']='test_empty' if cfg.get('negative')=='empty' else 'test_opt14_baseline'
    if cfg.get('task')=='OPT09':env['COCOTB_TEST_MODULES']='test_empty' if cfg.get('negative')=='empty' else 'test_opt09'
    started=time.time_ns()
    with Path('simulation.log').open('w') as stream:
        extra=[]
        if cfg.get('task') in ('T17','T18'):
            extra=[f"+boot={cfg['boot']}",f"+boot_bytes={cfg['boot_bytes']}",f"+mode={cfg['test_mode']}",
                   f"+seed={cfg['seed']}",f"+max_cycles={cfg['max_cycles']}",f"+max_delay={cfg['max_delay']}"]
            if cfg['test_mode']=='PRELOAD':extra += [f"+app={cfg['app']}",f"+app_bytes={cfg['app_bytes']}"]
            if cfg.get('negative')=='held-reset':extra.append('+held_reset')
        if cfg.get('task') in ('T12','T13','T14','T15','T16','T24','T19','T20','OPT06','OPT07','OPT08_COPY','OPT09','OPT14_BASELINE'):
            extra=[f"+image_plan={cfg['image_plan']}",f"+seed={cfg['seed']}",f"+max_cycles={cfg['max_cycles']}",f"+max_delay={cfg['max_delay']}"]
            if cfg.get('task') in ('T14','T15'):extra += [f"+image={cfg['image']}",'+mode=PRELOAD',f"+mem_latency={cfg['latency']}",f"+mem_interval={cfg['interval']}",f"+mem_ready_period={cfg['ready_period']}"]
            if cfg.get('negative')=='held-reset':extra.append('+held_reset')
            if cfg.get('negative')=='early-completion':extra.append('+early_completion')
            if cfg.get('negative')=='stale-data':extra.append('+stale_data')
            if cfg.get('task') in ('T16','T24') and cfg['profile']=='head':extra.append('+head_run')
            if cfg.get('negative')=='dropped-action':extra.append('+drop_action')
        if cfg.get('fgp_cores',1)>1:extra.append(f"-fgp=num_threads:{cfg['fgp_cores']},num_fsdb_threads:0")
        code=subprocess.call([str(args.sim.resolve()),'-no_save',f"+ntb_random_seed={cfg['seed']}",*extra],env=env,stdout=stream,stderr=subprocess.STDOUT)
    try:
        if cfg.get('negative')=='missing-xml' and Path('results.xml').exists():
            Path('results.xml').rename('intentionally-removed-results.xml')
        if code: raise ValueError(f'simulator exit {code}')
        checks=validate(Path.cwd(),cfg,started)
        sys.path.insert(0,str(root/'tests/cocotb'))
        if cfg.get('task') in ('OPT07','OPT08_COPY','OPT09','OPT14_BASELINE'):
            # The runtime bus waveform parser is intentionally independent of
            # the arithmetic checker and consumes the finite initial window.
            from common.runtime_waveform import check_waveform
        elif cfg.get('task')=='OPT06':
            sys.path.insert(0,str(root))
            from tests.opt06.verify import check_waveform
        elif cfg.get('task')=='T23':
            from common.ddr_waveform import check_waveform
        elif cfg.get('task')=='T22':
            from common.platform_waveform import check_waveform
        elif cfg.get('task')=='T18':
            sys.path.insert(0,str(root/'tests/boot/sd'))
            from waveform import check_waveform
        elif cfg.get('task')=='T17':
            sys.path.insert(0,str(root/'tests/boot/uart'))
            from waveform import check_waveform
        elif cfg.get('task') in ('T16','T19','T24'):
            sys.path.insert(0,str(root/'tests/soc_accel'))
            from waveform import check_waveform
        elif cfg.get('task') in ('T12','T20'):
            from common.runtime_waveform import check_waveform
        elif cfg.get('task')=='T13':
            from common.accel_waveform import check_waveform
        elif cfg.get('task') in ('T14','T15'):
            sys.path.insert(0,str(root/'tests/streaming'))
            from waveform import check_waveform
        else:
            from common.waveform import check_waveform
        check_waveform(Path.cwd())
        write_json('case-status.json',{'status':'PASS','exit_code':0,'checks':checks['check_count'],'started_ns':started})
        print(f"PASS {cfg['case_id']}: {checks['check_count']} independent checks")
        return 0
    except Exception as error:
        write_json('case-status.json',{'status':'FAIL','exit_code':1,'reason':str(error),'simulator_exit':code,'started_ns':started})
        print(f"FAIL {cfg['case_id']}: {error}",file=sys.stderr)
        return 1


if __name__=='__main__': sys.exit(main())
