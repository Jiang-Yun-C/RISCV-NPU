"""Cross-check full backend VCD handshakes/payload/owner against passive CSV."""
import csv,json
from pathlib import Path

def check_waveform(directory):
    d=Path(directory);ids={};scope=[];current={};updates={};time=0;edges=0;owner_edges=0;actual=[]
    fields={'NA':('aw',('awaddr','awid','awsize')),'NW':('w',(None,'wdata','wstrb')),
            'NB':('b',(None,'bid','bresp')),'NR':('ar',('araddr','arid','arsize')),'ND':('r',(None,'rdata','rresp'))}
    def sample():
        nonlocal edges,owner_edges
        nxt=current|updates
        if current.get('owner')!=nxt.get('owner'):owner_edges+=1
        if current.get('clk')==0 and nxt.get('clk')==1 and current.get('reset')==0:
            edges+=1;cycle=time//10000
            for kind,(channel,keys) in fields.items():
                if current.get('backend.'+channel+'valid')==1 and current.get('backend.'+channel+'ready')==1:
                    payload=[0 if k is None else current.get('backend.'+k) for k in keys]
                    if None in payload:raise ValueError('unknown active backend VCD payload')
                    actual.append((cycle,kind,*payload,current['owner']))
        current.update(updates);updates.clear()
    header=True
    for line in (d/'cpu.vcd').open():
        parts=line.split()
        if not parts:continue
        if header:
            if parts[0]=='$scope':scope.append(parts[2])
            elif parts[0]=='$upscope':scope.pop()
            elif parts[0]=='$var':
                name=parts[4]
                if scope==['tb_cpu'] and name in ('clk','reset','owner'):ids[parts[3]]=name
                elif scope==['tb_cpu','backend'] and name!='aclk':ids[parts[3]]='backend.'+name
            elif parts[0]=='$enddefinitions':header=False
            continue
        if line[0]=='#':sample();time=int(line[1:])
        elif line[0] in '01xzXZ' and line.strip()[1:] in ids:updates[ids[line.strip()[1:]]]=int(line[0]) if line[0] in '01' else None
        elif line[0] in 'bB' and len(parts)==2 and parts[1] in ids:updates[ids[parts[1]]]=None if any(c in parts[0].lower() for c in 'xz') else int(parts[0][1:],2)
    sample()
    expected=[(int(r[0]),r[1],int(r[2],16),int(r[3],16),int(r[4],16),int(r[5])) for r in csv.reader((d/'transactions.csv').open()) if r[1] in fields]
    if edges<1000 or owner_edges<20:raise ValueError('missing clock/ownership VCD activity')
    if sorted(actual)!=sorted(expected):raise ValueError(f'VCD/passive AXI mismatch {len(actual)}/{len(expected)}')
    result={'status':'PASS','scope':'full backend handshake, payload, ID/response and owner cross-check',
        'active_edges':edges,'owner_edges':owner_edges,'handshakes_compared':len(actual),'last_time_ps':time}
    (d/'waveform-check.json').write_text(json.dumps(result,indent=2)+'\n');return result
