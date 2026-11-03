"""Unmodified CoreMark algorithms on real T09 CPU; passive CRC and execution checks."""
import hashlib
import json
import os
from pathlib import Path
import cocotb
from cocotb.triggers import Timer
from common.axi import AxiEnvironment, AxiMonitor, SparseMemory
from common.checks import Checks, digest

@cocotb.test()
async def coremark_debug(dut):
    cfg=json.loads(Path(os.environ['NEXUSRV_CASE']).read_text())
    image=json.loads(Path(cfg['fixture']).read_text());mem=SparseMemory();checks=Checks()
    checks.equal(hashlib.sha256(Path(cfg['fixture']).read_bytes()).hexdigest(),cfg['fixture_sha256'],'input_identity','ELF segments')
    for s in image['segments']:mem.load(s['address'],bytes.fromhex(s['hex']))
    done=[]
    def write(a,v,strobe,cycle):
        if a==0x10000020:done.append(v)
    envs=[AxiEnvironment(dut,'iAxi',mem,1^0x49,3),AxiEnvironment(dut,'dAxi',mem,1^0x44,3,True,write_hook=write)]
    monitors=[AxiMonitor('i',checks),AxiMonitor('d',checks,True)]
    retires=[];branches=[];stalls=[];rom=0;cycle=0;drain=0
    for s in ('timerInterrupt','externalInterrupt','softwareInterrupt'):getattr(dut,s).value=0
    try:
        for cycle in range(cfg['max_cycles']):
            reset=cycle<12;dut.clk.value=0;dut.reset.value=int(reset);dut.rom_data.value=rom
            for e in envs:e.drive(cycle,reset)
            await Timer(5,unit='ns')
            if not reset:
                if int(dut.rom_enable.value):rom=mem.read(int(dut.rom_address.value))
                if int(dut.trace_retire.value):retires.append([cycle,int(dut.trace_pc.value),int(dut.trace_instruction.value)])
                if int(dut.trace_branch.value):branches.append([cycle,int(dut.trace_branch_pc.value),int(dut.trace_mispredict.value)])
                if int(dut.trace_stall.value):stalls.append(cycle)
            for e,m in zip(envs,monitors):
                v={} if reset else e.snapshot();m.sample(v,cycle,reset,0);e.sample(v,cycle,reset)
            dut.clk.value=1;await Timer(5,unit='ns')
            if done:
                drain+=1
                if drain==32:break
        checks.equal(done,[0xc021],'completion','real CPU completion')
        uart=''.join(chr(v&255) for _,_,a,v,_ in monitors[1].observed_writes if a==0x10000000)
        Path('coremark.log').write_text(uart)
        expected={'seedcrc':'e9f5','crclist':'e714','crcmatrix':'1fd7','crcstate':'8e3a','crcfinal':'e714'}
        import re
        actual={k:re.search(k+r'\s*:\s*0x([0-9a-f]+)',uart).group(1) for k in expected}
        checks.equal(actual,expected,'crc','official 2000-byte performance-seed known CRCs, one iteration')
        checks.require('ERROR! Must execute for at least 10 secs for a valid result!' in uart,'reporting','upstream short-run warning retained')
        checks.require('Errors detected' in uart and uart.count('ERROR!')==1,'reporting','only explained short-duration error; no CRC/type failure')
        checks.require(len(retires)>1000 and len(branches)>100 and len(stalls)>100,'execution','passive retired/branch/stall events')
        cache={m.name:[e for e in m.events if e[2]=='ar' and e[4]==7] for m in monitors}
        checks.require(all(cache.values()),'cache','actual I/D 8-beat refill requests')
        obs=dict(summary={'cycles':cycle+1},retire=retires,branches=branches,stall_cycles=stalls,i_axi=monitors[0].events,d_axi=monitors[1].events,cache_refills=cache,uart=uart)
        Path('observations.json').write_text(json.dumps(obs))
        seq=digest(obs)
    finally:
        checks.save('checks.json',case_id=cfg['case_id'],run_id=cfg['run_id'],seed=1,profile='coremark',fixture_sha256=cfg['fixture_sha256'],golden_sha256=cfg['golden_sha256'],sequence_sha256=locals().get('seq'),result=dict(cycles=cycle+1,retired=len(retires),branches=len(branches),stalls=len(stalls),crc=locals().get('actual'),formal_score=False))
