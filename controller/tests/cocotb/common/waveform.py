"""Cross-check externally visible VCD handshakes/retirement against VPI records."""
import json
from pathlib import Path


def check_waveform(directory):
    directory=Path(directory)
    observed=json.loads((directory/'observations.json').read_text())
    expected={p:[e[:1]+e[2:] for e in observed[p+'_axi']] for p in ('i','d')}
    actual={'i':[],'d':[]};retired=[];ids={};current={};updates={};header=True;time=0;edges=0
    def sample():
        nonlocal edges
        nxt=current|updates
        if current.get('clk')==0 and nxt.get('clk')==1 and current.get('reset')==0:
            edges+=1
            cycle=time//10000
            for port in ('i','d'):
                fields={'ar':('addr','len'),'r':('data','resp','last')}
                if port=='d': fields.update(aw=('addr','len','size'),w=('data','strb','last'),b=('resp',))
                for ch,keys in fields.items():
                    prefix=f'{port}Axi_{ch}_'
                    if current.get(prefix+'valid')==1 and current.get(prefix+'ready')==1:
                        payload=[current.get(prefix+'payload_'+k) for k in keys]
                        if None in payload: raise ValueError('unknown active VCD payload')
                        actual[port].append([cycle,ch,*payload])
            if current.get('trace_retire')==1:
                retired.append([cycle,current['trace_pc'],current['trace_instruction']])
        current.update(updates);updates.clear()
    with (directory/'cpu.vcd').open() as stream:
        for line in stream:
            parts=line.split()
            if not parts: continue
            if header:
                if parts[0]=='$var': ids[parts[3]]=parts[4]
                elif parts[0]=='$enddefinitions': header=False
                continue
            if line[0]=='#':
                sample();time=int(line[1:])
            elif line[0] in '01xXzZ' and line.strip()[1:] in ids:
                updates[ids[line.strip()[1:]]]=int(line[0]) if line[0] in '01' else None
            elif line[0] in 'bB' and len(parts)==2 and parts[1] in ids:
                updates[ids[parts[1]]]=None if any(c in parts[0].lower() for c in 'xz') else int(parts[0][1:],2)
        sample()
    if edges!=observed['summary']['cycles']-12:
        raise ValueError('VCD incomplete active clock count')
    for port in ('i','d'):
        # Different channels at one cycle have no total ordering; compare sorted event tuples.
        if sorted(actual[port])!=sorted(expected[port]):
            raise ValueError(f'VCD/{port} VPI handshake mismatch: {len(actual[port])}/{len(expected[port])}')
    if not retired or retired!=observed['retire']:
        raise ValueError(f'VCD/VPI retirement mismatch: {len(retired)}/{len(observed["retire"])}')
    report={'status':'PASS','active_edges':edges,'i_handshakes':len(actual['i']),
            'd_handshakes':len(actual['d']),'retire_checks':len(retired)}
    (directory/'waveform-check.json').write_text(json.dumps(report,indent=2)+'\n')
    return report
