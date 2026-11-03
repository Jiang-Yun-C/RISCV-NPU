"""Isolated digital service environment; production application/RTL stay exact."""
import hashlib
import inspect
import json
from pathlib import Path
import re
import shutil
import struct
import sys

from evidence import sha256,write_json
from model_tools.verify_pack import verify
import run_ce64_soc

ROOT=Path(__file__).resolve().parents[1]


def prepare_snapshot(r,parent,tools,token):
    """Verify all data, then derive exactly the loader success-state structure."""
    image=r.build/'image';image.mkdir()
    pm=json.loads((ROOT/'docs/spec/model-pack-v1-manifest.json').read_text())
    pack=verify(ROOT/pm['pack_path'],expected_sha256=pm['sha256'])
    write_json(r.path/'independent-pack-verification.json',pack.summary)
    trusted=(parent/'loader/trusted.h').read_text()
    hashes={n:''.join(re.findall(r'0x([0-9a-f]{2})',body)) for n,body in
            re.findall(r'nx_trusted_(apps|models)\[\]\[32\]=\{\{([^}]+)\}',trusted)}
    app=parent/'production/application.bin'
    r.check('snapshot-exact-loader-trust',hashes==dict(apps=sha256(app),models=pm['sha256']),hashes)
    m=json.loads((parent/'manifest.json').read_text());repo=Path(m['candidate_repo'])
    entries=list(pack.entries.values());regions=[];spans=[]
    def add(name,address,p,kind):
        regions.append(dict(name=name,address=address,bytes=p.stat().st_size,path=str(p),sha256=sha256(p),kind=kind))
    add('exact_application',0xb4000000,app,'unmodified_production_application')
    spans.append((0xb4000000,app.stat().st_size))
    with pack.path.open('rb') as f:
        f.seek(192);directory=f.read(256*len(entries));p=image/'directory.bin';p.write_bytes(directory)
        add('exact_directory',0xba000000,p,'loader_directory');spans.append((0xba000000,len(directory)))
        for i,e in enumerate(entries):
            if e['alias_of'] is not None:continue
            f.seek(e['offset']);data=f.read(e['length']);p=image/f'payload-{i}.bin';p.write_bytes(data)
            r.check('snapshot-payload-'+str(i),sha256(p)==e['sha256'],e['name'])
            add(e['name'],e['soc_address'],p,'exact_verified_model_or_tokenizer')
            spans.append((e['soc_address'],e['length']))
    # Independent executable of the *original* accounting function. It sees the
    # same application/directory/payload store order and <=64B chunk boundaries.
    source=r.build/'derive_handoff.c'
    source.write_text('''#include <stdio.h>
#include "ddr_accounting.h"
int main(int argc,char **argv){if(argc!=2)return 2;FILE *f=fopen(argv[1],"r");if(!f)return 3;
t25_load_memory m={0};unsigned address,bytes;
while(fscanf(f,"%x %u",&address,&bytes)==2){while(bytes){unsigned n=bytes>64?64:bytes;
if(t25_count_store(&m,address,n)){return 4;}
address+=n;bytes-=n;}}
fclose(f);for(unsigned i=0;i<4;i++)printf("%u ",m.bytes[i]);for(unsigned i=0;i<4;i++)printf("%u ",m.end[i]);return 0;}
''')
    spanfile=r.build/'loader-store-spans.txt';spanfile.write_text(''.join(f'{a:x} {n}\n' for a,n in spans))
    binary=r.build/'derive_handoff'
    r.execute('compile-original-accounting',['/usr/bin/gcc','-std=c11','-O2','-Wall','-Wextra','-Werror',
        '-I',repo/'firmware/runtime/board',source,'-o',binary],60)
    out=r.execute('execute-original-accounting',[binary,spanfile],60)
    derived=list(map(int,out.read_text().split()));r.check('original-accounting-record-size',len(derived)==8,derived)
    counts=[0]*4;ends=[0]*4;bases=[0x80000000,0xb8000000,0xb4000000,0xba000000]
    limits=[0xa8000000,0xba000000,0xb4800000,0xba080000]
    for address,n in spans:
        which=[i for i,(lo,hi) in enumerate(zip(bases,limits)) if lo<=address and address+n<=hi]
        assert len(which)==1
        i=which[0];assert address>=ends[i];counts[i]+=n;ends[i]=address+n
    r.check('independent-handoff-cross-check',derived==counts+ends and all(counts),dict(bytes=counts,ends=ends))
    handoff=image/'handoff.bin';handoff.write_bytes(struct.pack('<9I',0x4d323544,*derived))
    add('derived_loader_accounting_handoff',0xba080010,handoff,'simulated_postload_success_metadata')
    origin=image/'snapshot-origin.bin';origin.write_bytes(struct.pack('<Q',0))
    add('logical_snapshot_origin_not_measured_load_time',0xba080000,origin,'logical_component_time_origin')
    first=entries[0]
    with pack.path.open('rb') as f:f.seek(first['offset']);dot=sum(struct.unpack('64b',f.read(64)))
    r.check('original-loader-dot-selftest',re.search(r'nx_trusted_dot\[\]=\{\s*'+str(dot)+r'\s*\}',trusted) is not None,dict(dot=dot))
    ordered=sorted(regions,key=lambda x:x['address'])
    r.check('all-snapshot-spans-disjoint',all(a['address']+a['bytes']<=b['address'] for a,b in zip(ordered,ordered[1:])),len(regions))
    # The reset ROM is a fixture trampoline, not a modified production loader.
    # It performs only LUI t0,0xb4000 / JALR x0,0(t0); the normal app _start then
    # initializes gp/sp/FPU/BSS and seeds the original complete SRAM stack.
    words=[0xb40002b7,0x00028067]
    rom=struct.pack('<2I',*words).ljust(65536,b'\0')
    (image/'postload-rom.hex').write_text(''.join(f'{int.from_bytes(rom[i:i+4],"little"):08x}\n' for i in range(0,len(rom),4)))
    sys.path.insert(0,str(ROOT/'tests/reference'));from oracle import Oracle
    oracle=Oracle();logits=oracle.forward([token]);import numpy as np
    values=np.concatenate((logits.reshape(-1),oracle.cache().reshape(-1))).astype('<f4');values.tofile(image/'golden.bin')
    write_json(image/'fixture.json',dict(regions=regions,model_pack_sha256=pm['sha256'],
        app_bin_sha256=sha256(app),application_elf_sha256=sha256(parent/'production/application.elf'),
        accounting_handoff_words=[0x4d323544,*derived],sd_success_state=dict(model_ready=1,selftest=dot,directory_count=len(entries)),
        snapshot_clock_origin=0,loader_guest_executed=False,native_initial_load_readback_executed=False,
        no_fabricated_hardware_performance_counters=True,scope='SIMULATED_CONSISTENT_POSTLOAD_INITIAL_STATE_ONLY'))
    (image/'load.plan').write_text(''.join(f"B {x['address']:x} {x['bytes']:x} {x['path']}\n" for x in regions))
    write_json(r.path/'snapshot-proof.json',dict(status='PASS_SIMULATION_STATE_CONSISTENCY_ONLY',
        independent_pack_verifier=pack.summary,application_hash=sha256(app),loader_trusted_hashes=hashes,
        original_accounting_header_sha256=sha256(repo/'firmware/runtime/board/ddr_accounting.h'),
        loader_success_source_sha256=sha256(repo/'firmware/runtime/board/sd_loader_core.c'),
        counts=counts,ends=ends,selftest=dot,directory_entries=len(entries),regions=len(regions),
        logical_origin=0,loader_authentication_execution='NOT_RUN',physical_ddr_readback_execution='NOT_RUN',
        model_seal_source='Actual t18_spi.model_ready state initialized once after digital DDR ready; actual nx_t25_local derives model_sealed',
        hardware_counters='Actual reset and live SoC outputs only',go=False))
    # Initial runtime bytes are outside every authenticated payload. They were
    # never cleared by the loader, so this declared nonzero power-on pattern
    # must be physically cleared/read back by the unchanged application.
    catalog=json.loads((ROOT/'evidence/OPT10_R1_STARTUP_ZERO/opt10-r1-startup-zero-contract-20261020-v1/contract.json').read_text())['catalog']
    for e in catalog:
        assert all(not(e['base']<r['address']+r['bytes'] and r['address']<e['base']+e['bytes']) for r in regions)
        p=image/f"runtime-poison-{e['index']}.bin";p.write_bytes(bytes([0x51+17*e['index']])*e['bytes'])
        add(p.stem,e['base'],p,'declared_uninitialized_mutable_runtime_poison_not_loader_stores')
    # Execute a component ROM publication using actual SPI MMIO and actual CPU
    # retirement. No seal/auth/counter register is initialized by testbench.
    # The independent host pack/trust/accounting proof supplies these exact
    # postload bytes; this ROM does not claim cryptographic loader execution.
    words=[0x4d323544,*derived]
    source=image/'postload-component-rom.S'
    assembly='''.section .text.start,"ax",@progbits
.globl _start
_start:
    lui t0,0x10002
    sw zero,0x18(t0)
    sw zero,0x1c(t0)
1:  lw t1,0x34(t0)
    beqz t1,1b
'''
    assembly+=f'    li t1,{dot}\n    sw t1,0x28(t0)\n    li t1,{len(entries)}\n    sw t1,0x2c(t0)\n    lui t2,0xba080\n    addi t2,t2,16\n'
    for i,v in enumerate(words):assembly+=f'    lw t3,{4*i}(t2)\n    li t1,{v}\n    bne t3,t1,3f\n'
    assembly+='''    fence iorw,iorw
    .word 0x0000500f
    li t1,0x4d323544
    sw t1,0(t2)
    li t1,1
    sw t1,0x18(t0)
    fence iorw,iorw
    lw t2,0x18(t0)
    bne t1,t2,3f
    lui t0,0x10000
    lw t1,0x208(t0)
    andi t1,t1,512
    beqz t1,3f
    lui t0,0xb4000
    jr t0
3:  lui t0,0x10000
    li t1,0xbad00001
    sw t1,0x20(t0)
    j 3b
'''
    source.write_text(assembly);link=image/'postload-component-rom.ld'
    link.write_text('OUTPUT_ARCH(riscv)\nENTRY(_start)\nPHDRS { rom PT_LOAD FLAGS(5); }\nSECTIONS { . = 0x10000; .text : { *(.text.start) *(.text*) *(.rodata*) } :rom /DISCARD/ : { *(.comment*) *(.riscv.attributes) } }\n')
    elf=image/'postload-component-rom.elf'
    r.execute('compile-component-rom-publication',[tools['rv32_gcc'],'-march=rv32im_zicsr_zifencei','-mabi=ilp32','-ffreestanding','-nostdlib','-nostartfiles','-Wl,--build-id=none','-T',link,source,'-o',elf],60)
    from tests.models.prepare_image import parse_elf
    entry,segments,abi=parse_elf(elf.read_bytes(),base=0x10000,capacity=65536)
    r.check('actual-component-ROM-publication-entry',entry==0x10000 and abi==0 and len(segments)==1,'Actual original T09 ROM retires and actual t18 SPI registers publish only after all exact derived handoff words read back; no authenticated SD execution')
    rom=bytearray(65536)
    for segment in segments:rom[segment.address-0x10000:segment.address-0x10000+len(segment.data)]=segment.data
    (image/'postload-rom.hex').write_text(''.join(f'{int.from_bytes(rom[i:i+4],"little"):08x}\n' for i in range(0,len(rom),4)))
    fixture=json.loads((image/'fixture.json').read_text());fixture.update(regions=regions,startup_catalog=catalog,
        component_ROM_elf_sha256=sha256(elf),component_ROM_handshake='Actual ROM retire, actual SPI MMIO selftest/directory/model_ready write, actual handoff readback, real T25 boot capability; host-verified postload bytes only',
        runtime_poison_bytes=17877696,scope='CONSISTENT_POSTLOAD_BYTES_PLUS_REAL_ROM_PUBLICATION_NOT_AUTHENTICATED_SD_BOOT')
    write_json(image/'fixture.json',fixture);(image/'load.plan').write_text(''.join(f"B {x['address']:x} {x['bytes']:x} {x['path']}\n" for x in regions))
    proof=json.loads((r.path/'snapshot-proof.json').read_text());proof.update(component_ROM_elf_sha256=sha256(elf),publication='Real CPU MMIO through actual t18 SPI after actual ROM retirement; actual nx_t25_local boot capability grant',model_seal_source='Actual component ROM CPU SPI MMIO publication after exact host-verified postload handoff readback; no testbench state write',initial_runtime_poison='Uninitialized mutable state only, outside every verified payload; excluded from derived loader store handoff',old_direct_SD_state_initialization_used=False)
    write_json(r.path/'snapshot-proof.json',proof)
    return image,dict(dot=dot,entries=len(entries))


def service_wrapper(wrapper,metadata):
    def change(old,new):
        nonlocal wrapper
        assert wrapper.count(old)==1,('wrapper schema',old,wrapper.count(old))
        wrapper=wrapper.replace(old,new)
    change('wire board_tx;wire [31:0] board_exit,board_report;wire board_exited;',
           'wire board_tx;wire [31:0] board_exit,board_report;wire board_exited;\nlogic uart_input=1;wire startup_authorized;')
    change('.model_sealed(model_sealed),.auxiliary,','.model_sealed(model_sealed),.startup_authorized,.auxiliary,')
    change('nx_ce64_local #(.UART_DIVISOR(2),.PRELOAD_MODE(1),.LOCAL_READ_PIPELINE(LOCAL_READ_PIPELINE),.REQUEST_PMU(ENABLE_REQUEST_PMU)) board_local(',
           'nx_t25_local #(.UART_DIVISOR(250),.LOCAL_READ_PIPELINE(LOCAL_READ_PIPELINE),.REQUEST_PMU(ENABLE_REQUEST_PMU)) board_local(')
    change('.telemetry({request_pmu_stats,2048\'b0}),.uart_rx(1\'b1)',
           '.telemetry(service_telemetry),.uart_rx(uart_input)')
    change('.exit_code(board_exit),.report_tag(board_report),.exited(board_exited),.local_i,.local_d,.local_n);',
           '.card_generation(32\'d1),.sd_miso(1\'b1),.sd_sck(),.sd_cs_n(),.sd_mosi(),\n    .startup_trace_retire(trace_retire),.startup_trace_pc(trace_pc),.startup_authorized,\n    .exit_code(board_exit),.report_tag(board_report),.exited(board_exited),.local_i,.local_d,.local_n);')
    change('  initial force board_local.profile_head=head_run;','')
    # Remove the legacy fault harness forces. CE/guard legality, internal test
    # cycles and all actual hardware counters are left driven by original RTL.
    begin=wrapper.index('  initial begin\n    force soc.test_mode=')
    end=wrapper.index('  end',begin)+len('  end')
    wrapper=wrapper[:begin]+wrapper[end:]
    declarations='''
  wire [255:0] service_cpu_i_stats=soc.cpu_i_stats;
  wire [255:0] service_cpu_d_stats=soc.cpu_d_stats;
  wire [255:0] service_ce_stats=soc.ce_stats;
  wire service_native_quarantine=soc.native_quarantine_status;
  reg [4095:0] service_telemetry;
  reg [63:0] service_reference_ticks=0;
  always @(posedge clk)if(reset)service_reference_ticks<=0;else service_reference_ticks<=service_reference_ticks+1;
  always @* begin
    service_telemetry='0;
    service_telemetry[0+:32]=32'h34364543;
    service_telemetry[32+:32]=32'd2;
    service_telemetry[64+:32]={22'b0,model_sealed,backend_idle,owner,service_native_quarantine,ddr_fault,4'b0,ddr_init_done};
    service_telemetry[128+:64]=service_reference_ticks;
    service_telemetry[512+:64]=ddr_cycles;
    service_telemetry[576+:64]=ddr_write_bytes;
    service_telemetry[640+:64]=ddr_read_bytes;
    service_telemetry[704+:64]=native_write_bytes;
    service_telemetry[768+:64]=native_read_bytes;
    service_telemetry[1024+:256]=service_cpu_i_stats;
    service_telemetry[1280+:256]=service_cpu_d_stats;
    service_telemetry[1536+:256]=service_ce_stats;
    service_telemetry[2048+:2048]=request_pmu_stats;
  end
  logic service_request_observation=0;
  logic snapshot_state_installed=0;
  // Observe real component ROM publication through the actual hardware gate.
  // No state assignment, authority bypass, or fabricated performance count.
  always @(posedge clk)if(!reset&&startup_authorized&&model_sealed)snapshot_state_installed<=1;
  wire [31:0] service_startup_status=soc.compute.ce.startup_status;
  logic service_finalize_observation=0;
  logic [31:0] service_stack_peek_address=32'h20000;
  wire [31:0] service_stack_peek_value=board_local.core.ram[service_stack_peek_address[15:2]];
  logic service_stack_seed_done=0;
  logic service_guard_written_after_seed=0;
  longint unsigned service_entry_cycle=0;
  always @(posedge clk)if(!reset)begin
    if(trace_retire && trace_pc==32'h@MAIN@)begin service_stack_seed_done<=1;service_entry_cycle<=cycles;end
    if(service_stack_seed_done&&board_local.core.d_ram_write&&board_local.core.wa<32'h20010)
      service_guard_written_after_seed<=1;
  end
'''
    declarations=declarations.replace('@DOT@',str(metadata['dot'])).replace('@ENTRIES@',str(metadata['entries'])).replace('@MAIN@',f"{metadata['main']:08x}")
    change('  axi4_if #(.DATA_W(32),.ID_W(1)) environment_unused(clk);',declarations+'\n  axi4_if #(.DATA_W(32),.ID_W(1)) environment_unused(clk);')
    # Bound waveform to actual selected windows using existing behavior; no
    # performance or bus signal is changed by the observation addition.
    assert 'force soc.' not in wrapper
    return wrapper


def build_service(r,tools,vpi,repo,metadata,tb):
    """Fork the existing builder into this run and add one final wrapper hook."""
    source=inspect.getsource(run_ce64_soc.build)
    marker="    tb=compiled/'tb_cpu.sv';tb.write_text(wrapper);shutil.copy2(tb,src/'tb_cpu.sv')"
    assert source.count(marker)==1
    source=source.replace(marker,"    wrapper=service_wrapper(wrapper,service_metadata)\n"+marker)
    generated=r.build/'isolated_service_builder.py';generated.write_text(source)
    namespace=dict(run_ce64_soc.__dict__);namespace.update(service_wrapper=service_wrapper,service_metadata=metadata)
    exec(compile(source,str(generated),'exec'),namespace)
    overrides={str(f.relative_to(repo)):f for f in (repo/'rtl').rglob('*') if f.is_file()}
    overrides['tests/ce64_soc/tb_body.svh']=tb
    extras=[str(f.relative_to(repo)) for f in sorted((repo/'rtl/sfu').glob('*.sv'))]
    extras+=['rtl/soc/t17_uart_router.sv','rtl/soc/t18_spi.sv','rtl/ce64/nx_t25_local.sv']
    return namespace['build'](r,tools,vpi,board_memory=True,wave_window=4000,
        source_overrides=overrides,additional_sources=extras,defines=['OPT11_LANES=2'])
