"""Observe real CPU reports, submissions, quantization, AXI and output reads."""
import csv,hashlib,json
from collections import deque,Counter
from pathlib import Path
import numpy as np
from common.checks import Checks
from scoreboard import Memory

def score(directory,fixture,golden,folder,checks=None,negative=None):
    d=Path(directory);folder=Path(folder);c=checks or Checks();mem=Memory(fixture['regions'],folder)
    p=folder/'golden.npz';c.equal(hashlib.sha256(p.read_bytes()).hexdigest(),golden['arrays_sha256'],'input_identity','independent numeric arrays')
    arrays=np.load(p,allow_pickle=False);threshold=Path(__file__).resolve().parents[2]/'configs/t05-thresholds.json';c.equal(hashlib.sha256(threshold.read_bytes()).hexdigest(),golden['thresholds_sha256'],'input_identity','frozen T05 thresholds');limits=json.loads(threshold.read_text())
    reports={};stages={};max_abs=0.;elements=0
    for line in (d/'cpu-output.txt').read_text().splitlines():
        g,i,v=map(int,line.split());c.require((g,i) not in reports,'output_set','unique CPU trace');reports[g,i]=v
    required=set()
    def expect(g,i,value,cat):required.add((g,i));c.equal(reports.get((g,i)),value&0xffffffff,cat,f'group={g}/index={i}')
    for g,i,v in [(1,0,0),(1,1,0),(1,2,1),(1,3,2*fixture['layers']*fixture['capacity']*fixture['kv']*4),(1,4,len(golden['jobs']))]:expect(g,i,v,'execution')
    for step in range(golden['steps']):
        length=step+1 if step<len(fixture['tokens']) else step-len(fixture['tokens'])+1
        expect(100+step,0,0,'completion');expect(100+step,1,length,'session')
    if fixture['profile']=='continuous':
        for i,v in enumerate([-1,9,1,0,0,-1,1,-4]):expect(2,i,v,'reset' if i in (3,4) else 'boundary')
    for i in range(len(golden['jobs'])):
        for z,v in enumerate([2,1,0,0]):expect(700+i,z,v,'dispatch')
        required.add((700+i,4));c.require(reports.get((700+i,4),0)>0,'timing','real dispatch ticks')
    for key,spec in golden['specs'].items():
        ref=arrays[key].copy();g=int(key);required|={(g,i) for i in range(ref.size)}
        c.require(all((g,i) in reports for i in range(ref.size)),'output_set',spec)
        got=np.array([reports[g,i] for i in range(ref.size)],dtype='<u4').view('<f4')
        if negative=='bad-golden' and not stages:ref.flat[0]+=100
        if negative=='bad-kv' and spec['stage']=='cache_k':ref.flat[0]+=100
        category='kv' if spec['stage'].startswith('cache_') else 'data'
        tol=limits['cumulative']['kv' if category=='kv' else 'logits_24_layers' if spec['stage']=='logits' else 'block']
        delta=np.abs(got.astype('f8')-ref);bad=~np.isfinite(got)|(delta>tol['atol']+tol['rtol']*np.abs(ref.astype('f8')))
        nrmse=float(np.sqrt(np.mean(delta**2))/max(np.sqrt(np.mean(ref.astype('f8')**2)),1e-12))
        first=int(np.flatnonzero(bad)[0]) if bad.any() else int(np.argmax(delta))
        c.require(not bad.any() and nrmse<=tol['nrmse'],category,dict(**spec,index=first,actual=float(got[first]),expected=float(ref[first]),nrmse=nrmse))
        # Count the independently compared elements, not merely array invocations.
        c.counts[category]+=ref.size-1;elements+=ref.size;max_abs=max(max_abs,float(delta.max()));stages[key]=dict(**spec,max_abs=float(delta.max()),nrmse=nrmse)
    layers=fixture['layers'];steps=golden['steps'];has_head=fixture['profile']!='block'
    expected_calls=[steps,steps*(2*layers+int(has_head)),steps*7*layers,steps*2*layers,steps*layers,steps*layers,steps*2*layers,steps*int(has_head)]
    profile={}
    for i,(name,count) in enumerate(zip(['embedding','rmsnorm','linear','rope','attention','swiglu','residual','head'],expected_calls)):
        expect(4,2*i+1,count,'dispatch');required.add((4,2*i));ticks=reports.get((4,2*i),0);c.require(ticks>0 if count else ticks==0,'timing','actual stage profile '+name);profile[name]=dict(calls=count,ticks=ticks,executor='CORAL_RVV_WITH_CPU_DISPATCH' if name in ('linear','head') else 'CPU_C_ON_REAL_CPU')
    c.equal(set(reports),required,'output_set','exact trace, dispatch and status inventory')
    expected_jobs=golden['jobs'];active=-1;request={};outstanding=0;ar=deque();aw=deque();w=deque();b=deque();outputs={};cpu_reads={};channels=Counter();read_address=0;cache=0
    for row in csv.reader((d/'transactions.csv').open()):
        cycle=int(row[0]);kind=row[1];a,data,extra=(int(v,16) for v in row[2:5]);owner=int(row[5]);channels[kind]+=1
        if kind=='CW':
            c.require(not 0x80000000<=a<0xa8000000,'protection','sealed model is read only')
            if 0xa8000000<=a<0xb4000000 or 0xba000000<=a<0xbc000000:
                c.equal(owner,0,'ownership','CPU shared write after release')
                if 0xa8000000<=a<0xac000000:c.require(a+4<=0xa8000000+2*fixture['layers']*fixture['capacity']*fixture['kv']*4,'gqa','KV contains two heads, no sevenfold replicas')
                for lane in range(4):
                    if extra>>lane&1:mem.write((a&~3)+lane,data>>(8*lane)&255)
            if 0x20010000<=a<0x20010060:request[(a-0x20010000)//4]=data
            if a==0x20030000 and data==0:
                active+=1;c.require(active<len(expected_jobs),'submission','no extra operator launch');j=expected_jobs[active]
                c.equal(owner,1,'ownership','launch under backend ownership');c.equal(outstanding,0,'visibility','drain before next request');c.equal(len(request),24,'submission','complete native descriptor')
                for ix,value in {0:0x4c4e3135,1:96,6:2,7:1,8:j['n'],9:j['k'],10:j['w_address'],11:0xac100000,12:j['sw_address'],14:0xac000000,15:0xac00a000,16:j['n']*4}.items():c.equal(request[ix],value,'submission',dict(job=active,field=ix))
                for key,address in [('aq',0xac000000),('sa',0xac00a000)]:
                    ref=arrays[f'job{active}.{key}'];observed=mem.read(address,ref.nbytes);wanted=ref.tobytes();first=next((i for i,(a,b) in enumerate(zip(observed,wanted)) if a!=b),None)
                    c.require(observed==wanted,'quantization',dict(job=active,key=key,first_byte=first,policy='integer and scale bitwise'))
                    c.counts['quantization']+=ref.size-1
                outputs[active]={};cpu_reads[active]={};request={}
            if a==0x10000100 and data==0:c.equal(outstanding,0,'visibility','release after actual R/B')
        elif kind=='CR':
            read_address=a
            if data==7 and 0xb4000000<=a<0xb8000000:cache+=1
            if 0xac100000<=a<0xac200000:c.equal(owner,0,'visibility','CPU consumes result after release');c.equal(data,0,'cache','shared result is not cached')
        elif kind=='CD':
            if 0xac100000<=read_address<0xac200000 and active>=0:
                off=read_address-0xac100000;ref=arrays[f'job{active}.y'];c.require(0<=off<ref.nbytes,'protection','CPU reads submitted Y');c.equal(extra,0,'axi','CPU actual read response')
                c.equal(data,int(ref.view('u4').flat[off//4]),'data',dict(job=active,stage='CPU_READ',offset=off));cpu_reads[active][off]=data
            read_address+=4
        elif kind=='NA':aw.append((a,data,extra));outstanding+=1;c.equal(owner,1,'ownership','backend write owner')
        elif kind=='NW':w.append((data,extra))
        elif kind=='NB':
            c.require(bool(b),'axi','paired B');addr,ident=b.popleft();c.equal(data,ident,'axi','B ID');c.equal(extra,0,'axi','B OKAY');outstanding-=1
        elif kind=='NR':ar.append((a,data,extra));outstanding+=1;c.equal(owner,1,'ownership','backend read owner')
        elif kind=='ND':
            c.require(bool(ar),'axi','paired R');addr,ident,size=ar.popleft();c.equal(a,ident,'axi','R ID');c.equal(extra,0,'axi','R OKAY');outstanding-=1
            aligned=addr&~15;end=(addr>>size<<size)+(1<<size);ref=int.from_bytes(bytes(mem.byte(aligned+i) if addr<=aligned+i<end else 0 for i in range(16)),'little')
            c.equal(data,ref,'read_data','real backend model/input read')
        elif kind=='EARLY':c.require(False,'visibility','early owner release')
        while aw and w:
            addr,ident,size=aw.popleft();value,strobe=w.popleft();b.append((addr,ident));ref=arrays[f'job{active}.y'];off=addr-0xac100000
            c.require(0<=off<ref.nbytes and off%4==0,'protection','backend output bounds');c.equal(strobe,15<<(addr&15),'axi','one FP32 output')
            actual=(value>>(8*(addr&15)))&0xffffffff;c.equal(actual,int(ref.view('u4').flat[off//4]),'data',dict(job=active,stage='CORAL_WRITE',offset=off))
            c.require(off not in outputs[active],'output_set','no duplicate backend output');outputs[active][off]=actual
            for lane in range(16):
                if strobe>>lane&1:mem.write((addr&~15)+lane,value>>(8*lane)&255)
    c.equal(active+1,len(expected_jobs),'submission','every operator launched once');c.equal(outstanding,0,'visibility','final drain');c.equal(channels['CW'],channels['CB'],'axi','all CPU write responses');c.require(cache>0,'cache','actual private cache refill')
    for i,j in enumerate(expected_jobs):
        wanted=set(range(0,j['n']*4,4));c.equal(set(outputs[i]),wanted,'output_set','all actual backend outputs');c.equal(set(cpu_reads[i]),wanted,'output_set','CPU consumed all backend outputs')
    for a in fixture['guards']:c.equal(mem.read(a,16).hex(),'a5'*16,'protection','shared guard')
    np.savez(d/'actual-stages.npz',**{key:np.array([reports[int(key),i] for i in range(arrays[key].size)],dtype='<u4').view('<f4') for key in golden['specs']})
    result=dict(profile=profile,linear_cpu_fallback_calls=0,linear_cpu_fallback_fraction=0.,steps=golden['steps'],jobs=len(expected_jobs),stage_elements=elements,max_abs=max_abs,stages=stages,channels=dict(channels),private_cache_refills=cache,gqa=dict(q_heads=14,kv_heads=2,physical_kv_bytes=2*fixture['layers']*fixture['capacity']*fixture['kv']*4))
    return result,c
