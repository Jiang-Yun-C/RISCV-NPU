#!/usr/bin/env python3
"""Portable read-only host-file verification; never opens hardware or starts a service."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def main():
    manifest = json.loads((ROOT / 'HOST_MANIFEST.json').read_text(encoding='utf-8'))
    actual = {}
    for name, expected in manifest['files'].items():
        path = (ROOT / name).resolve()
        if ROOT not in path.parents or not path.is_file():
            raise ValueError('Missing/invalid host file: ' + name)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != expected:
            raise ValueError('Host file changed: ' + name)
        actual[name] = digest
    content = ''.join(name + '\0' + actual[name] + '\n' for name in sorted(actual)).encode()
    digest = hashlib.sha256(content).hexdigest()
    if digest != manifest['host_content_sha256']:
        raise ValueError('Host content identity mismatch')
    binding = json.loads((ROOT / 'static/binding.json').read_text(encoding='utf-8'))
    if any(binding.get(k) != v for k, v in manifest['historical_board_binding'].items()):
        raise ValueError('Historical board binding mismatch')
    print(json.dumps(dict(status='PASS_READ_ONLY_HOST_FILES', host_content_sha256=digest,
                         files=len(actual), hardware_actions=0, historical_board_binding_only=True), indent=2))

if __name__ == '__main__':
    main()
