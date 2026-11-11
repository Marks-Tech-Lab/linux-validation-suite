"""Build-specific kernel attribution in the private Stage 2B-4A QEMU fixture."""
from __future__ import annotations

from collections import Counter
import ctypes
import fcntl
import hashlib
import json
import mmap
import os
from pathlib import Path
import re
import resource
import signal
import stat
import struct
import subprocess
import threading
import time

KERNEL_RELEASE = '7.2.9-200.fc44.x86_64'
KERNEL_SHA256 = '5806981b246bfd6e0b9f8dd0ee5e5d2e35561aca66bdf8377f190c8abcc4b2cc'
BUILD_ID = bytes.fromhex('faa25318575065a0d5ae9ca29300268a42d91cbb')
PROBE_GROUP = 'lvs_causal'
# Offsets checked against the executable extracted from KERNEL_SHA256.
MAPPING_FIELDS = 'mapping=$arg1:x64 pages=+80($arg1):u64 tags=+15($arg1):x8'
PROBES = {
    'read_iter': ('p', 'blkdev_read_iter', ''),
    'kiocb_wait': ('p', 'kiocb_write_and_wait',
                  'mapping=+16(+0($arg1)):x64 offset=+8($arg1):u64 bytes=$arg2:u64'),
    'kiocb_done': ('r', 'kiocb_write_and_wait', 'rc=$retval:s64'),
    'wait_range': ('p', 'filemap_write_and_wait_range.part.0',
                   MAPPING_FIELDS + ' start=$arg2:u64 end=$arg3:u64'),
    'writeback_call': ('p', 'filemap_writeback', MAPPING_FIELDS),
    'writeback_done': ('r', 'filemap_writeback', 'rc=$retval:s64'),
    'wait_pages': ('p', '__filemap_fdatawait_range', MAPPING_FIELDS),
    'wait_pages_done': ('r', '__filemap_fdatawait_range', ''),
    'wait_folio': ('p', 'folio_wait_writeback', ''),
    'ext4_pages': ('p', 'ext4_writepages', MAPPING_FIELDS),
    'dio': ('p', 'blkdev_direct_IO', ''),
    'dio_done': ('r', 'blkdev_direct_IO', 'rc=$retval:s64'),
    'open': ('p', 'blkdev_open', ''),
    'release': ('p', 'bdev_release+0x42', 'openers=-0x398(%bx):u32 mapping=+16(%bp):x64'),
    'last_close': ('p', 'blkdev_flush_mapping', ''),
    'media_events': ('p', 'disk_flush_events', 'mask=$arg2:x32'),
    'invalidate': ('p', 'invalidate_bdev', ''),
    'invalidate_pages': ('p', 'invalidate_mapping_pages', MAPPING_FIELDS),
    'truncate_pages': ('p', 'truncate_inode_pages_range', MAPPING_FIELDS),
}
EVENTS = (
    'block/block_bio_queue', 'block/block_rq_issue', 'block/block_rq_complete',
    'filemap/mm_filemap_add_to_page_cache', 'filemap/mm_filemap_delete_from_page_cache',
    'writeback/writeback_dirty_folio', 'writeback/writeback_start',
    'writeback/writeback_written', 'jbd2/jbd2_start_commit', 'jbd2/jbd2_end_commit',
    'sched/sched_switch',
)
TRACE = Path('/sys/kernel/tracing')
TRACE_LINE = re.compile(r'^\s*(.+)-(\d+)\s+\[\d+\].*?\s(\d+\.\d+): (\w+):\s*(.*)$')
BLOCK = re.compile(r'^(\d+,\d+)\s+(\S+)\b')
BS = 65536


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def require_kernel_image(path):
    with Path(path).open('rb') as stream:
        require(stat.S_ISREG(os.fstat(stream.fileno()).st_mode), 'regular kernel image required')
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    require(digest == KERNEL_SHA256, 'causal probes require the exact inspected kernel image')


def trace_events(trace):
    for line in trace.splitlines():
        m = TRACE_LINE.match(line)
        if m:
            task, pid, timestamp, event, detail = m.groups()
            yield dict(task=task, pid=int(pid), time=float(timestamp), event=event, detail=detail)


def correlate(trace, worker_pids, device):
    """Attribute only task-local events and keep other requests unclassified."""
    probes = Counter()
    requests = {'worker': Counter(), 'other': Counter()}
    waits = {}
    samples = []
    for event in trace_events(trace):
        name = event['event']
        pid = event['pid']
        worker = pid in worker_pids
        if name == 'block_rq_issue':
            match = BLOCK.match(event['detail'])
            if match and match[1] == device:
                requests['worker' if worker else 'other'][match[2]] += 1
        if not worker:
            continue
        if name in PROBES:
            probes[name] += 1
        if name == 'kiocb_wait':
            waits[pid] = event
        if name == 'kiocb_done' and pid in waits:
            begin = waits.pop(pid)
            samples.append(dict(pid=pid, start=begin['time'], end=event['time'],
                                mapping_and_range=begin['detail'], result=event['detail']))
    return dict(worker_probes=dict(probes), target_requests=requests,
                write_and_wait_samples=samples, unmatched_wait_entries=len(waits))


class Trace:
    def __init__(self, install=False):
        require(os.uname().release == KERNEL_RELEASE, 'unexpected guest kernel release')
        notes = Path('/sys/kernel/notes').read_bytes()
        require(BUILD_ID in notes, 'unexpected guest kernel build ID')
        if install:
            subprocess.run(['/bin/mount', '-t', 'tracefs', 'tracefs', str(TRACE)],
                           check=True, capture_output=True)
            self.write('tracing_on', '0')
            self.write('trace_clock', 'mono')
            self.write('buffer_size_kb', '8192')
            for name, (kind, symbol, args) in PROBES.items():
                command = f'{kind}:{PROBE_GROUP}/{name} {symbol} {args}\n'.encode()
                fd = os.open(TRACE/'kprobe_events', os.O_WRONLY | os.O_APPEND)
                try:
                    require(os.write(fd, command)==len(command), 'short kprobe definition write')
                except OSError as error:
                    raise RuntimeError(f'{command!r}: {(TRACE/"error_log").read_text()}') from error
                finally:
                    os.close(fd)
                self.write(f'events/{PROBE_GROUP}/{name}/enable', '1')
            self.enabled = []
            for event in EVENTS:
                path = f'events/{event}/enable'
                if (TRACE/path).exists():
                    self.write(path, '1')
                    self.enabled.append(event)
            require(set(EVENTS[:5]) <= set(self.enabled), 'required tracepoints missing')
        self.anchors = []

    @staticmethod
    def write(name, value):
        (TRACE/name).write_text(value)

    def mark(self, label):
        before = time.monotonic_ns()
        wall = time.time_ns()
        self.write('trace_marker', 'LVS_CAUSAL ' + label)
        self.anchors.append(dict(label=label, before_ns=before,
                                 after_ns=time.monotonic_ns(), realtime_ns=wall))

    def start(self, label):
        self.anchors = []
        self.write('trace', '')
        self.write('tracing_on', '1')
        self.mark(label + ' begin')

    def stop(self, label):
        self.mark(label + ' end')
        self.write('tracing_on', '0')
        data = (TRACE/'trace').read_text()
        stats = {p.name: p.read_text() for p in (TRACE/'per_cpu').glob('cpu*/stats')}
        require(bool(stats), 'trace buffer statistics missing')
        for value in stats.values():
            for field in ('overrun', 'commit overrun', 'dropped events'):
                require(re.search(rf'^{field}:\s*0\s*$', value, re.M), f'trace loss: {field}')
        markers = {e['detail']:e['time'] for e in trace_events(data) if e['event']=='tracing_mark_write'}
        for anchor in self.anchors:
            ts = markers.get('LVS_CAUSAL ' + anchor['label'])
            require(ts is not None and anchor['before_ns']/1e9-1e-6 <= ts <= anchor['after_ns']/1e9+1e-6,
                    'trace marker outside monotonic clock bracket')
        return data, dict(anchors=self.anchors, stats=stats,
                          kprobe_profile=(TRACE/'kprobe_profile').read_text())


def pre_mount(active):
    active.validate_guest()
    trace = Trace(install=True)
    trace.start('last close positive control')
    fd = os.open('/dev/sda', os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        require(len(os.pread(fd, 4096, active.START_SECTOR*512)) == 4096, 'cache fill failed')
    finally:
        os.close(fd)
    data, meta = trace.stop('last close positive control')
    seen = {e['event'] for e in trace_events(data) if e['pid']==os.getpid()}
    require({'open','release','last_close','truncate_pages'} <= seen, 'last-close positive control invisible')
    return data, meta


def mapped_offset(fd, partition_start):
    """Query the first allocated extent with FIEMAP flags=0 (no sync)."""
    buf = bytearray(32+56)
    struct.pack_into('=QQIIII', buf, 0, 0, 4096, 0, 0, 1, 0)
    fcntl.ioctl(fd, 0xc020660b, buf, True)
    mapped, = struct.unpack_from('=I', buf, 20)
    logical, physical, length = struct.unpack_from('=QQQ', buf, 32)
    flags, = struct.unpack_from('=I', buf, 72)
    require(mapped == 1 and logical == 0 and length >= 4096 and physical % 4096 == 0
            and flags & ~1 == 0, 'fixture extent is not a stable written allocation')
    return partition_start+physical


def direct_page(fd, offset):
    with mmap.mmap(-1, 4096) as buffer:
        require(os.preadv(fd, [buffer], offset) == 4096, 'short direct control read')
        return hashlib.sha256(buffer).hexdigest()


def overlap_control(active, trace, directory):
    fd = os.open('/ordinary-data', os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW)
    raw = active.open_target()
    try:
        offset = mapped_offset(fd, active.START_SECTOR*512)
        old = direct_page(raw, offset)
        trace.start('overlap')
        dirty = b'Q'*4096
        require(os.pwrite(fd, dirty, 0) == 4096, 'short dirty control write')
        expected = hashlib.sha256(dirty).hexdigest()
        require(expected != old, 'dirty control contents match original')
        trace.mark('raw read over dirty extent')
        observed = direct_page(raw, offset)
        trace.mark('file direct positive control')
        file_fd = os.open('/ordinary-data', os.O_RDONLY | os.O_DIRECT | os.O_CLOEXEC | os.O_NOFOLLOW)
        try:
            require(os.fstat(fd).st_ino == os.fstat(file_fd).st_ino, 'control inode changed')
            file_result = direct_page(file_fd, 0)
        finally:
            os.close(file_fd)
        trace.mark('file direct complete')
        require(direct_page(raw, offset) == expected, 'positive control writeback did not reach disk')
    finally:
        os.close(raw)
        os.close(fd)
    data, meta = trace.stop('overlap')
    (directory/'overlap.trace').write_text(data)
    events = list(trace_events(data))
    markers = {e['detail']:e['time'] for e in events if e['event']=='tracing_mark_write'}
    positive = [e for e in events if e['pid']==os.getpid()
                and markers['LVS_CAUSAL file direct positive control'] <= e['time']
                <= markers['LVS_CAUSAL file direct complete']]
    require({'wait_range','writeback_call','wait_pages','ext4_pages'} <= {e['event'] for e in positive},
            'dirty file direct-read positive control not visible')
    return dict(trace=meta, raw_offset=offset, raw_read_saw_old_data=observed==old,
                file_direct_saw_new_data=file_result==expected, positive_events=positive)


def writer(path, mode, observations, start, errors):
    try:
        with path.open('r+b', buffering=0) as file:
            count = 24 if mode == 'busy' else 8
            for index in range(count):
                due = start + (index*.1 if mode == 'busy' else 0)
                time.sleep(max(0, due-time.monotonic()))
                begin = time.monotonic()
                require(os.pwrite(file.fileno(), bytes([65+index])*4096, (index%8)*4096)==4096,
                        'short ordinary write')
                observations.append(dict(due=due, start=begin, end=time.monotonic(), offset=(index%8)*4096))
    except Exception as error:
        errors.append(repr(error))


def target_reads(text, capacity):
    # strace -yy appends a nested block-device identity to the pathname.
    reads, latencies = [], []
    for line in text.splitlines():
        if not re.search(r'pread64\(\d+</dev/sda(?:<block \d+:\d+>)?>', line):
            continue
        match = re.search(r', (\d+), (\d+)\)\s+=\s+(\d+) <([\d.]+)>$', line)
        require(match is not None, 'unparsed target read: ' + line)
        length, offset, done = map(int, match.groups()[:3])
        require(length==done==BS and offset%BS==0 and offset+length<=capacity, 'invalid target read')
        reads.append(offset)
        latencies.append(float(match[4]))
    return reads, latencies


def run_phase(active, trace, directory, number, mode, assist):
    from Modules.lvs_storage_thermal_recovery import RecoveryScope
    name = f'{number:02d}-{mode}-{"assist" if assist else "control"}'
    folder = directory/name
    folder.mkdir()
    # Match target open/close and report/recovery operations in every arm.
    scope = RecoveryScope(folder/'intent').enter(evidence_directory=folder)
    observations = []
    errors = []
    proc = None
    thread = None
    fd = exe = None
    cleanup = False
    trace.start('phase')
    started = time.monotonic()
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    try:
        fd = active.open_target()
        exe, argv = active.guard_args(fd, seconds=30 if mode=='cancel' else 3)
        if mode in ('busy','dirty'):
            start = time.monotonic()+.02
            thread = threading.Thread(target=writer,
                args=(Path(f'/causal-data-{number}'),mode,observations,start,errors))
            thread.start()
            if mode=='dirty':
                thread.join(2)
                require(not thread.is_alive() and not errors, 'dirty setup failed')
        with (folder/'stdout').open('wb') as stdout,(folder/'stderr').open('wb') as stderr:
            if assist:
                trace.mark('launch')
                proc = subprocess.Popen(
                    ['/bin/strace','-ff','-ttt','-T','-yy','-s','0','--kill-on-exit',
                     '-o',str(folder/'syscall'),*argv], stdin=fd, pass_fds=(exe,),
                    stdout=stdout,stderr=stderr,start_new_session=True)
                try:
                    proc.wait(timeout=1 if mode=='cancel' else 8)
                except subprocess.TimeoutExpired:
                    require(mode=='cancel', 'unexpected assist timeout')
                    trace.mark('cancel')
                    os.killpg(proc.pid, signal.SIGTERM)
                    proc.wait(timeout=3)
                require(active.reap_group(proc.pid), 'traced group cleanup unconfirmed')
        if thread:
            thread.join(4)
            require(not thread.is_alive() and not errors, 'writer cleanup unconfirmed')
        time.sleep(max(0, started+4.5-time.monotonic()))
        cleanup = True
    finally:
        if proc is not None and proc.poll() is None:
            os.killpg(proc.pid,signal.SIGKILL)
            proc.wait(timeout=3)
        for handle in (exe,fd):
            if handle is not None:
                os.close(handle)
        try:
            if cleanup:
                scope.resolve(cleanup_confirmed=True)
        finally:
            scope.close()
    trace.mark('target closed')
    # Observe deferred work without requesting a sync or resetting cache state.
    time.sleep(2)
    data, meta = trace.stop('phase')
    (folder/'kernel.trace').write_text(data)
    calls = list(folder.glob('syscall.*'))
    worker_pids = {int(p.suffix[1:]) for p in calls}
    text = '\n'.join(p.read_text() for p in calls)
    syscall = active.base.audit(text.replace('/dev/sda','/dev/vda'))
    reads, latencies = target_reads(text, active.DISK_BYTES)
    unknown = [line for line in syscall['unknown_target_calls'] if 'pread64(' not in line]
    if assist:
        require(reads and not unknown and not syscall['target_mutations'],
                f'{name}: guarded syscall evidence incomplete: {len(reads)} reads, {unknown}, {syscall["target_mutations"]}')
        require(proc.returncode==0 if mode!='cancel' else proc.returncode!=0,'wrong worker outcome')
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    device = Path('/sys/class/block/sda/dev').read_text().strip().replace(':',',')
    result = correlate(data,worker_pids,device)
    result.update(name=name,mode=mode,assist=assist,read_offsets=reads,read_seconds=latencies,
                  trace=meta,ordinary_writes=observations,worker_pids=sorted(worker_pids),
                  child_cpu_seconds=after.ru_utime+after.ru_stime-usage.ru_utime-usage.ru_stime,
                  direct_mutations=syscall['target_mutations'],unknown_target_calls=unknown)
    return result


def guest(active, directory):
    active.validate_guest(mounted=True)
    trace = Trace()
    # Warm the whole-device mapping with an ordinary buffered read. Keeping the
    # mounted partition open tests the shared-parent release branch.
    fd = os.open('/dev/sda', os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        require(len(os.pread(fd, BS, active.START_SECTOR*512)) == BS, 'warm read failed')
    finally:
        os.close(fd)
    phases = []
    for mode in ('idle','busy','dirty','cancel'):
        repetitions = 1 if mode=='cancel' else 3
        for pair in range(repetitions):
            for assist in ((False,True) if pair%2==0 else (True,False)):
                phases.append(run_phase(active,trace,directory,len(phases),mode,assist))
    overlap = overlap_control(active,trace,directory)
    trace.start('background tail')
    time.sleep(35)
    data, meta = trace.stop('background tail')
    (directory/'background-tail.trace').write_text(data)
    return dict(contract='lvs.storage_thermal.causal_research.v1',
                kernel=os.uname().release, build_id=BUILD_ID.hex(),
                target=Path('/sys/class/block/sda/dev').read_text().strip(),
                control=Path('/sys/class/block/sdb/dev').read_text().strip(),
                fio_version=subprocess.check_output(['/bin/fio','--version'],text=True).strip(),
                phases=phases,overlap=overlap,background_tail=meta,
                disposition='INCONCLUSIVE')


def verify(result):
    require(not result.get('error'), result.get('error', ''))
    require(result['contract']=='lvs.storage_thermal.causal_research.v1','unexpected research contract')
    require(result['kernel']==KERNEL_RELEASE and result['build_id']==BUILD_ID.hex(),'kernel identity missing')
    counts = Counter((row['mode'],row['assist']) for row in result['phases'])
    require(counts=={(mode,assist):1 if mode=='cancel' else 3 for mode in ('idle','busy','dirty','cancel')
                    for assist in (False,True)}, 'paired phase inventory missing')
    require(result['overlap']['file_direct_saw_new_data'],'positive writeback comparison failed')
    require(result['disposition']=='INCONCLUSIVE','research result cannot qualify a provider')
