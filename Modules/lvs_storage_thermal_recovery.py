"""Small Linux stage-ownership journal. All calls belong off the primary timer.

A never-unlinked flock anchor serializes cooperating processes. The JSON journal
is armed and file+directory-fsynced before admission; owner death releases only
its lock, never its obligation. Missing/corrupt state beside an anchor is unsafe.
Only confirmed cleanup may publish CLEAN. No device paths are opened here.
"""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import stat
import tempfile
from uuid import uuid4
from .lvs_storage_thermal import canonical_lease_identity

HEADER = b'LVS storage recovery scope v1\n'
CONTRACT = 'lvs.storage_thermal.execution_intent'
EVIDENCE_MAX_BYTES = 8 * 1024 * 1024
_UNCERTAIN_SCOPES=[]


def durable_json(path, value):
    path = Path(path)
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as stream:
            name = stream.name
            json.dump(value, stream, allow_nan=False)
            stream.flush(); os.fsync(stream.fileno())
        os.replace(name, path); name = None
        sync_directory(path.parent)
    finally:
        if name is not None: Path(name).unlink(missing_ok=True)


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try: os.fsync(fd)
    finally: os.close(fd)


def durable_directory(path):
    """Persist newly created parent entries as well as the journal itself."""
    missing=[];current=Path(path)
    while not current.exists():
        missing.append(current);current=current.parent
    for directory in reversed(missing):
        try:directory.mkdir()
        except FileExistsError:pass
        sync_directory(directory.parent)
    sync_directory(path)


def anchor_path(marker): return Path(str(marker) + '.scope')


def read_state(marker):
    info = marker.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > 65536:
        raise ValueError('invalid recovery journal type/size')
    fd = os.open(marker, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        actual = os.fstat(fd)
        if (actual.st_dev, actual.st_ino) != (info.st_dev, info.st_ino):
            raise ValueError('recovery journal changed while opening')
        value = json.loads(os.read(fd, 65537))
    finally: os.close(fd)
    if (not isinstance(value, dict) or value.get('contract_id') != CONTRACT or type(value.get('version')) is not int or value.get('version') != 1
            or value.get('state') not in ('ARMED', 'CLEAN') or not isinstance(value.get('token'), str)
            or not value['token'] or type(value.get('owner_pid')) is not int):
        raise ValueError('inconsistent recovery journal')
    if value.get('lease_identity')!=canonical_lease_identity(value.get('lease_identity'),optional=True):
        raise ValueError('Noncanonical recovery lease identity')
    if value['state'] == 'CLEAN' and value.get('cleanup_confirmed') is not True:
        raise ValueError('CLEAN journal lacks cleanup confirmation')
    return value


class RecoveryScope:
    def __init__(self, marker):
        self.marker = Path(marker)
        self.anchor = anchor_path(self.marker)
        self.fd = None
        self.token = uuid4().hex
        self._expected=None;self._pin=None;self._reference=None;self._probe=None
        self._pid=os.getpid();self._active=False;self._admission=None;self._lease_identity=None

    def _validate(self,fd):
        actual=os.fstat(fd);named=self.anchor.lstat()
        if (not stat.S_ISREG(actual.st_mode) or actual.st_nlink!=1 or
                (actual.st_dev,actual.st_ino)!=self._expected or
                (named.st_dev,named.st_ino)!=self._expected or
                os.pread(fd,len(HEADER)+1,0)!=HEADER):
            raise ValueError('Authoritative recovery anchor identity changed')

    def _identity(self):
        # Identity alone is never an ownership certificate.
        self._validate(self.fd)

    def _authority(self):
        if os.getpid()!=self._pid:raise ValueError('Recovery authority cannot be inherited across fork')
        if self._admission is not None and self._admission.verified_identity()!=self._lease_identity:
            raise ValueError('Recovery and native admission identities disagree')
        for fd in (self.fd,self._pin,self._reference,self._probe):self._validate(fd)
        for probe in (self._probe,self.fd):
            try:fcntl.flock(probe,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except OSError as exc:
                if exc.errno not in (11,13):raise
            else:
                fcntl.flock(probe,fcntl.LOCK_UN)
                raise ValueError('Recovery lock lost/shared/ambiguous; no reacquisition')
        # Pin and lifetime reference alone hold authority. Public fd and probe
        # are independent descriptions, so closing/unlocking them cannot release it.
        fcntl.flock(self._pin,fcntl.LOCK_EX|fcntl.LOCK_NB)
        fcntl.flock(self._reference,fcntl.LOCK_EX|fcntl.LOCK_NB)
        self._validate(self._reference)

    def enter(self, *, evidence_directory='', lease_identity=None, admission=None):
        lease_identity=canonical_lease_identity(lease_identity,optional=admission is None)
        if admission is not None and admission.verified_identity()!=lease_identity:
            raise ValueError('Recovery and native admission identities disagree')
        self._admission=admission;self._lease_identity=lease_identity
        durable_directory(self.marker.parent)
        if self.marker.parent.is_symlink(): raise ValueError('symlink recovery directory')
        created = False
        try:
            self.fd = os.open(self.anchor, os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
            created = True
        except FileExistsError:
            self.fd = os.open(self.anchor, os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW)
        info=os.fstat(self.fd);self._expected=(info.st_dev,info.st_ino)
        try:
            self._pin=os.open(f'/proc/self/fd/{self.fd}',os.O_RDWR|os.O_CLOEXEC)
            fcntl.flock(self._pin, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._reference=os.dup(self._pin)
            self._probe=os.open(f'/proc/self/fd/{self._pin}',os.O_RDWR|os.O_CLOEXEC)
            if created:
                # A pre-existing journal without its original anchor is ambiguous.
                if self.marker.exists() or self.marker.is_symlink(): raise ValueError('orphan recovery journal')
                if os.write(self.fd, HEADER) != len(HEADER): raise OSError('incomplete recovery anchor')
                os.fsync(self.fd); sync_directory(self.anchor.parent)
            self._active=True
            self._authority()
            if not created:
                previous = read_state(self.marker)
                if previous['state'] != 'CLEAN': raise ValueError('unresolved previous storage ownership')
            self.record = dict(contract_id=CONTRACT, version=1, state='ARMED', token=self.token,
                owner_pid=os.getpid(), evidence_directory=str(evidence_directory), lease_identity=lease_identity,
                cleanup_confirmed=False)
            self._authority()
            durable_json(self.marker, self.record)
            self._authority()
            if read_state(self.marker) != self.record: raise ValueError('durable intent verification failed')
            return self
        except BaseException:
            self.close(); raise

    def resolve(self, *, cleanup_confirmed=False):
        if cleanup_confirmed is not True:raise ValueError('Confirmed cleanup certificate required for CLEAN')
        self._authority()
        if read_state(self.marker) != self.record: raise ValueError('execution intent ownership changed')
        clean = dict(self.record, state='CLEAN', cleanup_confirmed=True)
        durable_json(self.marker, clean)
        self._authority()
        if read_state(self.marker) != clean: raise ValueError('cleanup journal verification failed')

    def close(self):
        if self._active:
            try:self._authority()
            except (OSError,ValueError,TypeError) as exc:
                if self not in _UNCERTAIN_SCOPES:_UNCERTAIN_SCOPES.append(self)
                raise OSError('Recovery descriptor ownership unconfirmed; retained references') from exc
        # Construction failures have never authorized work. Otherwise authority
        # above proves public/probe independence and live private lock ownership.
        for name in ('fd','_probe','_reference','_pin'):
            fd=getattr(self,name)
            if fd is not None:
                info=os.fstat(fd)
                if (info.st_dev,info.st_ino)!=self._expected:raise OSError('Recovery close identity changed')
                os.close(fd);setattr(self,name,None)
        self._active=False


def blocker(marker):
    """Inspection only. A new deployment has neither file; an incomplete one blocks."""
    marker = Path(marker); anchor = anchor_path(marker)
    fd = None
    try:
        try: fd = os.open(anchor, os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW)
        except FileNotFoundError:
            if marker.exists() or marker.is_symlink(): return 'Recovery journal has no authoritative scope anchor'
            return ''  # first use still MUST establish durable intent before I/O
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        scope = RecoveryScope(marker); scope.fd = fd
        info=os.fstat(fd);scope._expected=(info.st_dev,info.st_ino);scope._identity()
        if read_state(marker)['state'] != 'CLEAN': return 'Unresolved storage ownership; manual recovery required'
        return ''
    except (OSError, ValueError) as exc: return 'Storage recovery scope unavailable or unresolved: ' + str(exc)
    finally:
        if fd is not None: os.close(fd)


def retain_uncertain(marker, reason):
    """Preserve an armed owner; never overwrite a journal held by another actor."""
    marker = Path(marker)
    if anchor_path(marker).exists():
        # ARMED, corrupt, missing, or currently locked state already fails closed.
        # Only a verifiably CLEAN, unlocked state needs a new obligation.
        if blocker(marker): return
    elif marker.exists() or marker.is_symlink():
        return  # legacy unresolved marker remains a blocker
    scope = RecoveryScope(marker)
    try: scope.enter(evidence_directory=str(reason))
    finally: scope.close()  # deliberately ARMED, including after process restart


_IO_UNCONFIRMED = []  # evidence-only children, never inherit a target descriptor


def evidence_operation(action, *args, payload=None):
    """Post-primary, bounded supervision of auxiliary filesystem operations."""
    import subprocess
    import sys
    for child in list(_IO_UNCONFIRMED):
        if child.poll() is not None:
            try:child.communicate(timeout=.25)
            except (OSError,subprocess.SubprocessError):continue
            _IO_UNCONFIRMED.remove(child)
    if _IO_UNCONFIRMED: raise OSError('Previous auxiliary evidence helper cleanup remains unconfirmed')
    text = json.dumps(payload, allow_nan=False) if payload is not None else ''
    if len(text.encode('utf-8'))>EVIDENCE_MAX_BYTES:
        raise ValueError('Auxiliary evidence operation exceeds 8 MiB budget')
    from .lvs_storage_thermal_launch import OwnedProcess
    from types import SimpleNamespace
    holder=SimpleNamespace(process=None)
    import time
    deadline=time.monotonic()+2
    try:
        child = OwnedProcess([sys.executable, '-B', '-m', __name__, action, *map(str,args)],
            cwd=Path(__file__).resolve().parents[1], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, start_new_session=True, close_fds=True,owner=holder,deadline=deadline)
    except BaseException:
        if holder.process is not None:_IO_UNCONFIRMED.append(holder.process)
        raise
    try:
        output, error = child.communicate(text, timeout=max(0,deadline-time.monotonic()))
    except BaseException:
        # Ownership survives failed kill/reap too, not just a normal timeout.
        _IO_UNCONFIRMED.append(child)
        try: child.kill()
        except OSError: pass
        try: child.communicate(timeout=.25)
        except (subprocess.TimeoutExpired,OSError): pass
        else: _IO_UNCONFIRMED.remove(child)
        raise
    if child.returncode: raise OSError('Auxiliary evidence operation failed: '+error[-2000:])
    return json.loads(output)


def _main():
    import sys
    action = sys.argv[1]
    if action == '--read-terminal':
        directory, marker = map(Path,sys.argv[2:4])
        result = None
        try:
            with (directory/'completion.json').open('rb') as stream: raw=stream.read(EVIDENCE_MAX_BYTES+1)
            if len(raw)>EVIDENCE_MAX_BYTES: raise ValueError('terminal evidence exceeds 8 MiB')
            result=json.loads(raw)
        except FileNotFoundError: pass
        ownership=None
        try:
            with (directory/'launch_ownership.json').open('rb') as stream:raw=stream.read(EVIDENCE_MAX_BYTES+1)
            if len(raw)>EVIDENCE_MAX_BYTES:raise ValueError('ownership evidence exceeds 8 MiB')
            ownership=json.loads(raw)
        except FileNotFoundError:pass
        print(json.dumps(dict(result=result,ownership=ownership,recovery_blocker=blocker(marker))))
    elif action == '--retain':
        retain_uncertain(Path(sys.argv[2]),sys.argv[3]);print('{}')
    elif action == '--publish-json':
        from .lvs_profile_report_artifacts import atomic_preflight_json
        raw=sys.stdin.read(EVIDENCE_MAX_BYTES+1)
        if len(raw)>EVIDENCE_MAX_BYTES:raise ValueError('auxiliary evidence exceeds 8 MiB')
        atomic_preflight_json(Path(sys.argv[2]),json.loads(raw));print('{}')
    elif action == '--publish-summary':
        from .lvs_profile_report_artifacts import atomic_preflight_json
        raw=sys.stdin.read(EVIDENCE_MAX_BYTES+1)
        if len(raw)>EVIDENCE_MAX_BYTES:raise ValueError('auxiliary summary exceeds 8 MiB')
        packet=json.loads(raw);result=packet['summary'];root=Path(sys.argv[2])
        (root/'storage_thermal_summary.txt').write_text('Storage Thermal Assist observations\nAuthority: run_manifest.json storage_thermal_summary\n'+'\n'.join(packet['text'].splitlines()[1:])+'\n')
        atomic_preflight_json(root/'storage_thermal_summary.json',result);print('{}')
    else:raise ValueError('unsupported evidence action')


if __name__ == '__main__': _main()
