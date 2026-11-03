"""CPU-to-CE64-to-writeback-to-CPU VCD correlation with absolute cycle indices."""
import csv,json
from pathlib import Path

def check_waveform(directory):
    d=Path(directory);scope=[];ids={};current={};updates={};time=0;header=True;actual=[];edges=0;first=None;last=0
    fields={'NA':('aw',('awaddr','awid','awsize')),'NW':('w',(None,'wdata','wstrb')),'NB':('b',(None,'bid','bresp')),'NR':('ar',('araddr','arid','arsize')),'ND':('r',('rid','rdata','rresp'))}
    dumped=True;windows=[];begin=0;cpu_read_active=False
    def sample():
        nonlocal edges,first,last,cpu_read_active
        nxt=current|updates
        if dumped and current.get('clk')==0 and nxt.get('clk')==1 and current.get('reset')==0:
            edges+=1;cycle=time//8000;first=cycle if first is None else first;last=cycle
            for kind,(channel,keys) in fields.items():
                if current.get('backend.'+channel+'valid')==1 and current.get('backend.'+channel+'ready')==1:
                    values=[0 if k is None else current.get('backend.'+k) for k in keys]
                    if None in values:raise ValueError('unknown active payload')
                    actual.append((cycle,kind,*values,current['owner']))
            # The head completion window contains the actual CPU readback,
            # after the backend has halted. Correlate those channels as well.
            if current.get('cpu_bus.rvalid')==1 and current.get('cpu_bus.rready')==1 and cpu_read_active:
                values=[current.get('cpu_bus.'+k) for k in ('rdata','rresp')]
                if None in values:raise ValueError('unknown active CPU read payload')
                actual.append((cycle,'CD',0,*values,current['owner']))
            if current.get('cpu_bus.arvalid')==1 and current.get('cpu_bus.arready')==1:
                address=current.get('cpu_bus.araddr');length=current.get('cpu_bus.arlen');size=current.get('cpu_bus.arsize')
                if None in (address,length,size):raise ValueError('unknown active CPU read request')
                cpu_read_active=0xac100000<=address<0xac200000 or length!=0 or address==0x1000300c
                if cpu_read_active:actual.append((cycle,'CR',address,length,size,current['owner']))
        current.update(updates);updates.clear()
    with (d/'cpu.vcd').open() as stream:
        for line in stream:
            parts=line.split()
            if not parts:continue
            if header:
                if parts[0]=='$scope':scope.append(parts[2])
                elif parts[0]=='$upscope':scope.pop()
                elif parts[0]=='$var':
                    if scope==['tb_cpu'] and parts[4] in ('clk','reset','owner'):ids[parts[3]]=parts[4]
                    elif scope==['tb_cpu','backend']:ids[parts[3]]='backend.'+parts[4]
                    elif scope==['tb_cpu','cpu_bus']:ids[parts[3]]='cpu_bus.'+parts[4]
                elif parts[0]=='$enddefinitions':header=False
                continue
            if line.startswith('$dumpoff'):sample();windows.append((begin,time//8000));dumped=False
            elif line.startswith('$dumpon'):
                sample()
                # $dumpon is idempotent while recording is already enabled. The
                # harness calls it each halted cycle; these are one continuous
                # readback window, not 2.3 million replacement windows.
                if not dumped:begin=time//8000;current.clear()
                dumped=True
            elif line[0]=='#':sample();time=int(line[1:])
            elif line[0] in '01xzXZ' and line.strip()[1:] in ids:updates[ids[line.strip()[1:]]]=int(line[0]) if line[0] in '01' else None
            elif line[0] in 'bB' and len(parts)==2 and parts[1] in ids:updates[ids[parts[1]]]=None if any(x in parts[0].lower() for x in 'xz') else int(parts[0][1:],2)
    sample()
    if dumped:windows.append((begin,time//8000))
    expected=[]
    with (d/'transactions.csv').open() as stream:
        for row in csv.reader(stream):
            if row[1] in {*fields,'CR','CD'} and any(lo<=int(row[0])<hi for lo,hi in windows):expected.append((int(row[0]),row[1],*(int(v,16) for v in row[2:5]),int(row[5])))
    actual=[v for v in actual if any(lo<=v[0]<hi for lo,hi in windows)]
    if edges<1000 or not actual or sorted(actual)!=sorted(expected):raise ValueError('VCD/AXI window correlation %d/%d'%(len(actual),len(expected)))
    head_reads={row[2] for row in actual if row[1]=='CR' and 0xac100000<=row[2]<0xac200000}
    config=json.loads((d/'case.json').read_text()) if (d/'case.json').exists() else {}
    if config.get('profile')=='head' and head_reads!={0xac100000+4*i for i in range(151936)}:
        raise ValueError('VCD full head CPU readback coverage: %d reads, windows=%r'%(len(head_reads),windows))
    result=dict(status='PASS',active_edges=edges,handshakes_compared=len(actual),head_readback_elements=len(head_reads) if config.get('profile')=='head' else 0,windows=windows,scope='VCD compares every backend handshake and every logged CPU AR/R handshake in these windows; head requires all 151936 actual CPU output reads')
    (d/'waveform-check.json').write_text(json.dumps(result,indent=2)+'\n');return result
