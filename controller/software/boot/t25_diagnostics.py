"""Independent raw-log checks for the instrumented T25 SD application."""
import re


def fields(line, prefix):
    if not line.startswith(prefix):
        raise ValueError('Wrong record')
    tokens = line[len(prefix):].split()
    result = {}
    for token in tokens:
        match = re.fullmatch(r'(\w+)=([0-9a-f]{16})', token)
        if not match or match[1] in result:
            raise ValueError('Malformed/duplicate counter')
        result[match[1]] = int(match[2], 16)
    return result


def telemetry(lines):
    """Require complete ordered snapshots; none of the zero-filled upper half."""
    snapshots = []
    current = None
    for line in lines:
        if line.startswith('T25 TELEMETRY BEGIN '):
            if current is not None:
                raise ValueError('Nested snapshot')
            current = dict(fields(line, 'T25 TELEMETRY BEGIN '), words=[])
            if set(current) != {'begin_ticks','end_ticks','status_after','profile','words'}:
                raise ValueError('Missing snapshot interval')
        elif line.startswith('T25 TELEMETRY WORD '):
            match = re.fullmatch(r'T25 TELEMETRY WORD ([0-9a-f]{8}) ([0-9a-f]{8})',line)
            if current is None or not match or int(match[1],16)!=len(current['words']):
                raise ValueError('Out-of-order/duplicate telemetry word')
            current['words'].append(int(match[2],16))
        elif line == 'T25 TELEMETRY END':
            if current is None or len(current['words'])!=64:
                raise ValueError('Incomplete snapshot')
            w=current['words']
            if w[:2]!=[0x34364543,2] or current['end_ticks']<current['begin_ticks']:
                raise ValueError('Identity/time mismatch')
            if w[2]&0x3ff!=0x307 or current['status_after']&0x3ff!=0x307:
                raise ValueError('Calibration/full/masks/seal/idle or fault flags')
            if w[7] or w[11] or w[15] or w[6]&15!=8 or not w[8]:
                raise ValueError('BIST failed or full-capacity qualification incomplete')
            snapshots.append(current);current=None
    if current is not None or not snapshots:
        raise ValueError('Missing complete telemetry')
    return snapshots


def u64(words,index):
    return words[index] | words[index+1]<<32


def pressure(before,after,min_seconds=3600,clock_hz=125000000):
    """Both snapshots precede OFF; CPU/CE payload deltas are actual handshakes."""
    if before['profile']!=2 or after['profile']!=2:
        raise ValueError('Pressure profile was not enabled at endpoints')
    if after['begin_ticks']-before['end_ticks']<min_seconds*clock_hz:
        raise ValueError('Insufficient measured pressure interval')
    a,b=before['words'],after['words']
    if b[12]<=a[12]:
        raise ValueError('No new pressure16MiB/masks pass inside the measured interval')
    changes={}
    for name,index in [('cpu_i',32),('cpu_d',40),('ce',48),('pressure',56)]:
        writes=u64(b,index)-u64(a,index);reads=u64(b,index+2)-u64(a,index+2)
        if writes<0 or reads<0 or not reads or (name!='cpu_i' and not writes):
            raise ValueError('Missing/regressing real traffic: '+name)
        if b[index+4]<a[index+4] or b[index+5]<a[index+5]:
            raise ValueError('Cumulative maximum regressed: '+name)
        changes[name]=dict(write_bytes=writes,read_bytes=reads,
            max_blocked_before=a[index+4],max_blocked_after=b[index+4],
            max_pending_before=a[index+5],max_pending_after=b[index+5])
    return dict(duration_ticks=after['begin_ticks']-before['end_ticks'],bus_deltas=changes,
                scope='Payload deltas over a pressure-enabled workload interval; maxima are cumulative since platform reset, not differences or pressure-only maxima; no cycle-by-cycle simultaneity claim')


def memory(lines,expected_regions):
    """Match board-reported readback counters to independently derived spans."""
    regions=[];reports=[]
    for line in lines:
        if line.startswith('T25 MEMORY REGION '):
            match=re.fullmatch(r'T25 MEMORY REGION ([0-9a-f]{8}) ([0-9a-f]{8}) ([0-9a-f]{8})',line)
            if not match or int(match[1],16)!=len(regions):
                raise ValueError('Duplicate/missing memory region')
            regions.append((int(match[2],16),int(match[3],16)))
        elif line.startswith('T25 MEMORY '):
            reports.append(fields(line,'T25 MEMORY '))
    if regions!=expected_regions or not reports:
        raise ValueError('Missing/unexpected committed DDR spans')
    measured=sum(n for _,n in regions)
    # 0..3 are authenticated loader store/readback counts; 5 is its 44-byte
    # timestamp/counter handoff. BSS and seven runtime arenas are verified here.
    runtime=regions[4][1]+sum(n for _,n in regions[6:])
    for r in reports:
        if r!={'committed_bytes':measured,'peak_committed_bytes':measured,
               'regions':len(regions),'runtime_write_readback_bytes':runtime}:
            raise ValueError('Counter total/readback mismatch')
    return dict(peak_application_committed_ddr_bytes=measured,regions=regions,
                runtime_write_readback_bytes=runtime,
                excludes='BIST test traffic, alignment holes, local SRAM stack; no heap or deallocation')
