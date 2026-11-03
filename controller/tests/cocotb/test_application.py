"""Real VexRiscv executor; pin stimuli and independent action/state oracle."""
import csv
import hashlib
import json
import io
import os
from pathlib import Path
import sys
import cocotb
from cocotb.triggers import Timer
from common.checks import Checks,digest
from peripherals import UART,Sensor
from prepare import fingerprint
from pin_wave import capture,check as check_pins

@cocotb.test()
async def application(dut):
    cfg=json.loads(Path(os.environ['NEXUSRV_CASE']).read_text());checks=Checks();responses=[];pins=[];sensors=[];result={};tasks=[]
    try:
        for key in ('fixture','golden'):
            checks.equal(hashlib.sha256(Path(cfg[key]).read_bytes()).hexdigest(),cfg[key+'_sha256'],'input_identity',key)
        fixture=json.loads(Path(cfg['fixture']).read_text());golden=json.loads(Path(cfg['golden']).read_text())
        for image in fixture['images']:
            checks.equal(hashlib.sha256(Path(image['path']).read_bytes()).hexdigest(),image['sha256'],'input_identity',image['path'])
        uart=UART(dut,checks);tasks.append(cocotb.start_soon(uart.receive()))
        tasks.append(cocotb.start_soon(capture(dut)))
        if cfg.get('negative')=='held-reset':
            while not int(dut.timed_out.value):await Timer(10000,unit='ns')
            checks.require(False,'completion','held reset cannot complete')
        checks.equal(await uart.line(),'READY T20 UART_INTENT_REPLAY','uart','real firmware startup text')
        for row in golden['groups'][cfg['profile']]:
            if row.get('check_actuator_snapshot'):
                checks.equal([int(dut.gpio_led.value),int(dut.pwm_duty.value)],[row['state']['led'],row['state']['pwm']],'snapshot','actual actuator pins/register match model snapshot before request')
            sensor=Sensor(dut,row,checks);job=cocotb.start_soon(sensor.serve())
            raw_text=row['text'].encode();raw_intent=row['intent'].encode()
            frame=f"{row['id']} {row['epoch']} {len(raw_text)} {len(raw_intent)}\n".encode()+raw_text+b'\n'+raw_intent+b'\n'
            await uart.send(frame)
            response=json.loads(await uart.line());display=await uart.line();responses.append(response)
            expected=row['expected'];status=expected['error'] or 'OK'
            if cfg.get('negative')=='bad-golden' and len(responses)==1:status='INTENTIONAL_BAD_GOLDEN'
            checks.equal(response['validation'],status,'validation',row['name'])
            checks.equal(response['id'],row['id'],'request','request id')
            checks.equal(response['text'],row['text'],'request','UTF8 text arrived via UART')
            checks.equal(response['intent'],row['intent'],'provenance','exact recorded model bytes')
            checks.equal(response['intent_fnv32'],fingerprint(row['intent']),'provenance','CPU fingerprint binds raw model output')
            checks.equal(response['actions'],expected['actions'],'actions','ordered validated actions')
            checks.equal(response['readings'],expected['readings'],'sensor','current-state query values')
            checks.equal(display,f"RESULT {row['id']} {status}",'display','deterministic display template')
            job.cancel();dut.sensor_sda.value=1;dut.sensor_scl.value=1;sensors.append(dict(name=row['name'],events=sensor.events))
            # Data originates on I2C pins; compare CPU decoded packet independently.
            if status=='OK':
                checks.equal(response['temperature'],row['state']['temperature'],'sensor','current temperature')
                checks.equal(response['light'],row['state']['light'],'sensor','current light')
                checks.equal(response['sampled_at'],sensor.sampled_at,'freshness','sample timestamp')
                checks.require(any(e[0]=='stop' for e in sensor.events),'i2c','STOP after complete sensor packet')
            if status in ('STALE','STATE'):checks.require(bool(sensor.events),'freshness','state fault exercised on I2C')
            if status in ('NACK','TIMEOUT'):checks.require(bool(sensor.events),'fault','sensor failure exercised on pins')
            if status=='NACK':checks.require(any(e[0]=='stop' for e in sensor.events),'i2c','STOP after address NACK')
            events=list(csv.DictReader(io.StringIO(Path('events.csv').read_text())))
            request_positions=[i for i,e in enumerate(events) if e['kind']=='R']
            segment=events[request_positions[-1]+1:]
            actual=[[('led' if e['kind']=='G' else 'pwm'),int(e['value'])] for e in segment if e['kind'] in ('G','P')]
            checks.equal(actual,expected['actions'],'side_effects','passive AXI/device events; rejects have zero writes')
            for e in segment:
                if e['kind'] in ('G','P'):checks.equal(int(e['id']),row['id'],'request','actual action request id')
            # Count real PWM high samples across a full 100-clock period.
            await Timer(10,unit='ns');led=int(dut.gpio_led.value);duty=int(dut.pwm_duty.value);high=0
            for _ in range(100):
                await Timer(10,unit='ns');high+=int(dut.pwm_pin.value)
            checks.equal(high,duty,'pwm','actual PWM pin high cycles / 100')
            if status!='OK' and pins:
                checks.equal([led,duty],[pins[-1]['led'],pins[-1]['pwm_duty']],'side_effects','rejected request leaves output pins unchanged')
            if actual:
                for op,val in actual:
                    if op=='led':led_expected=val
                if any(a[0]=='led' for a in actual):checks.equal(led,led_expected,'gpio','actual LED pin')
                if any(a[0]=='pwm' for a in actual):checks.equal(duty,[a[1] for a in actual if a[0]=='pwm'][-1],'pwm','last PWM action on hardware pin')
            pins.append(dict(name=row['name'],id=row['id'],led=led,pwm_duty=duty,pwm_high=high))
            if row['name'].endswith('-recover'):checks.equal(status,'OK','recovery','valid request immediately after failure')
        await uart.send(b'END\n');checks.equal(await uart.line(),'DONE T20','completion','terminal completion text')
        await Timer(2000,unit='ns')
        checks.equal(int(dut.exit_code.value),0x2000,'completion','CPU exit code')
        checks.require(int(dut.completed.value)==1,'completion','CPU actually exited')
        checks.require(int(dut.retired.value)>1000,'execution','real instruction retirement')
        checks.require(int(dut.protocol_checks.value)>1000 and int(dut.axi_reads.value)>1000,'axi','real memory and passive protocol checks')
        checks.equal(int(dut.protection_error.value),0,'protection','stores only approved CPU and peripheral regions')
        events=list(csv.DictReader(io.StringIO(Path('events.csv').read_text())))
        led=0;duty=0;expected_edges=[];observed_edges=[]
        for event in events:
            if event['kind'] in ('G','P'):
                previous=[led,duty]
                if event['kind']=='G':led=int(event['value'])
                else:duty=int(event['value'])
                if [led,duty]!=previous:expected_edges.append([led,duty])
            elif event['kind']=='O':observed_edges.append([int(event['id']),int(event['value'])])
        checks.equal(observed_edges,expected_edges,'side_effects','every intermediate physical output transition in action order')
        checks.require(bool(check_pins('peripherals.vcd')),'pins','independent UART/I2C/GPIO/PWM VCD')
        result=dict(requests=len(responses),actions=sum(len(r['actions']) for r in responses),rejected=sum(r['validation']!='OK' for r in responses),
            cycles=int(dut.cycles.value),retired=int(dut.retired.value),axi_reads=int(dut.axi_reads.value),axi_writes=int(dut.axi_writes.value),scope='DESKTOP_MODEL_REPLAY_REAL_RV32_VIRTUAL_PIN_PERIPHERALS')
    except BaseException as e:
        if checks.first_failure is None:checks.first_failure=dict(category='test_exception',detail=repr(e))
        raise
    finally:
        for task in tasks:task.cancel()
        sequence=digest(dict(responses=responses,pins=pins,sensors=sensors,events=Path('events.csv').read_text() if Path('events.csv').exists() else ''))
        Path('observations.json').write_text(json.dumps(dict(responses=responses,pins=pins,sensors=sensors,summary=result),ensure_ascii=False,indent=2)+'\n')
        checks.save('checks.json',case_id=cfg['case_id'],run_id=cfg['run_id'],seed=cfg['seed'],profile=cfg['profile'],
            fixture_sha256=cfg['fixture_sha256'],golden_sha256=cfg['golden_sha256'],sequence_sha256=sequence,
            runtime=dict(prefix=sys.prefix,cocotb=cocotb.__version__,python=sys.version),result=result)
