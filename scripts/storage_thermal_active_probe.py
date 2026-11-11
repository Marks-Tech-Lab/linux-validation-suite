"""Gate 2B-4A research only: mounted, private writable QEMU images.

No device/path override, host block access, production provider or automatic GO.
A completed experiment is not qualified unless kernel-side causality is resolved.
"""
from __future__ import annotations
import argparse
import base64
import errno
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import re
import signal
import stat
import struct
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
from unittest.mock import patch

try:
    from scripts import storage_thermal_fio_probe as base
except ModuleNotFoundError:
    try:import storage_thermal_fio_probe as base
    except ModuleNotFoundError:import probe as base

ROOT=Path(__file__).resolve().parent
if ROOT.name=='scripts':ROOT=ROOT.parent
PARTITION_BYTES=512*1024**2
START_SECTOR=2048
DISK_BYTES=PARTITION_BYTES+START_SECTOR*512
CONTROL_BYTES=128*1024**2
TRACE=Path('/sys/kernel/tracing')
FUNCTIONS=('blkdev_read_iter','filemap_write_and_wait_range','sync_blockdev',
           'bdev_release','blkdev_flush_mapping','kill_bdev','invalidate_bdev')
LIFECYCLE=('normal','cancel','deadline','wrong-identity','partition-confusion','readwrite-fd',
    'buffered-fd','guard-policy','source-substitution','stale-backend','durable-ENOSPC','durable-EIO',
    'unsupported-direct','wrong-topology','missing-backend','old-fio','clean-ENOSPC','clean-EIO')
EVENTS=('block/block_bio_queue','block/block_rq_issue','block/block_rq_complete',
        'writeback/writeback_start','writeback/writeback_written')


def regular(path):
    p=Path(path).resolve(strict=True)
    base.require(stat.S_ISREG(p.stat().st_mode),'host inputs must be regular tool/source files')
    return p


def partition_image(bundle,name,size,tree=None):
    """mkfs operates only on newly created regular files; never mounts on host."""
    base.require(bool(re.fullmatch('[a-z][a-z0-9-]{0,31}',name)) and type(size) is int and 4096<=size<=2*1024**3 and size%512==0,'invalid disposable image specification')
    part=bundle/(name+'.ext4');disk=bundle/(name+'.raw')
    with part.open('xb') as f:f.truncate(size)
    command=['mkfs.ext4','-q','-F','-E','lazy_itable_init=0,lazy_journal_init=0']
    if tree is not None:command+=['-d',str(tree)]
    subprocess.run(command+[str(part)],check=True,capture_output=True,timeout=60)
    mbr=bytearray(512);sectors=size//512
    mbr[446:462]=struct.pack('<B3sB3sII',0x80,b'\0\2\0',0x83,b'\xfe\xff\xff',START_SECTOR,sectors)
    mbr[510:512]=b'\x55\xaa'
    with disk.open('xb') as f:
        f.write(mbr);f.seek(START_SECTOR*512)
        with part.open('rb') as source:
            import shutil
            shutil.copyfileobj(source,f,1024**2)
    base.require(disk.stat().st_size==size+START_SECTOR*512,'incorrect disposable image size')
    return disk


def build_fixture(bundle,root,token,args):
    for source,dest in (('/usr/bin/switch_root','bin/switch_root'),):
        import shutil
        shutil.copy2(source,root/dest)
        libs=subprocess.check_output(['ldd',source],text=True)
        for lib in re.findall(r'(?:=>\s*)?(/[^\s()]+)',libs):
            p=root/lib.lstrip('/');p.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(lib,p)
    for name in ('newroot','control','sys/kernel/tracing'):(root/name).mkdir(parents=True,exist_ok=True)
    if getattr(args, 'causal', False):
        (root/'causal-enabled').touch()
        for index in range(20):
            (root/f'causal-data-{index}').write_bytes(b'B'*65536)
    if getattr(args, 'targeted', False):
        (root/'targeted-enabled').touch()
    # A guest OS workload fixture, not a production thermal test file.
    (root/'ordinary-data').write_bytes(b'OS fixture\n'*4096)
    (root/'init').write_text('#!/bin/sh\n/bin/mount -t proc proc /proc\n/bin/mount -t sysfs sysfs /sys\n/bin/mount -t devtmpfs devtmpfs /dev\nexec /usr/bin/python3 /foundation_probe.py --guest-init\n')
    # mkfs -d preserves host ownership. Never import host setuid identities.
    for p in root.rglob('*'):
        if p.is_file():p.chmod(p.stat().st_mode & ~(stat.S_ISUID|stat.S_ISGID))
    target=partition_image(bundle,'active-root',PARTITION_BYTES,root)
    control=partition_image(bundle,'control',CONTROL_BYTES)
    drives=['-device','ich9-ahci,id=lvsahci']
    for index,(name,path,prefix) in enumerate((('target',target,'LVS'),('control',control,'LVC'))):
        drives+=['-drive',f'file={path},format=raw,if=none,id={name}',
                 '-device',f'ide-hd,drive={name},bus=lvsahci.{index},serial={prefix}-{token},rotation_rate=7200,logical_block_size=512,physical_block_size=4096']
    images = [target, control]
    if getattr(args, 'targeted', False):
        mapping = bundle/'mapping.raw'
        with mapping.open('xb') as stream:
            stream.write(b'M'*65536)
        images.append(mapping)
        drives += ['-drive', f'file={mapping},format=raw,if=none,id=mapping,throttling.bps-write=4096',
                   '-device', f'ide-hd,drive=mapping,bus=lvsahci.2,serial=LVW-{token},rotation_rate=7200']
    return dict(drive_args=drives,images=images,description=dict(
        partition_table='MBR',start_sector=START_SECTOR,root_partition_bytes=PARTITION_BYTES,
        root='ext4 rw on AHCI SATA-like /dev/sda1',target='/dev/sda',
        control='ext4 rw /dev/sdb1; separate persistent journal/results',
        virtual_fixture_not_physical_eligibility=True,
        qemu_version=subprocess.check_output(['qemu-system-x86_64','--version'],text=True).splitlines()[0],
        mkfs_version=subprocess.run(['mkfs.ext4','-V'],capture_output=True,text=True,check=True).stderr.strip(),
        guard_source_sha256=base.digest(ROOT/'native/storage_thermal_guard.c'),
        launch_source_sha256=base.digest(ROOT/'native/storage_thermal_launch.c'),
        launch_binary_sha256=base.digest(root/'bin/storage_thermal_launch.so')))


def serial(name):
    node=Path('/sys/class/block')/name/'device'
    if (node/'serial').exists():return (node/'serial').read_text().strip()
    data=(node/'vpd_pg80').read_bytes()
    return data[4:4+int.from_bytes(data[2:4],'big')].decode().strip()


def validate_guest(mounted=False):
    token=json.loads(Path('/fixture.json').read_text())['token']
    base.require(bool(re.fullmatch('[0-9a-f]{12}',token)) and os.getuid()==0 and
                 f'lvs_fixture={token}' in Path('/proc/cmdline').read_text().split() and
                 'QEMU' in Path('/sys/class/dmi/id/sys_vendor').read_text(),'not a disposable fixture guest')
    for name,prefix,size in (('sda','LVS',DISK_BYTES),('sdb','LVC',CONTROL_BYTES+START_SECTOR*512)):
        base.require(serial(name)==prefix+'-'+token,'wrong synthetic serial')
        node=Path('/sys/class/block')/name
        base.require('/ata' in str(node.resolve()) and int((node/'size').read_text())*512==size,'wrong SATA parent/geometry')
        base.require((Path('/sys/class/block')/(name+'1')).resolve().parent==node.resolve(),'partition parent confusion')
    if mounted:
        dev=(Path('/sys/class/block/sda1/dev')).read_text().strip()
        base.require(f'{os.major(os.stat("/").st_dev)}:{os.minor(os.stat("/").st_dev)}'==dev,'root is not the expected partition')
        base.require(os.stat('/').st_dev!=os.stat('/control').st_dev,'control disk is not separate')
        root_mount=[r.split() for r in Path('/proc/mounts').read_text().splitlines() if r.split()[1]=='/']
        base.require(any(r[2]=='ext4' and 'rw' in r[3].split(',') for r in root_mount),'ext4 root is not mounted rw')
    return token


def bootstrap():
    validate_guest()
    causal = None
    if Path('/causal-enabled').exists():
        import causal_probe
        if Path('/targeted-enabled').exists():
            import mapping_probe
            causal_probe.PROBES.update(mapping_probe.EXTRA_PROBES)
        causal = causal_probe.pre_mount(sys.modules[__name__])
    subprocess.run(['/bin/mount','-t','ext4','-o','rw','/dev/sda1','/newroot'],check=True)
    subprocess.run(['/bin/mount','-t','ext4','-o','rw','/dev/sdb1','/newroot/control'],check=True)
    if causal is not None:
        evidence = Path('/newroot/control/evidence')
        evidence.mkdir()
        data, meta = causal
        (evidence/'pre-mount.trace').write_text(data)
        (evidence/'pre-mount.json').write_text(json.dumps(meta,indent=2))
    os.execv('/bin/switch_root',['switch_root','/newroot','/usr/bin/python3','/foundation_probe.py','--mounted-guest'])


def open_target(name='sda'):
    validate_guest(mounted=True)
    base.require(name=='sda','only the validated synthetic physical parent is permitted')
    expected=Path('/sys/class/block/sda');device=tuple(map(int,(expected/'dev').read_text().split(':')))
    fd=os.open('/dev/sda',os.O_RDONLY|os.O_DIRECT|os.O_CLOEXEC|os.O_NOFOLLOW)
    try:
        info=os.fstat(fd);flags=fcntl.fcntl(fd,fcntl.F_GETFL)
        size=struct.unpack('Q',fcntl.ioctl(fd,0x80081272,bytes(8)))[0]
        sector=struct.unpack('I',fcntl.ioctl(fd,0x1268,bytes(4)))[0]
        base.require(stat.S_ISBLK(info.st_mode) and (os.major(info.st_rdev),os.minor(info.st_rdev))==device and size==DISK_BYTES and sector==512,'descriptor identity/geometry mismatch')
        base.require(flags&os.O_ACCMODE==os.O_RDONLY and flags&os.O_DIRECT,'readonly direct flags missing')
        validate_guest(mounted=True)
        return fd
    except BaseException:os.close(fd);raise


class KernelTrace:
    def __init__(self):
        self.error='';self.functions=[];self.events=[]
        try:
            if not (TRACE/'tracing_on').exists():
                subprocess.run(['/bin/mount','-t','tracefs','tracefs',str(TRACE)],check=True,capture_output=True)
            self.write('tracing_on','0');self.write('current_tracer','nop');self.write('buffer_size_kb','4096')
            available=(TRACE/'available_filter_functions').read_text().splitlines()
            names={r.split()[0] for r in available if r.split()}
            self.functions=[n for n in FUNCTIONS if n in names]
            if self.functions:
                self.write('set_ftrace_filter','\n'.join(self.functions));self.write('current_tracer','function')
            for event in EVENTS:
                p=TRACE/'events'/event/'enable'
                if p.exists():p.write_text('1');self.events.append(event)
        except (OSError,subprocess.SubprocessError) as exc:self.error=str(exc)
    def write(self,name,value):(TRACE/name).write_text(value)
    def start(self,name):
        if self.error:return
        self.write('trace','');self.write('tracing_on','1');self.write('trace_marker','LVS_BEGIN '+name)
    def stop(self,name,directory):
        if self.error:return dict(error=self.error,available_functions=self.functions,events=self.events)
        self.write('trace_marker','LVS_END '+name);self.write('tracing_on','0')
        data=(TRACE/'trace').read_text();(directory/(name+'.kernel.trace')).write_text(data)
        stats={str(p.relative_to(TRACE)):p.read_text() for p in (TRACE/'per_cpu').glob('cpu*/stats')}
        return dict(functions=self.functions,events=self.events,stats=stats,
            function_calls={f:sum(f in line for line in data.splitlines()) for f in self.functions},
            block_lines=[line for line in data.splitlines() if 'block_' in line],
            causal_writeback_attribution='UNRESOLVED: task attribution and paired timing alone do not exclude deferred kernel work')


def ordinary_writer(stop,observations):
    fd=os.open('/ordinary-data',os.O_RDWR|os.O_CLOEXEC|os.O_NOFOLLOW)
    try:
        for i in range(30):
            if stop.is_set():break
            os.pwrite(fd,bytes([65+i%26])*4096,(i%8)*4096);os.fsync(fd)
            observations.append(dict(index=i,monotonic=time.monotonic(),bytes=4096))
            stop.wait(.1)
    finally:os.close(fd)


def guard_args(fd,seconds=3,rate=7,major=None,backend=None):
    from Modules.lvs_storage_thermal_backend import guard_command,executable_identity
    info=os.fstat(fd)
    backend=backend or dict(status='available',guard=executable_identity('/bin/thermal-guard'),fio=executable_identity('/bin/fio'))
    exe=os.open('/bin/fio',os.O_RDONLY|os.O_CLOEXEC)
    try:
        argv=guard_command('/bin/thermal-guard',exe,backend=backend,uid=65534,gid=65534,
            major=os.major(info.st_rdev) if major is None else major,minor=os.minor(info.st_rdev),
            size=DISK_BYTES,block_size=65536,iops=rate,seconds=seconds)
        return exe,argv
    except BaseException:os.close(exe);raise


def reap_group(group):
    """PID1 reaps its adopted fixture descendants; never signal a reaped ID."""
    end=time.monotonic()+3
    while time.monotonic()<end:
        while True:
            try:
                pid,_=os.waitpid(-group,os.WNOHANG)
                if not pid:break
            except ChildProcessError:break
        try:os.killpg(group,0)
        except ProcessLookupError:return True
        time.sleep(.02)
    return False


def traced_case(name,directory,*,assist=True,writing=False,cancel=False):
    from Modules.lvs_storage_thermal_recovery import RecoveryScope
    scope=RecoveryScope(directory/(name+'.intent')).enter(evidence_directory=directory)
    trace=KernelTrace();writes=[];writer_errors=[];stop=threading.Event();writer=None;fd=None;exe=None;p=None;clean=False
    def write_activity():
        try:ordinary_writer(stop,writes)
        except BaseException as exc:writer_errors.append(repr(exc))
    trace.start(name);started=time.monotonic()
    try:
        if writing:
            writer=threading.Thread(target=write_activity);writer.start()
        if assist:
            fd=open_target();exe,cmd=guard_args(fd,seconds=30 if cancel else 3)
            with (directory/(name+'.stdout')).open('wb') as stdout,(directory/(name+'.stderr')).open('wb') as stderr:
                p=subprocess.Popen(['/bin/strace','-ff','-ttt','-yy','-s','0','--kill-on-exit','-o',str(directory/(name+'.syscall')),*cmd],stdin=fd,pass_fds=(exe,),stdout=stdout,stderr=stderr,start_new_session=True)
                try:p.wait(timeout=1 if cancel else 15)
                except subprocess.TimeoutExpired:
                    os.killpg(p.pid,signal.SIGTERM)
                    try:p.wait(timeout=3)
                    except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);p.wait(timeout=3)
        else:time.sleep(3)
    finally:
        stop.set()
        if writer is not None:writer.join(timeout=4);base.require(not writer.is_alive(),'guest writer cleanup uncertain')
        try:
            clean=p is None or (p.poll() is not None and reap_group(p.pid))
            for value in (exe,fd):
                if value is not None:os.close(value)
            if clean and (writer is None or not writer.is_alive()):scope.resolve(cleanup_confirmed=True)
        finally:scope.close()
    base.require(clean,'paired trace worker/descendants cleanup unconfirmed')
    base.require(not writer_errors,'guest OS workload failed: '+str(writer_errors))
    if writing:base.require(bool(writes),'ordinary write control produced no writes')
    kernel=trace.stop(name,directory)
    calls='\n'.join(f.read_text() for f in directory.glob(name+'.syscall.*'))
    review=base.audit(calls.replace('/dev/sda','/dev/vda'))
    # Reuse the old parser, but use this fixture's larger bounds explicitly.
    review['aligned_bounded_reads']=bool(review['reads']) and all(n==65536 and r==n and o%65536==0 and o+n<=DISK_BYTES for n,o,r in review['reads'])
    fio=None
    if assist:
        try:
            text=(directory/(name+'.stdout')).read_text();fio=json.loads(text[text.index('{'):])['jobs'][0]
        except (ValueError,KeyError,IndexError):pass
    guard=None
    if assist:
        for line in (directory/(name+'.stderr')).read_text().splitlines():
            if line.startswith('{') and 'lvs.storage_thermal.guard' in line:guard=json.loads(line)
    return dict(name=name,guard=guard,cleanup_confirmed=clean,journal='CLEAN',assist=assist,ordinary_writing=writing,ordinary_writes=writes,
        elapsed=time.monotonic()-started,exit=p.returncode if p else None,cancelled=cancel,
        syscall=review,fio=fio,kernel=kernel,configured_iops=7 if assist else 0)


def lifecycle_cases(directory):
    from Modules.lvs_storage_thermal_stage import SharedAdmission,StageLease,StageLaunches
    from Modules.lvs_storage_thermal_recovery import RecoveryScope,read_state,blocker
    from Modules.lvs_storage_thermal_launch import prepare
    prepare('/bin');rows=[]
    for name in LIFECYCLE:
        state=SharedAdmission.create();folder=directory/name;folder.mkdir();scope=RecoveryScope(folder/'intent');fd=None;exe=None;registry=None;process=None;denied=False
        try:
            if name in ('durable-ENOSPC','durable-EIO'):
                error=errno.ENOSPC if name.endswith('ENOSPC') else errno.EIO
                with patch('Modules.lvs_storage_thermal_recovery.durable_json',side_effect=OSError(error,'injected durable publication failure')):
                    try:scope.enter(lease_identity=state.identity,admission=state)
                    except OSError:denied=True
                base.require(denied and blocker(scope.marker),'failed durable publication did not block')
                rows.append(dict(name=name,rejected=True,target_opened=False,fresh_blocked=fresh_blocker(scope.marker)));continue
            scope.enter(lease_identity=state.identity,admission=state)
            if name in ('unsupported-direct','wrong-topology'):
                real_open=os.open
                def unavailable(path,*a,**k):
                    if path=='/dev/sda':raise OSError(errno.EOPNOTSUPP,'injected direct-I/O refusal')
                    return real_open(path,*a,**k)
                context=patch('os.open',side_effect=unavailable) if name=='unsupported-direct' else patch.dict(open_target.__globals__,serial=lambda n:'SUBSTITUTED')
                with context:
                    try:open_target()
                    except (OSError,RuntimeError):denied=True
                base.require(denied,'invalid access condition accepted')
                scope.resolve(cleanup_confirmed=True);rows.append(dict(name=name,rejected=True,admitted=False,injected=True));continue
            if name=='old-fio':
                from Modules.lvs_storage_thermal_backend import capability
                evidence=capability('/bin/old-fio','/bin/thermal-guard',uid=65534,gid=65534)
                base.require(evidence['status']!='available','old backend unexpectedly qualified')
                scope.resolve(cleanup_confirmed=True);rows.append(dict(name=name,rejected=True,admitted=False,backend=evidence));continue
            fd=open_target();exe,argv=guard_args(fd,seconds=30 if name=='cancel' else 1)
            if name=='partition-confusion':argv[6]=str(os.minor(os.stat('/dev/sda1').st_rdev))
            if name=='wrong-identity':argv[5]=str(int(argv[5])+1)
            if name=='source-substitution':
                from Modules.lvs_storage_thermal_backend import guard_command,executable_identity
                bad=executable_identity('/bin/fio');bad['sha256']='0'*64
                try:
                    guard_command('/bin/thermal-guard',exe,backend=dict(status='available',guard=executable_identity('/bin/thermal-guard'),fio=bad),uid=65534,gid=65534,major=8,minor=0,size=DISK_BYTES,block_size=65536,iops=7,seconds=1)
                except ValueError:denied=True
            if name in ('stale-backend','missing-backend'):
                from Modules.lvs_storage_thermal_backend import guard_command
                try:guard_command('/bin/thermal-guard',exe,backend=dict(status='untested') if name=='stale-backend' else {},uid=65534,gid=65534,major=8,minor=0,size=DISK_BYTES,block_size=65536,iops=7,seconds=1)
                except ValueError:denied=True
            if name in ('source-substitution','stale-backend','missing-backend'):
                base.require(denied,'invalid backend accepted');scope.resolve(cleanup_confirmed=True)
                rows.append(dict(name=name,rejected=True,admitted=False));continue
            if name in ('readwrite-fd','buffered-fd'):
                os.close(fd);fd=os.open('/dev/sda',os.O_RDWR|os.O_DIRECT if name=='readwrite-fd' else os.O_RDONLY)
            with (folder/'out').open('wb') as stdout,(folder/'err').open('wb') as stderr:
                if name=='guard-policy':
                    cmd=['/bin/thermal-guard','--policy-test',*argv[3:]]
                    p=subprocess.run(['/bin/strace','-ff','-yy','-s','0','-o',str(folder/'denials'),*cmd],stdin=fd,stdout=stdout,stderr=stderr,timeout=10)
                    base.require(p.returncode==0 and '"policy_test":"PASS"' in (folder/'out').read_text(),'native mutation negative controls failed')
                    scope.resolve(cleanup_confirmed=True);rows.append(dict(name=name,exit=0,mutation_attempts_denied=True));continue
                lease=StageLease(time.monotonic()+(.15 if name=='deadline' else 35),os.getppid(),admission=state)
                registry=StageLaunches(None,lease,folder)
                if name=='deadline':time.sleep(.2)
                try:
                    process=registry.launch(argv,stdin=fd,pass_fds=(exe,),stdout=stdout,stderr=stderr,start_new_session=True)
                    if name=='cancel':time.sleep(.5);state.revoke();registry.stop(registry.owned[0],signal.SIGTERM)
                    process.wait(timeout=5)
                except (ValueError,OSError):denied=True
                finally:registry.finish()
            clean=registry.cleanup_confirmed
            publication_failed=False
            if clean:
                if name in ('clean-ENOSPC','clean-EIO'):
                    error=errno.ENOSPC if name.endswith('ENOSPC') else errno.EIO
                    with patch('Modules.lvs_storage_thermal_recovery.durable_json',side_effect=OSError(error,'injected CLEAN publication failure')):
                        try:scope.resolve(cleanup_confirmed=True)
                        except OSError:publication_failed=True
                    base.require(publication_failed and fresh_blocker(scope.marker),'failed CLEAN lost recovery obligation')
                else:scope.resolve(cleanup_confirmed=True)
            committed=any(r.get('io_admission')=='committed' for r in registry.owned)
            if name in ('normal','cancel'):base.require(committed and clean,'expected owned admission/cleanup missing')
            if name=='deadline':base.require(not committed,'expired admission committed')
            if name in ('wrong-identity','partition-confusion','readwrite-fd','buffered-fd'):
                base.require(process is None or process.returncode!=0,'invalid descriptor accepted')
            rows.append(dict(name=name,exit=process.returncode if process else None,rejected=denied,publication_failed=publication_failed,ownership=registry.snapshot(),journal=read_state(scope.marker)['state']))
        finally:
            if registry is not None:registry.finish()
            if scope.fd is not None:scope.close()
            for value in (exe,fd):
                if value is not None:os.close(value)
            state.close()
    return rows


def fresh_blocker(marker):
    text=subprocess.check_output(['/usr/bin/python3','-B','-c','from Modules.lvs_storage_thermal_recovery import blocker;from pathlib import Path;import sys;print(blocker(Path(sys.argv[1])))',str(marker)],text=True,timeout=5)
    return text.strip()


def death_child(directory):
    validate_guest(mounted=True)
    from Modules.lvs_storage_thermal_stage import SharedAdmission,StageLease,StageLaunches
    from Modules.lvs_storage_thermal_recovery import RecoveryScope
    from Modules.lvs_storage_thermal_launch import prepare
    prepare('/bin');state=SharedAdmission.create();scope=RecoveryScope(directory/'intent').enter(lease_identity=state.identity,admission=state)
    fd=open_target();exe,argv=guard_args(fd,seconds=30)
    registry=StageLaunches(None,StageLease(time.monotonic()+35,os.getppid(),admission=state),directory)
    with (directory/'out').open('wb') as out,(directory/'err').open('wb') as err:
        p=registry.launch(argv,stdin=fd,pass_fds=(exe,),stdout=out,stderr=err,start_new_session=True)
        (directory/'committed').write_text(str(p.authority_pid))
        time.sleep(60)


def supervisor_death(directory):
    folder=directory/'supervisor-death';folder.mkdir()
    p=subprocess.Popen(['/usr/bin/python3','/foundation_probe.py','--death-child',str(folder)])
    try:
        end=time.monotonic()+10
        while not (folder/'committed').exists():
            base.require(p.poll() is None and time.monotonic()<end,'supervisor never admitted')
            time.sleep(.02)
        child=int((folder/'committed').read_text());p.kill();p.wait(timeout=3)
        end=time.monotonic()+5;reaped=False
        while time.monotonic()<end:
            pid,_=os.waitpid(child,os.WNOHANG)
            if pid==child:reaped=True;break
            time.sleep(.02)
        base.require(reaped and fresh_blocker(folder/'intent'),'death/restart protection failed')
        return dict(admitted=True,supervisor_sigkill=True,worker_reaped=reaped,journal='ARMED',fresh_blocked=True)
    finally:
        if p.poll() is None:p.kill();p.wait(timeout=3)


def uncertain_cleanup(directory):
    from Modules.lvs_storage_thermal_stage import SharedAdmission,StageLease,StageLaunches
    from Modules.lvs_storage_thermal_recovery import RecoveryScope,read_state
    folder=directory/'uncertain-cleanup';folder.mkdir();state=SharedAdmission.create()
    scope=RecoveryScope(folder/'intent').enter(lease_identity=state.identity,admission=state)
    fd=open_target();exe,argv=guard_args(fd,seconds=1)
    registry=StageLaunches(None,StageLease(time.monotonic()+20,os.getppid(),admission=state),folder)
    victim=subprocess.Popen(['/usr/bin/python3','-c','import time;time.sleep(30)'])
    saved=None;foreign=None;p=None
    try:
        with (folder/'out').open('wb') as out,(folder/'err').open('wb') as err:
            p=registry.launch(argv,stdin=fd,pass_fds=(exe,),stdout=out,stderr=err,start_new_session=True)
            base.require(p.pidfd is not None,'guest pidfd witness unavailable')
            saved=os.dup(p.pidfd);foreign=os.pidfd_open(victim.pid);os.dup2(foreign,p.pidfd)
            registry.finish()
            base.require(not registry.cleanup_confirmed and victim.poll() is None,'uncertain authority certified cleanup or signaled victim')
            base.require(read_state(scope.marker)['state']=='ARMED' and fresh_blocker(scope.marker),'uncertain cleanup lost protection')
            os.dup2(saved,p.pidfd);os.close(saved);saved=None
            registry.finish();base.require(registry.cleanup_confirmed,'restored genuine cleanup unconfirmed')
            scope.resolve(cleanup_confirmed=True)
        return dict(before='ARMED',fresh_blocked=True,victim_untouched=True,after='CLEAN',owned_reaped=p.poll() is not None)
    finally:
        if saved is not None and p is not None:os.dup2(saved,p.pidfd);os.close(saved)
        if foreign is not None:os.close(foreign)
        if p is not None:p.kill();p.wait(timeout=3)
        victim.kill();victim.wait(timeout=3)
        scope.close();state.close();os.close(exe);os.close(fd)


def native_expiry(directory):
    import socket
    from types import SimpleNamespace
    from Modules.lvs_storage_thermal_stage import SharedAdmission
    from Modules.lvs_storage_thermal_recovery import RecoveryScope
    from Modules.lvs_storage_thermal_launch import OwnedProcess
    folder=directory/'native-expiry';folder.mkdir();state=SharedAdmission.create()
    scope=RecoveryScope(folder/'intent').enter(lease_identity=state.identity,admission=state)
    fd=open_target();exe,argv=guard_args(fd,seconds=1);parent,child=socket.socketpair(socket.AF_UNIX,socket.SOCK_SEQPACKET);parent.settimeout(2)
    deadline=time.monotonic_ns()+1_000_000_000;owner=SimpleNamespace(process=None);p=None
    try:
        command=[argv[0],'--stage-fio-fd',argv[2],str(child.fileno()),str(state.fd),str(deadline),str(os.getpid()),*map(str,state.identity),*argv[3:]]
        with (folder/'out').open('wb') as out,(folder/'err').open('wb') as err:
            p=OwnedProcess(command,stage_bootstrap=True,start_new_session=False,owner=owner,
                pass_fds=(exe,child.fileno(),state.fd),stdout=out,stderr=err)
            child.close();base.require(owner.process is p,'pre-release registration missing')
            parent.sendall(b'OWN');base.require(parent.recv(128)==b'R','native ownership ack missing');p.confirm_native_group()
            # The child waits for a target; no target descriptor has been passed.
            p.wait(timeout=3)
        error=(folder/'err').read_text()
        base.require(p.returncode==125 and 'stage admission closed/expired' in error and 'COMMITTED' not in error,'native expiry was not independently demonstrated')
        base.require(p.group_cleanup_confirmed(),'native expiry cleanup uncertain')
        scope.resolve(cleanup_confirmed=True)
        return dict(exit=p.returncode,registered_before_release=True,target_descriptor_transferred=False,native_deadline_rejected=True,stderr=error,journal='CLEAN')
    finally:
        if p is not None:p.kill();p.wait(timeout=3)
        parent.close();child.close();scope.close();state.close();os.close(exe);os.close(fd)


def visibility_change(directory):
    """Change the supervisor root view while an already admitted worker exists.

    This proves one namespace-visibility refusal, not live repartition/hot-unplug.
    The revoker's independent original-inode FD is opened before the transition.
    """
    from Modules.lvs_storage_thermal_stage import SharedAdmission,StageLease,StageLaunches
    from Modules.lvs_storage_thermal_recovery import RecoveryScope
    folder=directory/'visibility-change';folder.mkdir();empty=folder/'empty-root';empty.mkdir()
    state=SharedAdmission.create();scope=RecoveryScope(folder/'intent').enter(lease_identity=state.identity,admission=state)
    fd=open_target();exe,argv=guard_args(fd,seconds=5)
    registry=StageLaunches(None,StageLease(time.monotonic()+15,os.getppid(),admission=state),folder)
    root=os.open('/',os.O_PATH|os.O_DIRECTORY|os.O_CLOEXEC);changed=False;p=None;rejected=False;closed=False
    try:
        with (folder/'out').open('wb') as out,(folder/'err').open('wb') as err:
            p=registry.launch(argv,stdin=fd,pass_fds=(exe,),stdout=out,stderr=err,start_new_session=True)
            time.sleep(.2)
            with state._operation() as pin:
                try:
                    os.chroot(empty);os.chdir('/');changed=True
                    try:open_target()
                    except (OSError,RuntimeError):rejected=True
                    closed=state._revoke_pin(pin)
                    p.terminate()
                finally:
                    os.fchdir(root);os.chroot('.');os.chdir('/');changed=False
            registry.finish()
        base.require(rejected and closed and registry.cleanup_confirmed,'changed root visibility did not refuse/cancel safely')
        scope.resolve(cleanup_confirmed=True)
        return dict(root_view_changed_during_activity=True,new_open_rejected=True,original_lease_closed=closed,owned_cleanup=True,journal='CLEAN',scope='root visibility only; not physical topology/hot-unplug proof')
    finally:
        if changed:os.fchdir(root);os.chroot('.');os.chdir('/')
        if p is not None:p.kill();p.wait(timeout=3)
        scope.close();state.close();os.close(root);os.close(exe);os.close(fd)


def verify(results):
    base.require(results.get('contract')=='lvs.storage_thermal.active_access_research.v1','foreign research contract')
    cases=results['paired_cases']
    expected={'idle-control-A','idle-assist-A','idle-assist-B','idle-control-B','busy-control-A','busy-assist-A','busy-assist-B','busy-control-B','cancel'}
    base.require(len(cases)==len(expected) and {c['name'] for c in cases}==expected,'paired cases incomplete/duplicated')
    for case in cases:
        base.require(case['cleanup_confirmed'] is True and case['journal']=='CLEAN','paired worker cleanup unconfirmed')
        if case['ordinary_writing']:base.require(bool(case['ordinary_writes']),'ordinary write comparison missing')
        if not case['assist']:continue
        review=case['syscall'];guard=case['guard'] or {}
        base.require(review['aligned_bounded_reads'] and not review['target_mutations'] and not review['unknown_target_calls'],'workload syscall proof incomplete')
        base.require(guard.get('readonly_direct') is True and guard.get('capabilities')==0 and guard.get('seccomp')==2 and guard.get('no_new_privs')==1,'guard witness missing')
        if not case['cancelled']:
            fio=case['fio'];read=fio['read'];seconds=read['runtime']/1000
            base.require(case['exit']==0 and read['total_ios']>0 and seconds>=3 and read['io_bytes']==read['total_ios']*65536,'missing/inconsistent read activity')
            base.require(read['total_ios']/seconds<=8 and fio['write']['total_ios']==0 and fio['trim']['total_ios']==0 and fio['error']==0,'rate/direction/error violation')
        else:base.require(case['exit']!=0,'cancellation not demonstrated')
    rows=results['lifecycle_cases'];byname={r['name']:r for r in rows}
    base.require(len(rows)==len(LIFECYCLE) and set(byname)==set(LIFECYCLE),'lifecycle case inventory incomplete')
    for name in ('normal','cancel','clean-ENOSPC','clean-EIO'):
        row=byname[name];own=row['ownership']
        base.require(own['cleanup_confirmed'] is True and any(w.get('io_admission')=='committed' for w in own['workers']),'owned admission/cleanup not proved')
        base.require(row['journal']==('ARMED' if name.startswith('clean-') else 'CLEAN'),'wrong final recovery state')
    for name in ('wrong-identity','partition-confusion','readwrite-fd','buffered-fd'):
        base.require(byname[name]['exit']==125 and byname[name]['ownership']['cleanup_confirmed'] is True,'invalid native target not rejected/reaped')
    for name in ('unsupported-direct','wrong-topology','missing-backend','stale-backend','source-substitution','old-fio','deadline'):
        base.require(byname[name]['rejected'] is True,'negative admission check missing')
    for name in ('durable-ENOSPC','durable-EIO'):
        row=byname[name];base.require(row['rejected'] and not row['target_opened'] and row['fresh_blocked'],'durability failure admitted')
    base.require(byname['guard-policy']['mutation_attempts_denied'] is True and results['supervisor_death']['fresh_blocked'],'kernel denial/death evidence missing')
    base.require(results['misalignment']==errno.EINVAL and results['readonly_write']==errno.EBADF,'kernel descriptor negatives missing')
    base.require(results['visibility_change']['new_open_rejected'] is True and results['visibility_change']['original_lease_closed'] is True and results['visibility_change']['owned_cleanup'] is True,'changed visibility refusal missing')
    base.require(results['native_expiry']['native_deadline_rejected'] is True and not results['native_expiry']['target_descriptor_transferred'],'native deadline witness missing')
    base.require(results['uncertain_cleanup']['before']=='ARMED' and results['uncertain_cleanup']['after']=='CLEAN' and results['uncertain_cleanup']['victim_untouched'],'uncertain cleanup proof missing')
    base.require(results['provider_decision']=='NO-GO','unresolved kernel attribution must not become provider GO')


def guest():
    token=validate_guest(mounted=True)
    subprocess.run(['/bin/mount','-t','tmpfs','tmpfs','/tmp'],check=True)
    directory=Path('/control/evidence')
    if Path('/causal-enabled').exists():
        import causal_probe
        try:
            if Path('/targeted-enabled').exists():
                import mapping_probe
                causal_probe.PROBES.update(mapping_probe.EXTRA_PROBES)
                results = mapping_probe.guest(sys.modules[__name__], causal_probe, directory)
            else:
                results = causal_probe.guest(sys.modules[__name__], directory)
        except (OSError, RuntimeError, subprocess.SubprocessError) as error:
            results = dict(error=str(error), disposition='INCONCLUSIVE')
        publish_evidence(directory, results, sync_control=False)
        return
    directory.mkdir()
    phases=[]
    for name,assist,writing in (('idle-control-A',False,False),('idle-assist-A',True,False),
        ('idle-assist-B',True,False),('idle-control-B',False,False),
        ('busy-control-A',False,True),('busy-assist-A',True,True),
        ('busy-assist-B',True,True),('busy-control-B',False,True)):
        phases.append(traced_case(name,directory,assist=assist,writing=writing))
    phases.append(traced_case('cancel',directory,cancel=True))
    results=dict(contract='lvs.storage_thermal.active_access_research.v1',token=token,
        topology=dict(root='/dev/sda1 ext4 rw',physical_parent='/dev/sda',control='/dev/sdb1 ext4 rw',root_serial=serial('sda'),control_serial=serial('sdb'),mounted=os.stat('/').st_dev),
        versions=dict(kernel=os.uname().release,python=sys.version,fio=subprocess.check_output(['/bin/fio','--version'],text=True).strip(),guard=subprocess.check_output(['/bin/thermal-guard','--version'],text=True).strip(),strace=subprocess.check_output(['/bin/strace','--version'],text=True).splitlines()[0]),
        paired_cases=phases,lifecycle_cases=lifecycle_cases(directory),supervisor_death=supervisor_death(directory),uncertain_cleanup=uncertain_cleanup(directory),native_expiry=native_expiry(directory),visibility_change=visibility_change(directory),
        unresolved_controls=['general mount transitions and physical topology/hot-unplug during I/O remain unqualified; root-view change tested',
          'causal attribution of deferred kernel writeback/cache operations',
          'actual unsupported-direct-I/O kernel: only injected refusal tested',
          'runtime identity replacement/hot-unplug under active I/O'],
        provider_decision='NO-GO',reason='Kernel function and block traces expose operations, but paired task/time attribution does not establish absence of indirect writeback/cache effects under all lifecycle transitions.',
        physical_thermal_acceptance=False,production_eligibility_changed=False)
    # Independent alignment and no-write witnesses on this validated VM only.
    fd=open_target()
    try:
        for label,call,expected in (('misalignment',lambda:os.pread(fd,512,1),errno.EINVAL),('readonly_write',lambda:os.pwrite(fd,b'x'*4096,0),errno.EBADF)):
            try:call()
            except OSError as exc:base.require(exc.errno==expected,label+' did not reject');results[label]=exc.errno
            else:raise RuntimeError(label+' accepted')
    finally:os.close(fd)
    publish_evidence(directory, results)


def publish_evidence(directory, results, *, sync_control=True):
    (directory/'results.json').write_text(json.dumps(results,indent=2))
    # Results and ARMED obligations persist on the separate control disk.
    # This synchronization belongs to the evidence control plane only.
    import ctypes
    control=os.open('/control',os.O_RDONLY|os.O_DIRECTORY|os.O_CLOEXEC)
    try:
        if sync_control:
            base.require(ctypes.CDLL(None,use_errno=True).syncfs(control)==0,'control-disk synchronization failed')
    finally:os.close(control)
    buffer=io.BytesIO()
    with tarfile.open(fileobj=buffer,mode='w:gz') as archive:archive.add(directory,arcname='evidence')
    print('LVS_EVIDENCE_BEGIN',flush=True);print(base64.b64encode(buffer.getvalue()).decode(),flush=True);print('LVS_EVIDENCE_END',flush=True)


def host(args):
    from Modules.lvs_native_helpers import find_c_compiler,native_helper_build_command
    for name in ('fio','old_fio','strace','kernel','python','guard'):regular(getattr(args,name))
    tools=Path(tempfile.mkdtemp(prefix='lvs-active-tools-'));compiler=find_c_compiler()
    base.require(compiler is not None,'existing C compiler needed for disposable owned bootstrap')
    launch=tools/'storage_thermal_launch.so'
    subprocess.run(native_helper_build_command(compiler,ROOT/'native/storage_thermal_launch.c',launch)+['-shared','-fPIC','-Wall','-Wextra','-Werror'],check=True,capture_output=True,timeout=30)
    extras=[(p,'/Modules/'+p.name) for p in (ROOT/'Modules').glob('*.py')]
    extras += [(launch,'/bin/storage_thermal_launch.so'),(ROOT/'native/storage_thermal_launch.c','/native/storage_thermal_launch.c')]
    verifier = verify
    if args.causal:
        from scripts import storage_thermal_causal_probe as causal_probe
        causal_probe.require_kernel_image(args.kernel)
        extras.append((Path(causal_probe.__file__), '/causal_probe.py'))
        verifier = causal_probe.verify
        if args.targeted:
            from scripts import storage_thermal_mapping_probe as mapping_probe
            extras.append((Path(mapping_probe.__file__), '/mapping_probe.py'))
            verifier = mapping_probe.verify
    base.host(args,guest_script=Path(__file__).resolve(),verifier=verifier,extra_files=extras,fixture_builder=build_fixture)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--causal',action='store_true',help='run the build-specific causal comparisons')
    parser.add_argument('--targeted',action='store_true',help='with --causal, run the isolated dirty-mapping and startup probes')
    parser.add_argument('--guest-init',action='store_true',help=argparse.SUPPRESS)
    parser.add_argument('--mounted-guest',action='store_true',help=argparse.SUPPRESS)
    parser.add_argument('--death-child',help=argparse.SUPPRESS)
    for name in ('fio','old-fio','strace','kernel','python','guard'):parser.add_argument('--'+name)
    args=parser.parse_args()
    if args.guest_init:bootstrap()
    elif args.mounted_guest:guest()
    elif args.death_child:death_child(Path(args.death_child))
    else:
        if args.targeted and not args.causal:
            parser.error('--targeted requires --causal')
        if not all(getattr(args,n) for n in ('fio','old_fio','strace','kernel','python','guard')):parser.error('explicit tool/kernel paths required; no target/device option exists')
        host(args)
