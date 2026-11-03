"""Read-only, streaming scoreboard over real CPU and CE64 AXI handshakes."""
import csv,hashlib,json,struct
from collections import deque,Counter
from pathlib import Path
import numpy as np
from common.checks import Checks
class Memory:
    def __init__(self,regions,folder):
        self.pages={}
        for r in regions:
            p=Path(r['path']);p=p if p.exists() else Path(folder)/p.name
            raw=p.read_bytes()
            if len(raw)!=r['bytes'] or hashlib.sha256(raw).hexdigest()!=r['sha256']:raise ValueError('region identity '+r['name'])
            address=r['address'];offset=0
            while offset<len(raw):
                n=min(4096-(address&4095),len(raw)-offset);page=self.pages.setdefault(address>>12,bytearray(4096));page[address&4095:(address&4095)+n]=raw[offset:offset+n];offset+=n;address+=n
    def byte(self,a):page=self.pages.get(a>>12);return page[a&4095] if page is not None else 0
    def read(self,a,n):return bytes(self.byte(a+i) for i in range(n))
    def write(self,a,v):self.pages.setdefault(a>>12,bytearray(4096))[a&4095]=v

def score(directory,fixture,golden,folder,checks=None,negative=None):
    d=Path(directory);c=checks or Checks();mem=Memory(fixture['regions'],folder)
    reports={}
    for row in (d/'cpu-output.txt').read_text().splitlines():
        group,item,value=map(int,row.split());c.require((group,item) not in reports,'output_set','unique CPU report');reports[group,item]=value
    def expect(group,item,value,category):c.equal(reports.get((group,item)),value&0xffffffff,category,'%d:%d'%(group,item))
    expect(1,0,0,'completion');expect(1,1,1,'sequence');expect(1,2,0,'completion');expect(1,3,0,'completion');expect(1,4,0,'completion')
    for i,v in enumerate((-4,-5,-3,-4,0)):expect(2,i,v,'reject')
    audit_seen=set()
    jobs=golden['jobs'];session=1;sequence=0;successes=[]
    for i,j in enumerate(jobs):
        group=10+i;sequence+=1;status=j['status'];expect(group,0,status,'fault' if status else 'completion');expect(group,1,int(status==0),'visibility');expect(group,2,session,'sequence');expect(group,3,sequence,'sequence');expect(group,4,2 if status else 0,'ownership');expect(group,6,status,'sequence');expect(group,7,1,'sequence');expect(group,20,1,'execution');expect(group,21,1,'execution')
        c.require(reports.get((group,8),0)>0,'timing','nonzero actual CPU elapsed ticks')
        if status==0:
            p=Path(j['expected_path']);p=p if p.exists() else Path(folder)/p.name
            c.equal(hashlib.sha256(p.read_bytes()).hexdigest(),j['expected_sha256'],'input_identity',j['name'])
            f=np.load(p,allow_pickle=False);y=f['y'].copy()
            if negative=='bad-golden' and not successes:y.flat[0]+=np.float32(100)
            h=2166136261
            for v in y.view('u4').flat:h=((h^int(v))*16777619)&0xffffffff
            expect(group,10,h,'data');expect(group,11,y.size,'output_set')
            c.require(reports.get((group,9),0)>0,'execution','real Coral cycles')
            successes.append((i,y,f['aq'].copy(),f['sa'].copy()))
            if j['mode']==1:expect(group,5,0,'interrupt')
            if j['mode']==0:c.require(reports.get((group,5),0)>0,'interrupt','actual halt notification serviced by CPU')
        else:
            expect(group,12,-10,'recovery')
            if j['mode']==5:expect(group,13,-7,'recovery')
            expect(group,14,0,'recovery');session+=1;sequence=0;expect(group,15,session,'recovery');expect(group,16,0,'recovery');expect(group,17,-10,'recovery')
    c.require(reports.get((3,0),0)>0,'interrupt','real handler count');c.require(reports.get((3,1),0)>0,'interrupt','timer wake ensures lost IRQ cannot deadlock');expect(3,2,session,'sequence')
    c.require(not any(g==255 for g,_ in reports),'execution','no unexpected CPU traps')
    required_reports={(1,z) for z in range(5)}|{(2,z) for z in range(5)}|{(3,z) for z in range(3)}
    for i,j in enumerate(jobs):
        items=set(range(12))|{20,21} if j['status']==0 else set(range(10))|{12,14,15,16,17,20,21}
        if j['mode']==5:items.add(13)
        items|=set(range(22,28))
        required_reports|={(10+i,z) for z in items}
    c.equal(set(reports),required_reports,'output_set','exact complete CPU report inventory')
    burst_length=0;pending_r=deque();pending_aw=deque();pending_w=deque();pending_b=deque();request={};active=-1;outstanding=0;read_address=0;read_beats=0;mode=0;last_b=0;released=[];starts=[];cpu_reads={};numeric_outputs={};native=Counter();cache=0;channels=Counter();errors=Counter();cpu_store=set();late_halt=False
    success_by_index={i:(y,aq,sa) for i,y,aq,sa in successes}
    for row in csv.reader((d/'transactions.csv').open()):
        cycle=int(row[0]);kind=row[1];a,data,extra=int(row[2],16),int(row[3],16),int(row[4],16);owner=int(row[5]);channels[kind]+=1
        if kind=='CW':
            if 0x20000000<=a<0x20040000:c.require(False,'upload','CE never uploads a Coral ELF')
            if 0x80000000<=a<0xa8000000:c.require(False,'protection','CPU must not write sealed model')
            if (0xa8000000<=a<0xb4000000 or 0xba000000<=a<0xbc000000):
                c.equal(owner,0,'ownership','CPU shared store after release')
                for lane in range(4):
                    if extra>>lane&1:mem.write((a&~3)+lane,data>>(8*lane)&255)
                cpu_store.add(a)
            if a==0x100000a0:mode=data
            if a==0x10003010 and data&4:
                c.equal(owner,1,'recovery','CE reset is a request while isolation retains ownership')
            if 0x10003220<=a<0x10003280:request[(a-0x10003220)//4]=data
            if a==0x10003020 and data!=0:
                active+=1;j=jobs[active];starts.append(cycle);c.equal(owner,1,'ownership','CPU native start acquired owner');c.equal(len(request),24,'submission','complete CPU descriptor');c.equal(outstanding,0,'visibility','drained before launch')
                m,n,k=j['job']['a']['shape'][0],j['job']['wq']['shape'][0],j['job']['wq']['shape'][1]
                for index,value in {0:0x4c4e3135,1:96,6:99 if j['mode']==7 else 2,21:1 if j['mode']==6 else 0,7:m,8:n,9:k,10:j['job']['wq']['address'],11:j['job']['y']['address'],12:j['job']['sw']['address'],13:j['job']['bias'].get('address',0),14:0xac000000,15:0xac00a000,16:n*4}.items():c.equal(request[index],value,'submission','descriptor field %d'%index)
                if active in success_by_index:
                    y,aq,sa=success_by_index[active];c.equal(mem.read(0xac000000,aq.size),aq.tobytes(),'quantization','real CPU Aq vs producer');c.equal(mem.read(0xac00a000,sa.nbytes),sa.tobytes(),'quantization','real CPU Sa vs producer')
                numeric_outputs[active]={};cpu_reads[active]={};request={}
            if a==0x10000100 and data==0:
                c.equal(outstanding,0,'visibility','owner release after all actual R/B');released.append(cycle)
            
        elif kind=='CR':
            read_address=a;read_beats=data+1
            if data==7 and 0xb4000000<=a<0xb8000000:cache+=1
            if 0xac100000<=a<0xac200000:c.equal(owner,0,'visibility','CPU reads final Y after release');c.equal(data,0,'cache','shared Y bypasses D Cache')
        elif kind=='CD':
            if 0xac100000<=read_address<0xac200000 and active>=0 and active in success_by_index:
                j=jobs[active];offset=read_address-j['job']['y']['address'];c.equal(extra,0,'axi','CPU read response');cpu_reads[active][offset]=data
                y=success_by_index[active][0];c.equal(data,int(y.view('u4').flat[offset//4]),'data','CPU actual Y response')
            if read_address==0x1000300c and data&16 and outstanding:late_halt=True
            read_beats-=1;read_address+=4
        elif kind=='NA':
            c.equal(owner,1,'ownership','backend owns writes');pending_aw.append((a,data,extra));outstanding+=1
        elif kind=='NW':pending_w.append((data,extra))
        elif kind=='NB':
            c.require(bool(pending_b),'axi','B has paired AW/W');addr,ident=pending_b.popleft();c.equal(data,ident,'axi','B matches real request ID');outstanding-=1;last_b=cycle
            if extra:errors['write']+=1
        elif kind=='NL':burst_length=extra
        elif kind=='NR':
            c.equal(owner,1,'ownership','backend owns reads');pending_r.extend((a+(i<<extra),data,extra,i==burst_length) for i in range(burst_length+1));outstanding+=1
        elif kind=='ND':
            c.require(bool(pending_r),'axi','R has request');addr,ident,size,last=pending_r.popleft();c.equal(a,ident,'axi','R matches real request ID');outstanding-=int(last)
            if extra:errors['read']+=1
            else:
                aligned=addr&~15;lo=addr;hi=(addr>>size<<size)+(1<<size);expected=int.from_bytes(bytes(mem.byte(aligned+i) if lo<=aligned+i<hi else 0 for i in range(16)),'little')
                c.equal(data,expected,'read_data','Coral actual input/model read')
        elif kind=='EARLY':c.require(False,'visibility','owner released with pending backend response')
        while pending_aw and pending_w:
            addr,ident,size=pending_aw.popleft();value,strobe=pending_w.popleft();c.require(strobe!=0,'axi','nonempty backend write');pending_b.append((addr,ident))
            j=jobs[active];base=j['job']['y']['address'];length=j['job']['y']['allocation_bytes'];aligned=addr&~15
            audit=j.get('audit_address',0) and j['audit_address']<=addr<j['audit_address']+j['audit_bytes']
            for lane in range(16):
                if strobe>>lane&1:
                    address=aligned+lane;c.require(base<=address<base+length or (audit and j['audit_address']<=address<j['audit_address']+j['audit_bytes']),'protection','backend writes only submitted Y/audit')
                    # Error responses must not commit in T04 memory.
                    if mode!=4:mem.write(address,value>>(8*lane)&255)
            if audit:
                expected=bytes.fromhex(j['audit_hex'])[addr-j['audit_address']:addr-j['audit_address']+16]
                c.equal(strobe,65535,'axi','audit sixteen-byte strobe');c.equal(value,int.from_bytes(expected,'little'),'data','independent audit dot/p/v/partial');audit_seen.add(addr)
            if active in success_by_index and not audit:
                offset=addr-base
                width=16 if strobe==65535 and size==4 else 4
                c.equal(strobe,65535 if width==16 else 15<<(addr&15),'axi','packed/scalar write strobe')
                for sub in range(0,width,4):
                    off=offset+sub;actual=(value>>(8*((addr&15)+sub)))&0xffffffff
                    expected=int(success_by_index[active][0].view('u4').flat[off//4]);c.equal(actual,expected,'data','independent packed/scalar Y');c.require(off not in numeric_outputs[active],'output_set','no duplicate Y');numeric_outputs[active][off]=actual
        if kind in ('SA','SW'):native[kind]+=1
    c.equal(len(starts),len(jobs),'submission','one entire operator launch per accepted job')
    for i,y,aq,sa in successes:
        actual_y=np.array([numeric_outputs[i][z] for z in range(0,y.nbytes,4)],dtype='<u4').view('<f4').reshape(y.shape);np.save(d/('actual-'+jobs[i]['name']+'.npy'),actual_y)
        expected=set(range(0,y.nbytes,4));c.equal(set(numeric_outputs[i]),expected,'output_set','every real backend output');c.equal(set(cpu_reads[i]),expected,'output_set','CPU consumed every Y')
    c.equal(audit_seen,{a for j in jobs if j.get('audit_address') for a in range(j['audit_address'],j['audit_address']+j['audit_bytes'],16)},'output_set','complete independent audit inventory')
    c.equal(channels['CW'],channels['CB'],'axi','all real CPU write responses');c.equal(outstanding,0,'visibility','final drain');c.require(cache>0,'cache','real private D Cache refills');c.require(native['SA']>=32*len(starts) and native['SW']==native['SA'],'upload','actual full CE descriptor writes; no Coral ELF upload')
    for address in fixture['guards']:c.equal(mem.read(address,16),b'\xa5'*16,'protection','shared guard '+hex(address))
    if fixture['profile']=='control':
        c.require(errors['read']>0 and errors['write']>0,'fault','actual SLVERR and DECERR responses')
        c.require(late_halt or any(reports.get((10+i,13)) is not None for i,j in enumerate(jobs) if j['mode']==5),'recovery','held accepted write exercises drain')
    return dict(jobs=len(jobs),successful_jobs=len(successes),output_elements=sum(y.size for _,y,_,_ in successes),launches=len(starts),channels=dict(channels),fault_responses=dict(errors),private_cache_refills=cache,cpu_reports=len(reports),full_head_rows=151936 if fixture['profile']=='head' else 0),c
