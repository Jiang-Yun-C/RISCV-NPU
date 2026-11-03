#!/usr/bin/env python3
"""Read-only verification of the published code snapshot; no external tools."""
from pathlib import Path
import hashlib
import json
import sys


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(root):
    manifest = json.loads((root / 'SNAPSHOT_MANIFEST.json').read_text())
    errors = []
    for relative, item in manifest['files'].items():
        path = root / relative
        if not path.is_file() or path.is_symlink():
            errors.append(relative + ': missing or not an ordinary file')
        elif path.stat().st_size != item['bytes'] or sha(path) != item['sha256']:
            errors.append(relative + ': content mismatch')
    freeze = json.loads((root / 'records/SOURCE_FREEZE.json').read_text())
    actual = {str(p.relative_to(root / 'controller')): sha(p)
              for p in (root / 'controller').rglob('*') if p.is_file()}
    if actual != freeze['source_inventory']:
        errors.append('controller: file inventory mismatch')
    cid = hashlib.sha256(json.dumps(actual, sort_keys=True,
                                   separators=(',', ':')).encode()).hexdigest()
    if cid != freeze['source_content_id'] or len(actual) != freeze['source_files']:
        errors.append('controller: source identity mismatch')
    host = json.loads((root / 'host_console/HOST_MANIFEST.json').read_text())
    for relative, expected in host['files'].items():
        path = root / 'host_console' / relative
        if not path.is_file() or sha(path) != expected:
            errors.append('host_console/' + relative + ': original host mismatch')
    if errors:
        print(json.dumps({'status': 'FAIL', 'errors': errors}, indent=2))
        return 1
    print(json.dumps({'status': 'PASS', 'snapshot_files': len(manifest['files']),
                      'controller_source_files': len(actual),
                      'controller_source_content_id': cid,
                      'host_files': len(host['files']) + 1,
                      'hardware_or_simulation_actions': 0}, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(verify(Path(__file__).resolve().parent))
