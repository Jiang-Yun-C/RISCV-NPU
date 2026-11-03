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
    command_index=0;results=[]
    for i,j in enumerate(fixture['jobs']):
        group=10+i;status=j['status'];expect(group,0,status,'fault' if status else 'completion');expect(group,1,int(not status),'validity')
        c.require(reports.get((group,2),0)>0,'cycles','actual CPU kernel elapsed')
        if j['mode']!=2:
            cmd=commands[command_index];command_index+=1
            for f,v in {14:3,15:1,16:1,17:j['k'],18:j['gate'],19:j['fp32'],20:j['up'],22:j['aq'],23:j['sa'],24:int(j['mode']==1)}.items():c.equal(cmd[f],v,'submission','block command field '+str(f))
        if not status:
            p=Path(j['expected']);c.equal(hashlib.sha256(p.read_bytes()).hexdigest(),j['expected_sha256'],'identity','independent golden')
            expected=np.load(p);q=expected['aq'].tobytes();sa=expected['sa'].tobytes();y=expected['fp'].tobytes()
            if negative=='bad-golden' and i==0:q=bytes([q[0]^1])+q[1:]
            c.equal(read(j['aq'],len(q)),q,'integer',j['name']);c.equal(read(j['sa'],len(sa)),sa,'scale',j['name'])
            expect(group,7,hash_bytes(q),'cpu_observed');expect(group,8,hash_bytes(sa),'cpu_observed')
            if j['fp32']:
                c.equal(read(j['fp32'],len(y)),y,'fp32',j['name']);expect(group,9,hash_bytes(y),'cpu_observed')
            if j['mode']!=2:
                expect(group,4,j['k']*8,'payload');expect(group,5,len(q)+len(sa)+(len(y) if j['fp32'] else 0),'payload')
                c.require(reports.get((group,3),0)>0,'cycles','measured complete SFU path')
            if j['k']==65:expect(group,17,-3,'reject');expect(group,18,1,'view')
            if j['down']:
                expect(group,19,-10,'view')
                cmd=commands[command_index];command_index+=1
                c.equal(cmd[14],2,'down','real CE64 linear command');c.equal(cmd[22],j['aq'],'down','same Aq address');c.equal(cmd[23],j['sa'],'down','same Sa address')
                dy=expected['down'].tobytes();c.equal(read(j['y'],len(dy)),dy,'down','FP32 restored down projection');expect(group,10,0,'down');expect(group,13,hash_bytes(dy),'down');expect(group,14,-10,'view','consumed version cannot be reused')
        else:
            expect(group,15,0,'atomic');expect(group,16,0,'recovery')
            if status==-9:
                c.equal(read(j['aq'],64),bytes(64),'atomic','bad final input does not publish a partial group')
                c.equal(read(j['sa'],4),bytes(4),'atomic','invalid scale unpublished')
                if j['fp32']:c.equal(read(j['fp32'],j['k']*4),bytes(j['k']*4),'atomic','FP32 unpublished')
        results.append(dict(name=j['name'],status=status,cpu_cycles=reports[group,2],backend_cycles=reports[group,3],read_bytes=reports[group,4],write_bytes=reports[group,5],down_cycles=reports.get((group,12))))
    c.equal(command_index,len(commands),'submission','exact command count')
    phases=[];native_traffic=Counter()
    for row in csv.reader((d/'vector.csv').open()):
        if row[0] in ('NREAD','NWRITE'):
            native_traffic[(int(row[1])-10,row[0])]+=int(row[2]);continue
        if row[0]!='COMPLETE':continue
        values=list(map(int,row[1:]));cycle,launch,status,ticks,loads,computes,writes,rbytes,wbytes,mt,ml,mc,mw,mr,mb=values
        for a,b in ((ticks,mt),(loads,ml),(computes,mc),(writes,mw)):c.equal(a,b,'phase','independent state residency')
        if status==0:c.equal(rbytes,mr,'payload','accepted R bytes');c.equal(wbytes,mb,'payload','accepted W bytes')
        phases.append(dict(launch=launch,status=status,cycles=ticks,load=loads,compute=computes,write=writes,read_bytes=rbytes,write_bytes=wbytes))
    c.require(len(phases)>0,'phase','actual complete SFU commands')
    for i,j in enumerate(fixture['jobs']):
        results[i]['cpu_tensor_reads']={name:traffic[i,name,'read'] for name in ('gate','up','fp32','aq','sa')}
        results[i]['native_read_bytes']=native_traffic[i,'NREAD'];results[i]['native_write_bytes']=native_traffic[i,'NWRITE']
        if j['mode']!=2 and not j['status']:
            c.equal(sum(traffic[i,n,'read'] for n in ('gate','up','fp32','aq','sa')),0,'cpu_traversal','block driver does not scan tensor elements')
        if j['mode']==2:c.require(traffic[i,'gate','read']>0 and traffic[i,'fp32','read']>0,'cpu_traversal','original CPU SwiGLU and quantization scans observed')
    return dict(jobs=results,phases=phases,commands=len(commands),cpu_payload_bytes=dict(cpu_bytes))
