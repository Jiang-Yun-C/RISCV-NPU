"""Independent actual phase residency/payload ledger; no latency extrapolation."""
import csv
from pathlib import Path

def check(directory,observation):
    directory=Path(directory);linear=[];vector=[]
    for row in csv.reader((directory/'linear.csv').open()):
        if row[0]!='LCOMPLETE':raise ValueError('unexpected linear phase record')
        v=list(map(int,row[1:]));cycle,launch,status,ticks,load,compute,write,restore,rbytes,wbytes,mt,ml,mc,mw,mr=v
        if status or (ticks,load,compute,write,restore)!=(mt,ml,mc,mw,mr) or load+compute+write>ticks:raise ValueError('actual linear phase counters differ from passive residency')
        linear.append(dict(cycle=cycle,launch=launch,cycles=ticks,load=load,compute=compute,write=write,restore=restore,read_bytes=rbytes,write_bytes=wbytes))
    for row in csv.reader((directory/'vector.csv').open()):
        if row[0]!='COMPLETE':continue
        cycle,launch,status,ticks,load,compute,write,rbytes,wbytes,mt,ml,mc,mw,mr,mb=map(int,row[1:])
        if status or (ticks,load,compute,write,rbytes,wbytes)!=(mt,ml,mc,mw,mr,mb) or load+compute+write>ticks:raise ValueError('actual vector phase/payload counters differ from passive handshakes')
        vector.append(dict(cycle=cycle,launch=launch,cycles=ticks,load=load,compute=compute,write=write,read_bytes=rbytes,write_bytes=wbytes))
    if len(linear)!=169 or len(vector)!=218:raise ValueError('full actual graph command count')
    if sum(x['cycles'] for x in linear)!=observation['linear_backend_cycles'] or sum(x['cycles'] for x in vector)!=observation['sfu_backend_cycles']:raise ValueError('actual adapter cycle sums')
    launches=[x['launch'] for x in linear+vector]
    if len(set(launches))!=387:raise ValueError('repeated or missing graph launch identity')
    return dict(scope='ONE_ACTUAL_COMPLETE_GRAPH_NOT_FORTY_MODE_CALIBRATION',linear=linear,vector=vector,linear_backend_cycles=sum(x['cycles'] for x in linear),sfu_backend_cycles=sum(x['cycles'] for x in vector),linear_read_bytes=sum(x['read_bytes'] for x in linear),linear_write_bytes=sum(x['write_bytes'] for x in linear),vector_read_bytes=sum(x['read_bytes'] for x in vector),vector_write_bytes=sum(x['write_bytes'] for x in vector))
