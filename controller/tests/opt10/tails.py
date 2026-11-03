"""Private transport only: prequantized K tails over real CPU/guard/native."""
import csv,json,hashlib
from pathlib import Path
import numpy as np
from scripts.evidence import sha256,write_json
from tests.opt10.base_score import Memory
from collections import deque,Counter

def generate(folder):
    folder=Path(folder);folder.mkdir(parents=True);rng=np.random.default_rng(65);regions=[];jobs=[];header=[]
    def blob(name,address,raw):
        p=folder/(name+'.bin');p.write_bytes(raw);regions.append(dict(name=name,address=address,bytes=len(raw),path=str(p),sha256=sha256(p),kind='frozen_transport_input'))
    for i,k in enumerate((65,66,67)):
        m,n=(1,5) if i==0 else (4,6) if i==1 else (4,7)
        aq=rng.integers(-127,128,(m,128),dtype='i1');aq[:,k:]=0
        w=rng.integers(-127,128,(n,128),dtype='i1');w[:,k:]=-128 # padding must never enter arithmetic
        sa=np.full((m,2),.125,dtype='<f4');sw=np.full((n,2),.0625,dtype='<f4');y=np.zeros((m,n),dtype='<f4')
        for g in range(2):
            dot=aq[:,g*64:min(k,(g+1)*64)].astype('i4')@w[:,g*64:min(k,(g+1)*64)].astype('i4').T
            y=np.float32(y+np.float32(np.float32(dot.astype('f4')*sa[:,g,None])*sw[None,:,g]))
        aqa=0xb4500000+i*0x10000;saa=aqa+0x1000;wa=0x89000ff0+i*0x10000;swa=0x89100ff0+i*0x10000
        for name,a,raw in ((f'aq{i}',aqa,aq.tobytes()),(f'sa{i}',saa,sa.tobytes()),(f'w{i}',wa,w.tobytes()),(f'sw{i}',swa,sw.tobytes())):blob(name,a,raw)
        jobs.append(dict(k=k,m=m,n=n,aq=aqa,sa=saa,w=wa,sw=swa,expected_y=y.view('u4').tolist()))
        header.append('{'+','.join(str(v)+'u' for v in (m,n,k,aqa,saa,wa,swa))+'}')
    (folder/'tail_inputs.h').write_text('struct tail_case {unsigned m,n,k,aq,sa,w,sw;};\nstatic const struct tail_case tail_cases[]={'+','.join(header)+'};\n')
    f=dict(regions=regions,guards=[],profile='tails');g=dict(jobs=jobs,scope='private production transport component; public K capability unchanged')
    write_json(folder/'fixture.json',f);write_json(folder/'golden.json',g);return f,g

def score(folder,c):
    d=Path(folder);cfg=json.loads((d/'case.json').read_text());f=json.loads(Path(cfg['fixture']).read_text());g=json.loads(Path(cfg['golden']).read_text())
    mem=Memory(f['regions'],Path(cfg['fixture']).parent);reports={};active=-1;pending=deque();writes=deque();dataq=deque();pending_b=0;outstanding=0;length=0;seen=Counter();coverage=Counter()
    for line in (d/'cpu-output.txt').read_text().splitlines():
        group,item,value=map(int,line.split());c.require((group,item) not in reports,'output_set','unique CPU item');reports[group,item]=value
    for row in csv.reader((d/'transactions.csv').open()):
        kind=row[1];a,data,extra=(int(v,16) for v in row[2:5]);owner=int(row[5])
        if kind=='CW':
            if 0xac000000<=a<0xac00b000:
                c.equal(owner,0,'ownership','CPU prequantized input writes after release')
                for lane in range(4):
                    if extra>>lane&1:mem.write((a&~3)+lane,data>>(lane*8)&255)
            if a==0x10003020 and data:
                active+=1;c.equal(outstanding,0,'visibility','drained next tail');c.equal(owner,1,'ownership','CPU transport owns lease')
            if a==0x10000100 and data==0:c.equal(outstanding,0,'visibility','release after all responses')
        if kind=='NL':length=extra
        if kind=='NR':
            c.equal(owner,1,'ownership','owned reads');c.require((a&4095)+((length+1)<<extra)<=4096,'burst_boundary','Ktail page slicing')
            pending.extend((a+(i<<extra),data,extra,i==length) for i in range(length+1));outstanding+=1
            j=g['jobs'][active]
            if j['w']<=a<j['w']+j['n']*128:
                off=(a-j['w'])%128
                c.require(off+((length+1)<<extra)<=j['k'],'protection','no read of row padding')
                coverage['K'+str(j['k'])]+=1
        if kind=='ND':
            addr,ident,size,last=pending.popleft();outstanding-=int(last);c.equal(extra,0,'axi','successful read');c.equal(a,ident,'axi','read ID')
            expected=int.from_bytes(bytes(mem.byte((addr&~15)+z) if addr<=(addr&~15)+z<addr+(1<<size) else 0 for z in range(16)),'little')
            c.equal(data,expected,'read_data','actual frozen tensor read')
        if kind=='NA':writes.append((a,extra));outstanding+=1
        if kind=='NW':dataq.append((data,extra))
        while writes and dataq:
            addr,size=writes.popleft();value,mask=dataq.popleft();j=g['jobs'][active];pending_b+=1
            for lane in range(16):
                if mask>>lane&1:c.require(0xac100000<=(addr&~15)+lane<0xac100000+j['m']*j['n']*4,'protection','no tail output overrun')
            for z in range(0,16,4):
                if mask>>z&15:
                    off=(addr&~15)+z-0xac100000;c.equal(mask>>z&15,15,'axi','complete FP32 word')
                    c.equal(value>>(z*8)&0xffffffff,np.array(j['expected_y'],dtype='u4').ravel()[off//4].item(),'data','independent Ktail FP32')
                    seen[active]+=1
        if kind=='NB':c.require(pending_b>0,'axi','paired write B');pending_b-=1;outstanding-=1;c.equal(extra,0,'axi','write response')
        if kind=='EARLY':c.require(False,'visibility','early release')
    c.equal(active+1,3,'completion','all K65/66/67 transports')
    for i,j in enumerate(g['jobs']):
        c.equal(reports.get((400+i,0)),0,'completion','successful production transport')
        c.equal(seen[i],j['m']*j['n'],'output_set','all actual native outputs')
        for z,v in enumerate(np.array(j['expected_y'],dtype='u4').ravel()):c.equal(reports.get((400+i,100+z)),int(v),'data','CPU actual readback')
    c.equal(len(reports),3+sum(j['m']*j['n'] for j in g['jobs']),'output_set','exact reports')
    c.equal(outstanding,0,'visibility','final transport drained')
    return dict(scope=g['scope'],coverage=dict(coverage),outputs=sum(seen.values()))
