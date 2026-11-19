"""Sealed disposable VM system-root qualification. No standalone host entrypoint.

Only imported by storage_thermal_shared_probe after its QEMU/token/device seals.
Temperatures/primary stress and persistence faults are explicit synthetic inputs;
root block reads, guard, installed service, identities and recovery are genuine.
"""
from pathlib import Path
from dataclasses import replace
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time


def encrypted_root(source):
    from __main__ import seal,fixture_device
    seal()
    for module in ('dm-crypt','btrfs','xts'):subprocess.run(['/bin/modprobe',module],check=True)
    Path('/run').mkdir(exist_ok=True)
    key=Path('/fixture-key');key.write_bytes(os.urandom(32));key.chmod(0o600)
    try:
        dev=fixture_device(4)+'p1'
        subprocess.run(['/bin/cryptsetup','luksFormat','--type','luks2','--batch-mode','--pbkdf','pbkdf2','--pbkdf-force-iterations','1000','--key-file',str(key),dev],check=True,capture_output=True)
        subprocess.run(['/bin/cryptsetup','open','--key-file',str(key),dev,'fixture-system'],check=True,capture_output=True)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError('Encrypted-root fixture preparation failed: '+exc.stderr.decode(errors='replace')[:1200])from exc
    finally:key.unlink()
    subprocess.run(['/bin/mkfs.btrfs','-f','--nodiscard','/dev/mapper/fixture-system'],check=True,capture_output=True)
    dest=Path('/encrypted-root');dest.mkdir()
    subprocess.run(['/bin/mount','-t','btrfs','/dev/mapper/fixture-system',str(dest)],check=True)
    for p in source.iterdir():
        if p.name=='control':continue
        if p.is_dir() and not p.is_symlink():shutil.copytree(p,dest/p.name,symlinks=True)
        elif p.is_symlink():(dest/p.name).symlink_to(os.readlink(p))
        else:shutil.copy2(p,dest/p.name)
    (dest/'control').mkdir(exist_ok=True)
    subprocess.run(['/bin/mount','--move',str(source/'control'),str(dest/'control')],check=True)
    subprocess.run(['/bin/umount',str(source)],check=True)
    return dest


def client(identity):
    from Modules.lvs_storage_thermal import ThermalConfig
    from Modules.lvs_storage_thermal_runtime import preview
    from scripts.storage_thermal_integrated_probe import primary
    base=ThermalConfig(access_mode='shared_readonly_opt_in',selection='individual',device_ids=[identity],aggregate_iops_limit=16,aggregate_bps_limit=1048576,rate_mode='advanced',iops=16,bandwidth_bytes_per_second=1048576,temperature_limit_c=60)
    assert preview(base)['status']=='BLOCKED','system admitted without live authorization'
    c=replace(base,system_device_ids=[identity],control_plane_colocation=True)
    Path('/control/user/space-request').touch();end=time.monotonic()+15
    while not Path('/control/user/space-ready').exists()and time.monotonic()<end:time.sleep(.05)
    assert Path('/control/user/space-ready').exists()
    try:
        low=preview(c);assert low['status']!='READY',low
    except (OSError,ValueError):pass
    Path('/control/user/space-done').touch();end=time.monotonic()+15
    while not Path('/control/user/space-restored').exists()and time.monotonic()<end:time.sleep(.05)
    assert Path('/control/user/space-restored').exists()
    results={'unauthorized_blocked':True,'actual_low_space_blocked':True}
    # Preserve the existing data/shared and exclusive HDD production paths.
    inventory=preview(replace(base,selection='all_internal',device_ids=[],iops=8,bandwidth_bytes_per_second=524288,aggregate_iops_limit=128,aggregate_bps_limit=8388608))
    choices=[('data-regression',next(r for r in inventory['targets']if r['eligible']and r['drive_class']=='nvme')),
             ('exclusive-regression',next(r for r in inventory['targets']if r['eligible']and r['drive_class']=='hdd'))]
    for label,row in choices:
        Path('/control/user/case').write_text(label)
        cfg=replace(base,access_mode='exclusive'if label.startswith('exclusive')else'shared_readonly_opt_in',device_ids=[row['device_id']],duration_seconds=25,iops=8,bandwidth_bytes_per_second=524288)
        directory=Path('/var/tmp/lvs-system-user')/label;directory.mkdir()
        results[label]=primary(None,cfg.to_dict(),directory,25)
        assert results[label]['auxiliary']['cleanup_confirmed']and results[label]['auxiliary']['devices'][0]['read_ios']>0,results[label]
    cases=[('complete',12,None),('busy',12,None),('temperature',16,None),('cancel',20,2),('delayed',4,None),('eio-intent',8,None),('confidentiality',16,None),('topology-change',16,None)]
    for name,seconds,cancel in cases:
        Path('/control/user/case').write_text(name);Path('/control/user/sensor-hot').unlink(missing_ok=True)
        plan=preview(replace(c,duration_seconds=seconds));assert plan['status']=='READY',plan
        directory=Path('/var/tmp/lvs-system-user')/name;directory.mkdir(parents=True)
        result=primary(plan,replace(c,duration_seconds=seconds).to_dict(),directory,seconds,cancel_after=cancel,temperature_stop=name=='temperature')
        results[name]=result
        assert result['primary_verdict']=='pass'if cancel is None else result['aborted']
        aux=result['auxiliary'];assert aux['cleanup_confirmed'] and not aux.get('persistent_recovery_required'),result
        if name in ('complete','busy'):assert aux['executed_devices']==[identity] and aux['devices'][0]['read_ios']>0,result
        if name in ('temperature','cancel'):assert aux['auxiliary_outcome']=='STOPPED',result
        if name in ('eio-intent','confidentiality','topology-change'):assert aux['auxiliary_outcome']in('ERROR','NOT_RUN'),result
        assert seconds<=result['stage_elapsed']<seconds+1 if cancel is None else result['aborted']
        (directory/'result.json').write_text(json.dumps(result,indent=2))
        if name=='topology-change':
            Path('/control/user/topology-done').touch()
            end=time.monotonic()+10
            while not Path('/control/user/topology-restored').exists()and time.monotonic()<end:time.sleep(.05)
            assert Path('/control/user/topology-restored').exists()
    Path('/control/user/case').write_text('swap')
    # Root fixture enables a real regular-file swap on the selected root.
    Path('/control/user/swap-request').touch();end=time.monotonic()+10
    while not Path('/control/user/swap-ready').exists()and time.monotonic()<end:time.sleep(.05)
    assert Path('/control/user/swap-ready').exists(),'swap fixture did not activate'
    assert preview(c)['status']=='BLOCKED','disk swap was implicitly authorized'
    c=replace(c,system_swap=True,duration_seconds=10);p=preview(c);assert p['status']=='READY',p
    directory=Path('/var/tmp/lvs-system-user/swap');directory.mkdir()
    results['swap']=primary(p,c.to_dict(),directory,10);assert results['swap']['auxiliary']['cleanup_confirmed']
    assert results['swap']['auxiliary']['executed_devices']==[identity],results['swap']
    Path('/control/user/swap-done').touch()
    Path('/control/user/result.json').write_text(json.dumps(results,indent=2))


def final_client(identity, ending):
    from Modules.lvs_storage_thermal import ThermalConfig
    from scripts.storage_thermal_integrated_probe import primary
    c=ThermalConfig(access_mode='shared_readonly_opt_in',selection='individual',device_ids=[identity],system_device_ids=[identity],control_plane_colocation=True,system_swap=True,aggregate_iops_limit=16,aggregate_bps_limit=1048576,rate_mode='advanced',iops=16,bandwidth_bytes_per_second=1048576,duration_seconds=16,temperature_limit_c=60)
    Path('/control/user/case').write_text(ending)
    directory=Path('/var/tmp/lvs-system-user/final-fault');directory.mkdir()
    r=primary(None,c.to_dict(),directory,16,death_control=ending=='handler-death')
    (Path('/control/user')/'final-fault.json').write_text(json.dumps(r,indent=2))
    assert r['primary_verdict']=='pass' and r['auxiliary']['auxiliary_outcome']=='ERROR',r
    assert r['auxiliary'].get('persistent_recovery_required')or not r['auxiliary']['cleanup_confirmed'],r


def inside():
    from __main__ import seal,fixture_device
    from Modules.lvs_storage_thermal_targets import ThermalTargets
    from Modules.lvs_storage_thermal_recovery import blocker,read_state,RecoveryScope
    seal();sys.path.insert(0,'/lvs');encrypted=Path('/shared-campaign').read_text().startswith('encrypted')
    deployment=Path('/opt/lvs-thermal-fixture')
    for p in (Path('/opt'),deployment,*deployment.rglob('*')):
        os.chown(p,0,0);p.chmod(0o755 if p.is_dir()or p.name in('storage_thermal_guard','storage_thermal_launch.so')else 0o644)
    (deployment/'runtime/build/fio').chmod(0o711)
    for p in (Path('/var'),Path('/var/lib'),Path('/var/lib/lvs-thermal')):p.mkdir(exist_ok=True);p.chmod(0o755)
    Path('/run').mkdir(exist_ok=True);Path('/run').chmod(0o755)
    Path('/etc').mkdir(exist_ok=True)
    with Path('/etc/passwd').open('a')as f:f.write('lvs-thermal-worker:x:65533:65533:private fixture worker:/nonexistent:/sbin/nologin\n')
    with Path('/etc/group').open('a')as f:f.write('lvs-thermal-worker:x:65533:\n')
    control=Path('/control/user');control.mkdir();os.chown(control,1000,1000);control.chmod(0o700)
    user=Path('/var/tmp/lvs-system-user');user.mkdir(parents=True);os.chown(user,1000,1000);user.chmod(0o700)
    build=Path('/lvs/build');build.mkdir(exist_ok=True);shutil.copy2(deployment/'runtime/build/storage_thermal_launch.so',build/'storage_thermal_launch.so')
    # Keep the instrumented installed launcher otherwise byte-verified. No
    # payload is logged; faults are guest-only explicit software injections.
    launcher=deployment/'launch.py';text=launcher.read_text();needle='if integrated_serve or integrated_client:\n'
    injection='''if integrated_serve or integrated_client:
 from pathlib import Path
 import errno,time
 from Modules.lvs_storage_thermal_service import RuntimePolicy
 from Modules import lvs_storage_thermal_recovery as recovery
 original_runner=RuntimePolicy.runner
 original_durable=recovery.durable_json
 def case():
  try:return Path('/control/user/case').read_text()
  except OSError:return ''
 def durable(path,value):
  if case()=='eio-intent' and value.get('state')=='ARMED':raise OSError(errno.EIO,'sealed VM injected intent EIO')
  if case()=='clean-enospc' and value.get('state')=='CLEAN':raise OSError(errno.ENOSPC,'sealed VM injected CLEAN persistence ENOSPC')
  return original_durable(path,value)
 recovery.durable_json=durable
 def fixture_runner(self):
  r=original_runner(self)
  r.temperature=lambda row:dict(value_c=65. if Path('/control/user/sensor-hot').exists()else 30.,critical_c=70.,warning_c=55.,complete=True,synthetic_VM_sensor=True)
  original_publish=r.publish
  def publish(path,payload):
   if case()=='delayed':time.sleep(3)
   return original_publish(path,payload)
  r.publish=publish
  return r
 RuntimePolicy.runner=fixture_runner
'''
    assert needle in text;launcher.write_text(text.replace(needle,injection));m=json.loads((deployment/'manifest.json').read_text());m['files']['launch.py']=hashlib.sha256(launcher.read_bytes()).hexdigest();(deployment/'manifest.json').write_text(json.dumps(m))
    root=next(r for r in ThermalTargets().discover(access_mode='shared_readonly_opt_in')if r['identity']['path']==fixture_device(4 if encrypted else 0));assert root['system_drive']and not root['eligible'];identity=root['device_id']
    marker=Path('/var/lib/lvs-thermal/storage_thermal_recovery_required.json');canary=Path('/fixture-integrity');canary.write_bytes(b'unchanged-private-fixture'*4096);before=hashlib.sha256(canary.read_bytes()).hexdigest();events={};stop=threading.Event()
    # Positive core control stores only an invocation marker, never core data.
    core=Path('/bin/fixture-core');core.write_text('#!/bin/sh\necho invoked > /control/core-invoked\n');core.chmod(0o755)
    Path('/proc/sys/kernel/core_pattern').write_text('|/bin/fixture-core')
    positive=subprocess.run(['/usr/bin/python3','-c','import os;os.abort()'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    end=time.monotonic()+3
    while not Path('/control/core-invoked').exists()and time.monotonic()<end:time.sleep(.05)
    assert Path('/control/core-invoked').exists(),'core instrumentation positive control missing';Path('/control/core-invoked').unlink();events['core_positive_control']=True
    def observer():
        try:
            while not stop.is_set():
                try:name=(control/'case').read_text()
                except OSError:name=''
                if name=='busy':
                    with open('/ordinary-root-activity','w+b',buffering=0)as f:os.pwrite(f.fileno(),b'private-VM-write'*128,0);os.fsync(f.fileno());os.pread(f.fileno(),4096,0)
                    events['busy_cycles']=events.get('busy_cycles',0)+1
                if (control/'space-request').exists()and not(control/'space-ready').exists():
                    fs=os.statvfs('/');size=max(0,fs.f_bavail*fs.f_frsize-80*1024**2)
                    with open('/fixture.fill','wb')as fill:
                        os.posix_fallocate(fill.fileno(),0,size)
                        os.fsync(fill.fileno())
                    # Btrfs accounting can change as allocation creates chunks.
                    # Prove the reserve condition rather than assuming fallocate
                    # consumed the statvfs estimate on this filesystem.
                    for attempt in range(8):
                        fs=os.statvfs('/')
                        free=fs.f_bavail*fs.f_frsize
                        if free<96*1024**2:break
                        with open('/fixture.fill','r+b')as fill:
                            offset=os.fstat(fill.fileno()).st_size
                            os.posix_fallocate(fill.fileno(),offset,free-80*1024**2)
                            os.fsync(fill.fileno())
                    assert os.statvfs('/').f_bavail*fs.f_frsize<96*1024**2,'low-space fixture not established'
                    events['low_space_free_bytes']=os.statvfs('/').f_bavail*fs.f_frsize
                    (control/'space-ready').touch()
                if (control/'space-done').exists()and not(control/'space-restored').exists():
                    Path('/fixture.fill').unlink();(control/'space-restored').touch()
                if (control/'swap-request').exists()and not(control/'swap-ready').exists():
                    import fcntl,struct
                    with open('/fixture.swap','wb')as f:
                        if encrypted:fcntl.ioctl(f,0x40086602,struct.pack('L',0x00800000))
                        os.posix_fallocate(f.fileno(),0,32*1024**2)
                    Path('/fixture.swap').chmod(0o600)
                    subprocess.run(['/bin/mkswap','/fixture.swap'],check=True,capture_output=True);subprocess.run(['/bin/swapon','/fixture.swap'],check=True,capture_output=True);events['swap_active']=Path('/proc/swaps').read_text();(control/'swap-ready').touch()
                    import mmap
                    def counter():return int(dict(line.split()for line in Path('/proc/vmstat').read_text().splitlines())['pswpout'])
                    before_swap=counter();memory=mmap.mmap(-1,16*1024**2,flags=mmap.MAP_PRIVATE|mmap.MAP_ANONYMOUS);memory.write(b'P'*(16*1024**2));memory.madvise(21);time.sleep(1);events['swapout_pages']=counter()-before_swap;assert events['swapout_pages']>0,'swap pressure positive control missing';assert memory[0]==ord('P');memory.close()
                if name=='topology-change'and not events.get('topology_changed'):
                    active=False
                    for p in marker.parent.glob('integrated/1000/*/launch_ownership.json'):
                        active|=any(w.get('io_admission')=='committed'and not w.get('reaped')for w in json.loads(p.read_text()).get('workers',[]))
                    if active:
                        Path('/fixture-alias').mkdir(exist_ok=True)
                        subprocess.run(['/bin/mount','--bind','/etc','/fixture-alias'],check=True)
                        events['topology_changed']=True
                if (control/'topology-done').exists()and not(control/'topology-restored').exists():
                    subprocess.run(['/bin/umount','/fixture-alias'],check=True)
                    (control/'topology-restored').touch()
                if name=='handler-death' and (control/'kill-ready').exists()and not events.get('handler_killed'):
                    for p in marker.parent.glob('integrated/1000/*/launch_ownership.json'):
                        owned=json.loads(p.read_text());active=[w for w in owned.get('workers',[])if w.get('io_admission')=='committed'and not w.get('reaped')]
                        if not active:continue
                        owner=active[0]['supervisor_pgid'];children=[int(n)for n in Path(f'/proc/{server.pid}/task/{server.pid}/children').read_text().split()]
                        assert owner in children,'fixture handler ownership mismatch'
                        fd=os.pidfd_open(owner)
                        try:signal.pidfd_send_signal(fd,signal.SIGKILL)
                        finally:os.close(fd)
                        events['handler_killed']=True
                        break
                if name=='confidentiality' and not events.get('privacy'):
                    for p in marker.parent.glob('integrated/1000/*/launch_ownership.json'):
                        own=json.loads(p.read_text());workers=[w for w in own.get('workers',[])if w.get('io_admission')=='committed'and not w.get('reaped')]
                        if not workers:continue
                        pid=workers[0]['pid'];time.sleep(.5)
                        if not Path(f'/proc/{pid}').exists():continue
                        # Operator cannot inspect or signal the distinct identity.
                        child=os.fork()
                        if child==0:
                            try:
                                os.setgroups([]);os.setgid(1000);os.setuid(1000)
                                for path in (f'/proc/{pid}/mem',f'/proc/{pid}/fd/0'):
                                    try:fd=os.open(path,os.O_RDONLY)
                                    except PermissionError:pass
                                    else:os.close(fd);os._exit(2)
                                import ctypes,errno
                                libc=ctypes.CDLL(None,use_errno=True)
                                if libc.ptrace(16,pid,None,None)!=-1 or ctypes.get_errno()!=errno.EPERM:os._exit(5)
                                try:os.kill(pid,signal.SIGABRT)
                                except PermissionError:pass
                                else:os._exit(3)
                                os._exit(0)
                            except BaseException:os._exit(4)
                        _,status=os.waitpid(child,0);assert os.waitstatus_to_exitcode(status)==0,'worker memory/FD/signal exposed to operator'
                        assert Path(f'/proc/{pid}/fd').stat().st_uid==0,'exec is dumpable despite unreadable ELF'
                        os.kill(pid,signal.SIGABRT);events['privacy']=dict(operator_denied=True,nondumpable_exec=True,root_injected_worker_death=True)
                        time.sleep(.5);assert not Path('/control/core-invoked').exists(),'system worker generated a core'
                        break
                time.sleep(.1)
        except BaseException as e:events['observer_error']=str(e)
    thread=threading.Thread(target=observer);thread.start();server=subprocess.Popen(['/usr/bin/python3','-I','-B',str(launcher),'--serve-integrated'],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    try:
        end=time.monotonic()+15
        while not Path('/run/lvs-thermal/1000.sock').exists()and time.monotonic()<end:
            assert server.poll()is None,server.communicate();time.sleep(.05)
        child=os.fork()
        if child==0:
            os.setgroups([]);os.setgid(1000);os.setuid(1000);os.execv('/usr/bin/python3',['/usr/bin/python3','-B','/lvs/scripts/storage_thermal_system_probe.py','--client',identity])
        _,status=os.waitpid(child,0);assert os.waitstatus_to_exitcode(status)==0,'system client failed'
        results=json.loads((control/'result.json').read_text());assert not events.get('observer_error'),events
        assert read_state(marker)['state']=='CLEAN'and not blocker(marker)
        assert before==hashlib.sha256(canary.read_bytes()).hexdigest()
        # Existing standalone and integrated operations must share one scope.
        scope=RecoveryScope(marker).enter(evidence_directory=str(user))
        try:
            code="import sys;sys.path.insert(0,'/lvs');from Modules.lvs_storage_thermal import ThermalConfig;from Modules.lvs_storage_thermal_runtime import preview;c=ThermalConfig(access_mode='shared_readonly_opt_in',selection='individual',device_ids=[sys.argv[1]],system_device_ids=[sys.argv[1]],control_plane_colocation=True,system_swap=True,aggregate_iops_limit=16,aggregate_bps_limit=1048576,rate_mode='advanced',iops=16,bandwidth_bytes_per_second=1048576);assert preview(c)['status']=='BLOCKED'"
            subprocess.run(['/usr/bin/python3','-B','-c',code,identity],check=True,user=1000,group=1000,extra_groups=[])
            events['standalone_mutual_exclusion']=True
        finally:scope.resolve(cleanup_confirmed=True);scope.close()
        # Negative cases use the SAME canonical scope after real execution.
        ending='handler-death'if encrypted else'clean-enospc'
        child=os.fork()
        if child==0:
            os.setgroups([]);os.setgid(1000);os.setuid(1000);os.execv('/usr/bin/python3',['/usr/bin/python3','-B','/lvs/scripts/storage_thermal_system_probe.py','--final',identity,ending])
        _,status=os.waitpid(child,0);assert os.waitstatus_to_exitcode(status)==0,'final fault client failed'
        assert blocker(marker)and read_state(marker)['state']=='ARMED','uncertain cleanup/persistence became CLEAN'
        results['final_fault']=json.loads((control/'final-fault.json').read_text());events['final_fault']=ending
        probe="import sys;sys.path.insert(0,'/lvs');from Modules.lvs_storage_thermal_recovery import blocker;assert blocker(sys.argv[1])"
        subprocess.run(['/usr/bin/python3','-B','-c',probe,str(marker)],check=True)
        shutil.copytree(marker.parent,'/control/canonical-evidence');shutil.copytree(user,'/control/user-artifacts')
        return dict(contract='lvs.storage_thermal.system_vm.v1',root_filesystem='encrypted-btrfs'if encrypted else'ext4',root_identity=identity,results=results,events=events,integrity=True,canonical_CLEAN_before_interruption=True,fresh_process_ARMED=True,synthetic_primary_and_temperature=True)
    finally:
        stop.set();thread.join(5)
        if server.poll()is None:server.terminate()
        try:server.wait(timeout=8)
        except subprocess.TimeoutExpired:server.kill();server.wait(timeout=3)


if __name__=='__main__':
    assert sys.argv[1]in('--client','--final')and os.getuid()==1000 and 'QEMU'in Path('/sys/class/dmi/id/sys_vendor').read_text()and'lvs_fixture='in Path('/proc/cmdline').read_text()
    sys.path.insert(0,'/lvs')
    if sys.argv[1]=='--client':client(sys.argv[2])
    else:final_client(sys.argv[2],sys.argv[3])
