"""Full real RV32 graph; independently observed committed logits and KV."""
import hashlib,json,os
from pathlib import Path
import numpy as np
import cocotb
from cocotb.triggers import Timer
from common.checks import Checks
from common.final_drain import terminal_writes_drained

@cocotb.test()
async def opt10_r1(dut):
    cfg=json.loads(Path(os.environ['NEXUSRV_CASE']).read_text());c=Checks();result={}
    try:
        for name in ('fixture','golden'):
            c.equal(hashlib.sha256(Path(cfg[name]).read_bytes()).hexdigest(),cfg[name+'_sha256'],'identity',name)
        while not int(dut.completed.value) and not int(dut.timed_out.value):await Timer(100000,unit='ns')
        c.require(bool(int(dut.completed.value)),'completion','complete actual graph')
        c.equal(int(dut.exit_code.value),0,'completion','CPU exit')
        c.require(await terminal_writes_drained(dut),'drain','all accepted terminal CPU writes retired before observation closes')
        accepted=int(dut.cpu_write_accepts.value);responses=int(dut.cpu_write_responses.value)
        c.require(accepted>0 and accepted==responses,'drain','CPU write acceptance and B retirement counts equal')
        await Timer(32,unit='ns')
        c.equal(int(dut.cpu_write_accepts.value),accepted,'drain','no new writes during stable terminal interval')
        c.equal(int(dut.cpu_write_responses.value),responses,'drain','no delayed B during stable terminal interval')
        c.equal(int(dut.backend_idle.value),1,'drain','native backend remains idle')
        c.equal(int(dut.timed_out.value),0,'drain','terminal stable retirement precedes frozen deadline')
        terminal_drain=dict(accepted=accepted,responses=responses,stable=True,stable_interval_ns=32,cycle=int(dut.cycles.value))
        reports={}
        for line in Path('cpu-output.txt').read_text().splitlines():
            g,i,v=map(int,line.split());c.require((g,i) not in reports,'report','unique');reports[g,i]=v
        c.require(not any(g==255 for g,i in reports),'execution','no trap')
        u64=lambda g,i:reports[g,i]|reports[g,i+1]<<32
        for i in range(3):c.equal(reports.get((1,i)),0,'setup',str(i))
        for i in (0,4,5,10):c.equal(reports.get((2,i)),0,'graph','rc / IDLE / owner / fallback')
        c.equal(reports.get((2,6)),1,'KV','actual committed length')
        for i in (8,9):c.equal(reports.get((2,i)),169,'graph','all169 projections on hardware')
        expected=[169,169,218,449920*4,6144*4,203648*4,0,49*896*4,182144,11384,0]
        for i,want in enumerate(expected):c.equal(u64(3,i*2),want,'workload',str(i))
        c.equal(int(dut.owner.value),0,'owner','hardware released')
        c.equal(int(dut.backend_idle.value),1,'drain','all native work retired')
        c.equal(int(dut.ddr_fault.value),0,'fault','no quarantine')
        c.equal(reports.get((6,0)),0,'stack','complete8KiB guard intact')
        c.require(0<reports.get((6,1),0)<=57344,'stack','actual graph watermark budget')
        addresses=[(reports[2,7],151936)]
        c.require(0xac000000<=reports[2,7] and reports[2,7]+151936*4<=0xac000000+835072,'bounds','logits inside owned workspace')
        for l in range(24):
            for v in range(2):
                addr=reports[4,l*2+v]
                c.equal(addr,0xa8000000+v*7864320+l*327680,'KV','actual bounded layer view')
                addresses.append((addr,128))
        values=[]
        # The graph already returned and the native adapter is idle. This is
        # passive inspection of its committed memory, outside the API timer.
        for address,n in addresses:
            for i in range(n):
                dut.peek_address.value=address+i*4
                await Timer(2,unit='ns')
                values.append(int(dut.peek_value.value))
        actual=np.asarray(values,dtype='<u4').view('<f4');actual.tofile('snapshot.bin')
        want=np.fromfile(cfg['golden'],dtype='<f4');c.equal(actual.size,158080,'numeric','complete logits and all24layer KV')
        thresholds=json.loads(Path(cfg['thresholds']).read_text())['cumulative'];numeric={}
        for label,a,b,key in [('logits',0,151936,'logits_24_layers'),('KV',151936,158080,'kv')]:
            t=thresholds[key];av=actual[a:b];ev=want[a:b];err=np.abs(av.astype('f8')-ev.astype('f8'))
            for i in range(len(av)):c.require(np.isfinite(av[i]) and err[i]<=t['atol']+t['rtol']*abs(float(ev[i])),'numeric',dict(kind=label,index=i,error=float(err[i])))
            nrmse=float(np.sqrt(np.mean(err**2))/max(np.sqrt(np.mean(ev.astype('f8')**2)),1e-12));c.require(nrmse<=t['nrmse'],'numeric',label+' NRMSE')
            numeric[label]=dict(elements=b-a,max_abs=float(err.max()),nrmse=nrmse)
        order=np.argsort(-want[:151936],kind='stable');margin=float(want[order[0]]-want[order[1]])
        if margin>2*numeric['logits']['max_abs']:c.equal(reports[2,3],int(order[0]),'greedy','stable reference margin')
        c.equal(reports[2,3],int(np.argmax(actual[:151936])),'greedy','actual logits lowest-ID argmax')
        phases={n:dict(cycles=u64(5,i*4),calls=u64(5,i*4+2)) for i,n in enumerate(('embedding','norm','linear','rope','attention','swiglu','residual','head'))}
        for n,count in dict(embedding=1,norm=49,linear=168,rope=48,attention=24,swiglu=24,residual=48,head=1).items():c.equal(phases[n]['calls'],count,'phase',n)
        api=u64(2,1);c.require(api>0 and sum(p['cycles'] for p in phases.values())<=api,'timing','actual disjoint operator phases')
        expected_reports={(1,i) for i in range(3)}|{(2,i) for i in range(11)}|{(3,i) for i in range(26)}|{(4,i) for i in range(48)}|{(5,i) for i in range(32)}|{(6,i) for i in range(3)}
        c.equal(sorted(reports),sorted(expected_reports),'report','exact complete metadata set')
        result=dict(terminal_drain=terminal_drain,api_cycles=api,nominal_125mhz_seconds=api/125000000,phases=phases,greedy_and_unprofiled_cycles=api-sum(p['cycles'] for p in phases.values()),numeric=numeric,next=reports[2,3],reference_next=int(order[0]),reference_margin=margin,actual_stack_watermark_bytes=reports[6,1],guard_bad_words=reports[6,0],linear_backend_cycles=u64(3,22),sfu_backend_cycles=u64(3,24),scope='ACTUAL_FULL169_ONE_CONTEXT_POSTLOAD_GRAPH_NOT_BOARD_TEXT_TTFT_OR_CALIBRATED_MODEL',frequency_signoff_hz=None)
    except BaseException as error:
        if c.first_failure is None:c.first_failure={'category':'test_exception','detail':repr(error)}
        raise
    finally:
        Path('observations.json').write_text(json.dumps(result,indent=2)+'\n')
        c.save('checks.json',**{k:cfg[k] for k in ('case_id','run_id','seed','fixture_sha256')})
