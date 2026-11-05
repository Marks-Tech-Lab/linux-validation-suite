"""Stage 2B-1 synthetic-VM proof; no host device argument or physical workloads.

Reuses Wave 2A's disposable VM construction. --guard must be a locally compiled
native/storage_thermal_guard.c, not a setuid executable. No package installation.
"""
import argparse
import base64
import errno
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import tarfile
import time

try:
    import storage_thermal_fio_probe as base
except ModuleNotFoundError:
    try:
        from scripts import storage_thermal_fio_probe as base
    except ModuleNotFoundError:
        import probe as base  # private guest initramfs only


def verify(results):
    base.require(results['contract'] == 'lvs.storage_thermal.foundation_proof.v1', 'wrong proof')
    cases = {c['name']: c for c in results['cases']}
    base.require(set(cases) == {'guard-policy', 'normal', 'cancel', 'wrong-identity', 'readwrite-fd',
                               'buffered-fd', 'old-fio', 'inherited-descriptors', 'timed-kill', 'block-output'}, 'missing case')
    for c in cases.values():
        base.require(not c['remaining_group'], 'process group survived')
    for name in ('guard-policy', 'inherited-descriptors'):
        c = cases[name]
        base.require(c['returncode'] == 0 and '"policy_test":"PASS"' in c['stdout'], 'policy negative controls failed')
        # Denied syscalls are expected in these negative controls.
        base.require('BLKFLSBUF' in c['trace'] and '= -1 EPERM' in c['trace'], 'missing syscall denials')
    base.require('close(77</dev/vda' in cases['inherited-descriptors']['trace'], 'inherited writable descriptor not closed')
    for name in ('normal', 'cancel'):
        c = cases[name]; a = c['audit']
        base.require(a['aligned_bounded_reads'] and a['distinct_offsets'] > 1, 'no random reads')
        base.require(not a['target_mutations'] and not a['unknown_target_calls'], 'unsafe normal target operation')
        base.require('"uid":65534' in c['stderr'] and '"capabilities":0' in c['stderr'], 'drop evidence missing')
        base.require(c['timed_out'] == (name == 'cancel'), 'wrong deadline outcome')
        base.require(c['returncode'] == 0 if name == 'normal' else c['returncode'] != 0, 'wrong exit classification')
    for name in ('wrong-identity', 'readwrite-fd', 'buffered-fd', 'old-fio', 'block-output'):
        c = cases[name]
        base.require(c['returncode'] != 0 and not c['audit']['reads'], 'unsafe request not rejected')
    base.require(cases['timed-kill']['sigkill'] and cases['timed-kill']['timed_out'], 'kill escalation not tested')


def guest():
    token = json.loads(Path('/fixture.json').read_text())['token']
    base.validate_fixture(token, Path('/proc/cmdline').read_text(), Path('/sys/class/dmi/id/sys_vendor').read_text(),
                          Path('/sys/block/vda/serial').read_text().strip(),
                          int(Path('/sys/block/vda/size').read_text()) * 512, os.getuid())
    evidence = Path('/evidence'); evidence.mkdir()
    fd = os.open('/dev/vda', os.O_RDONLY | os.O_DIRECT | os.O_EXCL | os.O_CLOEXEC)
    info = os.fstat(fd)
    numbers = ['65534', '65534', str(os.major(info.st_rdev)), str(os.minor(info.st_rdev)),
               str(base.SIZE), str(base.BS), '30', '3']
    cases = []
    for name in ('guard-policy', 'normal', 'cancel', 'wrong-identity', 'readwrite-fd',
                 'buffered-fd', 'old-fio', 'inherited-descriptors', 'timed-kill', 'block-output'):
        used_fd = fd; extra = None
        exe = os.open('/bin/old-fio' if name == 'old-fio' else '/bin/fio', os.O_RDONLY | os.O_CLOEXEC)
        args = numbers.copy()
        if name == 'wrong-identity':
            args[3] = str(int(args[3])+1)
        if name in ('readwrite-fd', 'buffered-fd'):
            # Deliberate invalid descriptor, only on this synthetic block device.
            used_fd = os.open('/dev/vda', (os.O_RDWR | os.O_DIRECT) if name == 'readwrite-fd' else os.O_RDONLY)
        if name == 'cancel':
            args[-1] = '60'
        policy = name in ('guard-policy', 'inherited-descriptors')
        cmd = ['/bin/thermal-guard', '--policy-test', *args] if policy else ['/bin/thermal-guard', '--fio-fd', str(exe), *args]
        if name == 'inherited-descriptors':
            extra = os.open('/dev/vda', os.O_RDWR | os.O_DIRECT | os.O_CLOEXEC)
            os.dup2(extra, 77); os.close(extra); extra = 77
        if name == 'timed-kill':
            # Group escalation fixture holds no device or binary descriptor.
            cmd = ['/usr/bin/python3', '-c',
                   'import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(60)']
        pass_fds = () if name == 'timed-kill' else ((exe, extra) if extra is not None else (exe,))
        trace_args = ['/bin/strace', '-ff', '-ttt', '-yy', '-s', '0', '--kill-on-exit',
                      '-o', f'/evidence/{name}.trace', *cmd] if name != 'timed-kill' else cmd
        started = time.monotonic(); timed = False; killed = False
        with (evidence/f'{name}.stdout').open('wb') as out, (evidence/f'{name}.stderr').open('wb') as err:
            p = subprocess.Popen(trace_args, stdin=subprocess.DEVNULL if name == 'timed-kill' else used_fd,
                                 pass_fds=pass_fds, stdout=used_fd if name == 'block-output' else out,
                                 stderr=err, start_new_session=True,
                                 env={'PATH':'/usr/bin:/bin', 'LC_ALL':'C', 'HOME':'/', 'TMPDIR':'/tmp'})
            try:
                p.wait(timeout=1 if name in ('cancel', 'timed-kill') else 15)
            except subprocess.TimeoutExpired:
                timed = True; os.killpg(p.pid, signal.SIGTERM)
                try:
                    p.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    killed = True; os.killpg(p.pid, signal.SIGKILL); p.wait(timeout=3)
        remaining = []
        for _ in range(60):
            while True:
                try:
                    child, _status = os.waitpid(-1, os.WNOHANG)
                    if not child:
                        break
                except ChildProcessError:
                    break
            remaining = []
            for proc in Path('/proc').iterdir():
                if proc.name.isdigit():
                    try:
                        if int((proc/'stat').read_text().rsplit(')', 1)[1].split()[2]) == p.pid:
                            remaining.append(proc.name)
                    except (OSError, ValueError):
                        pass
            if not remaining:
                break
            time.sleep(.05)
        trace = '\n'.join(f.read_text() for f in evidence.glob(f'{name}.trace.*'))
        cases.append(dict(name=name, command=cmd, returncode=p.returncode, elapsed=time.monotonic()-started,
                          timed_out=timed, sigkill=killed, remaining_group=remaining,
                          stdout=(evidence/f'{name}.stdout').read_text(), stderr=(evidence/f'{name}.stderr').read_text(),
                          audit=base.audit(trace), trace=trace if policy else 'retained in per-process files'))
        os.close(exe)
        if extra is not None:
            os.close(extra)
        if used_fd != fd:
            os.close(used_fd)
        base.require(not remaining, 'cleanup unconfirmed; descriptor retained until VM stops')
    os.close(fd)
    results = dict(contract='lvs.storage_thermal.foundation_proof.v1', cases=cases)
    (evidence/'results.json').write_text(json.dumps(results, indent=2))
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode='w:gz') as tar:
        tar.add(evidence, arcname='evidence')
    print('LVS_EVIDENCE_BEGIN', flush=True)
    print(base64.b64encode(archive.getvalue()).decode(), flush=True)
    print('LVS_EVIDENCE_END', flush=True)


if __name__ == '__main__':
    if Path('/fixture.json').exists():
        guest()
    else:
        parser = argparse.ArgumentParser(description=__doc__)
        for name in ('fio', 'old-fio', 'strace', 'kernel', 'python', 'guard'):
            parser.add_argument('--'+name, required=True)
        base.host(parser.parse_args(), guest_script=Path(__file__).resolve(), verifier=verify)
