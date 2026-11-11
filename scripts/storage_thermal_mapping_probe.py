"""Final targeted VM research. Destructive writes require the third nonce-bound disk.

This disk is unmounted and disposable. It proves the whole-device kernel mapping
branch independently of ext4 inode mappings. Production providers never import it.
"""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import re
import signal
import stat
import struct
import subprocess
import time

EXTRA_PROBES = {
    'snapshot': ('p', 'blkdev_llseek', 'mapping=+16($arg1):x64 pages=+80(+16($arg1)):u64 tags=+15(+16($arg1)):x8'),
    'write_iter': ('p', 'blkdev_write_iter', ''),
    'writepages': ('p', 'do_writepages', 'mapping=$arg1:x64'),
    'readahead': ('p', 'page_cache_ra_unbounded', 'index=$arg2:u64 pages=$arg3:u64'),
    'mmap_fault': ('p', 'filemap_fault', ''),
}


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def mapping_identity(active):
    token = active.validate_guest(mounted=True)
    node = Path('/sys/class/block/sdc')
    require(active.serial('sdc') == 'LVW-'+token and '/ata' in str(node.resolve()), 'mapping fixture identity mismatch')
    require(int((node/'size').read_text())*512 == 65536 and not (node/'partition').exists(), 'mapping fixture geometry mismatch')
    require(not any(line.split()[0].startswith('/dev/sdc') for line in Path('/proc/mounts').read_text().splitlines()), 'mapping fixture mounted')
    return tuple(map(int, (node/'dev').read_text().split(':')))


def mapping_open(active, write=False):
    device = mapping_identity(active)
    fd = os.open('/dev/sdc', (os.O_RDWR if write else os.O_RDONLY | os.O_DIRECT) | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        size = struct.unpack('Q', fcntl.ioctl(fd, 0x80081272, bytes(8)))[0]
        require(stat.S_ISBLK(info.st_mode) and (os.major(info.st_rdev),os.minor(info.st_rdev)) == device and size == 65536, 'mapping descriptor mismatch')
        return fd
    except BaseException:
        os.close(fd)
        raise


def extents():
    """Resolve actual guest executable/library extents without FIEMAP_FLAG_SYNC."""
    result = []
    for path in sorted([Path('/bin/fio'), Path('/bin/thermal-guard'), *Path('/lib64').glob('*')]):
        if not path.is_file():
            continue
        with path.open('rb') as stream:
            info = os.fstat(stream.fileno())
            buffer = bytearray(32+56*128)
            struct.pack_into('=QQIIII', buffer, 0, 0, (1<<64)-1, 0, 0, 128, 0)
            fcntl.ioctl(stream.fileno(), 0xc020660b, buffer, True)
            count, = struct.unpack_from('=I', buffer, 20)
            require(count < 128, 'truncated source extent map')
            for index in range(count):
                logical, physical, length = struct.unpack_from('=QQQ', buffer, 32+index*56)
                result.append(dict(path=str(path), inode=info.st_ino, device=f'{os.major(info.st_dev)}:{os.minor(info.st_dev)}',
                                   logical=logical, disk_start=1048576+physical, length=length))
    return result


def guarded(active, folder, fd, size, cancel=False):
    from Modules.lvs_storage_thermal_backend import guard_command, executable_identity
    backend = dict(status='available', guard=executable_identity('/bin/thermal-guard'), fio=executable_identity('/bin/fio'))
    info = os.fstat(fd)
    exe = os.open('/bin/fio', os.O_RDONLY | os.O_CLOEXEC)
    argv = guard_command('/bin/thermal-guard', exe, backend=backend, uid=65534, gid=65534,
                         major=os.major(info.st_rdev), minor=os.minor(info.st_rdev), size=size, block_size=65536, iops=7, seconds=1)
    started = time.monotonic()
    try:
        with (folder/'stdout').open('wb') as out, (folder/'stderr').open('wb') as err:
            proc = subprocess.Popen(['/bin/strace','-ff','-ttt','-T','-yy','-s','0','--kill-on-exit',
                                     '-o',str(folder/'syscall'),*argv], stdin=fd, pass_fds=(exe,), stdout=out, stderr=err, start_new_session=True)
            try:
                if cancel:
                    time.sleep(.5)
                    os.killpg(proc.pid, signal.SIGTERM)
                proc.wait(timeout=35)
            finally:
                if proc.poll() is None:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait(timeout=20)
                require(active.reap_group(proc.pid), 'research worker cleanup unconfirmed')
        return dict(exit=proc.returncode, elapsed=time.monotonic()-started, cancelled=cancel)
    finally:
        os.close(exe)


def startup(active, causal, trace, directory):
    rows = []
    sources = extents()
    for index in range(2):
        folder = directory/f'startup-{index}'
        folder.mkdir()
        trace.start(f'startup-{index}')
        fd = active.open_target()
        try:
            row = guarded(active, folder, fd, active.DISK_BYTES)
        finally:
            os.close(fd)
        time.sleep(1)
        data, meta = trace.stop(f'startup-{index}')
        (folder/'kernel.trace').write_text(data)
        workers = {int(p.suffix[1:]) for p in folder.glob('syscall.*')}
        events = list(causal.trace_events(data))
        first = min(e['time'] for e in events if e['event']=='kiocb_wait' and e['pid'] in workers)
        requests = []
        for event in events:
            match = re.match(r'^8,0 (R\S*) (\d+) \(\) (\d+) \+ (\d+)', event['detail'])
            if event['event'] != 'block_rq_issue' or not match or event['time'] >= first:
                continue
            kind, size, sector, count = match.groups()
            start, length = int(sector)*512, int(count)*512
            candidates = [s for s in sources if start < s['disk_start']+s['length'] and s['disk_start'] < start+length]
            requests.append(dict(event, bytes=int(size), sector=int(sector), sectors=int(count), source_extents=candidates))
        row.update(trace=meta, before_first_read=requests, first_read=first, worker_pids=sorted(workers))
        rows.append(row)
    return dict(runs=rows, source_extents=sources)


def snapshot(causal, fd):
    os.lseek(fd, 0, os.SEEK_CUR)
    events = list(causal.trace_events((causal.TRACE/'trace').read_text()))
    values = [e for e in events if e['event']=='snapshot' and e['pid']==os.getpid()]
    require(bool(values), 'mapping snapshot probe invisible')
    value = values[-1]
    match = re.search(r'mapping=(0x[0-9a-f]+) pages=(\d+) tags=(0x[0-9a-f]+)', value['detail'])
    require(match is not None, 'unparsed mapping snapshot')
    return dict(value, mapping=match[1], pages=int(match[2]), tags=int(match[3],16))


def mapping_case(active, causal, trace, directory, mode):
    from Modules.lvs_storage_thermal_recovery import RecoveryScope
    folder = directory/mode
    folder.mkdir()
    scope = RecoveryScope(folder/'intent').enter(evidence_directory=folder)
    writer = reader = None
    cleanup = False
    trace.start(mode)
    try:
        writer = mapping_open(active, write=True)
        reader = mapping_open(active)
        if mode != 'clean':
            # Only this independently verified disposable disk permits raw fixture writes.
            require(os.pwrite(writer, bytes([65+len(mode)])*65536, 0) == 65536, 'short dirty fixture write')
        state = snapshot(causal, writer)
        if mode == 'clean':
            require(state['tags'] & 6 == 0, 'clean control unexpectedly dirty or in flight')
        else:
            require(state['tags'] & 2 and state['pages'] == 16, 'whole-device dirty state not proven')
        if mode == 'inflight-cancel':
            # Natural background writeback, slowed by QEMU on this fixture alone.
            # No sync, cache dropping or writable command is sent to the guard.
            deadline = time.monotonic()+15
            while not state['tags'] & 4 and time.monotonic()<deadline:
                time.sleep(.1)
                state = snapshot(causal, writer)
            require(state['tags'] & 4, 'whole-device in-flight state not observed')
        trace.mark('state proven before guard')
        worker = guarded(active, folder, reader, 65536, cancel=mode=='inflight-cancel')
        after_read = snapshot(causal, writer)
        trace.mark('guard reaped')
        os.close(reader)
        reader = None
        trace.mark('readonly descriptor closed')
        os.close(writer)
        writer = None
        trace.mark('final fixture descriptor closed')
        cleanup = True
    finally:
        for fd in (reader, writer):
            if fd is not None:
                os.close(fd)
        if cleanup:
            scope.resolve(cleanup_confirmed=True)
        scope.close()
    time.sleep(2)
    data, meta = trace.stop(mode)
    (folder/'kernel.trace').write_text(data)
    require('last_close:' in data, 'last-close positive probe missing')
    return dict(mode=mode, before=state, after_read=after_read, worker=worker, trace=meta, cleanup_confirmed=cleanup)


def guest(active, causal, directory):
    active.validate_guest(mounted=True)
    mapping_identity(active)
    trace = causal.Trace()
    causal.Trace.write(f'events/{causal.PROBE_GROUP}/readahead/trigger', 'stacktrace')
    startup_result = startup(active,causal,trace,directory)
    clean = mapping_case(active,causal,trace,directory,'clean')
    dirty = mapping_case(active,causal,trace,directory,'dirty')
    # These sysctls affect only this disposable guest and allow a natural flusher control.
    Path('/proc/sys/vm/dirty_expire_centisecs').write_text('100')
    Path('/proc/sys/vm/dirty_writeback_centisecs').write_text('100')
    inflight = mapping_case(active,causal,trace,directory,'inflight-cancel')
    return dict(contract='lvs.storage_thermal.targeted_research.v1', kernel=os.uname().release,
                startup=startup_result, mapping=[clean,dirty,inflight], disposition='INCONCLUSIVE',
                mapping_scope='unmounted 64 KiB third AHCI disk; root ext4 remains on separate sda')


def verify(result):
    require(not result.get('error'), result.get('error',''))
    require(result.get('contract') == 'lvs.storage_thermal.targeted_research.v1', 'wrong research contract')
    require([row['mode'] for row in result['mapping']] == ['clean','dirty','inflight-cancel'], 'targeted cases missing')
    require(all(row['cleanup_confirmed'] for row in result['mapping']), 'research cleanup unconfirmed')
    clean, dirty, inflight = result['mapping']
    require(clean['before']['tags'] & 6 == 0, 'clean control invalid')
    require(dirty['before']['pages'] == 16 and dirty['before']['tags'] & 2, 'dirty mapping not demonstrated')
    require(inflight['before']['pages'] == 16 and inflight['before']['tags'] & 4, 'in-flight mapping not demonstrated')
    require(clean['worker']['exit'] == dirty['worker']['exit'] == 0, 'full read controls failed')
    require(inflight['worker']['cancelled'] and inflight['worker']['exit'] != 0, 'cancellation control failed')
    require(len(result['startup']['runs']) == 2 and all(row['exit']==0 for row in result['startup']['runs']), 'startup comparison failed')
    require(result['disposition']=='INCONCLUSIVE', 'provider acceptance requires independent review')
