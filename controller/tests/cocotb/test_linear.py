"""Real Coral RVV, T13 firewall/drain, T04 memory and independent byte scoreboard."""
import hashlib,json,os,struct,sys
from pathlib import Path
import cocotb
from cocotb.triggers import Timer
from common.checks import Checks
from linear_check import score

@cocotb.test()
async def linear(dut):
    cfg=json.loads(Path(os.environ['NEXUSRV_CASE']).read_text());checks=Checks();result={};observations={'jobs':[]}
    async def edge():await Timer(10,unit="ns")
    async def wait(condition,category,detail,limit=20000000):
        start=int(dut.cycle.value)
        while not condition():
            await Timer(50000 if limit>100000 else 1000,unit='ns')
            checks.require(not int(dut.timed_out.value) and int(dut.cycle.value)-start<limit,category,detail)
    async def native(command,address=0,data=0,strobe=0xffff,size=4):
        await edge();dut.command_address.value=address;dut.command_data.value=data;dut.command_strobe.value=strobe;dut.command_size.value=size;dut.command.value=command
        await wait(lambda:int(dut.command_done.value),'completion','native AXI slave command',10000)
        value=int(dut.reply_data.value);await edge();dut.command.value=0
        await wait(lambda:not int(dut.command_done.value),'completion','command acknowledgement',10000)
        return value
    async def control(v):await native(1,0x30000,v,0xf,2)
    async def read_local(a):return (await native(2,a,0,0xffff,4)).to_bytes(16,'little')
    async def reset_core():
        await control(3);await Timer(200,unit='ns')
    def counters():
        return {k:int(getattr(dut,h).value) for k,h in dict(cycles='counter_cycles',read_bytes='counter_read',write_bytes='counter_write',read_wait='counter_read_wait',write_wait='counter_write_wait',ar='counter_ar',r='counter_r',aw='counter_aw',w='counter_w',b='counter_b').items()}
    try:
        for key in ('fixture','golden'):checks.equal(hashlib.sha256(Path(cfg[key]).read_bytes()).hexdigest(),cfg[key+'_sha256'],'input_identity',key)
        fixture=json.loads(Path(cfg['fixture']).read_text());golden=json.loads(Path(cfg['golden']).read_text())
        await wait(lambda:int(dut.booted.value),'completion','complete native upload and readback',100000)
        for job in golden['jobs']:
            await reset_core()
            request=struct.pack('<24I',*job['request'])
            for off in range(0,96,16):await native(1,0x10000+off,int.from_bytes(request[off:off+16],'little'))
            for off in range(0,112,16):await native(1,0x10100+off,0)
            await native(1,0x30004,fixture['entry']<<32,0xf0,2)
            address=job['request'][10] if job.get('inject_where')=='read' else job['request'][11]
            await edge();dut.inject_enable.value=bool(job.get('inject'));dut.inject_start.value=address;dut.inject_end.value=address+15;dut.inject_resp.value=job.get('inject',2) or 2
            dut.clear_error.value=1;await edge();dut.clear_error.value=0
            if job.get('inject_where')=='pause':dut.memory.fixed_latency.value=5000
            await edge();dut.counter_clear.value=0;dut.isolate.value=0
            start=int(dut.cycle.value)+1
            if cfg.get('negative')!='held-reset':await control(0)
            pause=False
            if job.get('inject_where')=='pause':
                await wait(lambda:int(dut.counter_ar.value)>0,'fault','pause accepted AR')
                await Timer(1000,unit='ns');pause=not int(dut.guard_idle.value)
                checks.require(pause,'fault','in-flight transaction held by long memory latency')
            else:await wait(lambda:(int(dut.halted.value) and (cfg.get('negative')!='held-reset' or int(dut.counter_ar.value)>0)) or int(dut.fault.value) or int(dut.guard_error.value),'completion','real Coral halt/fault',2000 if cfg.get('negative')=='held-reset' else cfg['job_max_cycles'])
            fault=bool(int(dut.guard_error.value));is_error=isinstance(job['status'],str)
            # Isolation freezes new addresses but every accepted response must drain.
            await edge();dut.isolate.value=1
            await wait(lambda:int(dut.guard_idle.value),'recovery','accepted bus transaction drains',100000)
            await Timer(100,unit='ns');snap=counters();stop=int(dut.cycle.value);fault=bool(int(dut.guard_error.value))
            entry=dict(name=job['name'],start=start,stop=stop,counters=snap,guard_error=fault,drained=bool(int(dut.guard_idle.value)),pause_observed=pause)
            await edge();dut.counter_clear.value=1;dut.inject_enable.value=0
            if is_error:
                checks.require(fault or pause,'fault','required injected failure observed');valid=bool(int(dut.halted.value)) and not bool(int(dut.fault.value)) and not fault and not pause
                await reset_core();dut.memory.fixed_latency.value=cfg['latency'];entry.update(output_valid=valid,recovered=True)
            else:
                checks.equal(int(dut.fault.value),0,'execution','no core fault');checks.equal(int(dut.halted.value),1,'completion','mpause retired')
                raw=b''.join([await read_local(0x10100+off) for off in range(0,112,16)])[:104]
                header=struct.unpack('<6Ii5I7Q',raw);names='abi size session_lo session_hi sequence_lo sequence_hi status valid tiles rows checksum reserved payload_read payload_write cycles load_cycles compute_cycles write_cycles other_cycles'.split()
                entry['result']=dict(zip(names,header));checks.equal(entry['result']['abi'],0x4c4e3135,'completion','private result ABI')
            observations['jobs'].append(entry);await native(3)
        # Read the actual private stack sentinel through the native slave.
        observations['stack_guard']=list((await read_local(0x16ff0)))
        first=0x18000
        for address in range(0x17000,0x18000,16):
            if (await read_local(address))!=bytes([0xa5])*16:first=address;break
        observations['stack_peak']=0x18000-first
        observations.update(protocol_error=int(dut.protocol_error.value),protocol_checks=int(dut.protocol_checks.value))
        await native(3)
        checks,result=score(Path.cwd(),fixture,golden,observations,Path(cfg['fixture']).parent,checks,cfg.get('negative'))
    except BaseException as error:
        if checks.first_failure is None:checks.first_failure={'category':'test_exception','detail':repr(error)}
        raise
    finally:
        Path('observations.json').write_text(json.dumps(observations,indent=2)+'\n')
        sequence=hashlib.sha256(Path('transactions.csv').read_bytes()).hexdigest() if Path('transactions.csv').exists() else None
        checks.save('checks.json',case_id=cfg['case_id'],run_id=cfg['run_id'],seed=cfg['seed'],profile=cfg['profile'],fixture_sha256=cfg['fixture_sha256'],golden_sha256=cfg['golden_sha256'],sequence_sha256=sequence,
            runtime={'python':sys.version,'executable':sys.executable,'prefix':sys.prefix,'cocotb':cocotb.__version__},result=result)
