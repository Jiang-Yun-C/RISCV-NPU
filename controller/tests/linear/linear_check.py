"""Streaming independent AXI, integer, FP32, tiling and byte-write scoreboard."""
import bisect,csv,hashlib,math,struct,sys
from collections import Counter,deque
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tests/cocotb'))
from common.checks import Checks
def local(folder,p):return Path(folder)/Path(p).name
def array_check(checks,a,b,category,label,tol=None):
    checks.equal(a.shape,b.shape,category,label+' shape')
    if tol is None:ok=a==b
    else:ok=np.isfinite(a)&(np.abs(a.astype('f8')-b)<=tol['atol']+tol['rtol']*np.abs(b.astype('f8')))
    first=tuple(int(index) for index in np.argwhere(~ok)[0]) if not ok.all() else None
    checks.require(first is None,category,dict(item=label,first=first,actual=float(a[first]) if first else None,expected=float(b[first]) if first else None))
    checks.counts[category]+=a.size-1
    if tol:
        err=a.astype('f8')-b;nrmse=float(np.sqrt(np.mean(err*err))/max(float(np.sqrt(np.mean(b.astype('f8')**2))),1e-12))
        checks.require(nrmse<=tol['nrmse'],category,dict(item=label+' NRMSE',value=nrmse));return nrmse
    return 0
def score(directory,fixture,golden,observations,folder,checks=None,negative=None):
    checks=checks or Checks();regions=[]
    for rec in fixture['regions']:
        data=local(folder,rec['path']).read_bytes();checks.equal(hashlib.sha256(data).hexdigest(),rec['sha256'],'input_identity',rec['name'])
        regions.append((rec['address'],rec['address']+len(data),bytearray(data),rec['kind']))
    regions.sort(key=lambda r:r[0]);starts=[r[0] for r in regions]
    checks.require(all(a[1]<=b[0] for a,b in zip(regions,regions[1:])),'input_identity','nonoverlapping declared regions')
    def locate(a):
        ix=bisect.bisect_right(starts,a)-1
        return regions[ix] if ix>=0 and a<regions[ix][1] else None
    def read(a,n):
        out=bytearray()
        while n:
            r=locate(a)
            if r is None:
                nxt=next((s for s in starts if s>a),a+n);take=min(n,nxt-a);out.extend(bytes(take))
            else:take=min(n,r[1]-a);out.extend(r[2][a-r[0]:a-r[0]+take])
            a+=take;n-=take
        return bytes(out)
    checks.equal(len(observations['jobs']),len(golden['jobs']),'output_set','exact operator matrix')
    summaries=[];all_counts=Counter();seen_page=False;seen_partial=False
    stream=(Path(directory)/'transactions.csv').open();iterator=iter(csv.DictReader(stream));pending=next(iterator,None)
    for expected,actual in zip(golden['jobs'],observations['jobs']):
        checks.equal(actual['name'],expected['name'],'output_set','operator order')
        reads=deque();writes=deque();wdata=deque();counts=Counter();rb=wb=rw=ww=0
        touched={};errors=0
        while pending is not None and int(pending['cycle'])<actual['start']:pending=next(iterator,None)
        while pending is not None and int(pending['cycle'])<=actual['stop']:
            rec=pending;pending=next(iterator,None);ch=rec['ch'];cycle=int(rec['cycle']);counts[ch]+=1;all_counts[ch]+=1
            if ch in ('AR','AW'):
                a=int(rec['addr'],16);size=int(rec['size'],16);length=int(rec['len'],16);bid=int(rec['id'],16);step=1<<size;end=a+(length+1)*step
                checks.require(size<=4 and a%step==0 and int(rec['burst'],16)==1,'axi_request','aligned INCR width128')
                checks.require(a>>12==(end-1)>>12 and end<=2**32 and bid<64,'axi_request','4KiB split/no wrap/ID6')
                seen_page|=(a&4095)==0
                req=dict(a=a,size=size,length=length,id=bid,beat=0,cycle=cycle,data=[],complete=False)
                (reads if ch=='AR' else writes).append(req)
            elif ch=='R':
                checks.require(bool(reads),'axi_response','no unsolicited R');r=reads[0];a=r['a']+r['beat']*(1<<r['size']);size=1<<r['size'];rb+=size
                checks.equal(int(rec['id'],16),r['id'],'axi_response','RID');checks.equal(int(rec['last'],16),int(r['beat']==r['length']),'axi_response','RLAST')
                resp=int(rec['resp'],16)
                if resp==0:
                    data=int(rec['data'],16).to_bytes(16,'little');lo=a&15;got=data[lo:lo+size];want=read(a,size)
                    rgn=locate(a);checks.require(rgn is not None and a+size<=((rgn[1]+15)//16)*16,'memory_protection','input/declared lane padding')
                    checks.equal(got.hex(),want.hex(),'read_data',hex(a));checks.counts['read_data']+=size-1
                else:checks.require(resp in (2,3),'fault','R error response');errors+=1
                r['beat']+=1
                if int(rec['last'],16):rw+=cycle-r['cycle']-r['length']-1;reads.popleft()
            elif ch=='W':wdata.append(rec)
            elif ch=='B':
                checks.require(bool(writes) and writes[0]['complete'],'axi_response','B follows all W');w=writes.popleft();ww+=cycle-w['cycle']-1
                checks.equal(int(rec['id'],16),w['id'],'axi_response','BID');resp=int(rec['resp'],16)
                if resp==0:
                    for address,data in w['data']:
                        r=locate(address);r[2][address-r[0]:address-r[0]+len(data)]=data
                else:checks.require(resp in (2,3),'fault','B error response');errors+=1
            else:checks.require(False,'axi_response','unknown channel')
            while wdata and any(not w['complete'] for w in writes):
                w=next(w for w in writes if not w['complete']);rec=wdata.popleft();a=w['a']+w['beat']*(1<<w['size']);base=a&~15;mask=int(rec['strb'],16);legal=((1<<(1<<w['size']))-1)<<(a&15)
                checks.require(mask!=0 and mask&~legal==0,'axi_write','WSTRB active lanes');checks.equal(int(rec['last'],16),int(w['beat']==w['length']),'axi_write','WLAST')
                seen_partial|=mask!=0xffff;wb+=mask.bit_count();data=int(rec['data'],16).to_bytes(16,'little')
                for lane in range(16):
                    if mask>>lane&1:
                        target=base+lane;r=locate(target);checks.require(r is not None and r[3] in ('output','audit'),'memory_protection','only writable payload')
                        mark=touched.setdefault(r[0],bytearray(r[1]-r[0]));ix=target-r[0];checks.equal(mark[ix],0,'axi_write','no repeated byte');mark[ix]=1;w['data'].append((target,data[lane:lane+1]))
                w['beat']+=1;w['complete']=w['beat']==w['length']+1
        checks.require(not reads and not writes and not wdata,'completion','accepted AXI drained')
        for key,ch in [('ar','AR'),('r','R'),('aw','AW'),('w','W'),('b','B')]:checks.equal(actual['counters'][key],counts[ch],'counters',ch)
        for key,value in [('read_bytes',rb),('write_bytes',wb),('read_wait',rw),('write_wait',ww)]:checks.equal(actual['counters'][key],value,'counters',key)
        checks.equal(actual['counters']['cycles'],actual['stop']-actual['start']+1,'timing','independent epoch')
        status=expected['status'];numeric={}
        if isinstance(status,int):
            r=actual['result'];checks.equal(r['status'],status,'completion','firmware status');checks.equal(r['valid'],int(status==0),'completion','output validity')
            for i,key in enumerate(('session_lo','session_hi','sequence_lo','sequence_hi'),2):checks.equal(r[key],expected['request'][i],'completion',key)
            checks.equal(actual['guard_error'],False,'completion','no bus fault');checks.require(r['cycles']>0,'execution','real Coral mcycle')
            checks.equal(r['cycles'],sum(r[k] for k in ('load_cycles','compute_cycles','write_cycles','other_cycles')),'timing','disjoint phases')
            restore=(r['reserved']<<32)|r['checksum'];checks.require(restore<=r['other_cycles'],'timing','restoration included in total')
            if expected['logical_read'] is not None:checks.equal(r['payload_read'],expected['logical_read'],'counters','logical input')
            checks.equal(r['payload_write'],expected['logical_write'],'counters','logical output+audit')
            if status:
                if status!=-9:checks.equal(sum(counts.values()),0,'reject','reject before external traffic')
                else:checks.require(rb>0,'numeric_rejection','actual invalid operand read')
                checks.equal(wb,0,'reject','output untouched')
            else:
                req=expected['request'];m,n,k=expected['m'],expected['n'],expected['k'];g=(k+63)//64
                checks.equal(r['rows'],expected['rows'],'tiling','all output rows/M tiles');checks.equal(r['tiles'],((m+3)//4)*((n+127)//128),'tiling','autonomous 128-row/M4 tiles')
                p=local(folder,expected['expected_path']);checks.equal(hashlib.sha256(p.read_bytes()).hexdigest(),expected['expected_sha256'],'input_identity','oracle identity')
                wanted={};
                def mark(a,size):
                    reg=locate(a);marks=wanted.setdefault(reg[0],bytearray(reg[1]-reg[0]));marks[a-reg[0]:a-reg[0]+size]=bytes([1])*size
                with np.load(p,allow_pickle=False) as ref:
                    y=np.empty((m,n),dtype='<f4')
                    for token in range(m):
                        address=req[11]+token*req[16];y[token]=np.frombuffer(read(address,n*4),dtype='<f4');mark(address,n*4)
                    reference=ref['y'].copy()
                    if negative=='bad-golden':reference[0,0]+=100;negative=None
                    numeric['nrmse']=array_check(checks,y,reference,'data','complete FP32 output',golden['thresholds'])
                    numeric['output_elements']=m*n
                    output_path=Path(directory)/('actual-'+expected['name']+'.npy');np.save(output_path,y)
                    numeric['output_sha256']=hashlib.sha256(output_path.read_bytes()).hexdigest()
                    numeric['max_abs_error']=float(np.max(np.abs(y.astype('f8')-reference)))
                    if req[20]:
                        dtype=np.dtype([('dot','<i4'),('p','<f4'),('v','<f4'),('partial','<f4')]);observed={f:np.empty((g,m,n),dtype='<i4' if f=='dot' else '<f4') for f in dtype.names}
                        for mb in range(0,m,4):
                            mt=min(4,m-mb);address=req[20]+mb*n*g*16
                            chunk=np.frombuffer(read(address,n*g*mt*16),dtype=dtype).reshape(n,g,mt);mark(address,n*g*mt*16)
                            for field in dtype.names:observed[field][:,mb:mb+mt,:]=chunk[field].transpose(1,2,0)
                        if negative=='bad-integer':observed['dot'][0,0,0]^=1
                        if negative=='bad-restoration':observed['p'][0,0,0]+=100
                        if negative=='bad-reduction':observed['partial'][0,0,0]+=100
                        array_check(checks,observed['dot'],ref['dots'],'integer','each INT32 group')
                        for field in ('p','v','partial'):array_check(checks,observed[field],ref[field],'restoration',field,golden['thresholds'])
                        numeric['integer_groups']=g*m*n
                    else:checks.require(wb==m*n*4,'production','production returns only final logits');numeric['integer_groups']=0
                checks.equal(set(touched),set(wanted),'axi_write','exact output/audit region set')
                for address,mask in wanted.items():
                    checks.require(touched[address]==mask,'axi_write','all bytes exactly once, stride gaps untouched')
                    reg=locate(address);untouched=np.frombuffer(mask,dtype='u1')==0;values=np.frombuffer(reg[2],dtype='u1');checks.require(np.all(values[untouched]==0xa5),'memory_protection','both guards and all stride gaps')
                checks.equal(wb,expected['logical_write'],'counters','all actual output bytes');checks.require(rb>=expected['logical_read'],'counters','physical reads include overfetch')
        else:
            checks.equal(actual['output_valid'],False,'fault','partial output invalid');checks.require(actual['guard_error'] and errors>0,'fault','injected response observed')
            checks.require(actual['drained'] and actual['recovered'],'recovery','isolate/drain/recover')
        summaries.append(dict(name=expected['name'],shape_MNK=[expected.get('m'),expected.get('n'),expected.get('k')],logical_read=expected.get('logical_read'),logical_write=expected.get('logical_write'),axi_read=rb,axi_write=wb,channels=dict(counts),cycles=actual['counters']['cycles'],read_wait=rw,write_wait=ww,result=actual.get('result'),numeric=numeric))
    stream.close();checks.require(pending is None,'completion','no transactions outside registered operators')
    checks.require(seen_partial and seen_page,'axi_write','output lanes and page crossing exercised')
    checks.require(all_counts['AR']>0 and all_counts['AW']>0,'axi_request','real backend memory traffic')
    checks.equal(observations['protocol_error'],0,'axi_stability','stall payloads stable');checks.require(observations['protocol_checks']>1000,'axi_stability','whole execution protocol monitor')
    checks.equal(observations['stack_guard'],[0xa5]*16,'memory_protection','DTCM stack guard');checks.require(0<observations['stack_peak']<4096,'memory_protection','stack high water')
    return checks,dict(jobs=summaries,channels=dict(all_counts),stack_peak=observations['stack_peak'],scope=fixture['scope'])
