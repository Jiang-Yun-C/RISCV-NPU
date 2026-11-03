"""Unmodified service UART request plus passive true local-SRAM watermark."""
import hashlib
import json
import os
from pathlib import Path
import re
import numpy as np
import cocotb
from cocotb.triggers import FallingEdge,RisingEdge,ReadOnly,Timer
from common.checks import Checks
from common.final_drain import terminal_writes_drained


@cocotb.test()
async def production_service_postload(dut):
    cfg=json.loads(Path(os.environ['NEXUSRV_CASE']).read_text());c=Checks();raw=bytearray();bit_ns=8*cfg['uart_divisor']
    result=dict(scope=cfg['scope'],stage='STARTUP',complete_model_stack_qualified=False,
        actual_complete_model_stack_peak_bytes=None,actual_complete_model_guard_pass=None,
        actual_loader_authentication='NOT_RUN',board_execution=False,go=False)
    receiver=None
    async def receive():
        while True:
            await FallingEdge(dut.board_tx);await Timer(bit_ns*3//2,unit='ns');value=0
            for i in range(8):value|=int(dut.board_tx.value)<<i;await Timer(bit_ns,unit='ns')
            assert int(dut.board_tx.value)==1,'UART stop bit';raw.append(value)
    async def until(predicate,label):
        while not predicate():
            c.require(not int(dut.timed_out.value),'deadline',label+' exceeded original600M aggregate including startup')
            c.require(b'T25 ERROR' not in raw and b'T25 TRAP' not in raw,'guest',bytes(raw[-512:]).decode(errors='replace'))
            c.require(not int(dut.ddr_fault.value),'native','actual native quarantine/fault')
            await Timer(100000,unit='ns')
    async def peek_stack():
        words=[]
        for address in range(0x20000,0x30000,4):
            dut.service_stack_peek_address.value=address;await Timer(2,unit='ns');words.append(int(dut.service_stack_peek_value.value))
        first=next((i for i,w in enumerate(words) if w!=0xa5a5a5a5),len(words))
        data=dict(guard_bad_words=sum(w!=0xa5a5a5a5 for w in words[:4]),
            reserved_8k_bad_words=sum(w!=0xa5a5a5a5 for w in words[:8192//4]),
            watermark_bytes=65536-first*4,source='Actual nx_t25_local.core.ram, not sparse DDR mirror',
            seed_done=bool(int(dut.service_stack_seed_done.value)),stage=result['stage'])
        Path('stack-snapshot.json').write_text(json.dumps(data,indent=2)+'\n');return data
    try:
        for name in ('fixture','golden','thresholds'):
            c.equal(hashlib.sha256(Path(cfg[name]).read_bytes()).hexdigest(),cfg[name+'_sha256'],'identity',name)
        # Observe the existing fixture reset protocol before interpreting any
        # RTL status; no invented settling delay or X-resolution override.
        await FallingEdge(dut.reset)
        await RisingEdge(dut.clk)
        await ReadOnly()
        receiver=cocotb.start_soon(receive())
        await until(lambda:b'T25 READY\n' in raw,'production startup to READY')
        result.update(startup_cycles=int(dut.cycles.value),stage='REQUEST')
        c.equal(int(dut.snapshot_state_installed.value),1,'snapshot','declared postload state installed')
        c.equal(int(dut.model_sealed.value),1,'guard','actual SD publication feeds actual model guard')
        c.equal(int(dut.service_stack_seed_done.value),1,'startup','unmodified production entry seeded actual SRAM')
        start=int(dut.cycles.value);request=f":ids 1 {cfg['token']}\n".encode()
        for value in request:
            dut.uart_input.value=0;await Timer(bit_ns,unit='ns')
            for i in range(8):dut.uart_input.value=(value>>i)&1;await Timer(bit_ns,unit='ns')
            dut.uart_input.value=1;await Timer(bit_ns,unit='ns')
        prefix=len(raw)
        await until(lambda:b'T25 METRICS ' in raw[prefix:] and b'T25 READY\n' in raw[prefix:],'production full M1 service return')
        result.update(request_cycles_including_uart=int(dut.cycles.value)-start,stage='POST_RETURN_PASSIVE_CHECK')
        c.require(await terminal_writes_drained(dut),'drain','actual terminal CPU B and native drain')
        c.equal(int(dut.owner.value),0,'owner','real production backend released')
        c.equal(int(dut.backend_idle.value),1,'native','native idle after completed request')
        stack=await peek_stack();c.equal(stack['guard_bad_words'],0,'stack','original16B guard')
        c.equal(stack['reserved_8k_bad_words'],0,'stack','original8KiB reserved margin')
        c.require(0<stack['watermark_bytes']<=57344,'stack','actual full service watermark original56KiB budget')
        c.equal(int(dut.service_guard_written_after_seed.value),0,'stack','no guard store after real stack seeding')
        text=raw.decode('utf-8',errors='replace');line=next(s for s in text.splitlines() if s.startswith('T25 METRICS '))
        metrics={k:int(v,16) for k,v in re.findall(r'(\w+)=([0-9a-f]{16})',line)}
        c.equal(metrics.get('stack_peak_bytes'),stack['watermark_bytes'],'stack','guest telemetry matches passive actualSRAM sentinel')
        values=[]
        addresses=[(cfg['internal_logits_address'],151936)]
        addresses += [(0xa8000000+v*7864320+l*327680,128) for l in range(24) for v in range(2)]
        for address,n in addresses:
            for i in range(n):
                dut.peek_address.value=address+4*i;await Timer(2,unit='ns');values.append(int(dut.peek_value.value))
        actual=np.asarray(values,dtype='<u4').view('<f4');actual.tofile('actual-logits-kv.bin');want=np.fromfile(cfg['golden'],dtype='<f4')
        c.equal(actual.size,want.size,'numeric','complete logits and all24layer KV')
        limits=json.loads(Path(cfg['thresholds']).read_text())['cumulative'];numeric={}
        for label,lo,hi,key in [('logits',0,151936,'logits_24_layers'),('KV',151936,158080,'kv')]:
            av=actual[lo:hi].astype('f8');ev=want[lo:hi].astype('f8');error=np.abs(av-ev);t=limits[key]
            c.require(bool(np.isfinite(av).all() and np.all(error<=t['atol']+t['rtol']*np.abs(ev))),'numeric',label+' original element thresholds')
            nrmse=float(np.sqrt(np.mean(error**2))/max(np.sqrt(np.mean(ev**2)),1e-12));c.require(nrmse<=t['nrmse'],'numeric',label+' original NRMSE')
            numeric[label]=dict(elements=hi-lo,max_abs=float(error.max()),nrmse=nrmse)
        ids=re.search(r'T25 IDS ([0-9a-f]{8})',text);c.require(ids is not None,'guest','original emitted token')
        c.equal(int(ids[1],16),int(np.argmax(actual[:151936])),'greedy','actual argmax from complete logits')
        result.update(stage='COMPLETE_COMPONENT',complete_model_stack_qualified=True,
            actual_complete_model_stack_peak_bytes=stack['watermark_bytes'],actual_complete_model_guard_pass=True,
            metrics=metrics,numeric=numeric,aggregate_cycles=int(dut.cycles.value),
            frequency_signoff_hz=None,authentication_qualified=False,full_boot_qualified=False,text_ttft_qualified=False)
    except BaseException as e:
        if c.first_failure is None:c.first_failure=dict(category='test_exception',detail=repr(e))
        result.update(failure=repr(e),aggregate_cycles=int(dut.cycles.value),
            startup_completed=result['stage']!='STARTUP',startup_cycles=int(dut.cycles.value) if result['stage']=='STARTUP' else result.get('startup_cycles'))
        raise
    finally:
        if receiver is not None:receiver.cancel()
        Path('uart.bin').write_bytes(raw);Path('uart.txt').write_text(raw.decode('utf-8',errors='replace'))
        if not Path('stack-snapshot.json').exists() and int(dut.service_stack_seed_done.value):
            result['partial_stack_snapshot']=await peek_stack()
        Path('observations.json').write_text(json.dumps(result,indent=2)+'\n')
        c.save('checks.json',**{k:cfg[k] for k in ('case_id','run_id','seed','fixture_sha256')})
