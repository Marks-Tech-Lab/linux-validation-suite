"""Routine unprivileged preparation/readiness, reusing the accepted builder.

No elevation, package installation, device/sensor access or physical workload.
Privileged promotion is a separately reviewed standalone administrator tool.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import sys
from .lvs_source_provenance import _source_snapshot,collect_source_provenance

ROOT=Path(__file__).resolve().parents[1]


def verify_components(root,manifest):
    from .lvs_storage_thermal_system import SystemAuthority
    from .lvs_storage_thermal_backend import capability
    from .lvs_storage_thermal_launch import prepare
    from .lvs_python_environment import python_policy
    policy=python_policy(root/'runtime')
    if sys.version_info[:2]<policy['minimum']:raise ValueError('Trusted system Python is below the shared LVS minimum; provision a trusted OS interpreter first')
    authority=SystemAuthority(root,manifest);uid,gid=authority.worker(confidential=False)
    try:authority.worker();system_worker_ready=True;system_reason=''
    except ValueError as exc:system_worker_ready=False;system_reason=str(exc)
    backend=capability(str(root/'runtime/build/fio'),str(root/'runtime/build/storage_thermal_guard'),uid=uid,gid=gid)
    if backend['status']!='available':raise ValueError('Installed tool/dependency failure: '+str(backend['reasons']))
    prepare(root/'runtime/build',allow_build=False)
    return dict(status='VERIFIED',source=manifest['source'],system_worker_ready=system_worker_ready,system_worker_reason=system_reason,system_python=dict(path=sys.executable,version=list(sys.version_info[:3]),minimum=policy['minimum']),fio_version=backend['fio_version'],worker_uid=uid,worker_gid=gid,scope='regular-file native policy test; no device access')


def runtime_status():
    from .lvs_storage_thermal_runtime import rpc,owned_path
    try:
        value=rpc('health')
        if value['source']!=_source_snapshot(ROOT)[0]:
            return dict(status='INCOMPATIBLE',ready=False,reason='Installed runtime/source mismatch',action='Prepare and approve an update using ./setup.sh → 9; restart LVS afterward')
        bootstrap=owned_path(Path(value['root'])/'runtime/build/storage_thermal_launch.so')
        if hashlib.sha256(bootstrap.read_bytes()).hexdigest()!=value['bootstrap_sha256']:raise ValueError('Installed bootstrap changed')
        blocked=value.get('recovery_blocker')or value.get('installation_blocker')
        return dict(status=('RECOVERY_BLOCKED'if value.get('recovery_blocker')else'MAINTENANCE')if blocked else'AVAILABLE',ready=not bool(blocked),reason=blocked or('Trusted service available; system-worker confidentiality unavailable: '+value.get('system_worker_reason','unknown')if value.get('system_worker_ready')is False else'Trusted service available; target/workload authorization remains separate'),components=value,action='Inspect canonical recovery; never clear ARMED'if blocked else'Use normal run-local Thermal Assist configuration')
    except (OSError,ValueError,KeyError,TypeError)as exc:
        return dict(status='PERMISSION_DENIED'if isinstance(exc,PermissionError)else'UNAVAILABLE',ready=False,reason=str(exc),action='Use ./setup.sh → 9 to check/prepare the trusted runtime; administrator promotion/start is explicit')


def prepare_runtime(fio=None,approved_fio=None,approved_source=None,root=ROOT):
    if os.getuid()==0:raise ValueError('Prepare with the repository .venv as the normal operator')
    source,_=_source_snapshot(root)
    if source['status']!='complete'or approved_source!=source['digest']:raise ValueError('Exact independently approved execution-source fingerprint required')
    cache=root/'build/thermal-runtime';cache.mkdir(parents=True,exist_ok=True)
    imported=cache/'fio';approval=cache/'fio-approval.json'
    if fio is not None:
        fio=Path(fio)
        if fio.is_symlink()or not fio.is_file()or hashlib.sha256(fio.read_bytes()).hexdigest()!=approved_fio:raise ValueError('Qualified fio differs from approved SHA-256')
        if imported.exists()and hashlib.sha256(imported.read_bytes()).hexdigest()!=approved_fio:raise ValueError('Existing qualified fio cache differs; preserve it and review replacement explicitly')
        if not imported.exists():shutil.copyfile(fio,imported);imported.chmod(0o755)
        approval.write_text(json.dumps(dict(sha256=approved_fio,origin=str(fio.resolve()))))
    if not approval.is_file()or not imported.is_file():raise ValueError('Provide an approved fio 3.42 executable and its independently verified SHA-256 once; no automatic download/install')
    pinned=json.loads(approval.read_text())['sha256']
    if hashlib.sha256(imported.read_bytes()).hexdigest()!=pinned:raise ValueError('Qualified fio cache changed')
    from scripts.storage_thermal_prepare import prepare
    git=collect_source_provenance(root)['git']
    key=source['digest'][:24]+'-'+pinned[:12]+'-'+str(git.get('commit')or'no-git')[:12];destination=cache/key
    if destination.exists():
        manifest=json.loads((destination/'manifest.json').read_text())
        if manifest['source']!=source:raise ValueError('Existing preparation source mismatch')
        actual={str(p.relative_to(destination))for p in destination.rglob('*')if p.is_file()or p.is_symlink()}
        if actual!=set(manifest['files'])|{'manifest.json','SHA256SUMS'}:raise ValueError('Retained preparation inventory differs')
        expected=dict(manifest['files'],**{'manifest.json':hashlib.sha256((destination/'manifest.json').read_bytes()).hexdigest()})
        if (destination/'SHA256SUMS').read_text()!=''.join(h+'  '+n+'\n'for n,h in sorted(expected.items())):raise ValueError('Retained checksum list differs')
        for rel,h in manifest['files'].items():
            p=destination/rel
            if p.is_symlink()or not p.is_file()or hashlib.sha256(p.read_bytes()).hexdigest()!=h:raise ValueError('Retained preparation changed; preserve it for inspection')
    else:prepare(destination,imported,root=root)
    # Reconcile builder output with the independent approvals, not only its own
    # checksum list. Detect source/tool substitution during an otherwise valid
    # build or reuse before presenting any administrator handoff.
    completed=json.loads((destination/'manifest.json').read_text())
    if (completed.get('source')!=source or completed.get('uid')!=os.getuid()or completed.get('gid')!=os.getgid()or
            completed.get('files',{}).get('runtime/build/fio')!=pinned or
            hashlib.sha256((destination/'runtime/build/fio').read_bytes()).hexdigest()!=pinned or
            _source_snapshot(root)[0]!=source):
        raise ValueError('Prepared source/tool identities differ from independent approvals; preserve the preparation for inspection')
    manifest_sha=hashlib.sha256((destination/'manifest.json').read_bytes()).hexdigest()
    installer=root/'scripts/storage_thermal_install.py';installer_sha=hashlib.sha256(installer.read_bytes()).hexdigest()
    result=dict(status='PREPARED',source=source,git=git,bundle=str(destination.resolve()),manifest_sha256=manifest_sha,checksum_list_sha256=hashlib.sha256((destination/'SHA256SUMS').read_bytes()).hexdigest(),installer=str(installer.resolve()),installer_sha256=installer_sha,fio_sha256=pinned,
        approval='Administrator must independently review source/tools/build provenance and these identities. Locally generated checksums alone are not approval.',
        promotion=['Install the reviewed installer into /usr/local/libexec as root; verify its approved SHA-256 before executing it.',shlex.join(['/usr/bin/env','-i','PATH=/usr/bin:/bin','HOME=/root','LC_ALL=C','/usr/bin/python3','-I','-B','/usr/local/libexec/lvs-thermal-install.py','--approve','--bundle',str(destination.resolve()),'--manifest-sha256',manifest_sha])],
        physical_execution_authorized=False)
    (cache/'approval.json').write_text(json.dumps(result,indent=2));return result


def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--check',action='store_true');parser.add_argument('--prepare',action='store_true');parser.add_argument('--fio',type=Path);parser.add_argument('--approved-fio-sha256');parser.add_argument('--approved-source');args=parser.parse_args()
    if os.getuid()==0:parser.error('Use the normal repository-managed .venv; this command never elevates')
    if Path(sys.prefix).resolve()!=(ROOT/'.venv').resolve():parser.error('Launch with this repository .venv (./setup.sh can manage it)')
    if args.check==args.prepare:parser.error('Select exactly --check or --prepare')
    if args.check:value=runtime_status()
    else:
        from lvs_environment_manager import EnvironmentManager
        manager=EnvironmentManager(root=ROOT)
        with manager.maintenance_lock():
            manager.require_environment();value=prepare_runtime(args.fio,args.approved_fio_sha256,args.approved_source)
    print(json.dumps(value,indent=2));return 0

if __name__=='__main__':raise SystemExit(main())
