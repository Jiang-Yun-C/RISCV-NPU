"""Terminal observation and sealed raw checking for future, frozen runners.

This module changes no existing observer or DUT. API timing is supplied by the
guest; terminal observation closes only after the last time-advancing inspection.
"""
import csv
from collections import deque
from dataclasses import asdict, dataclass
import hashlib
import io
from pathlib import Path
import traceback


@dataclass(frozen=True)
class TerminalSample:
    cycle: int
    accepted: int
    responses: int
    transport_idle: bool
    timed_out: bool = False
    transport_activity: int = 0


async def close_after_inspection(inspect, sample, advance, *, deadline, stable_cycles=4):
    """Run inspection, then drain and observe unchanged counts over real clocks.

    sample/advance must use settled simulator values and advance at least one
    clock. No coroutine may advance simulation after the returned close sample.
    The parent checker still rejects any raw suffix beyond that sample.
    """
    if deadline <= 0 or stable_cycles < 1:
        raise ValueError('positive frozen deadline and stability interval required')
    inspected = await inspect()
    previous = None
    stable_since = None
    while True:
        current = sample()
        if min(current.cycle, current.accepted, current.responses, current.transport_activity) < 0:
            raise ValueError('negative terminal counter')
        if current.responses > current.accepted:
            raise ValueError('response without accepted write')
        if current.timed_out or current.cycle >= deadline:
            raise TimeoutError('original terminal observation deadline')
        if previous is not None:
            if current.cycle <= previous.cycle:
                raise ValueError('terminal observation must advance simulation')
            if current.accepted < previous.accepted or current.responses < previous.responses or current.transport_activity < previous.transport_activity:
                raise ValueError('counter reset during terminal observation')
        drained = current.accepted == current.responses and current.transport_idle
        unchanged = previous is not None and (
            current.accepted, current.responses, current.transport_idle, current.transport_activity
        ) == (previous.accepted, previous.responses, previous.transport_idle, previous.transport_activity)
        if not drained:
            stable_since = None
        elif stable_since is None or not unchanged:
            stable_since = current.cycle
        if stable_since is not None and current.cycle - stable_since >= stable_cycles:
            return inspected, dict(**asdict(current), stable=True,
                stable_since_cycle=stable_since, stable_cycles=stable_cycles,
                stage='AFTER_ALL_TIME_ADVANCING_INSPECTION')
        previous = current
        await advance()


def seal_cpu_trace(path, close, producer, *, require_exit=True, allowed_kinds=('CW', 'CB')):
    """Check the entire closed trace, including suffix, after producer exit.

    producer is the original subprocess.Popen handle. A live writer is rejected
    even when its currently visible prefix happens to be internally consistent.
    """
    if producer.poll() is None:
        raise ValueError('raw producer is still active; CSV may be unflushed')
    if producer.returncode != 0:
        raise ValueError('raw producer failed')
    if close.get('stage') != 'AFTER_ALL_TIME_ADVANCING_INSPECTION' or close.get('stable') is not True:
        raise ValueError('terminal snapshot did not close after inspection')
    if not close.get('transport_idle') or close['accepted'] != close['responses']:
        raise ValueError('terminal snapshot has outstanding transport work')
    if close.get('timed_out') or close['cycle'] - close.get('stable_since_cycle', close['cycle']) < close.get('stable_cycles', 1):
        raise ValueError('invalid terminal stability interval')
    path = Path(path)
    before = path.stat()
    digest = hashlib.sha256()
    pending = deque()
    accepts = responses = exits = 0
    exit_response = None
    last_cycle = -1
    records = 0
    with path.open('rb') as stream:
        for line in stream:
            digest.update(line)
            if not line.endswith(b'\n'):
                raise ValueError('truncated raw record')
            row = next(csv.reader(io.StringIO(line.decode('ascii'))))
            if len(row) != 6 or row[1] not in allowed_kinds:
                raise ValueError('unexpected raw record grammar')
            cycle = int(row[0])
            if cycle < last_cycle or cycle > close['cycle']:
                raise ValueError('raw event outside final observation boundary')
            last_cycle = cycle
            records += 1
            if row[1] == 'CW':
                address, data, strobe = (int(x, 16) for x in row[2:5])
                terminal = address == 0x10000020
                if terminal and (data != 0 or strobe != 15):
                    raise ValueError('failed terminal exit write')
                exits += int(terminal)
                accepts += 1
                pending.append((cycle, terminal))
            elif row[1] == 'CB':
                if not pending or int(row[4], 16) != 0:
                    raise ValueError('unmatched or failed B retirement')
                accepted_cycle, terminal = pending.popleft()
                if cycle < accepted_cycle:
                    raise ValueError('response before acceptance')
                responses += 1
                if terminal:
                    exit_response = cycle
    after = path.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
        raise ValueError('raw changed during sealing')
    if not records or pending or accepts != responses:
        raise ValueError('incomplete raw write ledger')
    if (accepts, responses) != (close['accepted'], close['responses']):
        raise ValueError('complete raw differs from final live counters')
    if require_exit and (exits != 1 or exit_response is None):
        raise ValueError('exactly one retired terminal exit required')
    return dict(path=str(path), sha256=digest.hexdigest(), bytes=after.st_size,
        records=records, accepted=accepts, responses=responses,
        exit_response_cycle=exit_response, close_cycle=close['cycle'],
        producer_returncode=producer.returncode, entire_file_checked=True,
        scope='CPU_WRITE_TRACE_ONLY_TRANSPORT_CALLBACK_REQUIRES_SEPARATE_RAW_CHECK')


def finalize_measurement(run, producer_exit, check):
    """Make a new receipt terminal even when its checker/finalizer raises.

    The caller must copy required raw files before invoking this function. It
    never edits an older receipt or converts an earlier failed step into PASS.
    """
    code = 1
    try:
        if producer_exit != 0:
            raise ValueError('measurement producer failed: ' + str(producer_exit))
        check()
        code = 0
    except BaseException:
        (run.path / 'finalizer-failure.txt').write_text(traceback.format_exc())
    finally:
        code = run.finish(code)
    return code
