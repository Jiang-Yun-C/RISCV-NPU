"""Independently decode the captured SPI waveform window."""
import csv
import json
from pathlib import Path
def check_waveform(directory):
    d=Path(directory);ids={};levels={};time=0;bits=0;tx=rx=0;decoded=[];enabled=True
    for line in (d/'cpu.vcd').open():
        p=line.split()
        if p and p[0]=='$var':ids[p[3]]=p[4]
        elif line.startswith('#'):time=int(line[1:])
        elif '$dumpoff' in line:enabled=False
        elif line[:1] in ('0','1'):
            name=ids.get(line.strip()[1:]);v=int(line[0]);old=levels.get(name,0);levels[name]=v
            if name=='spi_cs' and v!=old:bits=0;tx=rx=0
            if name=='spi_sck' and v==1 and old==0 and enabled:
                tx=tx*2+levels.get('spi_mosi',1);rx=rx*2+levels.get('spi_miso',1);bits+=1
                if bits==8:decoded.append([time//10000,levels.get('spi_cs',1),tx,rx]);bits=0;tx=rx=0
    actual=[[int(r['cycle']),int(r['c']),int(r['a']),int(r['b'])] for r in csv.DictReader((d/'spi.csv').open())]
    if not decoded or [p[1:] for p in decoded]!=[p[1:] for p in actual[:len(decoded)]]:raise ValueError('SPI VCD/independent sampler mismatch')
    if any(abs(a[0]-b[0])>1 for a,b in zip(decoded,actual)):raise ValueError('SPI VCD sample time mismatch')
    out=dict(status='PASS',scope='initialization and leading sector window; full transfer independently recorded in spi.csv',bytes=len(decoded),last_time_ps=time)
    (d/'waveform-check.json').write_text(json.dumps(out,indent=2)+'\n');return out
