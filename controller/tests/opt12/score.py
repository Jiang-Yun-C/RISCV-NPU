"""Replay real CPU and CE bus handshakes into independent paged memory."""
import csv,hashlib,json
from collections import deque,Counter
from pathlib import Path
import numpy as np

def hash_bytes(x):
    h=2166136261
    for b in x:h=((h^b)*16777619)&0xffffffff
    return h

def score(directory,fixture,c,negative=None):
    d=Path(directory);pages={}
    def put(a,v):pages.setdefault(a>>12,bytearray(4096))[a&4095]=v
    def byte(a):return pages.get(a>>12,bytearray(4096))[a&4095]
    def read(a,n):return bytes(byte(a+i) for i in range(n))
    for region in fixture['regions']:
        p=Path(region['path']);c.equal(hashlib.sha256(p.read_bytes()).hexdigest(),region['sha256'],'identity',region['name'])
        for i,v in enumerate(p.read_bytes()):put(region['address']+i,v)
    reports={}
    for line in (d/'cpu-output.txt').read_text().splitlines():
        g,i,v=map(int,line.split());c.require((g,i) not in reports,'report','no duplicate');reports[g,i]=v
    def expect(g,i,v,cat='completion',detail=''):c.equal(reports.get((g,i)),v&0xffffffff,cat,f'{g}/{i}')
    expect(1,0,0);expect(1,1,-1,'reject');expect(1,2,-1,'reject');expect(1,3,0,'sequence');expect(1,4,-4,'reject');expect(1,5,0,'atomic');expect(2,0,0);expect(2,1,0)
    c.require(not any(g==255 for g,i in reports),'execution','no CPU trap')
    pending_r=deque();aws=deque();ws=deque();bs=deque();length=0;outstanding=0
    commands=[];command={};backend_counts=Counter();cpu_bytes=Counter();writes=[];active=-1;current_job=-1
    releases=0;kernel_job=None;tag=0;cpu_read_address=0;cpu_read_size=0;cpu_read_beats=0;traffic=Counter()
    for row in csv.reader((d/'transactions.csv').open()):
        cycle=int(row[0]);kind=row[1];a,v,e=(int(x,16) for x in row[2:5]);owner=int(row[5])
        if kind=='CW':
            if a==0x10000080:tag=v
            if a==0x10000084:
                if tag&65535==20:kernel_job=(tag>>16)-10
                if tag&65535==21:kernel_job=None
            if 0x80000000<=a<0xa8000000:c.require(False,'protection','CPU store into model')
            if (0xac000000<=a<0xb4000000) or (0xba000000<=a<0xbc000000):
                c.equal(owner,0,'ownership','CPU shared store after release')
                for j in range(4):
                    if e>>j&1:put((a&~3)+j,(v>>(8*j))&255);cpu_bytes['write']+=1
            if 0x10003200<=a<0x10003280:command[(a-0x10003200)//4]=v
            if a==0x10003020 and v:
                c.equal(len(command),32,'submission','immutable complete descriptor');c.equal(owner,1,'ownership','owner on doorbell');c.equal(outstanding,0,'drain','no prior in-flight bus traffic')
                commands.append(dict(command));active+=1;command={}
            if a==0x10000100 and v==0:
                c.equal(outstanding,0,'drain','all accepted transactions drained before release');releases+=1
        elif kind=='CR':cpu_read_address=a;cpu_read_size=e;cpu_read_beats=v+1
        elif kind=='CD':
            if kernel_job is not None and cpu_read_beats:
                j=fixture['jobs'][kernel_job]
                for name,size in [('gate',j['k']*4),('up',j['k']*4),('fp32',j['k']*4),('aq',((j['k']+63)//64)*64),('sa',((j['k']+63)//64)*4)]:
                    if j[name] and j[name]<=cpu_read_address<j[name]+size:traffic[kernel_job,name,'read']+=1<<cpu_read_size
            cpu_read_beats-=1;cpu_read_address+=1<<cpu_read_size
        elif kind=='NA':
            c.equal(owner,1,'ownership','CE write owner');aws.append((a,v,e));outstanding+=1
        elif kind=='NW':ws.append((v,e,cycle))
        elif kind=='NB':
            c.require(bool(bs),'protocol','B paired with AW/W');address,ident=bs.popleft();c.equal(v,ident,'protocol','B ID');outstanding-=1
        elif kind=='NL':length=e
        elif kind=='NR':
            c.equal(owner,1,'ownership','CE read owner');c.require(a>>12==(a+((length+1)<<e)-1)>>12,'boundary','no 4KiB crossing');c.require(length<=31,'boundary','maximum 32 beats')
            pending_r.extend((a+(i<<e),v,e,i==length) for i in range(length+1));outstanding+=1
        elif kind=='ND':
            c.require(bool(pending_r),'protocol','R paired with AR');addr,ident,size,last=pending_r.popleft();c.equal(a,ident,'protocol','R ID');outstanding-=int(last)
            backend_counts[active,'read']+=1<<size
            if e==0:
                aligned=addr&~15;expected=int.from_bytes(bytes(byte(aligned+j) if addr<=aligned+j<addr+(1<<size) else 0 for j in range(16)),'little')
                c.equal(v,expected,'read_data','actual gate/up/Aq/Sa/model read')
        elif kind=='EARLY':c.require(False,'drain','owner released while backend active')
        while aws and ws:
            addr,ident,size=aws.popleft();value,mask,tick=ws.popleft();c.require(mask!=0,'protocol','nonempty W')
            for j in range(16):
                if mask>>j&1:put((addr&~15)+j,(value>>(8*j))&255);backend_counts[active,'write']+=1
            writes.append((active,addr,mask));bs.append((addr,ident))
    c.equal(outstanding,0,'drain','final outstanding');c.require(not aws and not ws and not bs and not pending_r,'protocol','all queues empty')
    c.require(releases>0,'ownership','actual releases')
    command_index=0;results=[];previous_valid=False
    c.equal(hashlib.sha256(Path(fixture['t05_input']).read_bytes()).hexdigest(),fixture['t05_input_sha256'],'identity','T05 block')
    for i,j in enumerate(fixture['jobs']):
        group=10+i;status=j['status'];expect(group,0,status);expect(group,1,int(not status))
        c.require(reports.get((group,2),0)>0,'cycles','actual CPU API')
        if j['hardware']:
            cmd=commands[command_index];command_index+=1
            for field,val in {14:3,15:1,16:1,17:j['k'],18:j['gate'],19:j['fp32'],20:j['up'],22:j['aq'],23:j['sa'],24:j['mode'],25:j['quant'],26:j['scalar']}.items():c.equal(cmd[field],val,'submission',str(field))
        if not status:
            p=Path(j['expected']);c.equal(hashlib.sha256(p.read_bytes()).hexdigest(),j['expected_sha256'],'identity',j['name'])
            data=np.load(p)
            expect(group,15,0,'view')
            if previous_valid:expect(group,16,-10,'view','old sequence invalid')
            previous_valid=True
            for key,addr,report_id in [('fp',j['fp32'],9),('aq',j['aq'],7),('sa',j['sa'],8)]:
                if not addr:continue
                expected=data[key].tobytes()
                if negative=='bad-golden' and i==0 and key=='fp':expected=bytes([expected[0]^1])+expected[1:]
                c.equal(read(addr,len(expected)),expected,'numeric',j['name']+'/'+key)
                expect(group,report_id,hash_bytes(expected),'cpu-observed')
            if j['hardware']:
                reads=j['k']*4*(3 if j['mode']==7 else 2 if j['up'] else 1)
                writes=(len(data['fp'].tobytes()) if j['fp32'] else 0)+(len(data['aq'])+len(data['sa'])*4 if j['aq'] else 0)
                expect(group,4,reads,'payload');expect(group,5,writes,'payload')
            if j['down']:
                cmd=commands[command_index];command_index+=1
                for field,val in {14:2,22:j['aq'],23:j['sa']}.items():c.equal(cmd[field],val,'resident-consumer',str(field))
                dy=data['down'].tobytes();c.equal(read(j['y'],len(dy)),dy,'down',j['name'])
                expect(group,10,0);expect(group,13,hash_bytes(dy));expect(group,14,-10,'view')
        else:
            previous_valid=False;expect(group,15,0,'atomic');expect(group,16,0,'recovery')
            if status==-9:
                if j['fp32']:c.equal(read(j['fp32'],j['k']*4),bytes(j['k']*4),'atomic','bad group unpublished')
                if j['aq']:c.equal(read(j['aq'],64),bytes(64),'atomic','bad Aq unpublished')
        results.append(dict(name=j['name'],mode=j['mode'],k=j['k'],hardware=j['hardware'],quant=j['quant'],status=status,cpu_cycles=reports[group,2],backend_cycles=reports[group,3],read_bytes=reports[group,4],write_bytes=reports[group,5],down_cpu_cycles=reports.get((group,11)),down_cycles=reports.get((group,12))))
    c.equal(command_index,len(commands),'submission','exact command count')
    phases=[];native_traffic=Counter()
    for row in csv.reader((d/'vector.csv').open()):
        if row[0] in ('NREAD','NWRITE'):native_traffic[(int(row[1])-10,row[0])]+=int(row[2]);continue
        if row[0]!='COMPLETE':continue
        cycle,launch,status,ticks,loads,computes,writes,rbytes,wbytes,mt,ml,mc,mw,mr,mb=map(int,row[1:])
        for a,b in ((ticks,mt),(loads,ml),(computes,mc),(writes,mw)):c.equal(a,b,'phase','passive state residency')
        if status==0:c.equal(rbytes,mr,'payload','actual R bytes');c.equal(wbytes,mb,'payload','actual W bytes')
        phases.append(dict(launch=launch,status=status,cycles=ticks,load=loads,compute=computes,write=writes,read_bytes=rbytes,write_bytes=wbytes))
    c.require(len(phases)>0,'execution','real block commands')
    for i,j in enumerate(fixture['jobs']):
        results[i]['cpu_tensor_reads']={name:traffic[i,name,'read'] for name in ('gate','up','fp32','aq','sa')}
        results[i]['native_read_bytes']=native_traffic[i,'NREAD'];results[i]['native_write_bytes']=native_traffic[i,'NWRITE']
    attention=[]
    for i,j in enumerate(fixture.get('attention',[])):
        p=Path(j['expected']);c.equal(hashlib.sha256(p.read_bytes()).hexdigest(),j['sha256'],'identity','attention golden')
        # The same output address is reused; CPU checksums record each query.
        expect(3,3*i,0,'attention');expect(3,3*i+2,hash_bytes(np.load(p).tobytes()),'attention')
        c.require(reports.get((3,3*i+1),0)>0,'attention','actual RV32 cycles')
        attention.append(dict(length=j['length'],cycles=reports[3,3*i+1]))
    if attention:c.equal(read(0xaf002000,896*4),np.load(fixture['attention'][-1]['expected']).tobytes(),'attention','final output')
    return dict(attention=attention,jobs=results,phases=phases,commands=len(commands),cpu_bytes=dict(cpu_bytes),handshakes=sum(backend_counts.values()))
