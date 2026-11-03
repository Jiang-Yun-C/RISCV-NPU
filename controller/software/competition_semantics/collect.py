#!/usr/bin/env python3
"""Collect every frozen public-development attempt, saving bytes before the next.

The default is a read-only plan. --capture opens the selected CP2102 UART; it
does not program a board, evaluate actuators, or substitute expected answers.
"""
import argparse
import base64
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import queue
import secrets
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from software.competition_semantics import evaluate
from software.demo_console.server import SerialBridge

HERE = Path(__file__).resolve().parent


def utc():
    return datetime.now(timezone.utc).isoformat()


def save_json(path, value, *, replace=False):
    """Fsync each completed export before making another serial request."""
    path = Path(path)
    temporary = path.with_name(path.name + '.writing') if replace else path
    with temporary.open('x', encoding='utf8') as output:
        output.write(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
        output.flush();os.fsync(output.fileno())
    if replace:os.replace(temporary, path)


def load_plan(manifest_path):
    manifest_path = Path(manifest_path).resolve()
    manifest = evaluate.load(manifest_path)
    dataset, commands, contract, prompts = evaluate.cases_and_commands()
    if manifest.get('schema') != 'competition-semantic-run-v1' or manifest.get('dataset_sha256') != evaluate.sha(evaluate.DATASET):
        raise ValueError('run must bind the frozen public-development set')
    if manifest.get('expected') != contract:raise ValueError('run identity/clock contract changed')
    records = manifest.get('records', [])
    ids = [case['id'] for case in dataset['cases']]
    if len(records) != len(ids) or {row.get('case_id') for row in records} != set(ids):
        raise ValueError('run must retain all 24 unique frozen cases')
    requests = [json.loads(line, object_pairs_hook=evaluate.unique_object)
                for line in (manifest_path.parent / 'requests.jsonl').read_text(encoding='utf8').splitlines()]
    if [row.get('case_id') for row in requests] != ids:raise ValueError('request order differs from the frozen plan')
    for row in requests:
        if row.get('command') != commands[row['case_id']] or row.get('prompt') != prompts[row['case_id']]:
            raise ValueError('a frozen request has changed')
    paths = set();indexed = {row['case_id']: row for row in records}
    for case_id in ids:
        row = indexed[case_id]
        path = (manifest_path.parent / row['export']).resolve()
        if not path.is_relative_to(manifest_path.parent) or path in paths or not path.parent.is_dir():
            raise ValueError('exports must be distinct paths in the prepared run')
        paths.add(path)
        if row.get('attempt_status') != 'pending' or path.exists() or path.with_suffix('.chunks.jsonl').exists():
            raise ValueError('capture refuses completed or partial attempts; create a new plan')
    if (manifest_path.parent / 'capture.lock').exists():raise ValueError('this plan has already been captured; create a new plan')
    return manifest_path, manifest, requests


class WireParser:
    """One parser instance across the connection preserves session ordering."""
    def __init__(self):
        self.process = subprocess.Popen(['node', str(HERE / 'protocol_worker.mjs')],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf8', bufsize=1)
        self.responses = queue.Queue()
        def read():
            for line in self.process.stdout:self.responses.put(line)
            self.responses.put('')
        self.reader = threading.Thread(target=read, daemon=True);self.reader.start()

    def call(self, **operation):
        self.process.stdin.write(evaluate.encode(operation) + '\n');self.process.stdin.flush()
        try:line = self.responses.get(timeout=10)
        except queue.Empty:raise ValueError('wire parser did not respond') from None
        if not line:raise ValueError('wire parser exited')
        return json.loads(line)

    def close(self):
        self.process.stdin.close()
        try:self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.process.kill();self.process.wait(timeout=2)
        self.reader.join(timeout=2);self.process.stdout.close();self.process.stderr.close()


class Capture:
    def __init__(self, bridge, owner, parser, *, wait_seconds, sync_seconds, source):
        self.bridge, self.owner, self.parser = bridge, owner, parser
        self.wait_seconds, self.sync_seconds, self.source = wait_seconds, sync_seconds, source
        self.after = 0;self.identity = None;self.capabilities = {};self.session = None

    def read_until_ready(self, *, timeout, journal=None, require_identity=False, require_result=False):
        chunks = [];events = [];wire = bytearray();failure = None;ready = False
        deadline = time.monotonic() + timeout
        while not ready:
            if time.monotonic() >= deadline:
                return chunks, wire, events, 'timeout', 'host wait deadline; disconnect does not cancel board inference'
            try:response = self.bridge.read(self.after, self.owner, wait=min(.25, max(0, deadline-time.monotonic())))
            except (OSError,ValueError,RuntimeError,KeyboardInterrupt) as exc:
                return chunks, wire, events, 'failed', str(exc) or 'capture interrupted; disconnect does not cancel inference'
            batch = []
            for incoming in response['chunks']:
                chunk = dict(incoming)
                try:data = base64.b64decode(chunk['data'], validate=True)
                except ValueError:return chunks, wire, events, 'failed', 'invalid receive base64'
                if chunk['seq'] != self.after + 1:return chunks, wire, events, 'failed', 'receive sequence gap'
                self.after = chunk['seq'];chunk['bytes'] = len(data);chunk['transport'] = 'python-serial-collector'
                if journal:
                    journal.write(evaluate.encode(chunk) + '\n')
                chunks.append(chunk);batch.append(chunk);wire.extend(data)
                if len(wire) > 2*1024*1024 or len(chunks) > 65536:
                    return chunks, wire, events, 'failed', 'capture exceeds bounded transcript capacity'
            if journal:journal.flush();os.fsync(journal.fileno())
            if batch:
                try:parsed = self.parser.call(operation='feed', chunks=batch)
                except (OSError,ValueError,RuntimeError,KeyboardInterrupt) as exc:
                    return chunks, wire, events, 'failed', str(exc) or 'capture interrupted; disconnect does not cancel inference'
                for event in parsed['events']:
                    events.append(event)
                    if event['type'] == 'identity':self.identity = {k:event[k] for k in ('model','tokenizer')}
                    if event['type'] == 'capabilities':self.capabilities = event
                    if event['type'] == 'request':self.session = event['request']['sessionHex']
                    if event['type'] == 'ready':
                        identity_seen = any(e['type']=='identity' for e in events)
                        result_seen = any(e['type']=='result' for e in events)
                        ready = (not require_identity or identity_seen) and (not require_result or result_seen)
                        self.session = None
                if parsed.get('error'):
                    return chunks, wire, events, 'failed', parsed['error']
            if response.get('error'):failure = response['error']
            if not response['connected'] and not ready:
                return chunks, wire, events, 'disconnected', failure or 'serial device disconnected'
        return chunks, wire, events, 'ready', failure

    def request(self, command, path, case_id, contract):
        timing = None;chunks = [];wire = bytearray();events = [];status = 'failed';error = None
        journal_path = path.with_suffix('.chunks.jsonl')
        with journal_path.open('x', encoding='utf8') as journal:
            try:
                timing = self.bridge.write(command, self.owner)
                chunks, wire, events, status, error = self.read_until_ready(timeout=self.wait_seconds, journal=journal, require_result=True)
            except (OSError, ValueError, RuntimeError) as exc:error = str(exc)
            except KeyboardInterrupt:error = 'capture interrupted; disconnect does not cancel board inference'
        results = [event for event in events if event['type'] == 'result']
        result = results[0] if len(results) == 1 else None
        complete = status == 'ready' and not error and result and result['complete']
        if status == 'ready':status = 'completed' if complete else 'failed'
        # A partial UTF-8 receive is retained byte-for-byte in rawChunks/journal.
        # Its replacement-character preview can never pass the final reparse.
        record = {'schema':'nexusrv-demo-v1','source':self.source,'fixture':self.source=='fixture',
            'case_id':case_id,'command':command,'raw':bytes(wire).decode('utf8', errors='replace'),
            'rawChunks':chunks,'complete':bool(complete),'error':error or (result or {}).get('error'),
            'clockHz':contract['clock_hz'],'identity':self.identity,
            'timing':{'host':timing},'finishedAt':utc(),
            'profiles':(result or {}).get('profiles'),'prefix':(result or {}).get('prefix'),
            'pmu':(result or {}).get('pmu'),'transfer':(result or {}).get('transfer')}
        if self.source=='fixture':record['fixture_note']='Explicit fake serial fixture; no model or board result.'
        save_json(path, record)
        verified = evaluate.node([{'case_id':case_id,'path':str(path),'expected_command':command}])['records'][0]
        if status == 'completed' and not verified['protocol_accepted']:status = 'failed'
        return status, {'export_sha256':evaluate.sha(path),'chunks_sha256':evaluate.sha(journal_path),
            'protocol_accepted':verified['protocol_accepted'],'issues':verified['issues'],
            'safe_ready':any(event['type']=='ready' for event in events) and error is None}


def collect(manifest_path, port, *, baud=115200, wait_seconds=86460, sync_seconds=30,
            bridge=None, source='live'):
    manifest_path, manifest, requests = load_plan(manifest_path)
    if source not in ('live','fixture'):raise ValueError('invalid capture source')
    if not 1 <= wait_seconds <= 172800 or not 1 <= sync_seconds <= 300:raise ValueError('invalid wait limits')
    directory = manifest_path.parent
    save_json(directory / 'capture.lock', {'startedAt':utc(),'plan_sha256':evaluate.sha(manifest_path),'source':source})
    owner = secrets.token_urlsafe(32);bridge = bridge or SerialBridge();parser = WireParser()
    capture = Capture(bridge, owner, parser, wait_seconds=wait_seconds, sync_seconds=sync_seconds, source=source)
    manifest['capture'] = {'status':'running','source':source,'port':port,'baud':baud,'startedAt':utc(),
        'wait_seconds':wait_seconds,'clock':'python.time.monotonic_ns',
        'parser_sha256':evaluate.sha(ROOT / 'software/demo_console/static/protocol.js'),
        'collector_sha256':evaluate.sha(Path(__file__))}
    save_json(manifest_path, manifest, replace=True)
    try:
        bridge.connect(port, owner, baud)
        bridge.write('', owner)
        chunks, wire, _, status, error = capture.read_until_ready(timeout=sync_seconds)
        save_json(directory / 'capture_sync.json', {'source':source,'rawChunks':chunks,
            'raw':bytes(wire).decode('utf8', errors='replace'),'status':status,'error':error})
        if status != 'ready' or error:raise ValueError(error or 'board did not become ready')
        if not capture.capabilities.get('textMax') or not capture.capabilities.get('identity'):
            raise ValueError('automatic capture requires bounded text and identity-query capabilities')
        if capture.capabilities.get('identity'):
            bridge.write(':identity', owner)
            chunks, wire, _, status, error = capture.read_until_ready(timeout=sync_seconds, require_identity=True)
            save_json(directory / 'capture_identity.json', {'source':source,'rawChunks':chunks,
                'raw':bytes(wire).decode('utf8', errors='replace'),'status':status,'error':error})
            if status != 'ready' or error:raise ValueError(error or 'identity query failed')
        manifest['capture']['observed_identity'] = capture.identity
        # Do not copy the expected hashes into observed identity. A mismatched
        # identity is actionable; an absent identity remains visibly unverified.
        expected = {k:manifest['expected'][k] for k in ('model','tokenizer')}
        if capture.identity != expected:raise ValueError('observed model/tokenizer identity differs from frozen run')
        manifest['capture']['identity_receipt_sha256'] = evaluate.sha(directory / 'capture_identity.json')
        indexed = {row['case_id']:row for row in manifest['records']}
        for request in requests:
            row = indexed[request['case_id']]
            path = (directory / row['export']).resolve()
            row['attempt_status'], detail = capture.request(request['command'], path, row['case_id'], manifest['expected'])
            row['capture'] = detail
            save_json(manifest_path, manifest, replace=True)
            if not detail['safe_ready']:
                raise ValueError('capture stopped after ' + row['case_id'] + '; remaining cases stay pending')
        manifest['capture']['status'] = 'all_attempts_saved'
    except (OSError, ValueError, RuntimeError, KeyboardInterrupt) as exc:
        manifest['capture'].update(status='stopped', error=str(exc) or 'interrupted')
    finally:
        try:bridge.disconnect()
        finally:parser.close()
        manifest['capture']['finishedAt'] = utc()
        save_json(manifest_path, manifest, replace=True)
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--port', help='explicit CP2102 port, only used by --capture')
    parser.add_argument('--baud', type=int, choices=(115200,500000), default=115200)
    parser.add_argument('--wait-seconds', type=float, default=86460,
                        help='host receive limit per request; default preserves the board 24-hour limit plus UART margin')
    parser.add_argument('--sync-seconds', type=float, default=30)
    parser.add_argument('--capture', action='store_true', help='open the real UART and save every attempt immediately')
    args = parser.parse_args(argv)
    try:
        path, manifest, requests = load_plan(args.run)
        if not args.capture:
            print(json.dumps({'status':'PLAN_ONLY','serial_opened':False,'cases':len(requests),
                'run':str(path),'exports':[row['export'] for row in manifest['records']]}, ensure_ascii=False, indent=2))
            return 0
        if not args.port:parser.error('--capture requires an explicit --port')
        manifest = collect(path,args.port,baud=args.baud,wait_seconds=args.wait_seconds,sync_seconds=args.sync_seconds)
        print(json.dumps(manifest['capture'],ensure_ascii=False,indent=2))
        return 0 if manifest['capture']['status']=='all_attempts_saved' else 2
    except (OSError,ValueError) as exc:
        parser.error(str(exc))


if __name__ == '__main__':raise SystemExit(main())
