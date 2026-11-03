#!/usr/bin/env python3
"""Real T09 -> new CE firmware -> CE RTL -> native DDR -> CPU replay.

Reuse immutable T16 payload/golden, never generate a replacement oracle.
This runner establishes digital integration only; board gates are independent.
"""
import argparse, json, re, shutil, sys, traceback
from pathlib import Path
from evidence import EvidenceRun, sha256, content_id, write_json
from run_ce64_e0 import VENDOR
from run_cocotb import environment
from run_t07 import simulate_batch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tests/models'))
from prepare_image import parse_elf

def build(run, tools, vpi,board_memory=False,loader_test=False,lowered_ce=False,uart_divisor=125,sd_loader_test=False,wave_window=None,source_overrides=None,additional_sources=None,defines=None):
    source_overrides=source_overrides or {}
    src=run.build/'sources';src.mkdir()
    names=['rtl/interfaces/axi4_if.sv','rtl/soc/nx_accel_map.sv']
    names += ['rtl/ce64/vendor/'+n for n in VENDOR]
    names += ['rtl/ce64/'+n for n in ['nx_ce64_math_pkg.sv','nx_ce64_dot16.sv','nx_ce64_fma_retimed.sv',
        'nx_ce64_fp32_op.sv','nx_ce64_fp32_ordered_s0.sv','nx_ce64_scratch.sv','nx_ce64_dma.sv',
        'nx_ce64_desc.sv','nx_ce64_fault.sv','nx_ce64_regs.sv','nx_ce64_control.sv','nx_ce64.sv']]
    names += list(additional_sources or [])
    if board_memory:names+=['rtl/soc/t03_uart_tx.sv','rtl/soc/t17_uart.sv','rtl/ce64/nx_ce64_local.sv']
    if sd_loader_test:
        if not (board_memory and loader_test):raise ValueError('SD loader requires actual CPU/board loader environment')
        names+=['rtl/soc/t17_uart_router.sv','rtl/soc/t18_spi.sv','rtl/ce64/nx_t25_local.sv']
    names += ['rtl/soc/'+n for n in ['nx_shared_memory_arbiter.sv','nx_axi_ddr_route.sv','nx_axi_ddr_mux.sv','nx_soc_test_response.sv','nx_soc_ce64.sv']]
    names += [str(p.relative_to(ROOT)) for p in sorted((ROOT/'rtl/ce64/common').glob('*.sv'))]
    names += ['tests/models/sparse_memory_pkg.sv','tests/models/axi_sparse_mem.sv','tests/ce64_soc/native_memory_model.sv']
    for n in names:
        dest=src/n;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source_overrides.get(n,ROOT/n),dest)
    for n in ['rtl/ce64/vendor/registers.svh','tests/ce64_soc/tb_body.svh','tests/ce64_soc/firmware.c',
              'scripts/run_ce64_soc.py','scripts/ce64_case.py','tests/ce64_soc/scoreboard.py',
              'tests/ce64_soc/waveform.py','tests/ce64_soc/test_ce64_soc.py',
              'software/include/backend_v1.h','software/include/backend_v2.h',
              'firmware/cpu/start.S','tests/soc_accel/link.ld',
              'configs/t16-soc-accel.json','configs/t24-soc-board.json','tests/ce64_soc/board_link.ld']:
        dest=src/n;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source_overrides.get(n,ROOT/n),dest)
    for p in (ROOT/'firmware/drivers/accel').glob('*'):
        if p.is_file():dest=src/'firmware/drivers/accel'/p.name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dest)
    shutil.copytree(ROOT/'tests/cocotb/common',src/'tests/cocotb/common',ignore=shutil.ignore_patterns('__pycache__'))
    frozen=ROOT/'evidence/T16/acceptance-20261007-v3'
    cpu=frozen/'artifacts/generated/hard/T09Cpu.v'
    cpu_digest=sha256(cpu)
    m=json.loads((frozen/'manifest.json').read_text())
    run.check('same-T09-CPU',cpu_digest==m['cpu_rtl_sha256'],'Frozen hard-FPU/cache/ISA CPU')
    generated=src/'cpu';shutil.copytree(cpu.parent,generated)
    compiled=run.build/'compiled';compiled.mkdir()
    for p in generated.glob('*.bin'):shutil.copy2(p,compiled/p.name)
    extra_designs=[]
    if lowered_ce:
        from spyglass_support import boundary_wrapper,module_ports,axi_fields
        from pds.flatten_sv2v_interfaces import flatten
        from pds.lower_t24_arithmetic import lower as lower_arithmetic
        from run_ce64_e0 import SV2V,YOSYS
        iface=(src/'rtl/interfaces/axi4_if.sv').read_text();original=(src/'rtl/ce64/nx_ce64.sv').read_text()
        adapter,top,_=boundary_wrapper('nx_ce64',original,iface,{'mmio':(128,6),'memory':(128,6)})
        probe=compiled/'ce-boundary.sv';probe.write_text(adapter)
        ce_names=[n for n in names if n.startswith('rtl/ce64/vendor/') or (n.startswith('rtl/ce64/') and '/common/' not in n and not n.endswith('nx_ce64_local.sv'))]
        log=run.execute('ce-convert',[SV2V,'--top='+top,'-DSYNTHESIS','-I'+str(src/'rtl/ce64/vendor'),src/'rtl/interfaces/axi4_if.sv',src/'rtl/soc/nx_accel_map.sv',src/'rtl/ce64/vendor/registers.svh',*[src/n for n in ce_names],probe],600)
        converted=compiled/'ce-converted.v';converted.write_text(flatten(log.read_text())[0]);lowered=compiled/'ce-lowered.v';ys=compiled/'ce-lower.ys'
        ys.write_text(f'read_verilog -sv -defer {converted}\nhierarchy -check -top {top}\nproc\nopt\nmemory_dff\nmemory_share\nmemory_collect\nopt_clean\ncheck -assert\nwrite_verilog -noattr {lowered}\n')
        run.execute('ce-lower',[YOSYS,'-s',ys],600)
        decl=re.search(r'module nx_ce64\s*\([\s\S]*?\);',original)[0];connections=[]
        for kind,width,name in module_ports(original,'nx_ce64'):
            if kind.startswith('axi4_if'):
                for signal,_,_ in axi_fields(iface,128,6):connections.append('.'+name+'__'+signal+'('+name+'.'+signal+')')
            else:connections.append('.'+name+'('+name+')')
        wrapper_ce=compiled/'ce-interface.sv';wrapper_ce.write_text(decl+'\n'+top+' ce_lowered('+','.join(connections)+');\nendmodule\n')
        extra_designs=[lowered,wrapper_ce];names=[n for n in names if n not in ce_names]
        bridge=src/'rtl/ce64/common/nx_ce64_bridge.sv';arb=src/'rtl/soc/nx_shared_memory_arbiter.sv'
        b,a,receipt=lower_arithmetic(bridge.read_text(),arb.read_text());bridge.write_text(b);arb.write_text(a)
        run.manifest['conversion']=dict(core_input_sha256=sha256(converted),core_output_sha256=sha256(lowered),bounded_functions=receipt,
            scope='Actual CPU/firmware with sv2v+Yosys CE hierarchy and the exact qualified finite bus functions; no PDS primitive/SDF replay claim')
    ports=re.findall(r'(input|output)\s+wire\s*(\[[^]]+\])?\s*(\w+)\s*[,\n]',cpu.read_text().split(');',1)[0])
    wrapper='`timescale 1ns/1ps\nmodule tb_cpu;\n'+''.join('%s %s %s;\n'%('logic' if d=='input' else 'wire',w,n) for d,w,n in ports)
    wrapper+=(src/'tests/ce64_soc/tb_body.svh').read_text()+'\nendmodule\n'
    if board_memory:
        # Replace only the storage/peripheral environment. Computation and CPU
        # submission are unchanged. SRAM/ROM are the actual board RTL.
        wrapper=wrapper.replace('wire ddr_init_done=!reset && cycles>=500;',
            'wire ddr_init_done=!reset && cycles>=500;\nwire model_sealed,platform_reset_request;\nwire board_tx;wire [31:0] board_exit,board_report;wire board_exited;')
        wrapper=wrapper.replace(".model_sealed(1'b1)",'.model_sealed(model_sealed)')
        begin=wrapper.index('  axi_sparse_mem #(.DATA_W(32)')
        end=wrapper.index('  logic injected_read',begin)
        env='''  axi4_if #(.DATA_W(32),.ID_W(1)) environment_unused(clk);
  axi_sparse_mem #(.DATA_W(32),.ID_W(1),.BASE_ADDR(0),.SIZE_BYTES(64'h100000000)) d_memory
    (.clk,.reset_n(!reset),.random_delays(1'b0),.seed(seed),.max_delay(0),
     .inject_enable(1'b0),.inject_start(32'b0),.inject_end(32'b0),.inject_resp(2'b0),.bus(environment_unused));
  assign environment_unused.awvalid=0;assign environment_unused.wvalid=0;assign environment_unused.arvalid=0;
  assign environment_unused.bready=1;assign environment_unused.rready=1;
  nx_ce64_local #(.UART_DIVISOR(2),.PRELOAD_MODE(1),.LOCAL_READ_PIPELINE(LOCAL_READ_PIPELINE),.REQUEST_PMU(ENABLE_REQUEST_PMU)) board_local(
    .clk,.reset_n(!reset),.ddr_init_done,.platform_ready(1'b1),.platform_status(32'b0),.telemetry({request_pmu_stats,2048'b0}),.uart_rx(1'b1),.uart_tx(board_tx),
    .rom_enable,.rom_address,.rom_data,.model_sealed,.platform_reset_request,
    .exit_code(board_exit),.report_tag(board_report),.exited(board_exited),.local_i,.local_d,.local_n);
  initial force board_local.profile_head=head_run;
'''
        wrapper=wrapper[:begin]+env+wrapper[end:]
        wrapper=wrapper.replace('#1;i_memory.mem=d_memory.mem;n_memory.mem=d_memory.mem;native_model.mem=d_memory.mem;',
            '#1;native_model.mem=d_memory.mem;')
        wrapper=wrapper.replace('softwareInterrupt=0;rom_data=0;', 'softwareInterrupt=0;')
        wrapper=wrapper.replace("    if(rom_enable)for(int i=0;i<4;i++)rom_data[8*i+:8]<=d_memory.mem.read_byte(64'(rom_address)+i);",'')
        wrapper=wrapper.replace('if(head_run&&core_running&&halted)$dumpon;', 'if(head_run&&soc.compute.ce.regs.pending)$dumpon;')
    if loader_test:
        if not board_memory:raise ValueError('Loader requires actual local board devices')
        wrapper=wrapper.replace('module tb_cpu;','module tb_cpu;\nlogic uart_input=1;')
        wrapper=wrapper.replace('.UART_DIVISOR(2),.PRELOAD_MODE(1)',f'.UART_DIVISOR({uart_divisor}),.PRELOAD_MODE(0)')
        wrapper=wrapper.replace(".uart_rx(1'b1)",'.uart_rx(uart_input)')
        wrapper=wrapper.replace('  initial force board_local.profile_head=head_run;','')
        wrapper=wrapper.replace('.ENABLE_TEST_CONTROL(1)) soc(','.ENABLE_TEST_CONTROL(1),.ENABLE_CE(0)) soc(')
        begin=wrapper.index('  // Observation only: diagnose actual protocol identities')
        end=wrapper.index('  always @(peek_address)',begin)
        wrapper=wrapper[:begin]+wrapper[end:]
        wrapper='\n'.join(line for line in wrapper.splitlines() if 'soc.compute.ce.' not in line)+'\n'
    if sd_loader_test:
        wrapper=wrapper.replace('logic uart_input=1;','logic uart_input=1,host_miso=1;wire spi_sck,spi_cs,spi_mosi;wire spi_miso=host_miso;')
        wrapper=wrapper.replace('nx_ce64_local #(', 'nx_t25_local #(')
        wrapper=wrapper.replace(f'.UART_DIVISOR({uart_divisor}),.PRELOAD_MODE(0)',f'.UART_DIVISOR({uart_divisor})')
        wrapper=wrapper.replace(".telemetry({request_pmu_stats,2048'b0})",".telemetry({request_pmu_stats,1952'b0,22'b0,model_sealed,9'b0,64'b0})")
        wrapper=wrapper.replace('.exit_code(board_exit)',".card_generation(32'd1),.sd_miso(host_miso),.sd_sck(spi_sck),.sd_cs_n(spi_cs),.sd_mosi(spi_mosi),.exit_code(board_exit)")
    if lowered_ce:
        begin=wrapper.index('  // Observation only: diagnose actual protocol identities');end=wrapper.index('  always @(peek_address)',begin)
        wrapper=wrapper[:begin]+wrapper[end:]
        wrapper=wrapper.replace('if(head_run&&soc.compute.ce.regs.pending)$dumpon;','if(head_run&&core_running&&!halted)$dumpon;')
    tb=compiled/'tb_cpu.sv';tb.write_text(wrapper);shutil.copy2(tb,src/'tb_cpu.sv')
    if wave_window:
        wrapper=wrapper.replace('logic completed=0,timed_out=0;', 'logic completed=0,timed_out=0;\n  longint unsigned wave_until=0;logic[31:0] wave_launch=0;')
        wrapper=wrapper.replace('if(head_run&&cycles==2000000)$dumpoff;', 'if(cycles==50000)$dumpoff;')
        wrapper=wrapper.replace('if(head_run&&soc.compute.ce.regs.pending)$dumpon;', f'if(launches!=wave_launch)begin wave_launch=launches;wave_until=cycles+{int(wave_window)};$dumpon;end\n    if(wave_until!=0&&cycles==wave_until)$dumpoff;')
        tb.write_text(wrapper);shutil.copy2(tb,src/'tb_cpu.sv')
    sim=compiled/'simv'
    pli=compiled/'pli.tab';pli.write_text('acc+=rw,cbk:tb_cpu\nacc+=r:axi4_if,nx_ce64_bridge,nx_ce64_guard\n')
    run.execute('vcs-build',[tools['vcs'],'-j16','-full64','-sverilog','-timescale=1ns/1ps','+vpi','-P',pli,
        *[f'+define+{x}' for x in (defines or [])],'-cc',tools['vcs_host_cc'],'-cpp',tools['vcs_host_cxx'],'-LDFLAGS','-Wl,--no-as-needed','-load',vpi,
        src/'rtl/ce64/vendor/registers.svh',*[src/n for n in names],*extra_designs,generated/'T09Cpu.v',tb,'-top','tb_cpu','-o',sim],600,cwd=compiled)
    files={str(p.relative_to(src)):sha256(p) for p in src.rglob('*') if p.is_file()}
    run.manifest.update(source_files=files,source_sha256=content_id(files),cpu_rtl_sha256=cpu_digest)
    return sim

def firmware(run,tools,profile,board_memory=False):
    parent=ROOT/'evidence/T16/acceptance-20261007-v3/artifacts/images'/profile
    image=run.build/'images'/profile;image.parent.mkdir(exist_ok=True);shutil.copytree(parent,image)
    fixture=json.loads((image/'fixture.json').read_text());frozen_golden=sha256(parent/'golden.json')
    fixture['regions']=[r for r in fixture['regions'] if r['kind']!='firmware']
    # Preserve every data byte, input address, original expected_path and NPZ
    # hash. Only new firmware regions receive a new execution identity.
    for r in fixture['regions']:
        run.check('frozen-'+profile+'-'+r['name'],sha256(image/Path(r['path']).name)==r['sha256'],r['name'])
        r['path']=str((image/Path(r['path']).name).resolve())
    run.check('same-golden-'+profile,sha256(image/'golden.json')==frozen_golden,'Original T16 golden, thresholds, timeouts and errors')
    src=ROOT/'firmware/drivers/accel';elf=image/'ce64.elf'
    flags=['-march=rv32imf_zicsr_zifencei','-mabi=ilp32f','-DHARD_FLOAT','-O2','-g',
        '-ffp-contract=off','-fno-fast-math','-ffreestanding','-fno-builtin','-fno-pic','-fno-strict-aliasing',
        '-nostdlib','-nostartfiles','-msmall-data-limit=0','-Wall','-Wextra','-Werror','-Wl,--build-id=none',f'-ffile-prefix-map={ROOT}=.']
    if board_memory:
        flags+=['-DNX_CE_BOARD_BOOT']
        control=(ROOT/'evidence/T16/acceptance-20261007-v3/artifacts/images/control/fixture_jobs.h').read_text()
        head=(ROOT/'evidence/T16/acceptance-20261007-v3/artifacts/images/head/fixture_jobs.h').read_text()
        count_c=int(re.search(r'FIXTURE_JOBS (\d+)',control)[1]);count_h=int(re.search(r'FIXTURE_JOBS (\d+)',head)[1])
        control=re.sub(r'#define FIXTURE_JOBS \d+\n','',control).replace('fixture_jobs[]','fixture_jobs_control[]')
        head=head[head.index('static const struct fixture_job'):].replace('fixture_jobs[]','fixture_jobs_head[]')
        (image/'fixture_jobs.h').write_text(control+head+f'extern uint32_t ce_board_profile;\n#define FIXTURE_JOBS (ce_board_profile==1?{count_h}u:{count_c}u)\n#define fixture_jobs (ce_board_profile==1?fixture_jobs_head:fixture_jobs_control)\n')
    linker=ROOT/('tests/ce64_soc/board_link.ld' if board_memory else 'tests/soc_accel/link.ld')
    run.execute('firmware-'+profile,[tools['rv32_gcc'],*flags,'-I',src,'-I',ROOT/'software/include','-I',image,
        '-T',linker,f'-Wl,-Map={image}/ce64.map',ROOT/'firmware/cpu/start.S',
        ROOT/'tests/ce64_soc/firmware.c',src/'accel.c',src/'target.c',src/'linear_api.c',src/'ce64_linear.c',
        *([src/'ce64_board_boot.c'] if board_memory else []),'-lc','-lgcc','-o',elf],60)
    dis=run.execute('disassemble-'+profile,[tools['rv32_objdump'],'-d',elf],30);shutil.copy2(dis,image/'ce64.dis')
    entry,segments,abi=parse_elf(elf.read_bytes(),base=0x10000,capacity=0xb8000000-0x10000)
    if board_memory:
        # The ROM byte stream is a physical ELF image, never a golden output.
        rom=bytearray(65536)
        for seg in segments:
            if 0x10000<=seg.address<0x20000:rom[seg.address-0x10000:seg.address-0x10000+len(seg.data)]=seg.data
        (image/'ce64-rom.hex').write_text(''.join(f'{int.from_bytes(rom[i:i+4],"little"):08x}\n' for i in range(0,65536,4)))
    run.check('new-CE-ELF-'+profile,entry==0x10000 and abi==2 and sha256(elf)!=sha256(parent/'firmware.elf'),'New CE identity; no Coral upload')
    for i,s in enumerate(segments):
        p=image/f'ce64-cpu-segment-{i}.bin';p.write_bytes(s.data)
        fixture['regions'].append(dict(name=p.stem,address=s.address,bytes=len(s.data),path=str(p.resolve()),sha256=sha256(p),kind='firmware'))
    fixture.update(elf_sha256=sha256(elf),ce64_route=2,capability_api_version=2,qualified_profile_mask=0)
    write_json(image/'fixture.json',fixture)
    (image/'load.plan').write_text(''.join(f"B {r['address']:x} {r['bytes']:x} {r['path']}\n" for r in fixture['regions']))
    run.manifest.setdefault('firmware',{})[profile]=dict(sha256=sha256(elf),frozen_golden_sha256=frozen_golden,
        original_T16_elf_sha256=sha256(parent/'firmware.elf'),flags=flags)
    return image

def main():
    p=argparse.ArgumentParser();p.add_argument('--run-id',required=True)
    p.add_argument('--board-memory',action='store_true')
    p.add_argument('--lowered-ce',action='store_true')
    p.add_argument('--suite',choices=['smoke','control','head','full'],default='full');a=p.parse_args()
    run=EvidenceRun(ROOT,'CE64_SOC',a.run_id);code=1
    run.manifest.update(route='C_CE64_PRIMARY',profile='CE64-S0',task_status='ACTIVE',
        acceptance_contract='docs/spec/ce64-s0-v2.json',qualification_scope='Digital real CPU/CE/native replay only',
        programming_performed=False,flash_modified=False,physical_qualification=False)
    try:
        cfg=json.loads((ROOT/'configs/t16-soc-accel.json').read_text())
        # T16 supplies frozen inputs/errors/call deadlines. The existing T24
        # native-DDR capture envelope is 80M, rather than the T16 25M envelope.
        board_cfg=json.loads((ROOT/'configs/t24-soc-board.json').read_text())
        cfg['max_cycles']=board_cfg['max_cycles']
        tools={k:v['path'] for k,v in json.loads((ROOT/'docs/spec/toolchain-lock.json').read_text())['tools'].items()}
        vpi=environment(run,cfg,tools);sim=build(run,tools,vpi,a.board_memory,lowered_ce=a.lowered_ce)
        cases=['smoke-seed1'] if a.suite=='smoke' else ['head-seed1'] if a.suite=='head' else cfg['suites']['regression'] if a.suite=='control' else cfg['suites']['full']
        images={profile:firmware(run,tools,profile,a.board_memory) for profile in {cfg['cases'][n]['profile'] for n in cases}}
        run.manifest['cases']={};jobs=[]
        for name in cases:
            param=cfg['cases'][name];image=images[param['profile']]
            dest=run.build/'cocotb'/name;dest.mkdir(parents=True)
            for f in sim.parent.glob('*.bin'):shutil.copy2(f,dest/f.name)
            case=dict(task='CE64',case_id=name,run_id=a.run_id,**param,python_prefix=sys.prefix,
                cocotb_version=cfg['cocotb_version'],test_mode='PRELOAD',negative=None,
                max_cycles=cfg['head_max_cycles'] if param['profile']=='head' else cfg['max_cycles'],
                fixture=str(image/'fixture.json'),golden=str(image/'golden.json'),image_plan=str(image/'load.plan'),
                checker_root=str(run.build/'sources'),
                ce_rom=str(image/'ce64-rom.hex') if a.board_memory else None,
                fixture_sha256=sha256(image/'fixture.json'),golden_sha256=sha256(image/'golden.json'))
            write_json(dest/'case.json',case)
            jobs.append(dict(name='case-'+name,case=dest,argv=[sys.executable,ROOT/'scripts/ce64_case.py','--case',dest/'case.json','--sim',sim],cost=151936 if param['profile']=='head' else 1))
        simulate_batch(run,jobs,cfg['timeouts_seconds']['simulation'],cfg['simulation_workers'])
        for name in cases:run.manifest['cases'][name]=json.loads((run.build/'cocotb'/name/'checks.json').read_text())
        run.flush()
        if a.suite in ('control','full'):run.check('same-seed-replay',run.manifest['cases']['control-seed1']['sequence_sha256']==run.manifest['cases']['control-seed1-replay']['sequence_sha256'],'Entire native/CPU/CE trace')
        code=0
    except Exception:(run.path/'failure.txt').write_text(traceback.format_exc())
    finally:
        for name in ['sources','images','cocotb']:
            if(run.build/name).exists():shutil.copytree(run.build/name,run.path/name)
        run.manifest['artifacts']={str(p.relative_to(run.path)):sha256(p) for p in run.path.rglob('*')
            if p.is_file() and p.name not in ['manifest.json','checks.json','commands.json','exit-status.txt']}
        code=run.finish(code)
    print('CE64_SOC='+run.manifest['status']+' EVIDENCE='+str(run.path),flush=True);return code
if __name__=='__main__':raise SystemExit(main())
