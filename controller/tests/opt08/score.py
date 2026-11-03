"""Read actual CPU/AXI events; compare quantized bytes at the real doorbell."""
import csv,hashlib,json
from pathlib import Path
import numpy as np
from tests.ce64_soc.scoreboard_opt02 import Memory
def score(directory,fixture,golden,checks,negative=None):
    d=Path(directory);c=checks;mem=Memory(fixture['regions'],d)
    reports={}
    for line in (d/'cpu-output.txt').read_text().splitlines():
        g,i,v=map(int,line.split());c.require((g,i) not in reports,'output_set','unique report');reports[g,i]=v
    def eq(g,i,want,cat):c.equal(reports.get((g,i)),int(want)&0xffffffff,cat,f'{g}/{i}')
    calls=0;hits=0;staged=0;saved=0;key=None;session=1;seq=0;used=set();cycles={}
    for f in golden['cases']:
        g=100+f['id'];p=Path(f['expected_path']);c.equal(hashlib.sha256(p.read_bytes()).hexdigest(),f['expected_sha256'],'input_identity',str(p))
        q=np.load(p);m,k=f['m'],f['k'];version=f['version']
        if f['reset']:
            if f['reset']==1:session+=1;seq=0
            key=None;eq(g,20,0,'recovery');used.add((g,20))
        hit=bool(version and key==(session,version,m,k,f['direct'],f['offset']))
        calls+=not hit;hits+=hit
        if hit or f['direct']:saved+=m*k*4
        else:staged+=m*k*4
        key=(session,version,m,k,f['direct'],f['offset']) if version and not f['error'] else None
        seq+=1
        eq(g,0,f['status'],'fault' if f['error'] else 'completion');eq(g,2,calls,'quantization');eq(g,3,hits,'quantization');eq(g,4,staged,'copy');eq(g,5,saved,'copy');eq(g,6,session,'sequence');eq(g,7,seq,'sequence')
        c.require(reports.get((g,1),0)>0,'timing','real mcycle interval');cycles[str(f['id'])]=reports[g,1]
        used|={(g,i) for i in range(8)}
        y=q['y'].copy()
        if negative=='bad-golden' and f['id']==1:y.flat[0]+=np.float32(100)
        if f['error']:eq(g,21,0,'recovery');used.add((g,21))
        for z,word in enumerate(y.view('u4').ravel()):eq(g,100+z,0xa5a5a5a5 if f['error'] else word,'atomic' if f['error'] else 'data');used.add((g,100+z))
        if f['error']:session+=1;seq=0
    eq(200,0,-3,'reject');eq(200,1,-100,'reject');eq(200,2,len(golden['cases']),'execution');eq(200,3,len(golden['cases'])-1,'execution')
    for i in (4,5):c.require(reports.get((200,i),0)>0,'timing','staging/output copy measured')
    c.require(reports.get((200,6),0)<=16384,'memory','RV32 session fits static state arena')
    eq(200,7,664576,'memory');eq(200,8,15728640,'memory')
    used|={(200,i) for i in range(9)};c.equal(set(reports),used,'output_set','exact inventory, no unexpected traps')
    launches=0;descriptor={};native=0;responses=0;writes=0
    cpu_bytes={"stage":0,"aq":0,"sa":0};last_key=None;traffic=[];scratch_poison=0
    for row in csv.reader((d/'transactions.csv').open()):
        cycle=int(row[0]);kind=row[1];a,data,extra=(int(v,16) for v in row[2:5]);owner=int(row[5])
        if kind=='CW':
            c.require(not 0x80000000<=a<0xa8000000,'protection','sealed model is read-only')
            if 0xa8000000<=a<0xb4000000 or 0xba000000<=a<0xbc000000:
                c.equal(owner,0,'ownership','CPU writes only after release')
                for lane in range(4):
                    if extra>>lane&1:mem.write((a&~3)+lane,(data>>(8*lane))&255)
            for label,lo,hi in [('stage',0xba100000,0xba110000),('aq',0xac000000,0xac009800),('sa',0xac00a000,0xac00a980)]:
                if lo<=a<hi:
                    if label=='aq' and a==0xac000000 and data==0xdeadbeef:scratch_poison+=1
                    else:cpu_bytes[label]+=extra.bit_count()
            if 0x10003220<=a<0x10003280:descriptor[(a-0x10003220)//4]=data
            if a==0x10003020 and data:
                c.equal(owner,1,'ownership','owner acquired at doorbell');c.require(launches<len(golden['cases']),'submission','bounded actual launches');f=golden['cases'][launches];q=np.load(f['expected_path'])
                if f['reset']:last_key=None
                hit=bool(f['version'] and last_key==(f['version'],f['m'],f['k'],f['direct'],f['offset']))
                c.equal(cpu_bytes['aq'],0 if hit else q['aq'].size,'quantization','observed CPU Aq writes')
                c.equal(cpu_bytes['sa'],0 if hit else q['sa'].nbytes,'quantization','observed CPU Sa writes')
                c.equal(cpu_bytes['stage'],0 if hit or f['direct'] else f['m']*f['k']*4,'copy','observed CPU staging writes')
                traffic.append(dict(id=f['id'],**cpu_bytes))
                last_key=(f['version'],f['m'],f['k'],f['direct'],f['offset']) if f['version'] and not f['error'] else None
                cpu_bytes={k:0 for k in cpu_bytes}
                c.equal(len(descriptor),24,'submission','all request fields written')
                for ix,value in {0:0x4c4e3135,1:96,6:2,7:f['m'],8:4,9:f['k'],11:0xba110000,14:0xac000000,15:0xac00a000,16:16}.items():c.equal(descriptor.get(ix),value,'submission',str(ix))
                c.equal(mem.read(0xac000000,q['aq'].size),q['aq'].tobytes(),'quantization','actual packed Aq before CE DMA')
                c.equal(mem.read(0xac00a000,q['sa'].nbytes),q['sa'].tobytes(),'quantization','actual Sa bits before CE DMA')
                launches+=1;descriptor={}
        if kind in ('NA','NW','NB','NR','ND'):
            c.equal(owner,1,'ownership','native transactions retain owner');native+=1
            if kind in ('ND','NB'):responses+=1
            if kind=='NW':writes+=1
    c.equal(scratch_poison,1,'recovery','deliberately poisoned scratch was requantized')
    c.equal(launches,len(golden['cases']),'submission','actual complete launch set')
    c.require(native>0 and responses>0 and writes>0,'axi','real native traffic and output writes')
    return dict(state_bytes=reports[200,6],work_bytes=reports[200,7],kv_bytes=reports[200,8],cycles=cycles,cpu_traffic=traffic,quantizations=calls,hits=hits,input_copy_bytes=staged,input_copy_saved_bytes=saved,launches=launches,native_transactions=native,output_copy_ticks=reports[200,5],input_copy_ticks=reports[200,4])
