"""Independent binary64-exp/FP32 and T05 group oracle against actual RTL."""
import hashlib,json,os,sys
from pathlib import Path
import numpy as np
import cocotb
from cocotb.triggers import Timer
from common.checks import Checks

def bits(x):return int(np.asarray(x,dtype=np.float32).view(np.uint32))

async def edge():await Timer(8,unit='ns')

@cocotb.test()
async def component(d):
    cfg=json.loads(Path(os.environ['NEXUSRV_CASE']).read_text());c=Checks();records=[];unit_records=[];digest=hashlib.sha256()
    try:
        c.equal(hashlib.sha256(Path(cfg['fixture']).read_bytes()).hexdigest(),cfg['fixture_sha256'],'identity','fixture')
        data=np.load(cfg['fixture']);lanes=cfg['lanes']
        await Timer(16,unit='ns');d.reset_n.value=1;await Timer(8,unit='ns')
        # Separate units include subnormal division and exp underflow boundaries.
        for i,(a,b,e,v) in enumerate(zip(data['unit_a'],data['unit_b'],data['unit_exp'],data['unit_div'])):
            d.unit_a.value=int(a);d.unit_b.value=int(b);d.unit_start.value=1;await edge();d.unit_start.value=0
            got_e=got_d=None;exp_latency=div_latency=None
            for unit_cycle in range(1,601):
                await edge()
                if int(d.exp_valid.value):got_e=int(d.exp_result.value);exp_latency=unit_cycle
                if int(d.div_valid.value):got_d=int(d.div_result.value);div_latency=unit_cycle
                if got_e is not None and got_d is not None:break
            c.equal(got_e,int(e),'exponential',str(i));c.equal(got_d,int(v),'division',str(i))
            unit_records.append(dict(exp=exp_latency,division=div_latency))
        for row,(g,u,y,q,s,n,mode,bad) in enumerate(zip(data['gate'],data['up'],data['fp'],data['q'],data['scale'],data['length'],data['mode'],data['bad'])):
            d.length.value=int(n);d.quantize_only.value=int(mode);d.start.value=1;await edge();d.start.value=0
            for offset in range(0,64,lanes):
                c.require(int(d.load_ready.value)==1,'input','group ready')
                d.gate_data.value=sum(int(g[offset+j])<<(32*j) for j in range(lanes))
                d.up_data.value=sum(int(u[offset+j])<<(32*j) for j in range(lanes))
                d.load_valid.value=1;await edge()
            d.load_valid.value=0
            for _ in range(1000):
                if int(d.valid.value):break
                await Timer(512,unit='ns')
            c.require(int(d.valid.value)==1,'completion',str(row));c.equal(int(d.error.value),int(bad),'finite',str(row))
            if not bad:
                c.equal(int(d.scale.value),int(s),'scale',str(row))
                for offset in range(0,64,4):
                    d.peek.value=offset;await Timer(1,unit='ns');actual=int(d.fp_data.value)
                    for j in range(4):c.equal((actual>>(32*j))&0xffffffff,int(y[offset+j]),'fp32',f'{row}/{offset+j}')
                for offset in range(0,64,16):
                    d.peek.value=offset;await Timer(1,unit='ns');actual=int(d.q_data.value)
                    for j in range(16):c.equal((actual>>(8*j))&255,int(q[offset+j])&255,'integer',f'{row}/{offset+j}')
                digest.update(int(d.scale.value).to_bytes(4,'little'));digest.update(y.tobytes());digest.update(q.tobytes())
            records.append(dict(row=row,cycles=int(d.cycles.value),length=int(n),mode=int(mode),bad=int(bad)))
            # Return to the same clock phase after combinational peeks.
            await Timer((8-int(cocotb.utils.get_sim_time(unit='ns'))%8)%8 or 8,unit='ns')
            d.ack.value=1;await edge();d.ack.value=0;await edge()
    except BaseException as e:
        if c.first_failure is None:c.first_failure={'category':'exception','detail':repr(e)}
        raise
    finally:
        Path('observations.json').write_text(json.dumps(dict(records=records,unit_latency=unit_records,sequence_sha256=digest.hexdigest()),indent=2)+'\n')
        c.save('checks.json',case_id=cfg['case_id'],fixture_sha256=cfg['fixture_sha256'],runtime=dict(prefix=sys.prefix,cocotb=cocotb.__version__))
