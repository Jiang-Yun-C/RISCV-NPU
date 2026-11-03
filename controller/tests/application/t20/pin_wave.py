"""Passive VCD of all external peripheral pins; CPU does not report these values."""
from pathlib import Path
import cocotb
from cocotb.triggers import Event
from cocotb.utils import get_sim_time

async def capture(dut):
    names=['uart_tx','host_rx','i2c_scl','i2c_sda','gpio_led','pwm_pin','sensor_scl','sensor_sda']
    signals=[getattr(dut,n) for n in names];codes=[chr(33+i) for i in range(len(names))]
    out=Path('peripherals.vcd').open('w',buffering=1)
    tasks=[]
    try:
        out.write('$timescale 1ns $end\n$scope module peripherals $end\n')
        for n,c in zip(names,codes):out.write(f'$var wire 1 {c} {n} $end\n')
        out.write('$upscope $end\n$enddefinitions $end\n#0\n')
        previous=[str(s.value).lower() for s in signals]
        for c,v in zip(codes,previous):out.write(v+c+'\n')
        async def monitor(signal,code):
            while True:
                await signal.value_change
                out.write(f'#{int(get_sim_time(unit="ns"))}\n{str(signal.value).lower()}{code}\n')
        # Each task waits on a single trigger. Repeated First() races leave
        # cancellation children in cocotb 2.1 at regression cleanup.
        tasks=[cocotb.start_soon(monitor(s,c)) for s,c in zip(signals,codes)]
        await Event().wait()
    finally:
        for task in tasks:task.cancel()
        out.close()

def check(path):
    identifiers={};changes={};last=0
    for line in Path(path).read_text().splitlines():
        p=line.split()
        if p and p[0]=='$var':identifiers[p[3]]=p[4]
        elif line.startswith('#'):last=int(line[1:])
        elif line and line[0] in '01xz' and line[1:] in identifiers:
            n=identifiers[line[1:]];changes[n]=changes.get(n,0)+1
    if set(identifiers.values())!={'uart_tx','host_rx','i2c_scl','i2c_sda','gpio_led','pwm_pin','sensor_scl','sensor_sda'} or changes.get('uart_tx',0)<100 or changes.get('i2c_scl',0)<100 or last<1000:raise ValueError('missing peripheral pin waveform')
    return dict(changes=changes,last_ns=last,scope='passive full peripheral-pin transitions; separate startup CPU VCD remains bounded')
