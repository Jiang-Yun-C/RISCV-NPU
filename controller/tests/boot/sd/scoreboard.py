"""Reconstruct accepted AXI transfers; check SD bytes and actual DDR contents."""
from collections import deque
import csv
import json
from pathlib import Path
import struct
from common.checks import Checks,digest

def score(directory,fixture,golden,cfg,checks):
    d=Path(directory);trace=json.loads((d/'spi-trace.json').read_text());actions=trace['actions']
    checks.equal(len(actions),len(fixture['actions']),'protocol','registered attempt count')
    pins=[]
    for row in csv.DictReader((d/'spi.csv').open()):pins.append([int(row['cycle']),int(row['c']),int(row['a']),int(row['b'])])
    checks.equal([p[1:] for p in pins],[p[1:] for p in trace['bytes']],'pins','independent SV pin sampler matches card driver')
    for a,b in zip(pins,trace['bytes']):checks.require(abs(a[0]-b[0])<=1,'pins','SPI sample time')
    checks.require(bool(pins),'protocol','nonzero signal-level transactions')
    aw,w,reads,ireads=deque(),deque(),deque(),deque();pending=0;writes=[];retire=[];fences=[];ready=[];done=[];signatures=[];data_signatures=[];errors=[];refills=[]
    for row in csv.DictReader((d/'transactions.csv').open()):
        cy,a,b,c=(int(row[x]) for x in ('cycle','a','b','c'));kind=row['kind']
        if kind=='DA':checks.require(b==0 and c<=2,'axi_request','CPU write shape');aw.append((a,c))
        elif kind=='DW':w.append((cy,a,b,c))
        elif kind=='DB':checks.require(pending>0 and a==0,'axi_response','successful write response');pending-=1
        elif kind in ('DR','IA'):
            checks.require(c<=2 and a//4096==(a+(b+1)*(1<<c)-1)//4096,'axi_request','read shape');(reads if kind=='DR' else ireads).append([a,b+1,0])
            if kind=='IA':refills.append((cy,a,b))
        elif kind in ('DD','IR'):
            q=reads if kind=='DD' else ireads;checks.require(bool(q),'axi_response','R follows AR')
            checks.equal(b,0,'axi_response','RRESP');checks.equal(c,int(q[0][2]==q[0][1]-1),'axi_response','RLAST');q[0][2]+=1
            if c:q.popleft()
        elif kind=='T':
            (retire if 0xb4000000<=a<0xb4010000 else fences).append((cy,a,b))
        else:checks.require(False,'axi_request','unexpected bus event')
        while aw and w:
            addr,size=aw.popleft();cy,value,strobe,last=w.popleft();pending+=1
            checks.equal(last,1,'axi_write','WLAST');checks.require(strobe>0 and strobe&~(((1<<(1<<size))-1)<<(addr%4))==0,'axi_write','byte lanes')
            allowed=0x20000<=addr<0x30000 or 0xba000000<=addr<0xba100000 or 0xb4000000<=addr<0xb7ff1000 or 0x80000000<=addr<0xa8000000 or 0xb8000000<=addr<0xba000000 or 0x10000000<=addr<0x10000100 or 0x10002000<=addr<0x10002100
            checks.require(allowed,'protection','only SRAM, directory, final destinations and device registers written')
            if addr>=0x80000000 and not 0xba000000<=addr<0xba100000 and not 0xb7ff0000<=addr<0xb7ff1000:
                for lane in range(4):
                    if strobe&(1<<lane):writes.append((cy,(addr&~3)+lane,(value>>(8*lane))&255))
            if addr==0x10002018:ready.append((cy,value))
            if addr==0x1000201c:errors.append((cy,value))
            if addr==0x10002020:done.append((cy,value))
            if addr==0x10000024:signatures.append((cy,value))
            if addr==0x10000028:data_signatures.append((cy,value))
    checks.require(not aw and not w and pending==0,'axi_response','write transactions drained')
    checks.equal([v for _,v in done],list(range(1,len(actions)+1)),'completion','all attempt completions')
    checks.equal([v for _,v in signatures],golden['signatures'],'signature','CPU application execution')
    checks.equal([v for _,v in data_signatures],golden['signatures'],'cache','same-address application data visibility')
    windows=[(0xb4000000,65536),(0x80000000,131072),(0xb8000000,128)]
    memory={base:bytearray(n) for base,n in windows};payload_total=0;cmd_count=0;stack_peak=0
    for action,expected in zip(actions,fixture['actions']):
        checks.equal(action['index'],expected['index'],'protocol','ordered generation');checks.equal(action['name'],expected['name'],'protocol','attempt identity')
        start,end=action['start'],action['end'];image=Path(expected['image']).read_bytes();appstart,appbytes,appbase=struct.unpack_from('<3I',image,20)
        accepted=[(cy,a,v) for cy,a,v in writes if start<=cy<end];actual_ready=[v for cy,v in ready if start<=cy<end]
        checks.equal(actual_ready,[0,1] if expected['expected_error']==0 else [0],'seal','failure never publishes model')
        states=[v for cy,v in errors if start<=cy<end];checks.equal(states,[0,expected['expected_error']],'rejection','firmware error code')
        current_retire=[(cy,pc,insn) for cy,pc,insn in retire if start<=cy<end]
        if expected['expected_error']:
            checks.equal(len(current_retire),0,'rejection','invalid boot cannot enter application')
        else:
            checks.require(len(current_retire)>30,'execution','real instructions execute from DDR')
            publication=next(cy for cy,v in ready if start<=cy<end and v==1)
            checks.require(publication<current_retire[0][0],'seal','seal before application entry')
            for cy,pc,insn in current_retire:
                off=appstart*512+pc-appbase;checks.equal(insn,int.from_bytes(image[off:off+4],'little'),'cache','current downloaded instruction')
            for insn in (0x100f,0x500f):checks.require(any(start<=cy<current_retire[0][0] and v==insn for cy,_,v in fences),'visibility','cache maintenance')
            checks.require(any(start<=cy<end and addr==appbase and n==7 for cy,addr,n in refills),'cache','new DDR I refill')
        modelwrites=[];appwrites=[]
        for cy,a,v in accepted:
            if appbase<=a<appbase+appbytes:offset=appstart*512+a-appbase;appwrites.append((a,v))
            else:
                view=next((e for e in expected['views'] if e['address']<=a<e['address']+e['bytes']),None)
                checks.require(view is not None,'loading','only declared unique tensor bytes written')
                offset=expected['model_lba']*512+view['offset']+a-view['address'];modelwrites.append((a,v))
            checks.equal(v,image[offset],'loading','accepted byte matches external SD media')
            for base,n in windows:
                if base<=a<base+n:memory[base][a-base]=v;break
            else:checks.require(False,'protection','small-fixture write outside independently captured windows')
        checks.equal(len(set(a for a,_ in modelwrites)),len(modelwrites),'alias','no duplicate embedding/head copy')
        if expected['full_payload']:
            checks.equal(len(modelwrites),sum(e['bytes'] for e in expected['views']),'loading','all unique payload bytes, no padding/aliases copied')
            checks.equal(len(appwrites),appbytes,'loading','complete application bytes')
        snapshot=(d/f"snapshot-{action['index']}.bin").read_bytes();checks.equal(snapshot,b''.join(memory[base] for base,_ in windows),'loading','final DDR reconstructed from actual AXI writes')
        stack=(d/f"stack-{action['index']}.bin").read_bytes()
        touched=next((i for i,v in enumerate(stack) if v!=0x5a),len(stack))
        checks.require(touched>0 and len(stack)==32768,'protection','stack guard intact')
        stack_peak=max(stack_peak,32768-touched)
        commands=[c for c in trace['commands'] if c['index']==action['index']];cmd_count+=len(commands)
        if expected['fault']=='ddr-timeout':checks.equal(commands,[],'protocol','wait for DDR before SD accesses')
        elif expected['fault']!='init-timeout':
            checks.equal([c['cmd'] for c in commands[:7]],[0,8,55,41,55,41,58],'protocol','SDHC initialization sequence')
            checks.require(commands[0]['cycle']>=cfg.get('ddr_delay',1000),'protocol','DDR user port readiness precedes initialization')
            lbas=[c['arg'] for c in commands[7:]];checks.equal(lbas,list(range(len(lbas))),'protocol','strictly sequential single-sector stream')
        payload_total+=len(modelwrites)
    checks.equal(sum(len([1 for cy,_,_ in writes if a['start']<=cy<a['end']]) for a in actions),len(writes),'protection','no hidden destination writes between attempts')
    return dict(spi_bytes=len(pins),commands=cmd_count,loaded_model_bytes=payload_total,stack_peak_bytes=stack_peak,t10_cases=sorted(set(a['t10_case'] for a in fixture['actions'])))

def revalidate(directory,fixture,golden,cfg):
    d=Path(directory);checks=Checks();summary=score(d,fixture,golden,cfg,checks)
    trace=json.loads((d/'spi-trace.json').read_text());report=json.loads((d/'checks.json').read_text())
    checks.equal(digest([trace['bytes'],trace['commands'],trace['actions']]),report['sequence_sha256'],'archive','recomputed SPI sequence identity')
    checks.equal((d/'initial.bin').read_bytes(),bytes(golden['initial_bytes']),'initial_memory','unloaded initial memory')
    return dict(status='PASS',checks=sum(checks.counts.values()),**summary)
