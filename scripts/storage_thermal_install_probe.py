"""Sealed VM installation qualification. No standalone host entrypoint.

Real installer transactions, useradd, privileged service and descriptor-bound fio.
The systemd supervisor is a fixture adapter (not a systemd boot proof). Primary
stress and temperature readings are explicitly simulated, elapsed time is real.
"""
from pathlib import Path
import base64
import hashlib
import json
import os
import shutil
import signal
import select
import subprocess
import sys
import threading
import time
from types import SimpleNamespace


def client(identity):
    from Modules.lvs_storage_thermal import ThermalConfig
    from scripts.storage_thermal_integrated_probe import primary
    c=ThermalConfig(access_mode='shared_readonly_opt_in',selection='individual',device_ids=[identity],rate_mode='advanced',iops=8,bandwidth_bytes_per_second=524288,aggregate_iops_limit=16,aggregate_bps_limit=1048576,temperature_limit_c=60)
    from dataclasses import replace
    from Modules.lvs_storage_thermal_runtime import preview
    root=next(r for r in preview(c)['devices']if r.get('system_drive')and r.get('identity',{}).get('name','').startswith('nvme'))
    authorized=preview(replace(c,device_ids=[root['device_id']],system_device_ids=[root['device_id']],control_plane_colocation=True))
    assert authorized['status']=='READY',authorized
    results={'postexec_system_ready_under_fs2':True}
    for case,seconds,cancel,thermal in [('normal',35,None,False),('cancel',45,2,False),('temperature',45,None,True)]:
        directory=Path('/control/user')/case;directory.mkdir();(Path('/control/user')/'case').write_text(case)
        r=primary(None,dict(c.to_dict(),duration_seconds=seconds),directory,seconds,cancel_after=cancel,temperature_stop=thermal);results[case]=r
        Path('/control/user/sensor-hot').unlink(missing_ok=True)
        (directory/'result.json').write_text(json.dumps(r,indent=2))
        assert r['auxiliary']['cleanup_confirmed']and r['auxiliary']['executed_devices']==[identity],r
        assert sum(d.get('read_ios',0)for d in r['auxiliary']['devices'])>0,r
        assert r['primary_verdict']=='pass'if cancel is None else r['aborted']
    Path('/control/user/client.json').write_text(json.dumps(results,indent=2))


def run(bundle,identity):
    from __main__ import seal
    seal()
    from scripts.storage_thermal_install import Installer,Systemd,ENV,digest,canonical_directory
    from Modules.lvs_storage_thermal_recovery import RecoveryScope,blocker,read_state
    # mkfs -d preserves the unprivileged image-builder UID; model a real OS
    # with trusted root-owned interpreter, libraries and shadow-utils.
    for folder in ('/bin','/usr','/lib','/lib64'):
        directory=Path(folder)
        if directory.exists():
            for p in (directory,*directory.rglob('*')):os.chown(p,0,0,follow_symlinks=False)
    Path('/run').chmod(0o755)
    for p in (Path('/etc'),Path('/etc/systemd'),Path('/etc/systemd/system'),Path('/var'),Path('/var/lib'),Path('/var/lib/lvs-thermal')):p.mkdir(exist_ok=True);p.chmod(0o755)
    Path('/etc/passwd').write_text('root:x:0:0:root:/root:/bin/sh\nfixture:x:1000:1000:operator:/nonexistent:/bin/sh\n')
    Path('/etc/group').write_text('root:x:0:\nfixture:x:1000:\n')
    Path('/etc/shadow').write_text('root:!:1:0:99999:7:::\nfixture:!:1:0:99999:7:::\n');Path('/etc/shadow').chmod(0o600)
    Path('/etc/login.defs').write_text('SYS_UID_MIN 200\nSYS_UID_MAX 999\nSYS_GID_MIN 200\nSYS_GID_MAX 999\n')
    # Model the workstation's root-owned immutable-OS aliases in the VM.
    if not Path('/opt').is_symlink():
        Path('/opt').rename('/var/opt');Path('/opt').symlink_to('/var/opt',target_is_directory=True)
    Path('/var/usrlocal').mkdir(exist_ok=True)
    if not Path('/usr/local').exists():Path('/usr/local').symlink_to('/var/usrlocal',target_is_directory=True)
    install_base=canonical_directory(Path('/opt/lvs-thermal'),allow_missing=True)
    control=Path('/control/user');control.mkdir();os.chown(control,1000,1000);control.chmod(0o700)
    build=Path('/lvs/build');build.mkdir(exist_ok=True);shutil.copy2(bundle/'runtime/build/storage_thermal_launch.so',build/'storage_thermal_launch.so')
    # Explicit guest-only sensor injection, covered by the fixture approval hash.
    launcher=bundle/'launch.py';text=launcher.read_text();needle='if integrated_serve or integrated_client:\n'
    injection='''if integrated_serve or integrated_client:
 from pathlib import Path
 from Modules.lvs_storage_thermal_service import RuntimePolicy
 original_runner=RuntimePolicy.runner
 def fixture_runner(self):
  r=original_runner(self);r.temperature=lambda row:dict(value_c=65. if Path('/control/user/sensor-hot').exists()else 30.,critical_c=70.,warning_c=55.,complete=True,synthetic_VM_sensor=True);return r
 RuntimePolicy.runner=fixture_runner
'''
    assert needle in text;launcher.write_text(text.replace(needle,injection))
    def reseal(path,variation):
        m=json.loads((path/'manifest.json').read_text());p=json.loads((path/'preparation.json').read_text());p['fixture_variation']=variation;(path/'preparation.json').write_text(json.dumps(p))
        m['files']={str(f.relative_to(path)):digest(f.read_bytes())for f in path.rglob('*')if f.is_file()and f.name not in ('manifest.json','SHA256SUMS')}
        (path/'manifest.json').write_text(json.dumps(m));raw=(path/'manifest.json').read_bytes();(path/'SHA256SUMS').write_text(''.join(h+'  '+n+'\n'for n,h in sorted(dict(m['files'],**{'manifest.json':digest(raw)}).items())));return digest(raw)
    approved=reseal(bundle,'A');versions=[(bundle,approved)]
    for name in ('B','C'):
        copy=Path('/opt')/('fixture-input-'+name);shutil.copytree(bundle,copy);versions.append((copy,reseal(copy,name)))
    class Supervisor:
        def __init__(self):self.process=None;self.boot=False;self.fail=False;self.crash=False;self.authority=None;self.creator=os.getpid()
        def run(self,*a,**kw):return SimpleNamespace(returncode=0,stdout='')
        def quiescent(self,*_):return not self.active()
        def active(self,*_):return self.authority is not None and not select.select([self.authority],[],[],0)[0]
        def enabled(self,*_):return self.boot
        def enable(self,unit,value):self.boot=value
        def old_unit(self,unit,path):return path.read_bytes()if path.exists()else None
        def stop(self,*_):
            if self.active():
                signal.pidfd_send_signal(self.authority,signal.SIGTERM)
                if not select.select([self.authority],[],[],12)[0]:signal.pidfd_send_signal(self.authority,signal.SIGKILL);assert select.select([self.authority],[],[],3)[0]
            if self.process is not None and self.creator==os.getpid():self.process.wait(timeout=3)
        def start(self,unit):
            if self.crash:os._exit(77)
            if self.fail:self.fail=False;raise OSError('sealed VM start failure')
            path=Path('/etc/systemd/system')/unit;line=next(l for l in path.read_text().splitlines()if l.startswith('ExecStart='));args=line.removeprefix('ExecStart=').split()
            self.process=subprocess.Popen(args,env=ENV,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);self.creator=os.getpid()
            if self.authority is not None:os.close(self.authority)
            self.authority=os.pidfd_open(self.process.pid)
    real_systemd=Path('/shared-campaign').read_text().endswith('-systemd')
    class NativeSupervisor(Systemd):
        fail=False;crash=False
        def start(self,unit):
            if self.crash:os._exit(77)
            if self.fail:self.fail=False;raise OSError('sealed VM start failure')
            result=super().start(unit)
            return result
        def crash_idle(self,unit):
            pid=int(self.run('show',unit,'--property=MainPID','--value').stdout)
            assert pid>1
            fd=os.pidfd_open(pid)
            try:
                assert int(self.run('show',unit,'--property=MainPID','--value').stdout)==pid
                signal.pidfd_send_signal(fd,signal.SIGKILL)
            finally:os.close(fd)
            end=time.monotonic()+10
            while self.active(unit)and time.monotonic()<end:time.sleep(.1)
    service=NativeSupervisor(install_base)if real_systemd else Supervisor();installer=Installer(base=install_base,service=service);out={};unit='lvs-thermal-1000.service';unitpath=Path('/etc/systemd/system')/unit
    marker=Path('/var/lib/lvs-thermal/storage_thermal_recovery_required.json')
    fixtures=[Path('/encrypted1/fixture-integrity'),Path('/encrypted2/fixture-integrity')]
    integrity=[digest(p.read_bytes())for p in fixtures]
    try:
        out['canonical_install_base']=str(install_base);out['root_owned_aliases']=True
        out['fresh']=installer.install(*versions[0]);out['repeat']=installer.install(*versions[0]);assert out['repeat']['status']=='UNCHANGED'
        worker=out['fresh']['worker_uid'];assert worker!=1000 and worker>0
        out['first_rollback']=installer.rollback(1000);assert not service.active(unit)and not unitpath.exists()
        # Actual previously accepted 7e9d892 source and launcher, not a mocked version.
        previous=Path('/opt/lvs-thermal/accepted-7e9d892');shutil.copytree('/opt/lvs-thermal-previous',previous)
        for p in (previous,*previous.rglob('*')):
            p.chmod(0o755 if p.is_dir()or p.name in ('fio','storage_thermal_guard')else 0o644)
        if real_systemd:
            legacy=subprocess.run(['/usr/bin/systemd-run','--unit=lvs-thermal-1000','--collect','--property=Type=exec','--property=KillMode=mixed','--property=TimeoutStopSec=45','--property=UMask=0077','/usr/bin/env','-i','PATH=/usr/bin:/bin','HOME=/root','LC_ALL=C','/usr/bin/python3','-I','-B',str(previous/'launch.py'),'--serve-integrated'],check=False,env=ENV,capture_output=True)
            assert legacy.returncode==0,legacy.stderr.decode(errors='replace')
            out['legacy_transient']=service.run('show',unit,'--property=FragmentPath','--value').stdout.strip()
        else:
            unitpath.write_text('[Service]\nExecStart=/usr/bin/python3 -I -B '+str(previous/'launch.py')+' --serve-integrated\n');unitpath.chmod(0o644);service.start(unit)
        old_source=json.loads((previous/'manifest.json').read_text())['source'];out['previous_source']=old_source
        out['upgrade']=installer.install(*versions[0]);out['rollback']=installer.rollback(1000)
        assert str(previous.resolve()/'launch.py')in unitpath.read_text()and service.active(unit)
        out['reapply']=installer.install(*versions[0]);before=unitpath.read_bytes();service.fail=True
        try:installer.install(*versions[1])
        except OSError:pass
        else:raise AssertionError('failed promotion accepted')
        assert service.active(unit)and unitpath.read_bytes()==before;out['failed_promotion_preserved']=True
        # SIGKILL-equivalent process loss between durable intent and service start.
        child=os.fork()
        if child==0:service.crash=True;installer.install(*versions[2]);os._exit(2)
        _,status=os.waitpid(child,0);assert os.waitstatus_to_exitcode(status)==77
        installer=Installer(base=install_base,service=service)
        try:installer.install(*versions[0])
        except ValueError as exc:assert 'interrupted'in str(exc)
        else:raise AssertionError('interrupted transaction ignored')
        installer.rollback(1000);assert unitpath.read_bytes()==before and service.active(unit);out['interrupted_promotion_recovered']=True
        current=installer.install(*versions[2]);deployment=Path(current['deployment']);service.stop(unit);service.start(unit);installer.health(deployment,json.loads((deployment/'manifest.json').read_text()));out['restart']=True
        # Abrupt idle supervisor loss leaves a stale path. Only canonical CLEAN,
        # a quiescent owned supervisor and ECONNREFUSED allow reconciliation.
        if real_systemd:service.crash_idle(unit)
        else:service.process.kill();service.process.wait(timeout=5)
        assert Path('/run/lvs-thermal/1000.sock').exists()
        assert installer.install(*versions[2])['status']=='UNCHANGED'
        out['idle_crash_restart']=True
        if real_systemd:
            # Exercise the administrator CLI only after root-owned verified copy.
            parent=Path('/usr/local/libexec').resolve();parent.mkdir(parents=True,exist_ok=True)
            for p in (Path('/usr/local').resolve(),parent):os.chown(p,0,0);p.chmod(0o755)
            copied=parent/'lvs-thermal-install.py';shutil.copyfile('/lvs/scripts/storage_thermal_install.py',copied);copied.chmod(0o755)
            assert digest(copied.read_bytes())==digest(Path('/lvs/scripts/storage_thermal_install.py').read_bytes())
            reply=json.loads(subprocess.check_output(['/usr/bin/python3','-I','-B',str(copied),'--approve','--bundle',str(versions[2][0]),'--manifest-sha256',versions[2][1]],env=ENV))
            assert reply['status']=='UNCHANGED';out['production_installer_CLI']=True
        # Metadata stays available, but pending activation cannot admit work.
        record=Path('/var/lib/lvs-thermal/installation-1000.json');saved_record=record.read_bytes();pending=json.loads(saved_record);pending['phase']='promoting';record.write_text(json.dumps(pending))
        try:
            assert installer.health(deployment,json.loads((deployment/'manifest.json').read_text()))['installation_blocker']
            code="import sys;sys.path.insert(0,'/lvs');from Modules.lvs_storage_thermal_runtime import rpc;from Modules.lvs_storage_thermal import ThermalConfig;rpc('inspect',configuration=ThermalConfig().to_dict())"
            rejected=subprocess.run(['/usr/bin/python3','-B','-c',code],user=1000,group=1000,extra_groups=[],capture_output=True,env=ENV)
            assert rejected.returncode!=0 and b'installation is not active'in rejected.stderr
            out['pending_admission_blocked']=True
        finally:record.write_bytes(saved_record)
        # Match the workstation core policy without weakening system admission.
        Path('/proc/sys/fs/suid_dumpable').write_text('2')
        verified=installer.check(deployment);assert verified['status']=='VERIFIED'and verified['system_worker_ready']
        out['fs2_data_components']=True
        # Genuine normal integrated stage API as an ordinary user.
        stop=threading.Event();events={}
        def watch():
            while not stop.wait(.1):
                for p in marker.parent.glob('integrated/1000/*/launch_ownership.json'):
                    try:workers=json.loads(p.read_text()).get('workers',[])
                    except (OSError,ValueError):continue
                    if any(w.get('io_admission')=='committed'and not w.get('reaped')for w in workers)and not events.get('busy_update_blocked'):
                        try:installer.install(*versions[0])
                        except BlockingIOError:events['busy_update_blocked']=True
                        except BaseException as exc:events['error']=repr(exc)
                        else:events['error']='active workload update accepted'
        thread=threading.Thread(target=watch);thread.start()
        try:
            child=os.fork()
            if child==0:os.setgroups([]);os.setgid(1000);os.setuid(1000);os.execv('/usr/bin/python3',['/usr/bin/python3','-B','/lvs/scripts/storage_thermal_install_probe.py','--client',identity])
            _,status=os.waitpid(child,0);assert os.waitstatus_to_exitcode(status)==0,'installed production client failed'
        finally:stop.set();thread.join(5)
        assert events.get('busy_update_blocked')and not events.get('error'),events
        out['events']=events;out['production']=json.loads((control/'client.json').read_text());assert read_state(marker)['state']=='CLEAN'and not blocker(marker);out['canonical_CLEAN']=True
        Path('/proc/sys/fs/suid_dumpable').write_text('0')
        assert integrity==[digest(p.read_bytes())for p in fixtures];out['fixture_integrity']=True
        # No installer/rollback may manufacture CLEAN over an unresolved intent.
        scope=RecoveryScope(marker).enter(evidence_directory='/control');scope.close();saved=marker.read_bytes()
        for action in (lambda:installer.install(*versions[0]),lambda:installer.rollback(1000)):
            try:action()
            except ValueError:pass
            else:raise AssertionError('ARMED bypassed')
            assert marker.read_bytes()==saved
        subprocess.run(['/usr/bin/python3','-B','-c',"import sys;sys.path.insert(0,'/lvs');from Modules.lvs_storage_thermal_recovery import blocker;assert blocker(sys.argv[1])",str(marker)],check=True)
        out['ARMED_preserved_across_restart']=True;shutil.copytree(marker.parent,'/control/canonical-installation-evidence')
        return dict(contract='lvs.storage_thermal.install_vm.v1',results=out,supervisor='genuine PID1 systemd'if real_systemd else'fixture adapter for systemd; real installed privileged processes',synthetic_primary_and_temperature=True)
    except BaseException:
        import traceback
        Path('/control/install-error.txt').write_text(traceback.format_exc())
        if real_systemd:
            Path('/control/service-status.txt').write_text(service.run('status',unit,'--no-pager','-l',check=False).stdout)
            rows=[]
            for p in Path('/proc').iterdir():
                if p.name.isdigit():
                    try:rows.append(dict(pid=p.name,cmdline=(p/'cmdline').read_text().replace('\x00',' '),status=(p/'status').read_text().splitlines()[:4]))
                    except OSError:pass
            Path('/control/processes.json').write_text(json.dumps(rows,indent=2))
        Path('/control/install-partial.json').write_text(json.dumps(out,indent=2))
        raise
    finally:
        service.stop(unit)
        if marker.parent.exists()and not Path('/control/install-final-state').exists():shutil.copytree(marker.parent,'/control/install-final-state')


if __name__=='__main__':
    assert sys.argv[1]=='--client'and os.getuid()==1000 and 'QEMU'in Path('/sys/class/dmi/id/sys_vendor').read_text()and'lvs_fixture='in Path('/proc/cmdline').read_text()
    sys.path.insert(0,'/lvs');client(sys.argv[2])
