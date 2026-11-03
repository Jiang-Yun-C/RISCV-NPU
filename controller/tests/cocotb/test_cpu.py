"""Real VexRiscv instruction execution with independent external observations."""
import json
import os
import hashlib
import sys
from pathlib import Path

import cocotb
from cocotb.triggers import Timer
from common.axi import AxiEnvironment, AxiMonitor, SparseMemory
from common.checks import Checks, digest


@cocotb.test()
async def cpu_execution(dut):
    cfg=json.loads(Path(os.environ['NEXUSRV_CASE']).read_text())
    checks=Checks()
    checks.equal(hashlib.sha256(Path(cfg['fixture']).read_bytes()).hexdigest(),cfg['fixture_sha256'],'input_identity','fixture')
    checks.equal(hashlib.sha256(Path(cfg['golden']).read_bytes()).hexdigest(),cfg['golden_sha256'],'input_identity','golden')
    events=[]; retires=[]; branches=[]; outputs={}; trap_words=[]; uart=[]
    state={"phase":0, "done":None, "irq":0, "irq_due":0, "cycle":0}
    mem=SparseMemory()
    image=json.loads(Path(cfg['fixture']).read_text())
    for segment in image['segments']:
        mem.load(segment['address'], bytes.fromhex(segment['hex']))
    # Input data only; final result addresses are never preloaded.
    for a,v in [(0xb4100000,0x11223344),(0xb4102000,0x22334455),(0xb4104000,0x33445566)]:
        mem.write(a,v,15)
    golden=json.loads(Path(cfg['golden']).read_text())
    symbols=image['symbols']
    if cfg.get('negative')=='bad-golden':
        golden['results']['2'] ^= 1
    def read_hook(a, v):
        return cfg['seed'] if a==0x10000018 else v
    def write_hook(a, v, strobe, cycle):
        if a==0x10000040:
            state['phase']=v
            dut._log.info('CPU phase %d at cycle %d',v,cycle)
            if v==12:  # External owner changes backing store before CPU invalidate.
                mem.write(0xb4100000,0x55667788,15)
        elif a==0x10000044:
            state.update(irq=v, irq_due=cycle+13+cfg['seed']%17)
            events.append([cycle,'irq_requested',v])
        elif a==0x10000048:
            state['irq']=0
            events.append([cycle,'irq_ack',v])
        elif a==0x10000020:
            state['done']=v
    envs=[AxiEnvironment(dut,'iAxi',mem,cfg['seed']^0x49,cfg['max_delay']),
          AxiEnvironment(dut,'dAxi',mem,cfg['seed']^0x44,cfg['max_delay'],True,read_hook,write_hook)]
    monitors=[AxiMonitor('i',checks),AxiMonitor('d',checks,True)]
    irq_handles={7:dut.timerInterrupt,11:dut.externalInterrupt,3:dut.softwareInterrupt}
    dut.clk.value=0; dut.reset.value=1; dut.rom_data.value=0
    for signal in irq_handles.values(): signal.value=0
    stalled=0; rom_reads=[]; rom_data=0; drain=0; cycle=0
    try:
        for cycle in range(cfg['max_cycles']):
            state['cycle']=cycle
            reset=cycle<12 or cfg.get('negative')=='held-reset'
            dut.clk.value=0; dut.reset.value=int(reset); dut.rom_data.value=rom_data
            for n,signal in irq_handles.items():
                signal.value=int(not reset and state['irq']==n and cycle>=state['irq_due'])
            for env in envs: env.drive(cycle,reset)
            await Timer(5,unit='ns')
            if not reset:
                if cfg['profile']!='nopredict' and cycle in (12,267,268,269):
                    checks.equal(int(dut.trace_predictor_ready.value),int(cycle>=268),'predictor_reset','256-entry reset scrub')
                if int(dut.rom_enable.value):
                    address=int(dut.rom_address.value)
                    rom_data=mem.read(address)
                    rom_reads.append([cycle,address,rom_data])
                if int(dut.trace_retire.value):
                    retires.append([cycle,int(dut.trace_pc.value),int(dut.trace_instruction.value)])
                stalled+=int(dut.trace_stall.value)
                if int(dut.trace_branch.value):
                    branches.append([cycle,int(dut.trace_branch_pc.value),int(dut.trace_mispredict.value)])
            for env,monitor in zip(envs,monitors):
                values={} if reset else env.snapshot()
                monitor.sample(values,cycle,reset,state['phase'])
                env.sample(values,cycle,reset)
            dut.clk.value=1
            await Timer(5,unit='ns')
            if state['done'] is not None:
                drain+=1
                if drain==32: break
        checks.require(state['done'] is not None,'completion','simulation cycle timeout without CPU exit')
        checks.equal(state['done'],golden['exit'],'completion','firmware exit code')
        # Scoreboard consumes passive monitor transactions, not active BFM state.
        for cy,phase,a,v,strobe in monitors[1].observed_writes:
            if 0x10000100 <= a < 0x10000180:
                idx=str((a-0x10000100)//4)
                checks.require(idx not in outputs,'signature','no duplicate output '+idx)
                checks.equal(strobe,15,'signature','full signature word')
                outputs[idx]=v
            elif 0x10000200<=a<=0x1000020c:
                checks.equal(a,0x10000200+4*(len(trap_words)%4),'trap','ordered cause/epc/tval/status')
                trap_words.append(v)
            elif a==0x10000000:
                uart.append(chr(v & 255))
        expected_keys=set(golden['results'])|{'17','18'}
        checks.equal(sorted(outputs),sorted(expected_keys),'signature','exact output set')
        for idx,value in golden['results'].items(): checks.equal(outputs[idx],value,'signature',idx)
        checks.equal(''.join(uart),golden['uart'],'uart','CPU UART MMIO bytes')
        checks.require(len(retires)>1000 and stalled>0,'execution','retirement and load stalls')
        checks.require(outputs['17']>outputs['18']>1000,'counters','mcycle/minstret')
        checks.require(0<cycle-outputs['17']<1000,'counters','mcycle vs observed clock')
        checks.require(abs(len(retires)-outputs['18'])<200,'counters','minstret vs observed retire')
        checks.equal(len(trap_words),4*(len(golden['traps'])+3),'trap','exact exception/interrupt count')
        traps=[trap_words[n:n+4] for n in range(0,len(trap_words),4)]
        for actual,expected in zip(traps,golden['traps']):
            checks.equal(actual[:3],expected,'trap','mcause/mepc/mtval')
        for actual,cause in zip(traps[len(golden['traps']):],golden['irq_causes']):
            checks.equal(actual[0],cause,'interrupt','mcause')
            checks.require(actual[1]%4==0 and 0xb4000000<=actual[1]<0xb4010000,'interrupt','mepc within executing code')
            checks.equal(actual[3]&0x1888,0x1880,'interrupt','MPP/MPIE/MIE at trap')
        checks.equal(sum(insn==0x30200073 for _,_,insn in retires),len(traps),'mret','every handler returned')
        for monitor,addresses,hit_phase,replacement_phase in (
                (monitors[1],{0xb4100000,0xb4102000,0xb4104000},10,11),
                (monitors[0],{0xb4010000,0xb4012000,0xb4014000},20,21)):
            refills=[e for e in monitor.events if e[2]=='ar' and e[3] in addresses]
            # Instruction fetch may run ahead of the posted MMIO phase marker.
            # Partition by the observed third-tag refill, not by store completion.
            window=[e for e in refills if e[1]<=replacement_phase]
            third=next((i for i,e in enumerate(window) if e[3]==max(addresses)),None)
            checks.require(third is not None,'cache','third conflicting tag fetched')
            first=[e[3] for e in window[:third]]
            checks.equal(first,sorted(addresses)[:2],'cache','two ways keep A/B for A,B,A,B before C')
            replace=[e[3] for e in window[third:]]
            checks.require(len(replace)>=2 and any(a!=max(addresses) for a in replace[1:]),'cache','third tag causes replacement/refill')
            for e in refills: checks.equal(e[4],7,'cache','32-byte INCR refill')
        checks.require(any(e[1]==12 and e[2]=='ar' and e[3]==0xb4100000 for e in monitors[1].events),
                       'cache','management instruction invalidates stale D line')
        checks.require(any(a==0xb4100000 and v==0xdecafbad for _,_,a,v,_ in monitors[1].observed_writes),
                       'cache','write-through visible externally')
        checks.require(not any(e[2]=='ar' and 0x10000<=e[3]<0x20000 for e in monitors[0].events) and len(rom_reads)>10,
                       'cache','Boot ROM uses uncached synchronous port')
        loop=[v for _,pc,v in branches if pc==symbols['branch_site']]
        checks.equal(len(loop),128,'branch','all loop decisions observed')
        if cfg['profile']=='nopredict': checks.equal(sum(loop),126,'branch','unpredicted taken redirects')
        else: checks.require(1<=sum(loop)<=8,'branch',['trained dynamic predictor',sum(loop)])
        checks.require(any(e[2]=='r' and e[4]==2 for e in monitors[1].events),'fault','actual SLVERR observed')
        checks.require(any(e[2]=='r' and e[4]==3 for e in monitors[0].events),'fault','actual instruction DECERR observed')
        checks.require(not any(a==0 for _,_,a,_,_ in monitors[1].observed_writes),'branch','wrong-path store flushed')
    except BaseException as error:
        if checks.first_failure is None:
            checks.first_failure={"category":"test_exception","detail":repr(error)}
        raise
    finally:
        result={"cycles":cycle+1,"retired":len(retires),"stall_cycles":stalled,
                "branches":len(branches),"outputs":outputs,"trap_words":trap_words,
                "uart":''.join(uart),"exit":state['done'],
                "loop_misses":sum(v for _,pc,v in branches if pc==symbols['branch_site'])}
        Path('observations.json').write_text(json.dumps({"summary":result,"i_axi":monitors[0].events,
            "d_axi":monitors[1].events,"retire":retires,"branch":branches,"interrupt":events,"rom":rom_reads})+'\n')
        checks.save('checks.json',case_id=cfg['case_id'],run_id=cfg['run_id'],seed=cfg['seed'],
                    profile=cfg['profile'],sequence_sha256=digest([monitors[0].events,monitors[1].events,retires,branches,events]),
                    runtime={'python':sys.version,'executable':sys.executable,'prefix':sys.prefix,'cocotb':cocotb.__version__},
                    result=result,fixture_sha256=cfg['fixture_sha256'],golden_sha256=cfg['golden_sha256'])
