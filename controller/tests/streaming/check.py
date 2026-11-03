"""Independent byte/AXI scoreboard. Does not import firmware or export numerics."""
import csv,hashlib,json,math,struct,sys
from collections import Counter,deque
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tests/cocotb'))
from common.checks import Checks

def local(folder,path):return Path(folder)/Path(path).name

def score(directory,fixture,golden,observations,folder,checks=None,negative=None):
    checks=checks or Checks();memory={};output_spans=[];input_spans=[]
    for r in fixture['regions']:
        data=local(folder,r['path']).read_bytes()
        checks.equal(hashlib.sha256(data).hexdigest(),r['sha256'],'input_identity',r['name'])
        for i,b in enumerate(data):memory[r['address']+i]=b
        (input_spans if r['kind']=='input' else output_spans).append((r['address'],r['address']+len(data)))
    with (Path(directory)/'transactions.csv').open() as f:rows=list(csv.DictReader(f))
    jobs=golden['jobs'];checks.equal(len(observations['jobs']),len(jobs),'output_set','exact required jobs')
    all_counts=Counter();summaries=[];seen_partial=False;seen_page=False
    for expected,actual in zip(jobs,observations['jobs']):
        checks.equal(actual['name'],expected['name'],'output_set','job order')
        traces=[r for r in rows if actual['start']<=int(r['cycle'])<=actual['stop']]
        reads=deque();writes=deque();wdata=deque();counts=Counter();read_bytes=0;write_bytes=0;read_wait=0;write_wait=0;written=set();requests=[]
        pending=[]
        for rec in traces:
            ch=rec['ch'];counts[ch]+=1;all_counts[ch]+=1
            if ch in ('AR','AW'):
                a=int(rec['addr'],16);size=int(rec['size'],16);length=int(rec['len'],16);bid=int(rec['id'],16);step=1<<size;end=a+(length+1)*step
                checks.require(size<=4 and a%step==0 and int(rec['burst'],16)==1,'axi_request','aligned INCR, width128')
                checks.require(a>>12==(end-1)>>12 and end<=2**32,'axi_request','4KiB split/no wrap')
                checks.require(0<=bid<64,'axi_request','ID6')
                requests.append((a,end));seen_page|=(a&4095)==0
                if ch=='AR':reads.append(dict(address=a,size=size,length=length,id=bid,beat=0,cycle=int(rec['cycle'])))
                else:writes.append(dict(address=a,size=size,length=length,id=bid,beat=0,data=[],complete=False,cycle=int(rec['cycle'])))
            elif ch=='R':
                checks.require(bool(reads),'axi_response','no duplicated/unsolicited R')
                r=reads[0];a=r['address']+r['beat']*(1<<r['size']);read_bytes+=1<<r['size']
                checks.equal(int(rec['id'],16),r['id'],'axi_response','RID')
                checks.equal(int(rec['last'],16),int(r['beat']==r['length']),'axi_response','RLAST')
                if int(rec['resp'],16)==0:
                    data=int(rec['data'],16).to_bytes(16,'little');lo=a&15
                    checks.require(any(lo1<=a and a+(1<<r['size'])<=((hi+15)//16)*16 for lo1,hi in input_spans+output_spans),'memory_protection','read within declared payload/lane padding')
                    for lane in range(lo,lo+(1<<r['size'])):checks.equal(data[lane],memory.get((a&~15)+lane,0),'read_data',hex((a&~15)+lane))
                else:checks.require(int(rec['resp'],16) in (2,3),'fault','legal error R')
                r['beat']+=1
                if int(rec['last'],16):
                    read_wait+=int(rec['cycle'])-r['cycle']-r['length']-1;reads.popleft()
            elif ch=='W':wdata.append(rec)
            elif ch=='B':
                checks.require(bool(writes) and writes[0]['complete'],'axi_response','B only after complete W')
                w=writes.popleft();write_wait+=int(rec['cycle'])-w['cycle']-1;checks.equal(int(rec['id'],16),w['id'],'axi_response','BID')
                if int(rec['resp'],16)==0:
                    for a,b in w['data']:memory[a]=b
                else:checks.require(int(rec['resp'],16) in (2,3),'fault','legal error B')
            else:checks.require(False,'axi_response','unknown channel')
            # W may precede AW; pair in AXI write-address order.
            while wdata and any(not w['complete'] for w in writes):
                w=next(w for w in writes if not w['complete']);rec=wdata.popleft();a=w['address']+w['beat']*(1<<w['size']);base=a&~15
                mask=int(rec['strb'],16);legal=((1<<(1<<w['size']))-1)<<(a&15)
                checks.require(mask!=0 and mask&~legal==0,'axi_write','WSTRB active lanes')
                checks.equal(int(rec['last'],16),int(w['beat']==w['length']),'axi_write','WLAST')
                seen_partial|=mask!=0xffff;write_bytes+=mask.bit_count();data=int(rec['data'],16).to_bytes(16,'little')
                for lane in range(16):
                    if mask>>lane&1:
                        target=base+lane
                        checks.require(any(lo<=target<hi for lo,hi in output_spans),'memory_protection','write inside declared output')
                        checks.require(target not in written,'axi_write','no repeated output byte');written.add(target);w['data'].append((target,data[lane]))
                w['beat']+=1;w['complete']=w['beat']==w['length']+1
        if expected['name'] in ('boundary-tail','recovered-boundary'):
            req=expected['request'];pages={a>>12 for a,e in requests if req[10]<=a<req[10]+req[17]}
            checks.require({req[10]>>12,(req[10]+req[17]-1)>>12}.issubset(pages),'axi_request','actual reads cross the requested page boundary')
        checks.require(not reads and not writes and not wdata,'completion','all AXI responses drained')
        for key,ch in [('ar','AR'),('r','R'),('aw','AW'),('w','W'),('b','B')]:checks.equal(actual['counters'][key],counts[ch],'counters',expected['name']+' '+ch)
        checks.equal(actual['counters']['read_bytes'],read_bytes,'counters','accepted R payload')
        checks.equal(actual['counters']['write_bytes'],write_bytes,'counters','WSTRB popcount')
        checks.equal(actual['counters']['read_wait'],read_wait,'counters','AR to R response wait cycles')
        checks.equal(actual['counters']['write_wait'],write_wait,'counters','AW to B response wait cycles')
        checks.equal(actual['counters']['cycles'],actual['stop']-actual['start']+1,'timing','epoch cycles independently bounded')
        status=expected['status']
        if isinstance(status,int):
            result=actual['result'];checks.equal(actual.get('guard_error',False),False,'completion','no sticky bus error');checks.equal(result['status'],status,'completion','firmware status')
            checks.equal(result['valid'],int(status==0),'completion','output validity')
            for field in ('session_lo','session_hi','sequence_lo','sequence_hi'):checks.equal(result[field],expected['request'][['session_lo','session_hi','sequence_lo','sequence_hi'].index(field)+2],'completion','identity '+field)
            checks.equal(result['payload_read'],expected['logical_read'],'counters','logical input bytes')
            checks.equal(result['payload_write'],expected['logical_write'],'counters','logical output bytes')
            checks.equal(result['cycles'],result['load_cycles']+result['compute_cycles']+result['write_cycles']+result['other_cycles'],'timing','disjoint firmware phases')
            checks.require(result['cycles']>0,'execution','real core mcycle')
            if status:
                checks.equal(len(traces),0,'reject','rejection before external submission')
                checks.equal(len(written),0,'reject','outputs untouched')
            else:
                checks.equal(result['rows'],expected['rows'],'tiling','all rows')
                checks.equal(result['tiles'],(expected['rows']+127)//128,'tiling','128 row blocks and tail')
                target=expected['request'][11]
                if expected['request'][6]==1:
                    blob=local(folder,expected['expected_path']).read_bytes()
                    if negative=='bad-golden':blob=bytes([blob[0]^1])+blob[1:];negative=None
                    wanted=set()
                    for row in range(expected['rows']):
                        for i in range(expected['row_bytes']):
                            addr=target+row*expected['destination_stride']+i;wanted.add(addr)
                            checks.equal(memory.get(addr,0),blob[row*expected['source_stride']+i],'data',hex(addr))
                    checks.equal(result['checksum'],expected['checksum'],'data','all transported input bytes summed by core')
                else:
                    reference=np.load(local(folder,expected['expected_path']),allow_pickle=False);values=[];wanted=set()
                    for token in range(expected['m']):
                        row=[]
                        for n in range(expected['n']):
                            addr=target+token*expected['output_stride']+n*4;wanted.update(range(addr,addr+4))
                            row.append(struct.unpack('<f',bytes(memory.get(addr+i,0) for i in range(4)))[0])
                        values.append(row)
                    values=np.array(values,dtype=np.float64);ref=reference.astype(np.float64);error=np.abs(values-ref)
                    thresholds=golden['thresholds']
                    for idx in np.ndindex(values.shape):checks.require(math.isfinite(values[idx]) and error[idx]<=thresholds['atol']+thresholds['rtol']*abs(ref[idx]),'data','FP32 '+str(idx))
                    nrmse=float(np.sqrt(np.mean(error**2))/max(float(np.sqrt(np.mean(ref**2))),1e-12));checks.require(nrmse<=thresholds['nrmse'],'data','FP32 NRMSE')
                checks.equal(written,wanted,'axi_write','each output byte exactly once; stride gaps untouched')
                checks.equal(write_bytes,expected['logical_write'],'counters','all output bytes on AXI')
                checks.require(read_bytes>=expected['logical_read'],'counters','physical read includes scalar lane overfetch')
                for addr in range(target-16,target):checks.equal(memory[addr],0xa5,'memory_protection','leading sentinel')
        else:
            checks.equal(actual['output_valid'],False,'fault','partial error output never valid')
            checks.require(actual['drained'] and actual['recovered'],'recovery','isolate/drain before native reset')
            if status=='IO_FAULT':checks.require(actual['guard_error'] and sum(int(r['resp'],16)!=0 for r in traces if r['ch'] in ('R','B'))>0,'fault','observed SLVERR/DECERR')
            else:checks.require(actual['pause_observed'],'fault','long pause timeout with in-flight transaction')
        summaries.append(dict(name=expected['name'],logical_read=expected.get('logical_read'),logical_write=expected.get('logical_write'),axi_read=read_bytes,axi_write=write_bytes,
            channels=dict(counts),cycles=actual['counters']['cycles'],read_wait=actual['counters']['read_wait'],write_wait=actual['counters']['write_wait'],result=actual.get('result')))
    checks.require(seen_partial,'axi_write','partial output strobes exercised')
    checks.require(seen_page,'axi_request','4KiB boundary split exercised')
    checks.require(all_counts['AR']>0 and all_counts['AW']>0,'axi_request','real external traffic')
    checks.equal(observations['protocol_error'],0,'axi_stability','every stalled channel stable')
    checks.require(observations['protocol_checks']>1000,'axi_stability','nonzero whole-execution protocol checks')
    checks.equal(observations['stack_guard'],[0xa5]*16,'memory_protection','actual local stack guard')
    checks.require(0<observations['stack_peak']<4096,'memory_protection','actual stack sentinel high water')
    return checks,dict(jobs=summaries,channels=dict(all_counts),stack_peak=observations['stack_peak'],scope=fixture['scope'])
