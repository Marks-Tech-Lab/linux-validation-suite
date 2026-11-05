"""Wave 2A research probe. Only a private, disposable QEMU guest block device.

No host device argument, workload integration, thermal control, or root required.
Linux/x86-64 host with QEMU, a compatible kernel, Python and strace required.
All outputs and the synthetic disk are retained in a new /tmp directory.
"""
from __future__ import annotations

import argparse
import base64
import fcntl
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import struct
import subprocess
import tarfile
import tempfile
import time
import uuid

SIZE = 32 * 1024 * 1024
BS = 65536


def digest(path):
    with open(path, 'rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def validate_fixture(token, cmdline, vendor, serial, size, uid):
    require(bool(re.fullmatch('[0-9a-f]{12}', token)), 'invalid fixture token')
    require(uid == 0 and f'lvs_fixture={token}' in cmdline.split(), 'not the disposable guest')
    require('QEMU' in vendor and serial == f'LVS-{token}' and size == SIZE,
            'fixture identity mismatch; no device access permitted')


def command(fio, iops=10, runtime=3):
    """Fixed research command; no pathname or arbitrary option passthrough."""
    if iops not in (10, 30) or not 1 <= runtime <= 60:
        raise ValueError('outside disposable pilot bounds')
    # fio 3.42's filename callback consumes filetype at parse time.
    return [fio, '--readonly', '--name=lvs-fixture', '--filetype=block',
            '--filename=-', '--ioengine=psync', '--rw=randread',
            '--direct=1', '--iodepth=1', '--numjobs=1', '--thread=1',
            '--bs=65536', f'--rate_iops={iops}', '--time_based=1',
            f'--runtime={runtime}', '--allow_file_create=0', '--create_on_open=0',
            '--fallocate=none', '--invalidate=0', '--create_fsync=0',
            '--fsync=0', '--fdatasync=0', '--end_fsync=0', '--end_syncfs=0',
            '--fsync_on_close=0', '--norandommap=1', '--randrepeat=1',
            '--randseed=719', '--output-format=json']


def audit(text):
    """Conservative trace review: unknown target operations need human review."""
    reads, unknown, mutations = [], [], []
    for line in text.splitlines():
        if '/dev/vda' not in line:
            continue
        if 'pread64(' in line:
            match = re.search(r', (\d+), (\d+)\)\s*=\s*(\d+)', line)
            if match:
                length, offset, returned = map(int, match.groups())
                reads.append([length, offset, returned])
            else:
                unknown.append(line)
        elif re.search(r'\b(?:pwrite\w*|write\w*|fsync|fdatasync|syncfs|ftruncate|fallocate)\(', line):
            mutations.append(line)
        elif 'ioctl(' in line:
            if not any(token in line for token in ('BLKGETSIZE64', 'BLKSSZGET', 'BLKPBSZGET')):
                mutations.append(line)  # unreviewed ioctl is never accepted
        elif 'fadvise64(' in line and 'POSIX_FADV_RANDOM' in line:
            pass  # access-pattern hint, not cache invalidation
        elif 'fcntl(' in line and ('F_SETFL' in line or 'F_SETLEASE' in line):
            mutations.append(line)
        elif 'mmap(' in line or ('open' in line and re.search(r'O_(?:RDWR|WRONLY|TRUNC|CREAT)', line)):
            mutations.append(line)
        elif not re.search(r'\b(?:dup\w*|close|fcntl|fstat|newfstatat|statx|lseek|openat)\(', line):
            unknown.append(line)
    return dict(reads=reads, target_mutations=mutations, unknown_target_calls=unknown,
                aligned_bounded_reads=bool(reads) and all(
                    n == BS and r == BS and o % BS == 0 and o + n <= SIZE
                    for n, o, r in reads), distinct_offsets=len({r[1] for r in reads}))


def verify_results(results):
    """A missing trace, unexpected exit or surviving process is never success."""
    cases = {case['name']: case for case in results['cases']}
    require(set(cases) == {'pilot10', 'pilot30', 'cancel', 'reject-write', 'reject-trim',
                           'old-version', 'wrong-order', 'unsafe-invalidation-witness'},
            'incomplete case inventory')
    for case in cases.values():
        require(not case['remaining_group'], 'cleanup unconfirmed')
    for name in ('pilot10', 'pilot30', 'cancel'):
        case = cases[name]; review = case['audit']
        require(review['aligned_bounded_reads'] and review['distinct_offsets'] > 1,
                f'{name}: missing aligned random-read evidence')
        require(not review['target_mutations'] and not review['unknown_target_calls'],
                f'{name}: target operation requires review')
        require(case['timed_out'] == (name == 'cancel'), f'{name}: unexpected timeout')
        require((case['returncode'] != 0) if name == 'cancel' else (case['returncode'] == 0),
                f'{name}: unexpected exit')
    for name in ('reject-write', 'reject-trim', 'old-version', 'wrong-order'):
        case = cases[name]
        require(case['returncode'] != 0 and not case['timed_out'] and not case['audit']['reads']
                and not case['audit']['target_mutations'] and not case['audit']['unknown_target_calls'],
                f'{name}: rejection not proven')
    require(any('BLKFLSBUF' in call for call in
                cases['unsafe-invalidation-witness']['audit']['target_mutations']),
            'missing negative invalidation witness')
    require(results['misaligned_read_errno'] == 22 and results['readonly_write_errno'] == 9,
            'kernel negative witnesses missing')


def guest():
    # Require the matching boot marker and synthetic identity before opening.
    token = json.loads(Path('/fixture.json').read_text())['token']
    validate_fixture(token, Path('/proc/cmdline').read_text(),
                     Path('/sys/class/dmi/id/sys_vendor').read_text(),
                     Path('/sys/block/vda/serial').read_text().strip(),
                     int(Path('/sys/block/vda/size').read_text()) * 512, os.getuid())
    evidence = Path('/evidence'); evidence.mkdir()
    fd = os.open('/dev/vda', os.O_RDONLY | os.O_DIRECT | os.O_EXCL | os.O_CLOEXEC)
    require(stat.S_ISBLK(os.fstat(fd).st_mode), 'not a block descriptor')
    flags = fcntl.fcntl(fd, fcntl.F_GETFL)
    require(flags & os.O_ACCMODE == os.O_RDONLY and flags & os.O_DIRECT,
            'descriptor must already be readonly and direct')
    size = struct.unpack('Q', fcntl.ioctl(fd, 0x80081272, bytes(8)))[0]
    require(size == SIZE, 'descriptor size changed')
    results = dict(size=size, flags=flags, cases=[], versions={})
    for name in ('fio', 'old-fio', 'strace'):
        results['versions'][name] = subprocess.run(
            [f'/bin/{name}', '--version'], capture_output=True, text=True).stdout.strip()
    for name, rate, runtime, change in (
        ('pilot10', 10, 3, None), ('pilot30', 30, 3, None),
        ('cancel', 10, 60, None), ('reject-write', 10, 3, 'randwrite'),
        ('reject-trim', 10, 3, 'trim'), ('old-version', 10, 3, None),
        ('wrong-order', 10, 3, None), ('unsafe-invalidation-witness', 10, 1, None),
    ):
        argv = command('/bin/old-fio' if name == 'old-version' else '/bin/fio', rate, runtime)
        if change:
            argv[argv.index('--rw=randread')] = f'--rw={change}'
        if name == 'wrong-order':
            index = argv.index('--filetype=block')
            argv[index:index+2] = ['--filename=-', '--filetype=block']
        if name == 'unsafe-invalidation-witness':
            argv[argv.index('--invalidate=0')] = '--invalidate=1'
        argv += [f'--output=/evidence/{name}.fio.json']
        started = time.monotonic()
        with (evidence / f'{name}.stdout').open('wb') as out, (evidence / f'{name}.stderr').open('wb') as err:
            p = subprocess.Popen(['/bin/strace', '-ff', '-ttt', '-yy', '-s', '0',
                                  '--kill-on-exit', '-o', f'/evidence/{name}.trace',
                                  *argv], stdin=fd, stdout=out, stderr=err, start_new_session=True)
            expired = False; killed = False
            try:
                p.wait(timeout=2 if name == 'cancel' else 20)
            except subprocess.TimeoutExpired:
                expired = True; os.killpg(p.pid, signal.SIGTERM)
                try:
                    p.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    killed = True; os.killpg(p.pid, signal.SIGKILL); p.wait(timeout=3)
        # PID1 reaps tracer descendants as well; group must be gone.
        deadline = time.monotonic() + 3
        remaining = []
        while time.monotonic() < deadline:
            while True:
                try:
                    child, _ = os.waitpid(-1, os.WNOHANG)
                    if not child:
                        break
                except ChildProcessError:
                    break
            remaining = []
            for entry in Path('/proc').iterdir():
                if entry.name.isdigit():
                    try:
                        fields = (entry / 'stat').read_text().rsplit(')', 1)[1].split()
                        if int(fields[2]) == p.pid:
                            remaining.append(int(entry.name))
                    except (OSError, ValueError):
                        pass
            if not remaining:
                break
            time.sleep(.05)
        traces = '\n'.join(path.read_text() for path in evidence.glob(f'{name}.trace.*'))
        results['cases'].append(dict(name=name, command=argv, returncode=p.returncode,
                                     elapsed=time.monotonic()-started, timed_out=expired,
                                     sigkill=killed, remaining_group=remaining, audit=audit(traces)))
        if remaining:
            raise RuntimeError('cleanup unconfirmed; stop before another case')
    # Independent kernel rejection witnesses, outside normal fio traces.
    try:
        os.pread(fd, 512, 1)
        raise AssertionError('misalignment accepted')
    except OSError as exc:
        results['misaligned_read_errno'] = exc.errno
    try:
        os.pwrite(fd, bytes(4096), 0)
        raise AssertionError('write accepted on readonly descriptor')
    except OSError as exc:
        results['readonly_write_errno'] = exc.errno
    os.close(fd)
    (evidence / 'results.json').write_text(json.dumps(results, indent=2))
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w:gz') as archive:
        archive.add(evidence, arcname='evidence')
    print('LVS_EVIDENCE_BEGIN', flush=True)
    print(base64.b64encode(buffer.getvalue()).decode(), flush=True)
    print('LVS_EVIDENCE_END', flush=True)


def host(args, *, guest_script=None, verifier=verify_results, extra_files=None):
    bundle = Path(tempfile.mkdtemp(prefix='lvs-wave2a-'))
    print(f'Retained disposable evidence: {bundle}', flush=True)
    root = bundle / 'root'; root.mkdir()

    def copy_file(source, destination=None):
        source = Path(source)
        target = root / str(destination or source).lstrip('/')
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target, follow_symlinks=True)

    copied = set()

    def binary(source, destination=None):
        copy_file(source, destination)
        if str(source) in copied:
            return
        copied.add(str(source))
        result = subprocess.run(['ldd', str(source)], capture_output=True, text=True, check=True)
        for lib in re.findall(r'(?:=>\s*)?(/[^\s()]+)', result.stdout):
            copy_file(lib)

    for src, dest in [(args.fio, '/bin/fio'), (args.old_fio, '/bin/old-fio'),
                      (args.strace, '/bin/strace'), ('/bin/bash', '/bin/sh'),
                      ('/usr/bin/mount', '/bin/mount'), (args.python, '/usr/bin/python3')]:
        binary(src, dest)
    if guest_script is not None:
        binary(args.guard, '/bin/thermal-guard')
        copy_file(guest_script, '/foundation_probe.py')
    for source,destination in extra_files or []:
        copy_file(source,destination)
    stdlib = subprocess.check_output([args.python, '-c', 'import sysconfig;print(sysconfig.get_path("stdlib"))'], text=True).strip()
    shutil.copytree(stdlib, root / stdlib.lstrip('/'), symlinks=False,
                    ignore=shutil.ignore_patterns('site-packages', '__pycache__', 'test', 'tests', 'tkinter', 'idlelib', 'ensurepip'))
    for module in (Path(stdlib) / 'lib-dynload').glob('*.so'):
        binary(module)
    token = uuid.uuid4().hex[:12]  # virtio block serial is at most 20 bytes
    (root / 'fixture.json').write_text(json.dumps(dict(token=token)))
    copy_file(Path(__file__).resolve(), '/probe.py')
    guest_entry = '/foundation_probe.py' if guest_script is not None else '/probe.py --guest'
    (root / 'init').write_text('#!/bin/sh\n/bin/mount -t proc proc /proc\n/bin/mount -t sysfs sysfs /sys\n/bin/mount -t devtmpfs devtmpfs /dev\nexec /usr/bin/python3 ' + guest_entry + '\n')
    (root / 'init').chmod(0o755)
    for directory in ('proc', 'sys', 'dev', 'tmp'):
        (root / directory).mkdir(exist_ok=True)
    # newc supports synthetic device nodes without host mknod privileges.
    archive = bytearray()

    def entry(name, mode, data=b'', major=0, minor=0):
        name_bytes = name.encode() + b'\0'
        values = [1, mode, 0, 0, 1, 0, len(data), 0, 0, major, minor, len(name_bytes), 0]
        archive.extend(b'070701' + ''.join(f'{v:08x}' for v in values).encode() + name_bytes)
        archive.extend(bytes(-len(archive) % 4)); archive.extend(data); archive.extend(bytes(-len(archive) % 4))
    for path in sorted(root.rglob('*')):
        entry(str(path.relative_to(root)), path.stat().st_mode, path.read_bytes() if path.is_file() else b'')
    entry('dev/console', stat.S_IFCHR | 0o600, major=5, minor=1)
    entry('dev/null', stat.S_IFCHR | 0o666, major=1, minor=3)
    entry('TRAILER!!!', 0)
    initrd = bundle / 'initrd.gz'; initrd.write_bytes(gzip.compress(archive, compresslevel=1))
    disk = bundle / 'synthetic.raw'
    # Deliberately nonzero fixture; never reads a host device to seed it.
    with disk.open('wb') as stream:
        for number in range(SIZE // BS):
            stream.write(hashlib.sha256(str(number).encode()).digest() * (BS // 32))
    argv = ['qemu-system-x86_64', '-no-user-config', '-nodefaults', '-accel', 'tcg,thread=single',
            '-machine', 'q35', '-m', '512', '-smp', '1', '-display', 'none', '-monitor', 'none',
            '-serial', 'stdio', '-nic', 'none', '-no-reboot', '-kernel', args.kernel, '-initrd', str(initrd),
            '-append', f'console=ttyS0 panic=1 rdinit=/init lvs_fixture={token}',
            '-drive', f'file={disk},format=raw,if=none,id=fixture', '-device',
            f'virtio-blk-pci,drive=fixture,serial=LVS-{token},logical_block_size=512,physical_block_size=4096']
    manifest = dict(command=argv, image_before=digest(disk), tools={
        str(p): digest(p) for p in (args.kernel, args.fio, args.old_fio, args.strace, args.python)})
    if guest_script is not None:
        manifest['tools'].update({str(args.guard): digest(args.guard), str(guest_script): digest(guest_script)})
    (bundle / 'host.json').write_text(json.dumps(manifest, indent=2))
    with (bundle / 'console.log').open('wb') as console:
        p = subprocess.Popen(argv, stdout=console, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            p.wait(timeout=150)
        except BaseException:
            os.killpg(p.pid, signal.SIGKILL); p.wait(timeout=10)
            raise
    manifest.update(qemu_returncode=p.returncode, image_after=digest(disk))
    (bundle / 'host.json').write_text(json.dumps(manifest, indent=2))
    console = (bundle / 'console.log').read_text(errors='replace')
    require('LVS_EVIDENCE_BEGIN\n' in console and 'LVS_EVIDENCE_END' in console,
            f'guest did not publish complete evidence; inspect {bundle}/console.log')
    encoded = console.split('LVS_EVIDENCE_BEGIN\n', 1)[1].split('LVS_EVIDENCE_END', 1)[0]
    with tarfile.open(fileobj=io.BytesIO(base64.b64decode(encoded)), mode='r:gz') as tar:
        tar.extractall(bundle, filter='data')
    require(manifest['image_before'] == manifest['image_after'], 'synthetic contents changed')
    require(p.returncode == 0, 'unexpected QEMU exit')
    verifier(json.loads((bundle / 'evidence/results.json').read_text()))
    print((bundle / 'evidence/results.json').read_text())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--guest', action='store_true', help=argparse.SUPPRESS)
    for option in ('fio', 'old-fio', 'strace', 'kernel', 'python'):
        parser.add_argument('--' + option)
    args = parser.parse_args()
    if args.guest:
        guest()
    else:
        if not all((args.fio, args.old_fio, args.strace, args.kernel, args.python)):
            parser.error('explicit tool/kernel/Python paths required; no disk argument is supported')
        host(args)
