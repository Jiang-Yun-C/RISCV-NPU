"""Decode UART frames from VCD and cross-check independent pin byte monitors."""
import json
from pathlib import Path

def decode(edges,divisor,with_times=False):
    bit=divisor*10000;index=0;result=[];previous=1
    while index<len(edges):
        start,value=edges[index]
        if previous==1 and value==0:
            end=start+bit*10;cursor=index;level=0;bits=[]
            for offset in range(10):
                sample=start+bit//2+offset*bit
                while cursor+1<len(edges) and edges[cursor+1][0]<=sample:
                    cursor+=1;level=edges[cursor][1]
                bits.append(level)
            if bits[0]!=0 or bits[9]!=1:raise ValueError('VCD UART framing')
            value=sum(bits[i+1]<<i for i in range(8))
            result.append((start,value) if with_times else value)
            while index<len(edges) and edges[index][0]<end:index+=1
            previous=1
        else:previous=value;index+=1
    return result

def check_waveform(directory):
    d=Path(directory);ids={};edges={'uart_rx':[],'uart_tx':[]};time=0
    with (d/'cpu.vcd').open() as stream:
        for line in stream:
            p=line.split()
            if p and p[0]=='$var':ids[p[3]]=p[4]
            elif line.startswith('#'):time=int(line[1:])
            elif line[:1] in ('0','1'):
                name=ids.get(line.strip()[1:])
                if name in edges:edges[name].append((time,int(line[0])))
    trace=json.loads((d/'uart-trace.json').read_text());cfg=json.loads((d/'case.json').read_text())
    counts={}
    for signal,key in [('uart_rx','rx'),('uart_tx','tx')]:
        frames=decode(edges[signal],cfg['uart_divisor'],True)
        actual=[v for _,v in frames];expected=[x[1] for x in trace[key]]
        if actual!=expected or not actual:raise ValueError('VCD/pin trace mismatch '+signal)
        for (frame_time,_),(cycle,_) in zip(frames,trace[key]):
            if not 0<=cycle-frame_time//10000<=cfg['uart_divisor']//4:
                raise ValueError('VCD/pin frame timestamp mismatch '+signal)
        counts[key]=len(actual)
    out={'status':'PASS','scope':'all UART frames including bad and truncated packets','bytes':counts,'last_time_ps':time}
    (d/'waveform-check.json').write_text(json.dumps(out,indent=2)+'\n');return out
