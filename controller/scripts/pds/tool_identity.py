"""Bind an experimental PDS run to its checked installation and receipts."""
import hashlib
import json
import os
from pathlib import Path


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def checked_tool(contract_path, evidence_path, require_environment=False):
    contract_path, evidence_path = Path(contract_path).resolve(), Path(evidence_path).resolve()
    contract = json.loads(contract_path.read_text())
    manifest = json.loads((evidence_path / 'manifest.json').read_text())
    checks = json.loads((evidence_path / 'checks.json').read_text())['checks']
    if manifest['status'] != 'PASS' or not checks or any(c['status'] != 'PASS' for c in checks):
        raise ValueError('PDS contract receipt did not pass')
    if sha(evidence_path / 'pds-toolchain.json') != sha(contract_path):
        raise ValueError('PDS receipt binds another contract')
    home = Path(contract['home']).resolve()
    if str(home) != contract['resolved_home']:
        raise ValueError('PDS installation path changed')
    for name, digest in contract['binary_sha256'].items():
        if sha(home / 'bin' / name) != digest:
            raise ValueError('PDS binary changed: ' + name)
    if sha(contract['license']['path']) != contract['license']['sha256']:
        raise ValueError('PDS license identity changed')
    effective = json.loads((evidence_path / 'effective-environment.json').read_text())
    expected = {'PDS_HOME': str(home), 'PANGO_LICENSE_FILE': contract['license']['path']}
    for key, value in expected.items():
        if Path(effective[key]).resolve() != Path(value).resolve():
            raise ValueError('PDS receipt environment mismatch: ' + key)
        if require_environment and Path(os.environ.get(key, '')).resolve() != Path(value).resolve():
            raise ValueError('PDS execution environment mismatch: ' + key)
    doctor = (evidence_path / 'logs/doctor.stdout.log').read_text()
    if contract['version'] not in doctor.splitlines() or 'PDS_LICENSE_PROBE_OK' not in doctor or 'LICENSE=PASS' not in doctor:
        raise ValueError('PDS licensed Tcl/version markers missing')
    target_receipt = contract.get('target_ads_evidence')
    if target_receipt:
        target_path = Path(target_receipt)
        target = json.loads(target_path.read_text())
        if (target['status'] != 'PASS' or target['version'] != contract['version']
                or target['build'] != contract['build'] or not all(target['checks'].values())):
            raise ValueError('Exact-target ADS qualification missing')
        for name, digest in target['artifacts'].items():
            if sha(target_path.parent / name) != digest:
                raise ValueError('Exact-target ADS artifact changed: ' + name)
    identity = {'contract': str(contract_path), 'contract_sha256': sha(contract_path),
                'evidence': str(evidence_path), 'evidence_manifest_sha256': sha(evidence_path / 'manifest.json'),
                'version': contract['version'], 'build': contract['build'], 'home': str(home),
                'receipt_files': {str(p.relative_to(evidence_path)): sha(p)
                                  for p in evidence_path.rglob('*') if p.is_file()},
                'target_ads_manifest_sha256': sha(target_receipt) if target_receipt else None}
    return contract, identity


def implementation_tool(run, require_environment=False):
    config = json.loads((Path(run) / 'inputs.json').read_text())
    bound = config.get('tool_identity')
    if bound is None:
        return None, None
    contract, actual = checked_tool(bound['contract'], bound['evidence'], require_environment)
    if actual != bound or sha(Path(run) / 'pds-toolchain.json') != actual['contract_sha256']:
        raise ValueError('Implementation PDS binding changed')
    return contract, actual
