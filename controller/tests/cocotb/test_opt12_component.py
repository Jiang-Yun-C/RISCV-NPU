import hashlib,json,os,sys
from pathlib import Path
import numpy as np
import cocotb
from cocotb.triggers import Timer
from common.checks import Checks

async def edge():await Timer(8,unit='ns')

@cocotb.test()
async def component(d):
    cfg=json.loads(Path(os.environ['NEXUSRV_CASE']).read_text());c=Checks();records=[];digest=hashlib.sha256()
    try:
        c.equal(hashlib.sha256(Path(cfg['fixture']).read_bytes()).hexdigest(),cfg['fixture_sha256'],'identity','fixture')
        data=np.load(cfg['fixture']);lanes=cfg['lanes']
        await Timer(16,unit='ns');d.reset_n.value=1;await edge()
        for i,(a,b) in enumerate(zip(data['unit_a'],data['unit_sqrt'])):
            d.unit_a.value=int(a);d.unit_start.value=1;await edge();d.unit_start.value=0
            for _ in range(64):
                await edge()
                if int(d.sqrt_valid.value):break
            c.require(int(d.sqrt_valid.value)==1,'sqrt','bounded completion')
            c.equal(int(d.sqrt_result.value),int(b),'sqrt',str(i))
        for row in range(len(data['length'])):
            n=int(data['length'][row]);mode=int(data['mode'][row]);q=int(data['quant'][row]);bad=int(data['bad'][row])
            d.length.value=n;d.mode.value=mode;d.quantize_result.value=q;d.scalar.value=int(data['factor'][row]);d.pad_full.value=int(data['full'][row]);d.start.value=1
            await edge();d.start.value=0
            for off in range(0,64,lanes):
                c.require(int(d.load_ready.value)==1,'input','ready')
                d.gate_data.value=sum(int(data['gate'][row,off+j])<<(32*j) for j in range(lanes))
                d.up_data.value=sum(int(data['up'][row,off+j])<<(32*j) for j in range(lanes))
                d.load_valid.value=1;await edge()
            d.load_valid.value=0
            for _ in range(1000):
                if int(d.valid.value):break
                await Timer(512,unit='ns')
            c.require(int(d.valid.value)==1,'completion',str(row));c.equal(int(d.error.value),bad,'numeric',str(row))
            if not bad:
                c.equal(int(d.scale.value),int(data['scale'][row]),'scale',str(row))
                for j in range(1 if mode in (5,6,7,9) else 64):
                    d.peek.value=j;await edge();actual=int(d.fp_data.value)&0xffffffff
                    expected=int(data['fp'][row,j]);c.equal(actual,expected,'fp32',f'{row}/{j}/mode{mode}')
                    digest.update(actual.to_bytes(4,'little'))
                if q:
                    for off in range(0,64,16):
                        d.peek.value=off;await edge();actual=int(d.q_data.value)
                        for j in range(16):c.equal((actual>>(8*j))&255,int(data['q'][row,off+j])&255,'integer',f'{row}/{off+j}')
            records.append(dict(row=row,mode=mode,length=n,quant=q,bad=bad,cycles=int(d.cycles.value)))
            d.ack.value=1;await edge();d.ack.value=0;await edge()
    except BaseException as e:
        if c.first_failure is None:c.first_failure={'category':'exception','detail':repr(e)}
        raise
    finally:
        Path('observations.json').write_text(json.dumps(dict(records=records,sequence_sha256=digest.hexdigest()),indent=2)+'\n')
        c.save('checks.json',case_id=cfg['case_id'],fixture_sha256=cfg['fixture_sha256'],runtime=dict(prefix=sys.prefix,cocotb=cocotb.__version__))
