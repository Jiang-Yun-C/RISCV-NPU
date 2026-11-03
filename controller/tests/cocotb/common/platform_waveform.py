"""Independently reconstruct simplified-port accepted traffic from VCD."""
import json
from pathlib import Path


def check_waveform(directory):
    directory = Path(directory)
    observed = json.loads((directory/'observations.json').read_text())
    ids = {}; current = {}; updates = {}; events = []
    scopes = []; header = True; timestamp = 0

    def sample():
        nxt = current | updates
        if current.get('clk') == 0 and nxt.get('clk') == 1 and current.get('rst_n') == 1:
            state = current.get('phase_status', 0) & 7
            for channel, active, fields in (
                ('aw', current.get('axi_awvalid') and current.get('axi_awready'), ('axi_awaddr','axi_awlen')),
                ('w', state == 2 and current.get('axi_wready'), ('axi_wdata','axi_wstrb','axi_wlast')),
                ('ar', current.get('axi_arvalid') and current.get('axi_arready'), ('axi_araddr','axi_arlen')),
                ('r', state == 5 and current.get('axi_rvalid'), ('axi_rdata','axi_rid','axi_rlast')),
            ):
                if active:
                    values = [current.get(n) for n in fields]
                    if None in values:
                        raise ValueError('unknown active platform VCD payload')
                    events.append([timestamp, channel, *values])
        current.update(updates); updates.clear()

    for line in (directory/'cpu.vcd').read_text().splitlines():
        parts = line.split()
        if not parts:
            continue
        if header:
            if parts[0] == '$scope': scopes.append(parts[2])
            elif parts[0] == '$upscope': scopes.pop()
            elif parts[0] == '$var' and scopes == ['tb_cpu']: ids[parts[3]] = parts[4]
            elif parts[0] == '$enddefinitions': header = False
            continue
        if line[0] == '#':
            sample(); timestamp = int(line[1:])
        elif line[0] in '01xXzZ' and line[1:] in ids:
            updates[ids[line[1:]]] = int(line[0]) if line[0] in '01' else None
        elif line[0] in 'bB' and len(parts) == 2 and parts[1] in ids:
            updates[ids[parts[1]]] = None if any(c in parts[0].lower() for c in 'xz') else int(parts[0][1:], 2)
    sample()
    if not events or sorted(events) != sorted(observed['events']):
        raise ValueError(f'platform VCD/VPI traffic mismatch: {len(events)}/{len(observed["events"])}')
    report = {'status': 'PASS', 'handshake_checks': len(events)}
    (directory/'waveform-check.json').write_text(json.dumps(report, indent=2)+'\n')
    return report
