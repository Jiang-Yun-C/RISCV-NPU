import json,struct
from pathlib import Path
from collections import defaultdict
import numpy as np

def score(path,g,c):
    rows=defaultdict(dict)
    for line in Path(path).read_text().splitlines():
        group,index,value=map(int,line.split());c.require(index not in rows[group],'output_set',f'duplicate {group}/{index}');rows[group][index]=value
    expected_groups={int(x) for x in g['numeric']}|{int(x) for x in g['generated']}|{100,110,120,130,200,300,400,900}
    c.equal(set(rows),expected_groups,'output_set','all required groups and no extras')
    c.equal(set(rows[200]),set(g['checks']),'output_set','all contract scenarios executed')
    for i in g['checks']:c.equal(rows[200][i],1,'invalidation',f'contract scenario {i}')
    for group,expected in g['exact'].items():
        group=int(group);c.equal(set(rows[group]),set(range(len(expected))),'output_set',group)
        for i,v in enumerate(expected):c.equal(rows[group][i],v,'boundary' if group==120 else 'identity',f'{group}/{i}')
    for group,expected in g['generated'].items():
        group=int(group);c.equal([rows[group][i] for i in sorted(rows[group])],expected,'ids',group)
    max_abs=0
    for key,values in g['numeric'].items():
        group=int(key);c.equal(set(rows[group]),set(range(len(values))),'output_set',group)
        if group%10==5:
            c.equal(list(rows[group].values()),values,'kv','bounded valid lengths');continue
        a=np.array([rows[group][i] for i in range(len(values))],dtype='u4').view('f4');e=np.array(values,'f4')
        delta=np.abs(a-e);max_abs=max(max_abs,float(delta.max()))
        for i in range(len(values)):c.require(np.isfinite(a[i]) and delta[i]<=g['comparison']['atol']+g['comparison']['rtol']*abs(e[i]),'logits' if group%10==0 else 'kv',f'{group}/{i}: {a[i]} vs {e[i]}')
    for a,b in ((10,20),(50,60)):
        for j in range(5):c.equal(rows[a+j],rows[b+j],'cold_hot_exact',f'cold/hot {a+j}/{b+j}')
    c.equal(rows[300],{0:0,1:2,4:0,5:2},'request','both complete requests')
    c.equal(rows[900],{0:1,1:0},'request','raw restore observation window')
    c.equal(set(rows[400]),set(range(18)),'timing','nine actual timing pairs')
    ticks={name:rows[400][2*i]+(rows[400][2*i+1]<<32) for i,name in enumerate(('raw_restore','cold_with_diagnostics','cold_ttft','prepare','hot_with_diagnostics','hot_ttft','controller_restore','cold_request_total','hot_request_total'))}
    for name,n in ticks.items():c.require(n>0,'timing',name)
    c.require(ticks['hot_ttft']<ticks['cold_ttft'],'timing','same suffix improves measured CPU TTFT')
    return dict(ticks=ticks,max_abs=max_abs,state_bytes=rows[130][0],kv_bytes=rows[130][1],work_bytes=rows[130][2],scope=g['scope'])
