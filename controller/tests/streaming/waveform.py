"""VCD window independently checked against the whole-execution AXI trace."""
import csv,json
from pathlib import Path

def check_waveform(directory):
    directory=Path(directory);scope=[];ids={};current={};updates={};time=0;actual=[];last_edge=-1;header=True;edges=0
    fields={'AR':('ar',('araddr','arid','arlen','arsize','arburst')),'AW':('aw',('awaddr','awid','awlen','awsize','awburst')),
            'W':('w',('wdata','wstrb','wlast')),'R':('r',('rid','rdata','rlast','rresp')),'B':('b',('bid','bresp'))}
    def sample():
        nonlocal edges,last_edge
        nxt=current|updates
        if current.get('clk')==0 and nxt.get('clk')==1 and current.get('resetn')==1:
            edges+=1;last_edge=time//10000
            if current.get('counter_clear')==0:
                for ch,(signal,keys) in fields.items():
                    if current.get('bus.'+signal+'valid')==1 and current.get('bus.'+signal+'ready')==1:
                        payload=tuple(current.get('bus.'+key) for key in keys)
                        if None in payload:raise ValueError('unknown active VCD payload')
                        actual.append((last_edge,ch,*payload))
        current.update(updates);updates.clear()
    for line in (directory/'cpu.vcd').open():
        parts=line.split()
        if not parts:continue
        if header:
            if parts[0]=='$scope':scope.append(parts[2])
            elif parts[0]=='$upscope':scope.pop()
            elif parts[0]=='$var':
                if scope==['tb_cpu'] and parts[4] in ('clk','resetn','counter_clear'):ids[parts[3]]=parts[4]
                if scope==['tb_cpu','bus'] and parts[4]!='aclk':ids[parts[3]]='bus.'+parts[4]
            elif parts[0]=='$enddefinitions':header=False
            continue
        if line[0]=='#':sample();time=int(line[1:])
        elif line[0] in '01xzXZ' and line.strip()[1:] in ids:updates[ids[line.strip()[1:]]]=int(line[0]) if line[0] in '01' else None
        elif line[0] in 'bB' and len(parts)==2 and parts[1] in ids:updates[ids[parts[1]]]=None if any(c in parts[0].lower() for c in 'xz') else int(parts[0][1:],2)
    sample();expected=[]
    with (directory/'transactions.csv').open() as f:
        for rec in csv.DictReader(f):
            cycle=int(rec['cycle']);ch=rec['ch']
            if cycle>last_edge:continue
            keys={'AR':('addr','id','len','size','burst'),'AW':('addr','id','len','size','burst'),
                  'W':('data','strb','last'),'R':('id','data','last','resp'),'B':('id','resp')}[ch]
            expected.append((cycle,ch,*(int(rec[k],16) for k in keys)))
    if edges<1000 or not actual:raise ValueError(f'missing real waveform execution edges={edges} handshakes={len(actual)}')
    if sorted(actual)!=sorted(expected):raise ValueError(f'VCD/AXI window mismatch {len(actual)}/{len(expected)}')
    result=dict(status='PASS',scope='upload and first 20000 core cycles; full execution trace checked separately',edges=edges,handshakes_compared=len(actual),last_cycle=last_edge)
    (directory/'waveform-check.json').write_text(json.dumps(result,indent=2)+'\n');return result
