"""Bounded ext4/NVMe existing-file research in disposable QEMU images only.

No production provider imports this module. No device, file-list, QEMU or fio-job
CLI override exists. Corpus data is generated only while preparing regular images.
"""
from __future__ import annotations

import argparse
import base64
import ctypes
import errno
import hashlib
import io
import json
import mmap
import os
from pathlib import Path
import re
import resource
import shutil
import signal
import stat
import struct
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
from types import SimpleNamespace

try:
    from scripts import storage_thermal_fio_probe as base
except ModuleNotFoundError:
    import probe as base

ROOT = Path(__file__).resolve().parent
if ROOT.name == 'scripts':
    ROOT = ROOT.parent
KERNEL = '7.2.9-200.fc44.x86_64'
SIZE = 512*1024**2
BS = 65536
BUDGET = dict(read_iops=64, read_bps=2097152, startup_read_bytes=33554432,
              session_read_bytes=134217728, cpu_quota_us=25000, cpu_period_us=100000,
              memory_high=201326592, memory_max=268435456, pids=16,
              logical_iops=7, logical_block_bytes=BS, seconds=2, workers=1,
              startup_deadline_seconds=60, supervisor_timeout_seconds=90)
FILE_PROBES = {
    'file_read': ('p','generic_file_read_iter','mapping=+16(+0($arg1)):x64 offset=+8($arg1):u64'),
    'filemap_read': ('p','filemap_read','mapping=+16(+0($arg1)):x64 offset=+8($arg1):u64'),
}


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def regular(path):
    path = Path(path).resolve(strict=True)
    require(stat.S_ISREG(path.stat().st_mode), 'regular host input required')
    return path


def validate_resources(available_memory, cpus, controllers):
    require(type(available_memory) is int and available_memory>=BUDGET['memory_max']+128*1024**2,
            'insufficient available memory for the declared experiment and reserve')
    require(type(cpus) is int and cpus>=1 and BUDGET['cpu_quota_us']<=BUDGET['cpu_period_us']*cpus,
            'CPU quota exceeds available research capacity')
    require({'io','cpu','memory','pids'}<=set(controllers),'required cgroup controls unavailable')


def copy_binary(root, source, dest):
    shutil.copy2(source,root/dest)
    libraries = subprocess.check_output(['ldd',source],text=True)
    for name in re.findall(r'(?:=>\s*)?(/[^\s()]+)',libraries):
        target = root/name.lstrip('/')
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(name,target)


def build_fixture(bundle, root, token, args):
    from scripts.storage_thermal_active_probe import partition_image
    for name in ('newroot','control','corpus','sys/kernel/tracing','sys/fs/cgroup','research'):
        (root/name).mkdir(parents=True,exist_ok=True)
    copy_binary(root,'/usr/bin/switch_root','bin/switch_root')
    copy_binary(root,'/usr/sbin/modprobe','bin/modprobe')
    copy_binary(root,'/usr/bin/sleep','bin/sleep')
    dependencies = subprocess.check_output(['modprobe','--show-depends','nvme'],text=True)
    for line in dependencies.splitlines():
        kind,path,*_ = line.split()
        require(kind=='insmod','unexpected NVMe module dependency')
        source = regular(path)
        target=root/'lib/modules'/KERNEL/source.relative_to(Path('/usr/lib/modules')/KERNEL)
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(source,target)
    for name in ('modules.dep','modules.dep.bin','modules.builtin','modules.builtin.bin','modules.alias','modules.alias.bin'):
        source=Path('/usr/lib/modules')/KERNEL/name
        if source.exists():shutil.copy2(source,root/'lib/modules'/KERNEL/name)
    manifest=dict(session=token,files={})
    for index in range(40):
        opaque=f'f{index:02d}'
        path=root/'corpus'/opaque
        content=hashlib.sha256(opaque.encode()).digest()*(BS//32)
        if index==38:
            with path.open('wb') as stream:stream.truncate(BS)
        else:path.write_bytes(content)
        path.chmod(0o644)
        os.utime(path,(1700000000,1700000000))
        manifest['files'][opaque]=dict(name=opaque,size=BS,kind='regular')
    (root/'file-manifest.json').write_text(json.dumps(manifest))
    (root/'research-tools.json').write_text(json.dumps({name:base.digest(root/'bin'/name) for name in ('fio','file-guard')}))
    (root/'research-budget.json').write_text(json.dumps(BUDGET,sort_keys=True))
    (root/'research-campaign').write_text(args.campaign)
    (root/'init').write_text('#!/bin/sh\n/bin/mount -t proc proc /proc\n/bin/mount -t sysfs sysfs /sys\n/bin/mount -t devtmpfs devtmpfs /dev\n/bin/modprobe nvme\nexec /usr/bin/python3 /foundation_probe.py --guest-init\n')
    for path in root.rglob('*'):
        if path.is_file():path.chmod(path.stat().st_mode & ~(stat.S_ISUID|stat.S_ISGID))
    target=partition_image(bundle,'file-root',SIZE,root)
    control=partition_image(bundle,'file-control',128*1024**2)
    return dict(images=[target,control],drive_args=[
        '-drive',f'file={target},format=raw,if=none,id=filetarget',
        '-device',f'nvme,drive=filetarget,serial=LVF-{token}',
        '-drive',f'file={control},format=raw,if=none,id=filecontrol',
        '-device',f'ich9-ahci,id=lvsahci',
        '-device',f'ide-hd,drive=filecontrol,bus=lvsahci.0,serial=LVC-{token}'],
        description=dict(root='partitioned ext4 rw on emulated NVMe',control='separate AHCI ext4',
                         corpus_files=40,corpus_file_bytes=BS,budget=BUDGET,module_dependencies=dependencies,
                         qemu=subprocess.check_output(['qemu-system-x86_64','--version'],text=True).splitlines()[0],
                         mkfs=subprocess.run(['mkfs.ext4','-V'],capture_output=True,text=True).stderr.strip(),
                         file_guard_source=base.digest(ROOT/'scripts/storage_thermal_file_guard.c'),
                         fio_engine_source=args.engine_source_sha256))


def validate(mounted=False):
    token=json.loads(Path('/fixture.json').read_text())['token']
    require(re.fullmatch('[0-9a-f]{12}',token) and os.getuid()==0 and
            f'lvs_fixture={token}' in Path('/proc/cmdline').read_text().split() and
            'QEMU' in Path('/sys/class/dmi/id/sys_vendor').read_text(), 'outside disposable file-research VM')
    require(Path('/sys/class/nvme/nvme0/serial').read_text().strip()=='LVF-'+token,'wrong NVMe identity')
    require(int(Path('/sys/class/block/nvme0n1/size').read_text())*512==SIZE+1048576,'wrong NVMe geometry')
    require(Path('/sys/class/block/nvme0n1p1').resolve().parent==Path('/sys/class/block/nvme0n1').resolve(),'wrong partition mapping')
    from pathlib import Path as P
    vpd=P('/sys/class/block/sda/device/vpd_pg80').read_bytes()
    require(vpd[4:4+int.from_bytes(vpd[2:4],'big')].decode().strip()=='LVC-'+token,'wrong control disk')
    if mounted:
        require(Path('/proc/self/ns/mnt').stat().st_ino==Path('/proc/1/ns/mnt').stat().st_ino,
                'mount namespace no longer matches fixture authority')
        device=Path('/sys/class/block/nvme0n1p1/dev').read_text().strip()
        require(f'{os.major(os.stat("/").st_dev)}:{os.minor(os.stat("/").st_dev)}'==device,'wrong root mount')
        mounts=[line.split() for line in Path('/proc/mounts').read_text().splitlines()]
        require(any(row[1]=='/' and row[2]=='ext4' and 'rw' in row[3].split(',') for row in mounts),'root not ext4 rw')
        require(os.stat('/').st_dev!=os.stat('/control').st_dev,'control volume not separate')
    return token


def bootstrap():
    validate()
    import causal_probe as causal
    causal.PROBES.update(FILE_PROBES)
    trace=causal.Trace(install=True)
    trace.start('mount and controller setup')
    subprocess.run(['/bin/mount','-t','ext4','-o','rw','/dev/nvme0n1p1','/newroot'],check=True)
    subprocess.run(['/bin/mount','-t','ext4','-o','rw','/dev/sda1','/newroot/control'],check=True)
    data,meta=trace.stop('mount and controller setup')
    evidence=Path('/newroot/control/evidence');evidence.mkdir()
    (evidence/'bootstrap.trace').write_text(data)
    (evidence/'bootstrap.json').write_text(json.dumps(meta,indent=2))
    os.execv('/bin/switch_root',['switch_root','/newroot','/usr/bin/python3','/foundation_probe.py','--driver'])


def authorize(opaque):
    session=validate(mounted=True)
    manifest=json.loads(Path('/file-manifest.json').read_text())
    require(manifest['session']==session and opaque in manifest['files'],'file not in session manifest')
    entry=manifest['files'][opaque]
    require(entry==dict(name=opaque,size=BS,kind='regular') and re.fullmatch('f[0-9]{2}',opaque),'invalid file authority')
    directory=os.open('/corpus',os.O_PATH|os.O_DIRECTORY|os.O_CLOEXEC|os.O_NOFOLLOW)
    try:
        # This proof is pinned to x86-64; openat2 is syscall 437 on that ABI.
        how=struct.pack('QQQ',os.O_RDONLY|os.O_CLOEXEC|os.O_NOATIME,0,0x08|0x04|0x02|0x01)
        libc=ctypes.CDLL(None,use_errno=True)
        fd=libc.syscall(437,directory,opaque.encode(),how,len(how))
        if fd<0:raise OSError(ctypes.get_errno(),'constrained corpus open refused')
    finally:os.close(directory)
    try:
        st=os.fstat(fd)
        require(stat.S_ISREG(st.st_mode) and st.st_size==entry['size'] and st.st_dev==os.stat('/').st_dev and st.st_nlink>0,'file identity/mount/size mismatch')
        return fd,dict(session=session,opaque=opaque,device=st.st_dev,inode=st.st_ino,size=st.st_size,
                       atime_ns=st.st_atime_ns,mtime_ns=st.st_mtime_ns,ctime_ns=st.st_ctime_ns)
    except BaseException:os.close(fd);raise


def residency(fd):
    with mmap.mmap(fd,BS,access=mmap.ACCESS_COPY) as mapping:
        address=ctypes.addressof(ctypes.c_char.from_buffer(mapping));vector=(ctypes.c_ubyte*16)()
        result=ctypes.CDLL(None,use_errno=True).mincore(ctypes.c_void_p(address),BS,vector)
        require(result==0,'mincore failed')
        return [int(value&1) for value in vector]


def extents(fd):
    import fcntl
    buffer=bytearray(32+56*8)
    struct.pack_into('=QQIIII',buffer,0,0,BS,0,0,8,0)
    fcntl.ioctl(fd,0xc020660b,buffer,True)  # flags=0 never requests synchronization
    count,=struct.unpack_from('=I',buffer,20)
    require(count<8,'extent evidence truncated')
    return [dict(zip(('logical','physical','length'),struct.unpack_from('=QQQ',buffer,32+i*56))) for i in range(count)]


def cgstats():
    cg=Path('/sys/fs/cgroup/aux')
    return {name:(cg/name).read_text() for name in ('io.stat','cpu.stat','memory.current','memory.peak','pids.current','memory.events')}


def io_values(stats,device):
    for line in stats['io.stat'].splitlines():
        fields=line.split()
        if fields[0]==device:
            return {key:int(value) for key,value in (field.split('=') for field in fields[1:])}
    return dict(rbytes=0,wbytes=0,rios=0,wios=0)


def research_executable(name):
    """Image-pinned proof with the declared startup budget, separate from production.

    The production one-second snapshot intentionally fails at low I/O budgets.
    Do not alter its policy or export this observation as production readiness.
    """
    require(name in ('fio','file-guard'), 'unknown research executable')
    expected=json.loads(Path('/research-tools.json').read_text())[name]
    fd=os.open('/bin/'+name,os.O_RDONLY|os.O_CLOEXEC|os.O_NOATIME|os.O_NOFOLLOW)
    try:
        start=time.monotonic();before=os.fstat(fd);digest=hashlib.sha256();size=0
        require(stat.S_ISREG(before.st_mode) and before.st_size<=32*1024**2,'invalid research ELF')
        while chunk:=os.read(fd,65536):
            size+=len(chunk);digest.update(chunk)
            require(time.monotonic()-start<BUDGET['startup_deadline_seconds'],'research provenance deadline')
        after=os.fstat(fd)
        identity=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
        require(identity(before)==identity(after) and size==before.st_size and digest.hexdigest()==expected,'research executable changed')
        return fd,dict(sha256=expected,device=before.st_dev,inode=before.st_ino,size=size,elapsed=time.monotonic()-start,
                       policy='image_digest_with_declared_research_startup_budget')
    except BaseException:os.close(fd);raise


class CgroupOwner:
    @property
    def process(self):return self._process
    @process.setter
    def process(self,value):
        # OwnedProcess invokes this callback before releasing its native gate.
        (Path('/sys/fs/cgroup/aux')/'cgroup.procs').write_text(str(value.authority_pid))
        self._process=value


def run_worker(folder,fd,identity,mode,deadline=None,delay_ms=0,event=None):
    from Modules.lvs_storage_thermal_launch import OwnedProcess
    exe,fio_provenance=research_executable('fio')
    guard,guard_provenance=research_executable('file-guard')
    provenance=dict(fio=fio_provenance,guard=guard_provenance)
    owner=SimpleNamespace(process=None)
    deadline=deadline if deadline is not None else time.monotonic_ns()+60_000_000_000
    argv=[f'/proc/self/fd/{guard}','--research-file',str(exe),str(identity['device']),str(identity['inode']),str(BS),str(mode),str(deadline),str(os.getpid()),identity['session']]
    start=time.monotonic();process=None
    try:
        with (folder/'out').open('wb') as out,(folder/'err').open('wb') as err:
            process=OwnedProcess(['/bin/strace','-ff','-ttt','-T','-yy','-s','0','--kill-on-exit','-o',str(folder/'syscall'),*argv],
                                 stdin=fd,stdout=out,stderr=err,pass_fds=(exe,guard),owner=owner,delay_ms=delay_ms)
            try:
                if event is not None:
                    timeout=time.monotonic()+20
                    while not any('preadv2(' in path.read_text() and '/corpus/' in path.read_text()
                                  for path in folder.glob('syscall.*')):
                        require(process.poll() is None and time.monotonic()<timeout,'event has no genuine file read')
                        time.sleep(.02)
                    event(process)
                process.wait(timeout=45)
            finally:
                if process.poll() is None:process.terminate()
                try:process.wait(timeout=3)
                except subprocess.TimeoutExpired:process.kill();process.wait(timeout=3)
            require(process.group_cleanup_confirmed(),'file worker group cleanup uncertain')
        return dict(exit=process.returncode,elapsed=time.monotonic()-start,cleanup_confirmed=True,
                    creation_pid=process.authority_pid,provenance=provenance)
    finally:os.close(exe);os.close(guard)


def fresh_blocker(marker):
    from Modules.lvs_storage_thermal_launch import OwnedProcess
    code='from pathlib import Path;from Modules.lvs_storage_thermal_recovery import blocker;import sys;print(bool(blocker(Path(sys.argv[1]))))'
    child=OwnedProcess(['/usr/bin/python3','-B','-c',code,str(marker)],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    stdout,stderr=child.communicate(timeout=15)
    require(child.returncode==0 and child.group_cleanup_confirmed(), 'fresh recovery inspection failed')
    return stdout.strip() in (b'True','True')


def durable_negative(folder,task):
    from Modules.lvs_storage_thermal_recovery import RecoveryScope
    from unittest.mock import patch
    scope=RecoveryScope(folder/'intent');rejected=False
    error=errno.ENOSPC if task['action']=='durable-enospc' else errno.EIO
    with patch('Modules.lvs_storage_thermal_recovery.durable_json',side_effect=OSError(error,'research durable failure')):
        try:scope.enter(evidence_directory=folder)
        except OSError:rejected=True
    require(rejected and fresh_blocker(scope.marker),'failed intent publication did not block restart')
    return dict(task=task,rejected=True,target_opened=False,journal='missing_or_ambiguous_unsafe',
                fresh_blocked=True,worker=dict(cleanup_confirmed=False),extents=[],residency_before=[],residency_after=[])


def aux(folder):
    session=validate(mounted=True)
    require('0::/aux' in Path('/proc/self/cgroup').read_text(),'auxiliary escaped resource boundary')
    from Modules.lvs_storage_thermal_launch import prepare
    from Modules.lvs_storage_thermal_recovery import RecoveryScope,read_state
    prepare('/bin')
    task=json.loads((folder/'task.json').read_text())
    if task.get('action') in ('durable-enospc','durable-eio'):
        (folder/'aux.json').write_text(json.dumps(durable_negative(folder,task),indent=2));return
    scope=RecoveryScope(folder/'intent').enter(evidence_directory=folder)
    fd=None;cleanup=False;result=dict(session=session,task=task)
    before=cgstats()
    writer=None;stop=threading.Event();mutations=[];writer_errors=[]
    try:
        fd,identity=authorize(task['opaque']);result['identity']=identity
        result['residency_before']=residency(fd)
        result['extents']=extents(fd)
        state=task.get('state','cold')
        def ordinary_write_loop():
            handle=None
            try:
                handle=os.open('/corpus/'+identity['opaque'],os.O_WRONLY|os.O_CLOEXEC|os.O_NOFOLLOW)
                require(os.fstat(handle).st_ino==identity['inode'],'fixture writer inode mismatch')
                for i in range(20 if state=='concurrent' else 1):
                    if stop.is_set():break
                    started=time.monotonic();n=os.pwrite(handle,b'D'*4096,0)
                    require(n==4096,'short controlled ordinary write')
                    mutations.append(dict(start=started,end=time.monotonic(),bytes=n,pid=os.getpid(),tid=threading.get_native_id()))
                    if state=='concurrent':stop.wait(.1)
            except BaseException as error:writer_errors.append(repr(error))
            finally:
                if handle is not None:os.close(handle)
        if state=='dirty':ordinary_write_loop()
        elif state=='concurrent':
            writer=threading.Thread(target=ordinary_write_loop);writer.start()
        result['residency_pre_worker']=residency(fd)
        if task.get('warm'):
            # This read is explicit, budgeted and reported; no unreported warmup.
            require(len(os.pread(fd,BS,0))==BS,'short warm control read')
            result['warmup_bytes']=BS
            result['residency_after_warmup']=residency(fd)
        action=task.get('action')
        result['lifetime']={}
        if action in ('memory-limit','pids-limit'):
            from Modules.lvs_storage_thermal_launch import OwnedProcess
            if action=='memory-limit':
                child=OwnedProcess(['/usr/bin/python3','-B','-c','x=bytearray(300*1024*1024)'])
                child.wait(timeout=25)
                require(child.returncode==-signal.SIGKILL and child.group_cleanup_confirmed(),'memory limit did not kill/reap the disposable allocator')
                result['resource_control']=dict(allocator_exit=child.returncode,events=cgstats()['memory.events'])
            else:
                children=[];refused=False
                try:
                    for _ in range(BUDGET['pids']+1):
                        try:children.append(OwnedProcess(['/bin/sleep','30']))
                        except OSError as error:
                            require(error.errno==errno.EAGAIN,'unexpected process limit failure');refused=True;break
                    require(refused,'pids limit was not enforced')
                    result['resource_control']=dict(children=len(children),refused=True,current=cgstats()['pids.current'])
                finally:
                    for child in children:
                        child.terminate();child.wait(timeout=3)
                        require(child.group_cleanup_confirmed(),'process-limit child cleanup uncertain')
        def lifetime_event(process):
            evidence=result['lifetime'];evidence['first_read_observed']=True
            path=Path('/corpus')/identity['opaque']
            if action in ('replace','rename','unlink','truncate','modify'):
                if action=='replace':os.replace('/corpus/f39',path)
                elif action=='rename':os.rename(path,path.with_name('renamed-fixture'))
                elif action=='unlink':path.unlink()
                elif action=='truncate':os.truncate(path,0)
                else:
                    with path.open('r+b',buffering=0) as stream:os.pwrite(stream.fileno(),b'M'*4096,0)
                now=os.fstat(fd)
                evidence.update(change_detected=True,identity_retained=now.st_ino==identity['inode'],
                                links=now.st_nlink,size=now.st_size,changed_at=time.monotonic())
            elif action=='namespace':
                require(ctypes.CDLL(None,use_errno=True).unshare(0x20000)==0,'mount namespace negative unavailable')
                try:authorize(identity['opaque'])
                except RuntimeError:evidence['new_acquisition_rejected']=True
                require(evidence.get('new_acquisition_rejected'),'changed namespace permitted acquisition')
            elif action=='uncertain':
                saved=os.dup(process.pidfd) if process.pidfd is not None else None
                require(saved is not None,'pidfd uncertainty fixture unavailable')
                foreign=os.open('/dev/null',os.O_RDONLY|os.O_CLOEXEC)
                try:
                    os.dup2(foreign,process.pidfd)
                    try:process.terminate()
                    except OSError:evidence['lost_authority_refused']=True
                    require(evidence.get('lost_authority_refused'),'uncertain process authority accepted')
                    evidence['fresh_blocked_before_restore']=fresh_blocker(scope.marker)
                    require(evidence['fresh_blocked_before_restore'],'uncertainty lost recovery intent')
                    try:scope.resolve(cleanup_confirmed=False)
                    except ValueError:evidence['clean_refused']=True
                finally:
                    os.dup2(saved,process.pidfd);os.close(saved);os.close(foreign)
            elif action=='supervisor-death':
                (folder/'kill-ready').write_text(str(process.authority_pid))
                time.sleep(30)
                raise RuntimeError('driver did not terminate the owned supervisor')
            process.terminate();evidence['cancellation_sent_at']=time.monotonic()
        if task['mode']=='control' or action in ('memory-limit','pids-limit'):
            result['provenance']={}
            for name in ('fio','file-guard'):
                handle,observed=research_executable(name);os.close(handle);result['provenance'][name]=observed
            time.sleep(2)
            result['worker']=dict(exit=None,cleanup_confirmed=True)
        else:
            deadline=time.monotonic_ns()-1 if action=='expired' else None
            delay=1500 if action=='delayed-expiry' else 0
            if action=='delayed-expiry':deadline=time.monotonic_ns()+1_000_000_000
            if action=='wrong-inode':identity=dict(identity,inode=identity['inode']+1)
            if action=='wrong-device':identity=dict(identity,device=identity['device']+1)
            if action=='missing-noatime':
                os.close(fd);fd=os.open('/corpus/'+identity['opaque'],os.O_RDONLY|os.O_CLOEXEC|os.O_NOFOLLOW)
            events=('replace','rename','unlink','truncate','modify','namespace','uncertain','cancel','slow-cancel','supervisor-death')
            result['worker']=run_worker(folder,fd,identity,task['mode'],deadline=deadline,delay_ms=delay,
                                        event=lifetime_event if action in events else None)
        stop.set()
        if writer is not None:writer.join(timeout=3);require(not writer.is_alive(),'fixture writer cleanup uncertain')
        require(not writer_errors,'controlled ordinary writer failed')
        result['ordinary_fixture_writes']=mutations
        result['residency_after']=residency(fd) if os.fstat(fd).st_size==BS else []
        result['atime_unchanged']=os.fstat(fd).st_atime_ns==identity['atime_ns']
        os.close(fd);fd=None
        cleanup=result['worker']['cleanup_confirmed']
        if cleanup:
            if action=='clean-enospc':
                from unittest.mock import patch
                with patch('Modules.lvs_storage_thermal_recovery.durable_json',side_effect=OSError(errno.ENOSPC,'CLEAN publication failure')):
                    try:scope.resolve(cleanup_confirmed=True)
                    except OSError:result['clean_publication_rejected']=True
                require(result.get('clean_publication_rejected'),'CLEAN failure injection not reached')
            else:scope.resolve(cleanup_confirmed=True)
        result['journal']=read_state(scope.marker)['state']
        # Restart inspection must follow release of this still-exclusive owner.
        scope.close()
        result['fresh_blocked_after_cleanup']=fresh_blocker(scope.marker)
        require(result['fresh_blocked_after_cleanup']==(action=='clean-enospc'),'wrong restart recovery state')
    finally:
        stop.set()
        if writer is not None:writer.join(timeout=3)
        if fd is not None:os.close(fd)
        scope.close()
    result['resources_before']=before;result['resources_after']=cgstats()
    (folder/'aux.json').write_text(json.dumps(result,indent=2))


def publish(directory,result):
    (directory/'results.json').write_text(json.dumps(result,indent=2))
    stream=io.BytesIO()
    with tarfile.open(fileobj=stream,mode='w:gz') as archive:archive.add(directory,arcname='evidence')
    print('LVS_EVIDENCE_BEGIN',flush=True);print(base64.b64encode(stream.getvalue()).decode(),flush=True);print('LVS_EVIDENCE_END',flush=True)


def observe_case(folder,record,causal):
    events=list(causal.trace_events((folder/'kernel.trace').read_text()))
    ranges=[(1048576+e['physical']//512*512,1048576+e['physical']+e['length']) for e in record['extents']]
    selected=[]
    for e in events:
        if e['event']!='block_bio_queue':continue
        match=re.match(r'^259,0 (\S+) (\d+) \+ (\d+)',e['detail'])
        if match:
            kind,sector,count=match.groups();first=int(sector)*512;last=first+int(count)*512
            if any(a<=first and last<=b for a,b in ranges):selected.append(dict(e,operation=kind,bytes=last-first))
    return dict(corpus_bios=selected,read_bytes=sum(e['bytes'] for e in selected if e['operation'].startswith('R')),
                write_bytes=sum(e['bytes'] for e in selected if e['operation'].startswith('W')),
                logical_reads=sum(bool(re.search(r'\) = 65536 <',line)) for line in record['preadv2_calls']))


def campaign_jobs(campaign):
    jobs=[dict(opaque=f'f{n:02d}',mode=mode,state='cold') for n,mode in enumerate((0,1))]
    for state in ('cold','warm','dirty','concurrent'):
        for repetition in range(3):
            for mode in (('control',0,1) if repetition%2==0 else (1,0,'control')):
                jobs.append(dict(opaque=f'f{len(jobs):02d}',mode=mode,state=state,warm=state=='warm',repetition=repetition))
    if campaign=='access':return list(enumerate(jobs))
    if campaign=='access-tail':return list(enumerate(jobs))[29:]
    if campaign.startswith('access-'):
        state=campaign.removeprefix('access-')
        return [(n,job) for n,job in enumerate(jobs) if n>=2 and job['state']==state]
    actions=('policy','unknown-flags','noatime-permission','expired','delayed-expiry','replace','rename',
             'unlink','truncate','modify','namespace','cancel','uncertain','sparse','slow-cancel',
             'supervisor-death','durable-enospc','durable-eio','wrong-inode','wrong-device','missing-noatime','clean-enospc',
             'io-limit','memory-limit','pids-limit')
    cases=[]
    for number,action in enumerate(actions):
        mode={'policy':3,'unknown-flags':2,'noatime-permission':4}.get(action,1)
        cases.append((number,dict(opaque='f38' if action=='sparse' else f'f{number+2:02d}',mode=mode,state='cold',action=action)))
    if campaign=='lifetime-recovery':
        selected={'cancel','uncertain','sparse','supervisor-death','durable-enospc','durable-eio','wrong-inode','wrong-device','missing-noatime','clean-enospc'}
        return [(number,task) for number,task in cases if task['action'] in selected]
    return cases[:11] if campaign=='lifetime-a' else cases[11:]


def terminate_supervisor(process,folder,group):
    """Synthetic private-cgroup death test. Keep the original obligation ARMED."""
    end=time.monotonic()+40
    while not (folder/'kill-ready').exists():
        require(process.poll() is None and time.monotonic()<end,'death control never reached actual file read')
        time.sleep(.02)
    handles=[]
    for pid in (group/'cgroup.procs').read_text().split():
        if int(pid)!=process.authority_pid:
            try:handles.append(os.pidfd_open(int(pid)))
            except ProcessLookupError:pass
    process.kill();process.wait(timeout=5)
    (group/'cgroup.kill').write_text('1')
    deadline=time.monotonic()+10
    while (group/'cgroup.procs').read_text().strip() and time.monotonic()<deadline:time.sleep(.02)
    require(not (group/'cgroup.procs').read_text().strip(),'dead supervisor descendants remain')
    reaped=0
    for handle in handles:
        try:
            try:
                status=os.waitid(os.P_PIDFD,handle,os.WEXITED|os.WNOHANG)
                if status is not None:reaped+=1
            except ChildProcessError:pass  # May have been reaped by its original tracer.
        finally:os.close(handle)
    require(fresh_blocker(folder/'intent'),'supervisor death lost durable obligation')
    return dict(private_cgroup_empty=True,pidfd_reaped=reaped,fresh_blocked=True,original_owner_dead=True)


def driver():
    session=validate(mounted=True)
    subprocess.run(['/bin/mount','-t','tmpfs','tmpfs','/tmp'],check=True)
    subprocess.run(['/bin/mount','-t','cgroup2','cgroup2','/sys/fs/cgroup'],check=True)
    from Modules.lvs_storage_thermal_launch import OwnedProcess,prepare
    import causal_probe as causal
    causal.PROBES.update(FILE_PROBES)
    trace=causal.Trace()
    trace.start('controller setup')
    prepare('/bin')
    cg=Path('/sys/fs/cgroup');(cg/'cgroup.subtree_control').write_text('+io +cpu +memory +pids')
    meminfo=Path('/proc/meminfo').read_text()
    available=int(re.search(r'^MemAvailable:\s*(\d+)',meminfo,re.M)[1])*1024
    validate_resources(available,os.cpu_count(),(cg/'cgroup.controllers').read_text().split())
    group=cg/'aux';group.mkdir()
    target=Path('/sys/class/block/nvme0n1/dev').read_text().strip()
    for name,value in {'io.max':f'{target} rbps={BUDGET["read_bps"]} riops={BUDGET["read_iops"]}',
                       'cpu.max':f'{BUDGET["cpu_quota_us"]} {BUDGET["cpu_period_us"]}',
                       'memory.high':str(BUDGET['memory_high']),'memory.max':str(BUDGET['memory_max']),
                       'pids.max':str(BUDGET['pids'])}.items():
        (group/name).write_text(value)
    data,meta=trace.stop('controller setup');directory=Path('/control/evidence')
    (directory/'controller.trace').write_text(data);(directory/'controller.json').write_text(json.dumps(meta,indent=2))
    rows=[]
    try:
        campaign=Path('/research-campaign').read_text()
        for number,job in campaign_jobs(campaign):
            folder=directory/f'case-{number:02d}';folder.mkdir()
            (folder/'task.json').write_text(json.dumps(job))
            trace.start(f'capability-{number}')
            boundary_before=cgstats()
            if job.get('action')=='slow-cancel':(group/'io.max').write_text(f'{target} rbps=4096 riops=64')
            if job.get('action')=='io-limit':(group/'io.max').write_text(f'{target} rbps=2097152 riops=1')
            applied_limits={name:(group/name).read_text() for name in ('io.max','cpu.max','memory.high','memory.max','pids.max')}
            owner=CgroupOwner()
            with (folder/'supervisor.out').open('wb') as out,(folder/'supervisor.err').open('wb') as err:
                proc=OwnedProcess(['/usr/bin/python3','-B','/foundation_probe.py','--aux',str(folder)],owner=owner,stdout=out,stderr=err)
                death=None
                try:
                    if job.get('action')=='supervisor-death':death=terminate_supervisor(proc,folder,group)
                    else:proc.wait(timeout=90)
                finally:
                    if proc.poll() is None:proc.kill();proc.wait(timeout=5)
                require(proc.group_cleanup_confirmed(),'auxiliary supervisor cleanup uncertain')
            boundary_after=cgstats()
            (group/'io.max').write_text(f'{target} rbps={BUDGET["read_bps"]} riops={BUDGET["read_iops"]}')
            time.sleep(1)
            data,meta=trace.stop(f'capability-{number}');(folder/'kernel.trace').write_text(data)
            if death is not None:
                record=dict(task=job,worker=dict(exit=proc.returncode,cleanup_confirmed=False),journal='ARMED',death=death,extents=[])
            else:
                require(proc.returncode==0,(folder/'supervisor.err').read_text())
                record=json.loads((folder/'aux.json').read_text())
            record['trace']=meta
            record['boundary_before']=boundary_before;record['boundary_after']=boundary_after
            record['applied_limits']=applied_limits
            counters_before=io_values(boundary_before,target);counters_after=io_values(boundary_after,target)
            record['resource_delta']={key:counters_after.get(key,0)-counters_before.get(key,0) for key in ('rbytes','wbytes','rios','wios')}
            record['budget_observation']=dict(case_read_bytes=record['resource_delta']['rbytes'],
                session_read_bytes=counters_after['rbytes'],case_exceeded=record['resource_delta']['rbytes']>BUDGET['startup_read_bytes'],
                session_exceeded=counters_after['rbytes']>BUDGET['session_read_bytes'],
                semantics='post-case stop budget; cgroup rate controls permit transient bursts')
            calls='\n'.join(p.read_text() for p in folder.glob('syscall.*'))
            record['preadv2_calls']=[line for line in calls.splitlines() if 'preadv2(' in line]
            output=(folder/'out').read_text() if (folder/'out').exists() else ''
            try:record['native_output']=json.loads(output[output.index('{'):])
            except (ValueError,IndexError):record['native_output']=None
            record['fio_help']=subprocess.check_output(['/bin/fio','--enghelp=pvsync2'],text=True)
            record['activity']=observe_case(folder,record,causal)
            rows.append(record)
            # These are control-volume evidence writes, outside the workload.
            from Modules.lvs_storage_thermal_recovery import durable_json
            for path in folder.iterdir():
                if path.is_file():
                    handle=os.open(path,os.O_RDONLY|os.O_CLOEXEC)
                    try:os.fsync(handle)
                    finally:os.close(handle)
            durable_json(folder/'record.json',record)
            print('LVS_FILE_CASE '+json.dumps(dict(case=number,campaign=campaign,record_sha256=base.digest(folder/'record.json'))),flush=True)
            require(not record['budget_observation']['case_exceeded'] and not record['budget_observation']['session_exceeded'],'declared read-byte stop budget exceeded')
            # Capability-first finite stop: no repeated cold device reads means
            # no useful transient-cache path for the proposed workload.
            if campaign=='access' and number==1 and (record['worker']['exit']!=0 or record['activity']['logical_reads']<2 or
                              record['activity']['read_bytes']<=BS):
                break
        result=dict(contract='lvs.storage_thermal.file_research.v1',session=session,kernel=os.uname().release,
                    fio=subprocess.check_output(['/bin/fio','--version'],text=True).strip(),budget=BUDGET,
                    boundary='aux supervisor placed in cgroup before native release; controller bootstrap separately traced',capability=rows,
                    campaign=campaign,decision='INCONCLUSIVE',production_eligibility=False)
    except Exception as error:
        result=dict(error=repr(error),capability=rows,decision='INCONCLUSIVE')
    publish(directory,result)


def verify(result):
    require(not result.get('error'),result.get('error',''))
    require(result['contract']=='lvs.storage_thermal.file_research.v1' and result['production_eligibility'] is False,'foreign research contract')
    require(result['decision']=='INCONCLUSIVE','automatic provider qualification forbidden')
    if result.get('campaign') and result['campaign']!='access':
        require([row['task'] for row in result['capability']]==[job for _,job in campaign_jobs(result['campaign'])],
                'missing, duplicated or reordered experimental cases')
    require(len(result['capability'])>=2,'capability records incomplete')
    for row in result['capability']:
        action=row['task'].get('action')
        if action in ('supervisor-death','durable-enospc','durable-eio','clean-enospc'):
            require(row.get('fresh_blocked',False) or row.get('fresh_blocked_after_cleanup',False) or row.get('death',{}).get('fresh_blocked',False),'uncertainty lost recovery protection')
        else:require(row['worker']['cleanup_confirmed'] and row['journal']=='CLEAN','cleanup evidence missing')
        if action in ('expired','delayed-expiry','wrong-inode','wrong-device','missing-noatime'):
            require(row['worker']['exit']==125 and not row['activity']['logical_reads'],'invalid authority reached file reads')
        if action=='unknown-flags':require(row['native_output']=={'unknown_flag_result':-1,'errno':errno.EOPNOTSUPP},'unsupported flag silently accepted')
        if action=='policy':require(row['native_output']=={'file_policy':'PASS'},'regular-file policy denials failed')
        if action=='noatime-permission':require(row['native_output']=={'noatime_permission_errno':errno.EPERM,'ordinary_open_succeeded':True},'noatime permission proof missing')
        if action in ('replace','rename','unlink','truncate','modify','namespace','cancel','slow-cancel'):
            require(row.get('lifetime',{}).get('first_read_observed') and row['worker']['exit']!=0,'lifetime interruption not demonstrated')
        if action=='uncertain':require(all(row['lifetime'].get(field) for field in ('lost_authority_refused','fresh_blocked_before_restore','clean_refused')),'uncertain authority did not preserve recovery')
        if action=='sparse':require(row['activity']['logical_reads']>0 and row['activity']['read_bytes']==0,'sparse zero-data control invalid')


def host(args):
    from scripts import storage_thermal_causal_probe as causal
    causal.require_kernel_image(args.kernel)
    for name in ('fio','old_fio','strace','kernel','python','guard'):regular(getattr(args,name))
    require(base.digest(args.fio)=='444ba07aeaa89d0f2f9ecdd2577f6846401d8dcbc54d6dedce96120cb95c9378','different fio binary requires independent qualification')
    bundle=Path(tempfile.mkdtemp(prefix='lvs-file-tools-'))
    from Modules.lvs_native_helpers import find_c_compiler,native_helper_build_command
    compiler=find_c_compiler();require(compiler is not None,'existing compiler required')
    binary=bundle/'file-guard';launch=bundle/'storage_thermal_launch.so'
    subprocess.run(native_helper_build_command(compiler,ROOT/'scripts/storage_thermal_file_guard.c',binary)+['-Wall','-Wextra','-Werror'],check=True,capture_output=True,timeout=30)
    subprocess.run(native_helper_build_command(compiler,ROOT/'native/storage_thermal_launch.c',launch)+['-shared','-fPIC','-Wall','-Wextra','-Werror'],check=True,capture_output=True,timeout=30)
    source=regular(Path(args.fio).parent/'engines/sync.c')
    args.engine_source_sha256=base.digest(source)
    require(args.engine_source_sha256=='af7609913c35877219f7e5e0ffd0025c6fac42e33ed527abd27025e4a4e2ed63','different fio engine source')
    extras=[(p,'/Modules/'+p.name) for p in (ROOT/'Modules').glob('*.py')]
    extras += [(binary,'/bin/file-guard'),(launch,'/bin/storage_thermal_launch.so'),
               (ROOT/'native/storage_thermal_launch.c','/native/storage_thermal_launch.c'),
               (Path(causal.__file__),'/causal_probe.py')]
    base.host(args,guest_script=Path(__file__).resolve(),verifier=verify,extra_files=extras,fixture_builder=build_fixture)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--guest-init',action='store_true',help=argparse.SUPPRESS)
    parser.add_argument('--driver',action='store_true',help=argparse.SUPPRESS)
    parser.add_argument('--aux',help=argparse.SUPPRESS)
    parser.add_argument('--campaign',choices=('access','access-tail','access-cold','access-warm','access-dirty','access-concurrent','lifetime-a','lifetime-b','lifetime-recovery'),default='access-cold')
    for name in ('fio','old-fio','strace','kernel','python','guard'):parser.add_argument('--'+name)
    args=parser.parse_args()
    if args.guest_init:bootstrap()
    elif args.driver:driver()
    elif args.aux:aux(Path(args.aux))
    else:
        if not all(getattr(args,k) for k in ('fio','old_fio','strace','kernel','python','guard')):parser.error('explicit existing tool/kernel paths required')
        host(args)
