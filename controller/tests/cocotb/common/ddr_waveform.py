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
            state = current.get('adapter_state', 0)
            for channel, active, fields in (
                ('saw', current.get('s_awvalid') and current.get('s_awready'), ('s_awaddr','s_awid','s_awlen','s_awsize','s_awburst')),
                ('sw', current.get('s_wvalid') and current.get('s_wready'), ('s_wdata','s_wstrb','s_wlast')),
                ('sar', current.get('s_arvalid') and current.get('s_arready'), ('s_araddr','s_arid','s_arlen','s_arsize','s_arburst')),
                ('sb', current.get('s_bvalid') and current.get('s_bready'), ('s_bid','s_bresp')),
                ('sr', current.get('s_rvalid') and current.get('s_rready'), ('s_rdata','s_rid','s_rresp','s_rlast')),
                ('aw', current.get('d_awvalid') and current.get('d_awready'), ('d_awaddr','d_awlen','d_awid')),
                ('w', state == 5 and current.get('d_wready'), ('d_wdata','d_wstrb','d_wlast')),
                ('ar', current.get('d_arvalid') and current.get('d_arready'), ('d_araddr','d_arlen','d_arid')),
                ('r', state == 8 and current.get('d_rvalid'), ('d_rdata','d_rid','d_rlast')),
            ):
                if active:
                    values = [current.get(n) for n in fields]
                    if None in values:
                        raise ValueError('unknown active DDR adapter VCD payload')
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
        raise ValueError(f'DDR adapter VCD/VPI traffic mismatch: {len(events)}/{len(observed["events"])}')
    report = {'status': 'PASS', 'handshake_checks': len(events)}
    (directory/'waveform-check.json').write_text(json.dumps(report, indent=2)+'\n')
    return report
