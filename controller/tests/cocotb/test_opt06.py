"""Actual UART pin replay; fixtures provide control IDs, never host model results."""
import json,os,sys,hashlib
from pathlib import Path
import cocotb
from cocotb.queue import Queue
from cocotb.triggers import Timer,with_timeout
from common.checks import Checks
from test_uart_boot import send
import random
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/'software/boot')]
from t25_stream import Stream,timing

@cocotb.test()
async def opt06_stream(dut):
    cfg=json.loads(Path(os.environ['NEXUSRV_CASE']).read_text());checks=Checks();rx=[];tx=[];tasks=[];requests=[]
    try:
        for k in ('fixture','golden'):checks.equal(hashlib.sha256(Path(cfg[k]).read_bytes()).hexdigest(),cfg[k+'_sha256'],'input_identity',k)
        golden=json.loads(Path(cfg['golden']).read_text())
        if cfg.get('negative')=='bad-golden':golden[0]['expected_text']='BAD'
        q=Queue();rng=random.Random(cfg['seed']^0x55)
        await Timer(20,unit='ns')
        async def monitor():
            count=0
            while True:
                await Timer(10000,unit='ns')
                available=int(dut.tx_count.value)
                while count<available:
                    value=int(dut.tx_bytes[count].value);cycle=int(dut.tx_cycles[count].value)
                    tx.append([cycle,value]);q.put_nowait(value);count+=1
        tasks=[cocotb.start_soon(monitor())]
        async def line():
            data=bytearray()
            while True:
                b=await q.get()
                if b==10:return data.decode('utf8')
                data.append(b)
                checks.require(len(data)<65536,'uart_bytes','bounded wire line')
        async def scenario():
            checks.equal(await line(),'OPT06 READY','completion','CPU startup')
            for i,g in enumerate(golden):
                await send(dut.host_rx,bytes([i]),cfg['uart_divisor'],rng)
                lines=[];s=Stream();t=None;result=None;prompt=None;legacy=None;ids=None
                while True:
                    value=await line();lines.append(value)
                    if value=='T25 READY' and result is not None:break
                    if value.startswith('T25 STREAM '):s.feed(value)
                    if value.startswith('T25 TIME '):t=timing(value)
                    if value.startswith('OPT06 RESULT '):result=[int(x,16) for x in value.split()[2:]]
                    if value.startswith('OPT06 PROMPT_ZERO '):
                        n,z=[int(x,16) for x in value.split()[2:]]
                        checks.equal(z,0,'tokenizer','all long-context prompt IDs are zero');prompt=[0]*n
                    if value.startswith('OPT06 PROMPT '):prompt=[int(x,16) for x in value.split()[2:]]
                    if value.startswith('T25 IDS '):ids=[int(x,16) for x in value.split()[2:]]
                checks.equal(result,[i,4 if g['error'] else 3,0 if g['error'] else g['stop'],len(g['expected_ids']),len(g['expected_prompt_ids'])],'state',g['name'])
                checks.equal(prompt,g['expected_prompt_ids'],'tokenizer',g['name'])
                checks.equal(len(prompt),result[4],'tokenizer','exact prompt length')
                if g['error']:
                    checks.require(s.aborted and not s.ended and ids is None,'recovery',g['name'])
                    checks.require('T25 ERROR %08x'%(g['error']&0xffffffff) in lines,'recovery','expected error')
                else:
                    checks.equal(ids,g['expected_ids'],'tokens',g['name'])
                    checks.require(t is not None,'timing','actual mcycle samples')
                    if g['enabled']:
                        checks.require(s.ended and not s.active,'state','preview closed')
                        checks.equal(s.text,g['expected_text'],'utf8',g['name'])
                        checks.equal(s.ids,g['expected_ids'],'tokens','preview token identity')
                    else:checks.require(not s.ids and not s.text,'state','legacy ablation has no preview')
                    # Raw compatibility TEXT can span lines; its boundary here is TIME.
                    a=next(j for j,x in enumerate(lines) if x.startswith('T25 TEXT '));b=next(j for j,x in enumerate(lines) if x.startswith('T25 TIME '))
                    legacy='\n'.join([lines[a][9:],*lines[a+1:b]])
                    checks.equal(legacy,g['expected_text'],'utf8','legacy/final decode')
                    checks.equal(len(t['tokens']),len(g['expected_ids']),'timing','every accepted token sampled')
                    checks.equal(t['first_text'] is None,not g['expected_text'],'timing','null has no visible text')
                    checks.require(t['decoder']>0 and (t['callback']>0)==bool(g['enabled']),'timing','measured overhead')
                    if g['name']=='split':checks.require(t['first_text']>t['first_token'],'timing','cross-token visible TTFT differs')
                requests.append(dict(name=g['name'],lines=lines,timing=t))
                checks.equal(int(dut.fault_code.value),0,'execution','no trap')
                checks.equal(int(dut.uart.overflow.value),0,'uart_framing','RX FIFO')
            await Timer(3000,unit='ns')
            checks.equal(int(dut.app_signature.value),0x600,'completion','actual CPU finished matrix')
        await with_timeout(scenario(),cfg['max_cycles']*10,'ns')
        dut.flush_trace.value=1;await Timer(50,unit='ns')
        writes=[int(x.split(',')[1]) for x in Path('uart-writes.csv').read_text().splitlines()]
        checks.equal(writes,[b for _,b in tx],'uart_bytes','every AXI UART write matches physical TX')
        checks.equal(int(dut.tx_framing_errors.value),0,'uart_framing','independent start/stop sampling of every TX pin frame')
        checks.equal(int(dut.tx_count.value),len(tx),'uart_bytes','every passive TX frame consumed')
        rx.extend([[int(dut.rx_cycles[i].value),int(dut.rx_bytes[i].value)] for i in range(int(dut.rx_count.value))])
        checks.equal([int(dut.rx_bytes[i].value) for i in range(int(dut.rx_count.value))],list(range(len(golden))),'uart_bytes','every external request observed on RX pin')
        checks.equal(int(dut.rx_framing_errors.value),0,'uart_framing','all RX frames')
        checks.require(int(dut.retired.value)>1000,'execution','real VexRiscv retirement')
    except BaseException as e:
        if checks.first_failure is None:checks.first_failure=dict(category='exception',detail=repr(e))
        raise
    finally:
        for task in tasks:task.cancel()
        sequence=hashlib.sha256(json.dumps(dict(rx=rx,tx=tx),sort_keys=True).encode()).hexdigest()
        Path('uart-trace.json').write_text(json.dumps(dict(rx=rx,tx=tx,requests=requests))+'\n')
        Path('observations.json').write_text(json.dumps(dict(sequence_sha256=sequence,cycles=int(dut.cycles.value),retired=int(dut.retired.value),requests=len(requests),scope=cfg['scope']))+'\n')
        checks.save('checks.json',case_id=cfg['case_id'],run_id=cfg['run_id'],seed=cfg['seed'],profile=cfg['profile'],fixture_sha256=cfg['fixture_sha256'],golden_sha256=cfg['golden_sha256'],sequence_sha256=sequence,runtime=dict(python=sys.version,prefix=sys.prefix,cocotb=cocotb.__version__))
