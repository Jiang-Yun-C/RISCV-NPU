"""Replay raw CPU + AXI records, including payload, burst policy and phase times."""
import csv,json
from collections import Counter,defaultdict,deque
from pathlib import Path
from tests.opt10.base_score import score as base_score

def score(directory,fixture,golden,folder,checks=None,negative=None):
    result,c=base_score(directory,fixture,golden,folder,checks,negative)
    d=Path(directory);cfg=json.loads((d/'case.json').read_text());switches=cfg['switches'];jobs=golden['jobs']
    reports={tuple(map(int,r.split()[:2])):int(r.split()[2]) for r in (d/'cpu-output.txt').read_text().splitlines()}
    for i,j in enumerate(jobs):
        c.equal(reports[10+i,25],0,'no_fallback','no CPU fallback hides DMA failure')
        c.equal(reports[10+i,27],0,'arbitration','CPU competing private DDR data intact')
        if j['pressure']:c.require(reports[10+i,26]>0,'arbitration','actual CPU pressure iterations')
        if not j['status']:
            c.require(reports[10+i,23]>0 and reports[10+i,24]>0,'timing','quantization and full dispatch/wait measured')
    phases=[]
    for row in csv.reader((d/'phases.csv').open()):
        v=list(map(int,row));i=v[1]-1
        for actual,expected,label in zip(v[3:8],v[10:15],('total','load','compute','write','restore')):
            c.equal(actual,expected,'phase_crosscheck',label+' counter vs independent cycle monitor')
        if v[2]==0:
            c.equal(v[8],v[15],'payload_crosscheck','CE read payload vs all actual R beats')
            c.equal(v[9],v[16],'payload_crosscheck','CE write payload vs all actual W strobes')
        if v[2]==0:c.require(v[17]>0 and v[18]>0,'physical_port','successful command uses DMA and compute on serialized SRAM')
        if jobs[i]['pressure']:c.require(v[19]>0,'arbitration','CPU shared DDR requests during CE ownership')
        phases.append(dict(name=jobs[i]['name'],status=v[2],cycles=v[3],load=v[4],compute=v[5],write=v[6],restore=v[7],
                           other=v[3]-sum(v[4:7]),payload_read=v[15],payload_write=v[16],scratch_dma_cycles=v[17],
                           scratch_control_cycles=v[18],shared_cpu_requests=v[19],cpu_elapsed=reports[10+i,8],
                           validate=reports[10+i,22],quantize=reports[10+i,23],execute=reports[10+i,24]))
    # Aborted commands can omit completion when a reset cancels publication.
    c.require(len(phases)>=sum(j['status']==0 for j in jobs),'phase_crosscheck','all successful commands have a timeline')
    commands=defaultdict(list);state_frames=defaultdict(list);dma_intervals=defaultdict(Counter);last_cmd=None;native=defaultdict(Counter)
    native_write_ends=defaultdict(list);physical_write_address=None
    for row in csv.reader((d/'timeline.csv').open()):
        cycle=int(row[0]);launch=int(row[2])-1
        if row[1]=='STATE':state_frames[launch].append((cycle,row[3],int(row[5]),int(row[6])))
        if row[1] in ('HMAR','HMAW'):
            word=int(row[3],16);beats=int(row[4])+1
            c.require((word&1023)+8*beats<=1024,'burst_boundary','native column boundary')
            if int(row[5]):
                native[launch]['lease_read_bus_bytes' if row[1]=='HMAR' else 'lease_write_bus_bytes']+=beats*32
                native[launch]['lease_reads' if row[1]=='HMAR' else 'lease_writes']+=1
        if row[1]=='HMAW':physical_write_address=0x80000000+int(row[3],16)*4
        if row[1]=='HMW' and int(row[3]):
            c.require(physical_write_address is not None,'native_protocol','native WLAST has accepted address')
            native_write_ends[physical_write_address&~31].append(cycle)
        if row[1]=='CMD':
            launch,write=int(row[2]),int(row[3]);a=int(row[4],16);size,length=int(row[5]),int(row[6])+1
            c.require(length<=32 and (a&4095)+(length<<size)<=4096,'burst_boundary','DMA command within 4KiB /32 beats')
            commands[launch-1].append((write,a,size,length))
            last_cmd=(cycle,launch-1,write)
        if row[1]=='RESULT' and last_cmd:
            start,idx,write=last_cmd;dma_intervals[idx]['write_cycles' if write else 'read_cycles']+=cycle-start+1;last_cmd=None
    backend_writes=deque()
    for row in csv.reader((d/'transactions.csv').open()):
        if row[1]=='NA':backend_writes.append(int(row[2],16))
        if row[1]!='NB':continue
        address=backend_writes.popleft()
        if row[1]=='NB' and int(row[4],16)==0:
            cycle=int(row[0])
            import bisect
            ends=native_write_ends[address&~31];idx=bisect.bisect_left(ends,cycle)-1
            c.require(idx>=0 and cycle-ends[idx]>=1024,'drain_baseline','successful B follows matching-address native WLAST by >=1024 cycles')
    for phase in phases:
        i=next(i for i,j in enumerate(jobs) if j['name']==phase['name'])
        frames=state_frames[i];hist=Counter()
        for (start,state,ph,restoring),(end,_,_,_) in zip(frames,frames[1:]):
            if state not in ('IDLE','DONE','PUBLISH'):hist[state]+=end-start
        if phase['status']==0:c.equal(sum(hist.values()),phase['cycles'],'phase_crosscheck','state residency independently accounts all CE cycles')
        phase.update(state_cycles=dict(hist),dma_intervals=dict(dma_intervals[i]),native=dict(native[i]))
    coverage=Counter();traffic=[]
    for i,j in enumerate(jobs):
        if j['status']:continue
        m,k=j['job']['a']['shape'][:2];n=j['job']['wq']['shape'][0];g=k//64
        w=j['job']['wq']['address'];sw=j['job']['sw']['address'];bias=j['job']['bias']['address'];y=j['job']['y']['address']
        counts=Counter();payload=Counter();weight_rows=Counter();sa_cmd=[]
        for write,a,size,beats in commands[i]:
            label='y' if write else 'w' if w<=a<w+n*k else 'sw' if sw<=a<sw+n*g*4 else 'bias' if bias<=a<bias+n*4 else 'aq' if 0xac000000<=a<0xac000000+m*k else 'sa' if 0xac00a000<=a<0xac00a000+m*g*4 else 'invalid'
            c.require(label!='invalid','payload_crosscheck','every DMA command has submitted tensor')
            counts[label]+=1;payload[label]+=beats<<size
            if label=='w':weight_rows[(a-w)//k]+=1
            if label=='sa':sa_cmd.append((a,size,beats))
            if label=='sw' and beats>1:coverage['B_scale_burst']+=1
            if label=='sw' and beats==32:coverage['scale_32']+=1
            if label=='y' and size==4:coverage['B_m1_pack']+=1
            if label=='y' and size==2:coverage['scalar_lane_'+str(a&15)]+=1
            if beats==32:coverage['burst32']+=1
            if a&4095==0:coverage['page_start']+=1
        expected=dict(aq=m*k,sa=m*g*4,w=n*k,sw=n*g*4,bias=n*4,y=m*n*4)
        c.equal(dict(payload),expected,'payload_crosscheck','exact useful bytes, no duplicate weights/scales or padding')
        c.equal(counts['sa'],(m*g+31)//32 if switches['SA_SCALE_BURST'] else m*g,'burst_policy','activation scale batching')
        if not switches['WEIGHT_ROW_BURST']:c.equal(counts['w'],n*g,'burst_policy','B one weight command per group')
        else:c.require(counts['w']<n*g,'burst_policy','row prefetch reduces weight commands')
        if m==1:
            c.equal(counts['y'],n//4+n%4,'burst_policy','inherited complete packs and scalar tails')
            coverage['tail'+str(n%4)]+=1
        else:c.equal(counts['y'],m*(n//4+n%4) if switches['M4_OUTPUT_PACK'] and n%4==0 else m*n,'burst_policy','per-token aligned pack or scalar stride fallback')
        traffic.append(dict(name=j['name'],shape=[m,n,k],commands=dict(counts),bytes=dict(payload)))
    for label in ('B_scale_burst','B_m1_pack','burst32','page_start','scalar_lane_0','scalar_lane_4','scalar_lane_8','scalar_lane_12'):
        c.require(coverage[label]>0,'coverage',label)
    for k in (896,4864):
        import numpy as np
        batch=np.load(d/f'actual-paired-{k}-m4.npy')
        serial=np.concatenate([np.load(d/f'actual-paired-{k}-row{r}.npy') for r in range(4)])
        c.equal(batch.tobytes(),serial.tobytes(),'m1_m4','same FP32 inputs and independent full-K output')
    result.update(phases=phases,traffic=traffic,transport_coverage=dict(coverage),overlap_proven=False)
    return result,c
