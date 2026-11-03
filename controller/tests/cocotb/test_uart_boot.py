"""Pin-only host download, passive UART observation and independent bus scoring."""
import json
import os
import random
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'software/boot'),str(ROOT/'tests/boot/uart')]

import cocotb
from cocotb.queue import Queue
from cocotb.triggers import Timer, with_timeout
from cocotb.utils import get_sim_time
from common.checks import Checks,digest
from evidence import sha256
from uart_protocol import response
from scoreboard import observe

def cycle():return int(get_sim_time(unit='ns'))//10

async def pin_monitor(pin,divisor,records,checks,queue=None):
    # The locked VCS/VPI runtime suppresses VCD events while a FallingEdge
    # callback on a driven reg is disarmed. Quarter-bit sampling observes the
    # actual pin independently and keeps every waveform transition available.
    checks.require(divisor>=4 and divisor%4==0,'uart_framing','sampling divisor')
    while True:
        while int(pin.value):await Timer(divisor*10//4,unit='ns')
        start=cycle()
        await Timer(divisor*5,unit='ns')
        checks.equal(int(pin.value),0,'uart_framing','start bit')
        value=0
        for bit in range(8):
            await Timer(divisor*10,unit='ns')
            value|=int(pin.value)<<bit
        await Timer(divisor*10,unit='ns')
        checks.equal(int(pin.value),1,'uart_framing','stop bit')
        records.append([start,value])
        if queue is not None:queue.put_nowait(value)
        await Timer(divisor*10//4,unit='ns')

async def send(pin,wire,divisor,rng):
    for byte in wire:
        await Timer((rng.randrange(13)+1)*10,unit='ns')
        for bit in [0,*[(byte>>i)&1 for i in range(8)],1]:
            pin.value=bit
            await Timer(divisor*10,unit='ns')

async def take(queue,n):return bytes([await queue.get() for _ in range(n)])

@cocotb.test()
async def uart_boot(dut):
    cfg=json.loads(Path(os.environ['NEXUSRV_CASE']).read_text());checks=Checks()
    rx=[];tx=[];actions=[];tasks=[];result={};observation={}
    fixture=json.loads(Path(cfg['fixture']).read_text());golden=json.loads(Path(cfg['golden']).read_text())
    try:
        checks.equal(sha256(cfg['fixture']),cfg['fixture_sha256'],'input_identity','fixture')
        checks.equal(sha256(cfg['golden']),cfg['golden_sha256'],'input_identity','golden')
        await Timer(20,unit='ns')
        checks.equal(Path('initial-app.bin').read_bytes(),bytes.fromhex(golden['initial_hex']),
                     'initial_memory','application initial state and no hidden preload')
        queue=Queue();rng=random.Random(cfg['seed']^0x55)
        dut.host_rx.value=1
        tasks=[cocotb.start_soon(pin_monitor(dut.uart_rx,cfg['uart_divisor'],rx,checks)),
               cocotb.start_soon(pin_monitor(dut.uart_tx,cfg['uart_divisor'],tx,checks,queue))]
        async def scenario():
            checks.equal(await take(queue,len(golden['boot_text'])),golden['boot_text'].encode(),
                         'source','explicit boot mode on TX pins')
            for index,action in enumerate(fixture['actions']):
                start=cycle();wire=bytes.fromhex(action['wire_hex'])
                await send(dut.host_rx,wire,cfg['uart_divisor'],rng)
                end_send=cycle()
                ack=await take(queue,20)
                actual=response(ack)
                checks.equal(list(actual),action['ack'],'protocol',action['name'])
                if action.get('text'):
                    text=action['text'].encode()
                    checks.equal(await take(queue,len(text)),text,'signature','application emits PASS and returns')
                await Timer(1000,unit='ns')
                actions.append(dict(index=index,name=action['name'],start=start,end=cycle(),end_send=end_send,
                                    ack=list(actual),writes=action['writes'],run=action.get('run')))
                checks.equal(int(dut.fault_code.value),0,'execution','no unexpected CPU trap')
                checks.equal(int(dut.uart.overflow.value),0,'uart_framing','no RX FIFO overflow')
                checks.equal(int(dut.uart.framing_error.value),0,'uart_framing','no receiver framing error')
        await with_timeout(scenario(),cfg['max_cycles']*10,'ns')
        dut.capture.value=1
        await Timer(100,unit='ns')
        checks.equal(int(dut.captured.value),1,'completion','capture complete')
        observation=observe('transactions.csv',checks)
        checks.equal([v for _,v in observation['rx']],[v for _,v in rx],'uart_bytes','RTL RX FIFO matches passive pin bytes')
        checks.equal([v for _,v in observation['tx']],[v for _,v in tx],'uart_bytes','CPU TX writes match wire frames')
        checks.equal([v for _,v in rx],list(b''.join(bytes.fromhex(a['wire_hex']) for a in fixture['actions'])),
                     'uart_bytes','all external packet bytes independently received')
        checks.equal([v for _,v in observation['sources']],[1 if cfg['profile']=='preload' else 0],
                     'source','firmware logs loading source')
        for action in actions:
            actual=[(a,v) for cy,a,v in observation['loaded'] if action['start']<=cy<action['end']]
            expected=[tuple(x) for x in action['writes']]
            checks.equal(actual,expected,'loading',action['name']+' exact accepted bytes and addresses')
            if not action['run']:
                checks.require(not any(action['start']<=cy<action['end'] for cy,_,_ in observation['retires']),
                               'rejection','no execution before successful RUN '+action['name'])
        expected_signatures=list(golden['signatures'])
        if cfg.get('negative')=='bad-golden':expected_signatures[-1]^=1
        checks.equal([v for _,v in observation['signatures']],expected_signatures,'signature','executed images A then B')
        checks.equal([v for _,v in observation['data_signatures']],golden['signatures'],'cache','new data signature is visible')
        checks.equal(Path('final-app.bin').read_bytes(),bytes.fromhex(golden['final_hex']),'loading','final RAM image')
        for action in actions:
            if not action['run']:continue
            image=bytes.fromhex(golden['images'][action['run']]['hex'])
            ret=[(cy,pc,insn) for cy,pc,insn in observation['retires'] if action['start']<=cy<action['end']]
            checks.require(len(ret)>30,'execution','actual application retirement '+action['run'])
            for cy,pc,insn in ret:
                checks.equal(insn,int.from_bytes(image[pc-0xb4000000:pc-0xb4000000+4],'little'),
                             'cache','retired instruction comes from current downloaded image')
            checks.require(any(action['start']<=cy<ret[0][0] and insn==0x100f for cy,_,insn in observation['fences']),
                           'visibility','FENCE.I before current application')
            checks.require(any(action['start']<=cy<ret[0][0] and insn==0x500f for cy,_,insn in observation['fences']),
                           'visibility','D invalidate before current application')
            checks.require(any(action['start']<=cy<action['end'] and a==0xb4000000 and n==7
                               for cy,a,n in observation['refills']),'cache','new I cache refill after reloading')
        checks.require(int(dut.retired.value)>1000,'execution','real CPU execution')
        checks.equal(int(dut.timed_out.value),0,'completion','within bounded simulation cycles')
        result=dict(cycles=cycle(),retired=int(dut.retired.value),rx_bytes=len(rx),tx_bytes=len(tx),
                    loaded_bytes=len(observation['loaded']),signatures=golden['signatures'],mode=cfg['test_mode'],
                    packet_cases=len(actions))
    except BaseException as error:
        if checks.first_failure is None:checks.first_failure={'category':'completion' if 'Timeout' in type(error).__name__ else 'test_exception','detail':repr(error)}
        raise
    finally:
        for task in tasks:task.cancel()
        Path('uart-trace.json').write_text(json.dumps(dict(rx=rx,tx=tx,actions=actions))+'\n')
        Path('observations.json').write_text(json.dumps(dict(summary=result,actions=actions,observation=observation))+'\n')
        checks.save('checks.json',case_id=cfg['case_id'],run_id=cfg['run_id'],seed=cfg['seed'],profile=cfg['profile'],
                    fixture_sha256=cfg['fixture_sha256'],golden_sha256=cfg['golden_sha256'],result=result,
                    sequence_sha256=digest([rx,tx,actions,observation]),
                    runtime=dict(python=sys.version,executable=sys.executable,prefix=sys.prefix,cocotb=cocotb.__version__))
