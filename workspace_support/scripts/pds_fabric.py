#!/usr/bin/env python3
"""Project entry for the qualified PDS/PVC/XVC/ATK link; no programming path."""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'configs/pds-fabric-link.json'
RUN_ID = re.compile(r'[A-Za-z0-9_-]{1,24}\Z')


def read(path):
    return json.loads(path.read_text())


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def need(ok, message):
    if not ok:
        raise ValueError(message)


def local(name):
    path = (ROOT / name).resolve()
    need(ROOT in path.parents, 'Project path escapes workspace: ' + name)
    return path


def contract():
    c = read(CONFIG)
    need(c['schema'] == 'pds-fabric-qualified-link-v1', 'Unknown link contract')
    b = read(local(c['physical_binding']))
    need(b['source_content_id'] == c['source_content_id'],
         'Current physical binding differs; select and qualify its own FIC/runner')
    need(sha(local(c['FIC'])) == c['FIC_sha256'], 'Matching FIC changed')
    inventory = local(c['qualified_inventory'])
    need(sha(inventory) == c['qualified_inventory_sha256'], 'Qualification inventory changed')
    frozen = read(inventory)['files']
    for name, digest in c['implementation_sha256'].items():
        need(sha(local(name)) == digest, 'Qualified implementation changed: ' + name)
        if name in frozen:
            need(digest == frozen[name], 'Implementation differs from qualification: ' + name)
    verifier = c['qualified_verifier']
    need(sha(local(verifier)) == frozen[verifier], 'Qualified verifier changed')
    need(c['runner'] in c['implementation_sha256'], 'Unpinned runner')
    for name, digest in c['dependency_recovery']['files_sha256'].items():
        need(sha(local(name)) == digest, 'Dependency recovery copy changed: ' + name)
    return c


def lock_state(c):
    path = local(c['board_lock'])
    if not path.exists():
        return 'ABSENT'
    with path.open('r') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 'BUSY'
        fcntl.flock(stream, fcntl.LOCK_UN)
    return 'FREE_AT_CHECK'


def doctor(c):
    for name, digest in c['external_files'].items():
        need(sha(Path(name)) == digest, 'Installed executable missing or changed: ' + name)
    for name in c['external_directories']:
        need(Path(name).is_dir(), 'Required dependency directory missing: ' + name)
    return dict(status='PASS_OFFLINE_LINK_CONTRACT_AND_INSTALLED_FILES',
                config_sha256=sha(CONFIG), implementation_files=len(c['implementation_sha256']),
                board_lock=lock_state(c), physical_link='NOT_CHECKED_NO_HARDWARE_OPEN',
                prior_qualification=c['qualified_evidence'], guide=c['guide'])


def run_path(c, run_id):
    need(bool(RUN_ID.fullmatch(run_id)), 'run-id must be 1–24 letters, digits, _ or -')
    return local(c['evidence_root']) / run_id


def state(c, run_id):
    path = run_path(c, run_id)
    need((path / 'SESSION.json').is_file(), 'No reusable session receipt: ' + run_id)
    session = read(path / 'SESSION.json')
    need(session['run_id'] == run_id and session['source_content_id'] == c['source_content_id'],
         'Session identity differs')
    result = dict(run_id=run_id, evidence=str(path.relative_to(ROOT)),
                  xvc_port=session['xvc_port'], server_port=session['server_port'])
    if (path / 'FINAL.json').is_file():
        final = read(path / 'FINAL.json')
        closed_file = Path(session['stage']) / 'hardware-link/CLOSED.json'
        closed = closed_file.is_file() and read(closed_file).get('HID_closed') is True
        result.update(state='CLOSED' if final['status'] == 'CLOSED'
                      and final['host_exit'] == final['native_exit'] == 0 and closed
                      else 'INCOMPLETE_INSPECT_SAME_PIDS',
                      final=final, HID_closed=closed)
    elif (path / 'hardware-link/PIDS.json').is_file():
        result.update(state='INSPECT_RECORDED_PIDS_BEFORE_RECONNECT',
                      PIDS=read(path / 'hardware-link/PIDS.json'))
    else:
        result['state'] = 'PREPARED_OR_STARTUP_INCOMPLETE_NO_READY_PROOF'
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('doctor', help='Check pinned files/dependencies/lock; no hardware access')
    sub.add_parser('verify', help='Replay the sealed actual board/Fabric evidence; no hardware access')
    status = sub.add_parser('status', help='Read session receipts; recorded PIDs are not liveness proof')
    status.add_argument('--run-id')
    close = sub.add_parser('close', help='Request same session supervisor cleanup using its STOP file')
    close.add_argument('--run-id', required=True)
    connect = sub.add_parser('connect', help='Start a fresh qualified native Debugger/ATK session')
    connect.add_argument('--run-id')
    connect.add_argument('--seconds', type=int)
    connect.add_argument('--xvc-port', type=int)
    connect.add_argument('--server-port', type=int)
    connect.add_argument('--headless', action='store_true')
    connect.add_argument('--probe', action='store_true', help='Qualified 4000-bit read-only IDCODE probe')
    connect.add_argument('--prepare-only', action='store_true', help='Generate files only; no hardware access')
    args = parser.parse_args()
    c = contract()
    if args.action == 'doctor':
        return doctor(c)
    if args.action == 'status':
        if args.run_id:
            sessions = [state(c, args.run_id)]
        else:
            files = sorted(local(c['evidence_root']).glob('*/SESSION.json'),
                           key=lambda p: p.stat().st_mtime, reverse=True)[:10]
            sessions = [state(c, p.parent.name) for p in files]
        return dict(status='READ_ONLY_RECEIPTS', board_lock=lock_state(c), sessions=sessions,
                    physical_link='NOT_CHECKED_NO_HARDWARE_OPEN')
    if args.action == 'verify':
        checked = doctor(c)
        workflow = read(local(c['workflow_inventory']))
        need(bool(workflow['files']), 'Empty workflow inventory')
        for name, digest in workflow['files'].items():
            need(sha(local(name)) == digest, 'Fixed workflow artifact changed: ' + name)
        p = subprocess.run([sys.executable, '-B', str(local(c['qualified_verifier']))],
                           cwd=ROOT, capture_output=True, text=True, timeout=180)
        need(p.returncode == 0, 'Qualified evidence replay failed: ' + p.stderr[-2000:])
        result = json.loads(p.stdout)
        need(result['status'] == 'PASS_V6_BOARD_AND_NATIVE_FABRIC_WITH_OBSERVATION_LIMITS',
             'Unexpected qualification result')
        return dict(status='PASS_FIXED_CONNECTION_WORKFLOW_AND_REAL_BOARD_EVIDENCE',
                    doctor=checked, qualification=result, physical_actions=0)
    if args.action == 'close':
        s = state(c, args.run_id)
        if s['state'] == 'CLOSED':
            return dict(status='ALREADY_CLOSED_NO_ACTION', session=s)
        path = run_path(c, args.run_id)
        need((path / 'NATIVE_PIDS.json').is_file(),
             'Native supervisor was not recorded; inspect original startup, no stop issued')
        try:
            with (path / 'STOP').open('x') as stream:
                stream.write('Public entry requested same session cleanup; retain FPGA/model\n')
        except FileExistsError:
            pass
        return dict(status='CLOSE_REQUESTED_NOT_YET_PROVEN_CLOSED', run_id=args.run_id,
                    next='pds_fabric.py status --run-id ' + args.run_id, FPGA_reset=0)
    checked = doctor(c)
    need(checked['board_lock'] != 'BUSY', 'Board lock is busy; inspect/adopt existing task')
    run_id = args.run_id or datetime.now(timezone.utc).strftime('ila-%Y%m%dT%H%M%S')
    path = run_path(c, run_id)
    stage = Path(c['Windows_stage_root']) / (c['Windows_stage_prefix'] + run_id)
    need(not path.exists() and not stage.exists(), 'Existing run-id preserved; use a new run-id')
    defaults = c['defaults']
    seconds = args.seconds if args.seconds is not None else defaults['seconds']
    xvc = args.xvc_port if args.xvc_port is not None else defaults['xvc_port']
    server = args.server_port if args.server_port is not None else defaults['server_port']
    need(5 <= seconds <= 7200, 'seconds must be 5..7200')
    need(1024 <= xvc <= 65535 and 1024 <= server <= 65535 and xvc != server,
         'Ports must be distinct and within 1024..65535')
    argv = [sys.executable, '-B', str(local(c['runner'])), '--run-id', run_id,
            '--seconds', str(seconds), '--xvc-port', str(xvc), '--server-port', str(server)]
    for enabled, flag in [(args.headless or args.probe, '--headless'),
                          (args.probe, '--probe'), (args.prepare_only, '--prepare-only')]:
        if enabled:
            argv.append(flag)
    print(json.dumps(dict(status='DELEGATE_QUALIFIED_RUNNER', run_id=run_id,
                          evidence=str(path.relative_to(ROOT)), config_sha256=sha(CONFIG),
                          prepare_only=args.prepare_only, UART_open=False)), flush=True)
    os.chdir(ROOT)
    os.execv(sys.executable, argv)


if __name__ == '__main__':
    try:
        print(json.dumps(main(), ensure_ascii=False, indent=2))
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print(json.dumps(dict(status='REFUSED_OR_FAILED_PRESERVED', error=str(error)),
                         ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
