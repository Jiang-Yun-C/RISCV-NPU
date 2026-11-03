"""Passive AXI/retirement reconstruction, independent of UART driver and ROM."""
import csv
from collections import deque
from pathlib import Path

BASE=0xb4000000
LIMIT=0xb7ff0000

def observe(path,checks):
    addresses,writes,reads,ireads=deque(),deque(),deque(),deque()
    pending=0;loaded=[];signatures=[];data_signatures=[];retires=[];fences=[];refills=[];rx=[];tx=[];sources=[]
    with Path(path).open() as stream:
        for row in csv.DictReader(stream):
            cycle,a,b,c=(int(row[x]) for x in ('cycle','a','b','c'));kind=row['kind']
            if kind=='DA':
                checks.require(b==0 and c<=2,'axi_request','CPU write shape')
                addresses.append((a,c))
            elif kind=='DW':writes.append((a,b,c,cycle))
            elif kind=='DB':
                checks.require(pending>0 and a==0,'axi_response','write response for accepted AW/W');pending-=1
            elif kind in ('DR','IA'):
                checks.require(c<=2 and a//4096==(a+(b+1)*(1<<c)-1)//4096,'axi_request','read shape')
                (reads if kind=='DR' else ireads).append([a,b+1,c,0])
                if kind=='IA':refills.append((cycle,a,b))
            elif kind in ('DD','IR'):
                q=reads if kind=='DD' else ireads
                checks.require(bool(q),'axi_response','R has AR')
                address,beats,size,beat=q[0]
                checks.equal(b,0,'axi_response','successful bus response')
                checks.equal(c,int(beat==beats-1),'axi_response','RLAST')
                if kind=='DD' and address==0x10000008:rx.append((cycle,a&255))
                q[0][3]+=1
                if c:q.popleft()
            elif kind=='T':
                if BASE<=a<BASE+65536:retires.append((cycle,a,b))
                else:fences.append((cycle,a,b))
            else:checks.require(False,'axi_request','unknown trace event')
            while addresses and writes:
                address,size=addresses.popleft();data,strobe,last,cy=writes.popleft();pending+=1
                checks.equal(last,1,'axi_write','WLAST')
                checks.require(strobe>0 and strobe&~(((1<<(1<<size))-1)<<(address%4))==0,'axi_write','byte lanes')
                checks.require(0x20000<=address<0x30000 or BASE<=address<LIMIT or 0x10000000<=address<0x10000100,
                               'protection','ROM, stack guard and unrelated regions protected')
                if BASE<=address<LIMIT:
                    for lane in range(4):
                        if strobe&(1<<lane):loaded.append((cy,(address&~3)+lane,(data>>(lane*8))&255))
                elif address==0x10000024:signatures.append((cy,data))
                elif address==0x10000028:data_signatures.append((cy,data))
                elif address==0x10000000:tx.append((cy,data&255))
                elif address==0x10000030:sources.append((cy,data))
    checks.require(not addresses and not writes and pending==0,'axi_response','all accepted writes drained')
    return dict(loaded=loaded,signatures=signatures,data_signatures=data_signatures,retires=retires,
                fences=fences,refills=refills,rx=rx,tx=tx,sources=sources)

def revalidate(directory,fixture,golden,cfg):
    """Re-score raw inputs/observations when accepting an archived run."""
    import json
    from common.checks import Checks,digest
    d=Path(directory);checks=Checks();raw=observe(d/'transactions.csv',checks)
    saved=json.loads((d/'observations.json').read_text());trace=json.loads((d/'uart-trace.json').read_text())
    checks.equal(json.loads(json.dumps(raw)),saved['observation'],'archive','raw bus and saved observations')
    checks.equal(Path(d/'initial-app.bin').read_bytes(),bytes.fromhex(golden['initial_hex']),'initial_memory','unloaded initial state')
    checks.equal(Path(d/'final-app.bin').read_bytes(),bytes.fromhex(golden['final_hex']),'loading','final image')
    checks.equal([v for _,v in raw['signatures']],golden['signatures'],'signature','executed signatures')
    checks.equal([v for _,v in raw['data_signatures']],golden['signatures'],'cache','data signatures')
    checks.equal([v for _,v in raw['rx']],[v for _,v in trace['rx']],'uart_bytes','RX FIFO and actual pins')
    checks.equal([v for _,v in raw['tx']],[v for _,v in trace['tx']],'uart_bytes','TX CPU and actual pins')
    checks.equal([v for _,v in trace['rx']],list(b''.join(bytes.fromhex(a['wire_hex']) for a in fixture['actions'])),
                 'uart_bytes','all original input bytes')
    checks.equal([v for _,v in raw['sources']],[int(cfg['test_mode']=='PRELOAD')],'source','explicit mode')
    checks.equal(trace['actions'],saved['actions'],'archive','two independent action records')
    actions=trace['actions'];checks.equal(len(actions),len(fixture['actions']),'protocol','mandatory packet cases')
    for i,(actual,expected) in enumerate(zip(actions,fixture['actions'])):
        for key in ('name','ack','writes','run'):checks.equal(actual[key],expected.get(key),'protocol','action '+key)
        checks.equal(actual['index'],i,'protocol','ordered action')
        checks.require(actual['start']<actual['end_send']<actual['end'],'protocol','bounded action timestamps')
        if i:checks.equal(actual['start'],actions[i-1]['end'],'protocol','no hidden action gap')
        writes=[(a,v) for cy,a,v in raw['loaded'] if actual['start']<=cy<actual['end']]
        checks.equal(writes,[tuple(x) for x in expected['writes']],'loading','exact accepted writes '+actual['name'])
        if actual['run']:
            image=bytes.fromhex(golden['images'][actual['run']]['hex'])
            retire=[(cy,pc,insn) for cy,pc,insn in raw['retires'] if actual['start']<=cy<actual['end']]
            checks.require(len(retire)>30,'execution','nonzero real application execution')
            for cy,pc,insn in retire:
                checks.equal(insn,int.from_bytes(image[pc-BASE:pc-BASE+4],'little'),'cache','current image instruction')
            for insn in (0x100f,0x500f):
                checks.require(any(actual['start']<=cy<retire[0][0] and v==insn for cy,_,v in raw['fences']),
                               'visibility','I/D maintenance before branch')
            checks.require(any(actual['start']<=cy<actual['end'] and a==BASE and n==7 for cy,a,n in raw['refills']),
                           'cache','new I cache refill')
        else:checks.require(not any(actual['start']<=cy<actual['end'] for cy,_,_ in raw['retires']),'rejection','no early jump')
    for cy,_,_ in raw['retires']:
        checks.require((cfg['test_mode']=='PRELOAD' and cy<actions[0]['start']) or
                       any(a['run'] and a['start']<=cy<a['end'] for a in actions),'rejection','only accepted RUN executes')
    checks.equal(sum(len(a['writes']) for a in actions),len(raw['loaded']),'loading','no extra memory writes')
    report=json.loads((d/'checks.json').read_text())
    checks.equal(digest([trace['rx'],trace['tx'],actions,raw]),report['sequence_sha256'],'archive','recomputed complete sequence')
    return dict(status='PASS',checks=sum(checks.counts.values()),packet_cases=len(actions))
