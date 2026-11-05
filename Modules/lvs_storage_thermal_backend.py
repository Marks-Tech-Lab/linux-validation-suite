"""Descriptor-only launch specifications for Stage 2B-1. No device opener/runner."""
from __future__ import annotations

import fcntl
import hashlib
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile

from .lvs_storage_thermal import integer
from .lvs_native_binary_provenance import executable_snapshot, MAX_BYTES


def guard_environment() -> dict[str, str]:
    """Mandatory clean launcher environment; never forward LD_* or FIO_* knobs."""
    return {'PATH': '/usr/bin:/bin', 'LC_ALL': 'C', 'HOME': '/', 'TMPDIR': '/tmp'}


def executable_identity(path: str) -> dict:
    resolved = Path(path).resolve(strict=True)
    observed = executable_snapshot(resolved)
    if observed['status'] != 'observed' or not os.access(resolved, os.X_OK):
        raise ValueError('executable must have stable bounded native provenance')
    return dict(path=str(resolved), sha256=observed['sha256'], device=observed['file_device'],
                inode=observed['file_inode'], size=observed['size_bytes'],
                modified_ns=observed['modified_time_ns'], changed_ns=observed['changed_time_ns'])


def capability(fio: str, guard: str, *, run=subprocess.run) -> dict:
    """No device access, privilege escalation, package install or compiler activity."""
    evidence = dict(status='unavailable', backend='descriptor_fio_psync_v1', reasons=[],
                    fixture_proof_required=True, active_storage_supported=False)
    try:
        evidence['fio'] = executable_identity(fio)
        evidence['guard'] = executable_identity(guard)
        env = guard_environment()
        def query(args):
            return run(args, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                       timeout=10, check=False, env=env)
        version = query([fio, '--version'])
        evidence['fio_version'] = version.stdout.strip()
        if version.returncode or not re.fullmatch(r'fio-\d+\.\d+', version.stdout.strip()):
            evidence.update(reasons=['fio version protocol unavailable'])
            return evidence
        guard_version = query([guard, '--version'])
        if guard_version.returncode or guard_version.stdout.strip() != 'lvs-storage-thermal-guard-v1':
            raise ValueError('guard version mismatch')
        filetype = query([fio, '--cmdhelp=filetype'])
        engine = query([fio, '--enghelp'])
        if (filetype.returncode or 'block' not in filetype.stdout or engine.returncode
                or not re.search(r'^\s*psync\s*$', engine.stdout, re.MULTILINE)):
            evidence.update(status='unsupported', reasons=['missing block filetype or psync capability'])
            return evidence
        if version.stdout.strip() != 'fio-3.42':
            evidence.update(status='untested', reasons=['capabilities present but this fio behavior family lacks fixture qualification; no automatic substitution'])
            return evidence
        if os.getuid() == 0 or os.getgid() == 0:
            raise ValueError('runtime guard proof requires an explicit non-root operator session')
        # Kernel policy proof uses only a private regular file, never a device.
        # It complements, and does not replace, synthetic block-device acceptance.
        with tempfile.TemporaryDirectory(prefix='lvs-thermal-policy-') as directory:
            path = Path(directory)/'readonly-fixture'; path.write_bytes(bytes(4096))
            fd = os.open(path, os.O_RDONLY | os.O_DIRECT | os.O_CLOEXEC)
            try:
                proof = run([guard, '--policy-test', str(os.getuid()), str(os.getgid()),
                             '0', '0', '4096', '4096', '1', '1'], stdin=fd,
                            capture_output=True, text=True, timeout=10, check=False, env=env)
            finally:
                os.close(fd)
        if proof.returncode or '"policy_test":"PASS"' not in proof.stdout:
            raise ValueError('kernel mutation restrictions could not be verified')
        evidence.update(status='available', kernel_policy='verified_on_disposable_regular_file',
                        reasons=['synthetic block proof does not establish physical-drive eligibility'])
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        evidence['reasons'] = [str(error)]
    return evidence


def guard_command(guard: str, executable_fd: int, *, backend: dict, uid: int, gid: int,
                  major: int, minor: int, size: int, block_size: int, iops: int,
                  seconds: int) -> list[str]:
    """Caller owns and pins all descriptors until child cleanup is confirmed.

    stdin must be the independently identity/topology-validated block descriptor.
    This is a specification builder, not a physical eligibility decision.
    """
    for name, value, low, high in [('fd', executable_fd, 3, 2**31-1), ('uid', uid, 1, 2**32-2),
        ('gid', gid, 1, 2**32-2), ('major', major, 0, 2**32-1), ('minor', minor, 0, 2**32-1),
        ('size', size, 4096, 2**63-1), ('read size', block_size, 4096, 1048576),
        ('IOPS', iops, 1, 1000000), ('duration', seconds, 1, 86400)]:
        integer(value, low, high, name)
    if block_size & (block_size-1) or size < block_size:
        raise ValueError('invalid geometry')
    info = os.fstat(executable_fd)
    flags = fcntl.fcntl(executable_fd, fcntl.F_GETFL)
    if not stat.S_ISREG(info.st_mode) or flags & os.O_ACCMODE != os.O_RDONLY:
        raise ValueError('pinned readonly executable descriptor required')
    if info.st_size > MAX_BYTES:
        raise ValueError('executable exceeds existing native provenance byte budget')
    if backend.get('status') != 'available' or executable_identity(guard) != backend.get('guard'):
        raise ValueError('guard/backend readiness changed')
    expected = backend.get('fio', {})
    digest = hashlib.sha256(); offset = 0
    while chunk := os.pread(executable_fd, 65536, offset):
        digest.update(chunk); offset += len(chunk)
    unchanged = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    if (digest.hexdigest() != expected.get('sha256') or info.st_dev != expected.get('device')
            or info.st_ino != expected.get('inode') or info.st_size != expected.get('size')
            or info.st_mtime_ns != expected.get('modified_ns') or info.st_ctime_ns != expected.get('changed_ns')
            or unchanged(os.fstat(executable_fd)) != unchanged(info)):
        raise ValueError('fio descriptor does not match capability evidence')
    return [guard, '--fio-fd', str(executable_fd), *map(str,
            (uid, gid, major, minor, size, block_size, iops, seconds))]
