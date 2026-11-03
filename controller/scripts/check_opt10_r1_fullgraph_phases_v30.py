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
    # Stream the raw CPU write ledger independently of cocotb's live counters.
    accepts=responses=0;pending=[];exit_accepts=[];exit_retired=None
    with (directory/'transactions.csv').open() as stream:
        for row in csv.reader(stream):
            if len(row)!=6:raise ValueError('malformed raw bus ledger')
            cycle=int(row[0]);kind=row[1]
            if kind=='CW':
                address,data,strobe=(int(x,16) for x in row[2:5]);accepts+=1
                terminal=address==0x10000020
                pending.append((cycle,terminal))
                if terminal:
                    if data or strobe!=15:raise ValueError('failed/incomplete terminal CPU exit write')
                    exit_accepts.append((cycle,accepts))
            elif kind=='CB':
                responses+=1
                if not pending or int(row[4],16):raise ValueError('unmatched/failed CPU B retirement')
                accepted_cycle,terminal=pending.pop(0)
                if cycle<accepted_cycle:raise ValueError('CPU response before its write acceptance')
                if terminal:exit_retired=cycle
    drain=observation.get('terminal_drain',{})
    if len(exit_accepts)!=1 or exit_retired is None or pending or accepts!=responses:
        raise ValueError('terminal CPU exit B not retired or outstanding CPU writes')
    if drain.get('stable') is not True or (drain.get('accepted'),drain.get('responses'))!=(accepts,responses):
        raise ValueError('raw terminal CPU write ledger differs from live stable counters')
    if exit_retired>drain.get('cycle',-1):raise ValueError('terminal B after closed observation')
    terminal=dict(accepted=accepts,responses=responses,exit_accept_cycle=exit_accepts[0][0],exit_response_cycle=exit_retired,stable_close_cycle=drain['cycle'])
    return dict(terminal_CPU_retirement=terminal,scope='ONE_ACTUAL_COMPLETE_GRAPH_NOT_FORTY_MODE_CALIBRATION',linear=linear,vector=vector,linear_backend_cycles=sum(x['cycles'] for x in linear),sfu_backend_cycles=sum(x['cycles'] for x in vector),linear_read_bytes=sum(x['read_bytes'] for x in linear),linear_write_bytes=sum(x['write_bytes'] for x in linear),vector_read_bytes=sum(x['read_bytes'] for x in vector),vector_write_bytes=sum(x['write_bytes'] for x in vector))
