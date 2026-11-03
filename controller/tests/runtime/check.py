"""Score only CPU-produced observations against independently generated golden."""
import argparse
import json
import hashlib
from pathlib import Path
import sys
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tests/cocotb'))
from common.checks import Checks

def records(path):
    result={}
    for line in Path(path).read_text().splitlines():
        group,index,value=map(int,line.split())
        if (group,index) in result:raise ValueError('duplicate CPU output')
        if not 0<=value<=0xffffffff:raise ValueError('non-u32 observation')
        result[group,index]=value
    if not result:raise ValueError('empty CPU output')
    return result

def score(observed,golden,profile,checks=None):
    c=checks or Checks();used=set()
    def get(g,i):
        c.require((g,i) in observed,'output_set',f'missing {g}/{i}');used.add((g,i));return observed[g,i]
    def eq(g,i,want,category):c.equal(get(g,i),int(want)&0xffffffff,category,f'{g}/{i}')
    def binary(g,data,category):
        eq(g,0,len(data),category)
        for i,b in enumerate(data):eq(g,i+1,b,category)
    threshold_bytes=(ROOT/'configs/t05-thresholds.json').read_bytes()
    c.equal(hashlib.sha256(threshold_bytes).hexdigest(),golden['thresholds_sha256'],'input_identity','frozen numeric thresholds')
    thresholds=json.loads(threshold_bytes)
    def floats(group,expected,key,category):
        actual=np.asarray([get(group,i) for i in range(len(expected))],dtype='u4').view('f4').astype('f8')
        reference=np.asarray(expected,dtype='f4').astype('f8');error=np.abs(actual-reference)
        limits=thresholds['operators'].get(key) or thresholds['cumulative'][key]
        c.require(bool(np.isfinite(actual).all()),category,f'{group}: finite')
        allowed=limits['atol']+limits['rtol']*np.abs(reference)
        for i,(e,a) in enumerate(zip(error,allowed)):c.require(bool(e<=a),category,{'group':group,'index':i,'error':float(e),'limit':float(a)})
        nrmse=float(np.sqrt(np.mean(error**2))/max(np.sqrt(np.mean(reference**2)),1e-12))
        c.require(nrmse<=limits['nrmse'],category,{'group':group,'nrmse':nrmse,'limit':limits['nrmse']})
        return float(error.max())
    metrics={}
    if profile=='control':
        for i,v in golden['control'].items():eq(100,int(i),v,'memory' if 3<=int(i)<=8 or int(i) in (27,28) else 'session')
        for i in range(11):eq(101,i,0,'tokenizer_errors')
        for i,record in enumerate(golden['texts']):
            eq(200+i,0,0,'tokenizer');eq(200+i,1,len(record['ids']),'tokenizer')
            for j,v in enumerate(record['ids']):eq(200+i,j+2,v,'tokenizer')
            eq(300+i,0,0,'utf8');binary(400+i,record['decode'].encode(),'utf8')
        binary(500,golden['template'].encode(),'template')
        eq(501,0,len(golden['template_ids']),'template')
        for i,v in enumerate(golden['template_ids']):eq(501,i+1,v,'template')
        for i in range(11):eq(502,i,0,'utf8')
        binary(503,bytes([0xe4,0xb8,0xad,0xf0,0x9f,0x8c,0x8d,0xe4,0x41,0xff]).decode(errors='replace').encode(),'utf8')
        eq(700,0,0,'t11');eq(700,1,0,'t11')
        for i,v in enumerate(golden['t11_tile']['aq']):eq(701,i,v&255,'t11_integer')
        for i,v in enumerate(golden['t11_tile']['sa_bits']):eq(702,i,v,'t11_integer')
        for i,v in enumerate(golden['t11_tile']['dots']):eq(704,i,v,'t11_integer')
        metrics['t11_linear_max_abs']=floats(703,golden['t11_tile']['y'],'linear','t11')
        eq(700,5,0,'t11');eq(700,6,0,'t11_integer')
        metrics['full_width_norm_max_abs']=floats(705,golden['t11_tile']['norm'],'rmsnorm','t11')
        for i,v in enumerate([127,-127,0,0,2,-2,2,-2]):eq(706,i,v&255,'t11_integer')
        c.require(0<get(700,2)<8192,'memory','full session state below private budget')
        eq(700,3,15728640,'memory');eq(700,4,(5*896+2*4864+151936)*4,'memory')
    elif profile=='small':
        eq(600,0,0,'model')
        for step,reference in enumerate(golden['small']['steps']):
            eq(600,step+1,0,'model');eq(600,step+4,reference['argmax'],'model')
            metrics[f'logits_{step}_max_abs']=floats(610+step,reference['logits'],'logits_24_layers','model')
            floats(620+step,reference['k'],'kv','kv');floats(630+step,reference['v'],'kv','kv')
        for i,v in {7:24,8:1,9:3,10:0,11:0,12:0,14:327680,15:2048,16:0}.items():eq(600,i,v,'dispatch' if i in (7,8,11) else 'session')
        c.require(0<get(600,13)<8192,'memory','static session footprint')
        eq(600,17,0,'session');eq(600,18,0,'session');eq(600,19,golden['small']['steps'][0]['argmax'],'model')
        floats(640,golden['small']['steps'][0]['logits'],'logits_24_layers','reset')
    else:raise ValueError('unregistered runtime profile')
    c.require(get(900,0)>0,'timing','actual elapsed ticks')
    c.equal(sorted(observed),sorted(used),'output_set','exact CPU output set, no traps or unknown diagnostics')
    return c,metrics

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('output');p.add_argument('golden');p.add_argument('profile',choices=['control','small']);p.add_argument('--report')
    a=p.parse_args();c=Checks()
    try:
        c,metrics=score(records(a.output),json.loads(Path(a.golden).read_text()),a.profile,c)
    finally:
        if a.report:c.save(a.report)
    print(json.dumps({'status':'PASS','checks':sum(c.counts.values()),'metrics':metrics},indent=2))
