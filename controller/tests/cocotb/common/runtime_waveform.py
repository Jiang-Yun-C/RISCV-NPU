"""Require real clock/retirement in T12's bounded startup VCD window."""
import json
from pathlib import Path
def check_waveform(directory):
    d=Path(directory);ids={};rises=0;retire=0;time=0
    with (d/'cpu.vcd').open() as stream:
        for line in stream:
            p=line.split()
            if not p:continue
            if p[0]=='$var':ids[p[3]]=p[4]
            elif line.startswith('#'):time=int(line[1:])
            elif line.startswith('1'):
                name=ids.get(line.strip()[1:]);rises+=name=='clk';retire+=name=='trace_retire'
    if rises<1000 or retire<100 or time<10000000:raise ValueError('missing real runtime clock/retirement waveform')
    out={'status':'PASS','scope':'bounded initial 10000 cycles','clock_rises':rises,'retire_rises':retire,'last_time_ps':time}
    (d/'waveform-check.json').write_text(json.dumps(out,indent=2)+'\n');return out
