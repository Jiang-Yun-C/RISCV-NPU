"""Candidate-parameterized production service observer, opt-in frozen runner only."""
import hashlib
import json
import os
from pathlib import Path
import re
import numpy as np
import cocotb
from cocotb.triggers import FallingEdge,RisingEdge,ReadOnly,Timer
from common.checks import Checks
from scripts.opt10_r1_measurement_cocotb import close_observation,inspect_writable,save_observer_output


def transport_state(dut):
    return bool(int(dut.service_transport_drained.value)),int(dut.service_transport_activity.value)


async def peek_words(dut,address_name,value_name,addresses):
    words=[]
    for address in addresses:
        getattr(dut,address_name).value=address
        await Timer(2,unit='ns')
        words.append(int(getattr(dut,value_name).value))
    return words


async def peek_stack(dut,stage):
    """Caller enters through inspect_writable; reads the actual local SRAM."""
    words=await peek_words(dut,'service_stack_peek_address','service_stack_peek_value',range(0x20000,0x30000,4))
    first=next((i for i,w in enumerate(words) if w!=0xa5a5a5a5),len(words))
    value=dict(guard_bad_words=sum(w!=0xa5a5a5a5 for w in words[:4]),
        reserved_8k_bad_words=sum(w!=0xa5a5a5a5 for w in words[:8192//4]),
        watermark_bytes=65536-first*4,source='Actual nx_t25_local.core.ram, not sparse DDR mirror',
        seed_done=bool(int(dut.service_stack_seed_done.value)),stage=stage)
    Path('stack-snapshot.json').write_text(json.dumps(value,indent=2)+'\n')
    return value


@cocotb.test()
async def production_service_observed(dut):
    cfg=json.loads(Path(os.environ['NEXUSRV_CASE']).read_text());checks=Checks();raw=bytearray()
    bit_ns=8*cfg['uart_divisor'];receiver=None
    result=dict(scope=cfg['scope'],candidate_id=cfg['candidate_id'],stage='STARTUP',
        complete_model_stack_observed=False,complete_model_stack_qualified=False,
        actual_complete_model_stack_peak_bytes=None,actual_complete_model_guard_pass=None,
        actual_loader_authentication='NOT_RUN',board_execution=False,go=False)
    async def receive():
        while True:
            await FallingEdge(dut.board_tx);await Timer(bit_ns*3//2,unit='ns');value=0
            for i in range(8):
                value|=int(dut.board_tx.value)<<i;await Timer(bit_ns,unit='ns')
            assert int(dut.board_tx.value)==1,'UART stop bit'
            raw.append(value)
    async def until(predicate,label):
        while not predicate():
            checks.require(not int(dut.timed_out.value),'deadline',label+' original aggregate deadline')
            checks.require(not int(dut.completed.value),'guest','unexpected component ROM/application exit')
            checks.require(b'T25 ERROR' not in raw and b'T25 TRAP' not in raw,'guest',bytes(raw[-512:]).decode(errors='replace'))
            checks.require(not int(dut.ddr_fault.value),'native','actual native fault/quarantine')
            await Timer(100000,unit='ns')
    async def no_inspection():return None
    try:
        for name in ('fixture','golden','thresholds','norm_catalog'):
            checks.equal(hashlib.sha256(Path(cfg[name]).read_bytes()).hexdigest(),cfg[name+'_sha256'],'identity',name)
        await FallingEdge(dut.reset);await RisingEdge(dut.clk);await ReadOnly()
        receiver=cocotb.start_soon(receive())
        await until(lambda:b'T25 READY\n' in raw,'startup to READY')
        result.update(startup_cycles=int(dut.cycles.value),stage='REQUEST')
        for name,want in [('snapshot_state_installed',1),('model_sealed',1),('service_stack_seed_done',1),
                          ('startup_authorized',1),('service_startup_status',58)]:
            checks.equal(int(getattr(dut,name).value),want,'startup',name)
        _,startup_close=await close_observation(dut,no_inspection,transport_state=lambda:transport_state(dut),
            deadline=cfg['max_cycles'],stable_cycles=cfg['stable_cycles'])
        result['startup_transport_close']=startup_close
        await Timer(1,unit='ns')
        dut.service_request_observation.value=1
        start=int(dut.cycles.value)
        for value in f":ids 1 {cfg['token']}\n".encode():
            dut.uart_input.value=0;await Timer(bit_ns,unit='ns')
            for i in range(8):
                dut.uart_input.value=(value>>i)&1;await Timer(bit_ns,unit='ns')
            dut.uart_input.value=1;await Timer(bit_ns,unit='ns')
        prefix=len(raw)
        await until(lambda:b'T25 METRICS ' in raw[prefix:] and b'T25 READY\n' in raw[prefix:],'service return')
        result.update(request_cycles_including_uart=int(dut.cycles.value)-start,stage='POST_RETURN_PASSIVE_CHECK')
        # No receiver or other observer coroutine may advance time after close.
        receiver.cancel();receiver=None
        async def inspect_all():
            dut.service_finalize_observation.value=1
            checks.equal(int(dut.owner.value),0,'owner','real backend released')
            checks.equal(int(dut.backend_idle.value),1,'native','backend idle after request')
            stack=await peek_stack(dut,result['stage'])
            checks.equal(stack['guard_bad_words'],0,'stack','original16B guard')
            checks.equal(stack['reserved_8k_bad_words'],0,'stack','original8KiB reserved margin')
            checks.require(0<stack['watermark_bytes']<=57344,'stack','original56KiB budget')
            checks.equal(int(dut.service_guard_written_after_seed.value),0,'stack','no guard store after real seeding')
            text=raw.decode('utf-8',errors='replace')
            line=next(s for s in text.splitlines() if s.startswith('T25 METRICS '))
            metrics={k:int(v,16) for k,v in re.findall(r'(\w+)=([0-9a-f]{16})',line)}
            checks.equal(metrics.get('stack_peak_bytes'),stack['watermark_bytes'],'stack','guest vs passive actual SRAM')
            for name,want in [('ce_calls',169),('cpu_calls',0),('fallback_calls',0)]:
                checks.equal(metrics.get(name),want,'dispatch',name)
            values=[];addresses=[(cfg['internal_logits_address'],151936)]
            addresses += [(0xa8000000+v*7864320+l*327680,128) for l in range(24) for v in range(2)]
            for address,n in addresses:
                for i in range(n):
                    dut.peek_address.value=address+4*i;await Timer(2,unit='ns')
                    values.append(int(dut.peek_value.value))
            actual=np.asarray(values,dtype='<u4').view('<f4');actual.tofile('actual-logits-kv.bin')
            want=np.fromfile(cfg['golden'],dtype='<f4')
            checks.equal(actual.size,want.size,'numeric','complete logits and all24layer KV')
            limits=json.loads(Path(cfg['thresholds']).read_text())['cumulative'];numeric={}
            for label,lo,hi,key in [('logits',0,151936,'logits_24_layers'),('KV',151936,158080,'kv')]:
                av=actual[lo:hi].astype('f8');ev=want[lo:hi].astype('f8');error=np.abs(av-ev);limit=limits[key]
                checks.require(bool(np.isfinite(av).all() and np.all(error<=limit['atol']+limit['rtol']*np.abs(ev))),'numeric',label+' original thresholds')
                nrmse=float(np.sqrt(np.mean(error**2))/max(np.sqrt(np.mean(ev**2)),1e-12))
                checks.require(nrmse<=limit['nrmse'],'numeric',label+' original NRMSE')
                numeric[label]=dict(elements=hi-lo,max_abs=float(error.max()),nrmse=nrmse)
            ids=re.search(r'T25 IDS ([0-9a-f]{8})',text)
            checks.require(ids is not None,'guest','original emitted token')
            checks.equal(int(ids[1],16),int(np.argmax(actual[:151936])),'greedy','complete logits argmax')
            result.update(actual_complete_model_stack_peak_bytes=stack['watermark_bytes'],actual_complete_model_guard_pass=True,
                metrics=metrics,numeric=numeric,observed_prefill_target_cycles=250000000,
                observed_prefill_within_2second_compute_target=metrics.get('prefill_ticks',250000001)<=250000000,
                decode_throughput_seconds_per_token=None,visible_text_TTFT_seconds=None,frequency_signoff_hz=None,
                authentication_qualified=False,full_boot_qualified=False,text_ttft_qualified=False)
            return dict(stack=stack,inspection_end_cycle=int(dut.cycles.value))
        inspected,close=await close_observation(dut,inspect_all,transport_state=lambda:transport_state(dut),
            deadline=cfg['max_cycles'],stable_cycles=cfg['stable_cycles'])
        result.update(terminal_close=close,inspection=inspected,stage='COMPLETE_OBSERVER',complete_model_stack_observed=True,
            aggregate_cycles=close['cycle'],raw_checks='PENDING_PRODUCER_EXIT')
    except BaseException as error:
        if checks.first_failure is None:checks.first_failure=dict(category='test_exception',detail=repr(error))
        result.update(failure=repr(error),aggregate_cycles=int(dut.cycles.value))
        raise
    finally:
        if receiver is not None:receiver.cancel()
        Path('uart.bin').write_bytes(raw);Path('uart.txt').write_text(raw.decode('utf-8',errors='replace'))
        partial=None
        if result['stage']!='COMPLETE_OBSERVER' and not Path('stack-snapshot.json').exists() and int(dut.service_stack_seed_done.value):
            async def partial():return await peek_stack(dut,'FAILED_PARTIAL_INSPECTION')
        await save_observer_output(result,checks,{k:cfg[k] for k in ('case_id','run_id','seed','fixture_sha256')},partial_inspect=partial)
