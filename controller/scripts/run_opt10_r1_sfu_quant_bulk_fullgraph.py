#!/usr/bin/env python3
"""Run the full169 real RV32 graph with independently verified physical weights."""
import argparse,json,shutil,sys,traceback
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from evidence import EvidenceRun,sha256,write_json
from verify_opt14 import receipt
from run_cocotb import environment
from run_ce64_soc import build
from tests.models.prepare_image import parse_elf
from model_tools.verify_pack import verify

def prepare(r,repo,parent,tools,token):
    image=r.build/'image';image.mkdir();regions=[]
    manifest=json.loads((ROOT/'docs/spec/model-pack-v1-manifest.json').read_text())
    pack=verify(ROOT/manifest['pack_path'],expected_sha256=manifest['sha256'])
    with pack.path.open('rb') as f:
        for i,e in enumerate(pack.entries.values()):
            if e['kind']==4 or e['region']!=1 or e['alias_of'] is not None:continue
            f.seek(e['offset']);data=f.read(e['length']);p=image/f'tensor-{i}.bin';p.write_bytes(data)
            r.check('tensor-'+str(i),sha256(p)==e['sha256'],e['name'])
            regions.append(dict(name=e['name'],address=e['soc_address'],bytes=e['length'],path=str(p),sha256=sha256(p),kind='immutable_model'))
    sys.path.insert(0,str(ROOT/'tests/reference'));from oracle import Oracle
    oracle=Oracle();logits=oracle.forward([token]);golden=np.concatenate((logits.reshape(-1),oracle.cache().reshape(-1))).astype('<f4');golden.tofile(image/'golden.bin');del oracle
    shutil.copy2(parent/'production/full_weights.h',image/'full_weights.h')
    src=repo/'firmware/drivers/accel';port=repo/'firmware/runtime/port';ref=repo/'firmware/runtime/reference';elf=image/'fullgraph.elf'
    flags=['-march=rv32imf_zicsr_zifencei','-mabi=ilp32f','-DHARD_FLOAT','-DNX_PORTABLE',f'-DFULLGRAPH_TOKEN={token}','-O2','-g','-ffp-contract=off','-fno-fast-math','-fno-strict-aliasing','-ffreestanding','-fno-builtin','-fno-pic','-nostdlib','-nostartfiles','-msmall-data-limit=0','-ffunction-sections','-fdata-sections','-fstack-usage','-Wall','-Wextra','-Werror','-Wno-unknown-pragmas','-Wl,--gc-sections','-Wl,--build-id=none']
    r.execute('firmware',[tools['rv32_gcc'],*flags,'-I',src,'-I',port,'-I',ref,'-I',repo/'software/include','-I',image,'-T',ROOT/'tests/opt12/link.ld',f'-Wl,-Map={image}/fullgraph.map',repo/'firmware/cpu/start.S',ROOT/'tests/opt10_r1_direct_quant/fullgraph.c',port/'ce64_backend.c',ref/'nx_reference.c',*[src/n for n in ('accel.c','target.c','linear_api.c','ce64_linear.c','opt12.c')],'-lm','-lc','-lgcc','-o',elf],120)
    entry,segments,abi=parse_elf(elf.read_bytes(),base=0x10000,capacity=0xb8000000-0x10000);r.check('actual-RV32-ABI',entry==0x10000 and abi==2,'Full graph source and real production driver, no arithmetic stubs')
    rom=bytearray(65536)
    for i,s in enumerate(segments):
        if 0x10000<=s.address<0x20000:rom[s.address-0x10000:s.address-0x10000+len(s.data)]=s.data
        p=image/f'cpu-{i}.bin';p.write_bytes(s.data);regions.append(dict(name=p.stem,address=s.address,bytes=len(s.data),path=str(p),sha256=sha256(p),kind='firmware'))
    ordered=sorted(regions,key=lambda x:x['address']);r.check('fixture-nonoverlap',all(a['address']+a['bytes']<=b['address'] for a,b in zip(ordered,ordered[1:])),len(regions))
    write_json(image/'fixture.json',dict(regions=regions,model_pack_sha256=manifest['sha256'],scope='EXACT_VERIFIED_POSTLOAD_TENSOR_PRELOAD_NOT_AUTHENTICATED_LOADER'))
    (image/'load.plan').write_text(''.join(f"B {x['address']:x} {x['bytes']:x} {x['path']}\n" for x in regions))
    (image/'ce-rom.hex').write_text(''.join(f'{int.from_bytes(rom[i:i+4],"little"):08x}\n' for i in range(0,65536,4)))
    write_json(r.path/'fixture-freeze.json',dict(model_pack_sha256=manifest['sha256'],golden_sha256=sha256(image/'golden.bin'),fixture_sha256=sha256(image/'fixture.json'),token=token,thresholds_sha256=sha256(ROOT/'configs/t05-thresholds.json')))
    return image

def main():
    p=argparse.ArgumentParser();p.add_argument('--candidate',type=Path,required=True);p.add_argument('--run-id',required=True);p.add_argument('--token',type=int,choices=(0,255),default=0);a=p.parse_args()
    r=EvidenceRun(ROOT,'OPT10_R1_FULLGRAPH',a.run_id);code=1
    try:
        parent=a.candidate.resolve();m=receipt(parent,'OPT16_CANDIDATE');repo=Path(m['candidate_repo']);contract=json.loads((ROOT/'evidence/OPT10_R1_FULLGRAPH/opt10-r1-fullgraph-contract-20261020-v2/contract.json').read_text())
        r.check('frozen-fullgraph-contract',m['candidate_id']==contract['candidate_id'] and all(sha256(ROOT/n)==h for n,h in contract['frozen_inputs'].items()),m['candidate_id'])
        sources=json.loads((parent/'candidate-sources.json').read_text());r.check('candidate-before',all(sha256(repo/n)==h for n,h in sources.items()),m['candidate_id'])
        cfg=json.loads((ROOT/'configs/opt12-vector.json').read_text());cfg['max_cycles']=600000000;tools={k:v['path'] for k,v in json.loads((ROOT/'docs/spec/toolchain-lock.json').read_text())['tools'].items()};vpi=environment(r,cfg,tools)
        r.manifest.update(candidate_id=m['candidate_id'],scope=contract['scope'],board_execution=False,frequency_signoff_hz=None,production_call_deadline=900000000,aggregate_test_cycle_deadline=600000000,token=a.token)
        image=prepare(r,repo,parent,tools,a.token)
        tb=r.build/'tb_body.svh';s=(ROOT/'tests/ce64_soc/tb_body.svh').read_text().replace('soc.compute.ce.control.','soc.compute.ce.control.linear_control.').replace("cpu_bus.araddr<32'hac200000","cpu_bus.araddr<32'hb0000000")
        s=s.replace('backend.awlen!=0||backend.awburst!=1',"backend.awlen>31||backend.awburst!=1||(backend.awlen!=0&&backend.awsize!=4)")
        s=s.replace('      if(backend.awvalid&&backend.awready)$fwrite','      if(backend.awvalid&&backend.awready)$fwrite(trace_fd,"%0d,BA,%h,%h,%h,%0d\\n",cycles,backend.awaddr,backend.awlen,backend.awsize,owner);\n      if(backend.awvalid&&backend.awready)$fwrite')
        tb.write_text(s+'\n'+(ROOT/'tests/opt12/monitor.svh').read_text()+'\n'+(ROOT/'tests/opt10_r1_sfu_quant_bulk/fullgraph_monitor.svh').read_text());overrides={str(f.relative_to(repo)):f for f in (repo/'rtl').rglob('*') if f.is_file()};overrides['tests/ce64_soc/tb_body.svh']=tb
        sim=build(r,tools,vpi,board_memory=True,wave_window=4000,source_overrides=overrides,additional_sources=[str(f.relative_to(repo)) for f in sorted((repo/'rtl/sfu').glob('*.sv'))],defines=['OPT11_LANES=2'])
        dest=r.build/'cocotb/seed1';dest.mkdir(parents=True)
        for f in sim.parent.glob('*.bin'):shutil.copy2(f,dest/f.name)
        cfg.update(case_id='seed1',run_id=r.run_id,seed=1,fixture=str(image/'fixture.json'),golden=str(image/'golden.bin'),fixture_sha256=sha256(image/'fixture.json'),golden_sha256=sha256(image/'golden.bin'),thresholds=str(ROOT/'configs/t05-thresholds.json'),image_plan=str(image/'load.plan'),ce_rom=str(image/'ce-rom.hex'))
        write_json(dest/'case.json',cfg)
        try:r.execute('actual-full169',[sys.executable,ROOT/'scripts/opt10_r1_fullgraph_case.py','--case',dest/'case.json','--sim',sim],10800,cwd=dest)
        finally:shutil.copytree(dest,r.path/'cocotb/seed1')
        from check_opt10_r1_fullgraph_phases import check
        observation=json.loads((dest/'observations.json').read_text());observation['independent_phases']=check(dest,observation)
        write_json(r.path/'results.json',observation);r.check('candidate-after',all(sha256(repo/n)==h for n,h in sources.items()),m['candidate_id']);code=0
    except Exception:(r.path/'failure.txt').write_text(traceback.format_exc());print(traceback.format_exc(),flush=True)
    finally:
        for name in ('image','sources'):
            if(r.build/name).exists():shutil.copytree(r.build/name,r.path/name)
        shutil.copy2(__file__,r.path/Path(__file__).name)
        r.manifest['artifacts']={str(f.relative_to(r.path)):sha256(f) for f in r.path.rglob('*') if f.is_file() and not(f.parent==r.path and f.name in ('manifest.json','commands.json','checks.json','exit-status.txt'))};code=r.finish(code)
    print(r.manifest['status'],r.path,flush=True);return code
if __name__=='__main__':sys.exit(main())
