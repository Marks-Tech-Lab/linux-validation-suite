"""Sealed disposable VM old-installer -> retirement -> transient data proof."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import socket
import subprocess
import time


def vendor_abnormal_stop(migration,approval,unit,marker,proof):
    """Actual unchanged old server; VM tracer suppresses TERM, delivers ABRT.

    No memory/sector reads, executable mutation or production tracing feature.
    """
    import ctypes,signal,threading
    from Modules import lvs_storage_thermal_migration as m
    from Modules.lvs_storage_thermal_transient import systemctl,ENV
    pid=int(systemctl('show',unit,'--property=MainPID','--value'));identity=m.process_identity(pid)
    libc=ctypes.CDLL(None,use_errno=True);libc.ptrace.argtypes=[ctypes.c_uint,ctypes.c_uint,ctypes.c_void_p,ctypes.c_void_p];libc.ptrace.restype=ctypes.c_long
    ready=threading.Event();events=[];errors=[];finished=[]
    def ptrace(op,sig=0):
        if libc.ptrace(op,pid,None,ctypes.c_void_p(sig))<0:raise OSError(ctypes.get_errno(),'sealed tracer failure')
    def trace():
        try:
            assert m.process_identity(pid)==identity;ptrace(0x4206);ready.set()  # PTRACE_SEIZE
            end=time.monotonic()+110
            while time.monotonic()<end:
                got,status=os.waitpid(pid,os.WNOHANG|0x40000000)  # __WALL
                if not got:time.sleep(.01);continue
                if os.WIFSTOPPED(status):
                    sig=os.WSTOPSIG(status);events.append(dict(signal=sig,at=time.monotonic()))
                    ptrace(7,0 if sig==signal.SIGTERM else sig)  # only TERM suppressed
                else:finished.append(status);return
            raise RuntimeError('sealed tracer deadline')
        except BaseException as exc:errors.append(repr(exc));ready.set()
    thread=threading.Thread(target=trace,daemon=True);thread.start();assert ready.wait(10)and not errors,errors
    before=marker.read_bytes();start=time.monotonic()
    try:migration.retire(approval)
    except subprocess.TimeoutExpired:elapsed=time.monotonic()-start
    else:raise AssertionError('unresponsive service stop should exceed the existing 30-second administrative call')
    assert 28<=elapsed<40 and marker.read_bytes()==before
    state=json.loads((migration._pending(approval)/'state.json').read_text());assert state['phase']=='MASKED'
    assert json.loads(migration.record.read_text())['phase']=='retiring'
    # This failure is not cleanup. No transient owner may start on this marker.
    assert systemctl('is-active','lvs-thermal-demand-1000.service',check=False)!='active'
    thread.join(85);assert not thread.is_alive()and not errors and finished,(errors,events)
    signals=[v['signal']for v in events];assert signal.SIGTERM in signals and signal.SIGABRT in signals,events
    assert os.WIFSIGNALED(finished[0])and os.WTERMSIG(finished[0])==signal.SIGABRT,finished
    migration.retire(approval);migration.rollback(approval);assert marker.read_bytes()==before
    proof['vendor_abnormal_stop']=dict(control_timeout_seconds=elapsed,events=events,exit_signal=signal.SIGABRT,CLEAN_unchanged=True,resumed_and_rolled_back=True)
    # Companion policy proof: ignore ABRT too; final KILL must cover descendants.
    name='lvs-vendor-final-kill.service';event=Path('/control/vendor-final-kill.events')
    code="""import signal,time,os
from pathlib import Path
p=Path('/control/vendor-final-kill.events')
def record(s,f):
 with p.open('a')as out:out.write(str(s)+'\\n')
signal.signal(15,record);signal.signal(6,record)
child=os.fork()
if child:
 Path('/control/vendor-final-kill.child').write_text(str(child))
 p.write_text('READY\\n')
while True:time.sleep(.1)
"""
    subprocess.run(['/usr/bin/systemd-run','--quiet','--unit='+name,'--property=Type=exec','--property=KillMode=mixed','--property=TimeoutStopSec=1','--property=TimeoutAbortSec=1','/usr/bin/python3','-I','-B','-c',code],check=True,env=ENV,capture_output=True)
    end=time.monotonic()+10
    while not event.exists():assert time.monotonic()<end;time.sleep(.05)
    child=int(Path('/control/vendor-final-kill.child').read_text());handle=os.pidfd_open(child)
    r=subprocess.run(['/usr/bin/systemctl','stop',name],env=ENV,capture_output=True,text=True,timeout=12)
    result=systemctl('show',name,'--property=ExecMainCode','--property=ExecMainStatus','--property=MainPID','--property=ActiveState')
    assert 'ExecMainCode=2'in result and 'ExecMainStatus=9'in result and 'MainPID=0'in result,result
    assert '15'in event.read_text()and '6'in event.read_text(),event.read_text()
    import select
    assert select.select([handle],[],[],2)[0],'descendant survived final KILL';os.close(handle)
    assert marker.read_bytes()==before
    proof['vendor_final_kill']=dict(result=result,signals=event.read_text(),journal_unchanged=True)


def run(bundle,identity):
    from __main__ import seal
    seal()
    from Modules import lvs_storage_thermal_migration as m
    from Modules.lvs_storage_thermal_transient import ROOT_STAGER,ENV,digest,systemctl
    from Modules.lvs_storage_thermal_recovery import RecoveryScope,read_state
    from scripts.storage_thermal_install import Installer
    historical=Path('/shared-campaign').read_text()=='encrypted-ea60-migration-systemd'
    for folder in ('/bin','/usr','/lib','/lib64'):
        p=Path(folder)
        if p.exists():
            for item in (p,*p.rglob('*')):os.chown(item,0,0,follow_symlinks=False)
    for name in ('/run','/etc','/etc/systemd','/etc/systemd/system','/var','/var/lib','/var/lib/lvs-thermal'):
        Path(name).mkdir(exist_ok=True);Path(name).chmod(0o755)
    Path('/etc/passwd').write_text('root:x:0:0:root:/root:/bin/sh\noperator:x:1000:1000:operator:/control/user:/bin/sh\n')
    Path('/etc/group').write_text('root:x:0:\noperator:x:1000:\n')
    Path('/etc/shadow').write_text('root:!:1:0:99999:7:::\noperator:!:1:0:99999:7:::\n');Path('/etc/shadow').chmod(0o600)
    Path('/etc/login.defs').write_text('SYS_UID_MIN 200\nSYS_UID_MAX 999\nSYS_GID_MIN 200\nSYS_GID_MAX 999\n')
    # Qualify immutable-OS /opt alias too; no host path is touched.
    Path('/opt').rename('/var/opt');Path('/opt').symlink_to('/var/opt',target_is_directory=True)
    previous=Path('/opt/lvs-thermal-previous');legacy_source=json.loads((previous/'manifest.json').read_text())['source']
    installer=Installer(base=Path('/var/opt/lvs-thermal'));unit='lvs-thermal-1000.service'
    def start_historical():
        subprocess.run(['/usr/bin/systemd-run','--quiet','--collect','--unit='+unit,'--property=Type=exec','--property=KillMode=mixed','--property=TimeoutStopSec=45','--property=UMask=0077','/usr/bin/env','-i','PATH=/usr/bin:/bin','HOME=/root','LC_ALL=C','/usr/bin/python3','-I','-B','/opt/lvs-thermal/'+m.EA60+'/launch.py','--serve-integrated'],check=True,env=ENV,capture_output=True)
        deadline=time.monotonic()+20
        while not Path('/run/lvs-thermal/1000.sock').exists():
            assert time.monotonic()<deadline,'historical listener startup timeout';time.sleep(.1)
    if historical:
        m.SOCKETS.mkdir(exist_ok=True);m.SOCKETS.chmod(0o755)  # historical reviewed directory correction
        base=Path('/var/opt/lvs-thermal');base.mkdir()
        # A separate disposable Btrfs control disk models actual /var/opt while
        # keeping system/runtime ancestry off the selected data NVMe.
        from __main__ import fixture_device
        subprocess.run(['/bin/umount','/control'],check=True)
        subprocess.run(['/bin/mkfs.btrfs','-f','--nodiscard',fixture_device(1,partition=True)],check=True,capture_output=True)
        subprocess.run(['/bin/mount','-t','btrfs',fixture_device(1,partition=True),'/control'],check=True)
        carrier=Path('/control/retirement-code');carrier.mkdir()
        subprocess.run(['/bin/mount','--bind',str(carrier),str(base)],check=True)
        old=base/m.EA60;shutil.copytree(previous,old)
        m.historical_deployment(old,1000);start_historical()
        assert not(m.STATE/'installation-1000.json').exists()and not(m.STATE/'install.lock').exists()
    else:
        installed=installer.install(previous,digest(previous/'manifest.json'));old=Path(installed['deployment'])
    marker=m.STATE/'storage_thermal_recovery_required.json'
    # Genuine durable protection establishes CLEAN, not a synthetic journal edit.
    scope=RecoveryScope(marker);scope.enter(evidence_directory='/control');scope.resolve(cleanup_confirmed=True);scope.close()
    before=marker.read_bytes();anchor=Path(str(marker)+'.scope').stat().st_ino
    saved={str(p):digest(p)for p in old.rglob('*')if p.is_file()}
    worker_db={str(p):p.read_bytes()for p in (Path('/etc/passwd'),Path('/etc/group'),Path('/etc/shadow'))}
    migration=m.Migration(1000,historical_ea60=historical);proof={'historical_ea60':historical}
    def denied(fn):
        try:fn()
        except (ValueError,OSError,KeyError):return
        raise AssertionError('unsafe transition accepted')
    # Missing/corrupt/ARMED/locked canonical state always blocks, unchanged.
    held=RecoveryScope(marker);held.enter(evidence_directory='/control')
    denied(migration.inspect);held.resolve(cleanup_confirmed=True);held.close();before=marker.read_bytes()
    proof['active_canonical_owner_rejected']=True
    # A real authenticated connection creates a real service handler; inspection
    # may not stop that active legacy client merely to manufacture quiescence.
    user=Path('/control/user');user.mkdir(exist_ok=True);os.chown(user,1000,1000)
    program="import socket,time;from pathlib import Path;s=socket.socket(socket.AF_UNIX);s.connect('/run/lvs-thermal/1000.sock');s.sendall(b'J');Path('/control/user/peer-ready').touch();time.sleep(2)"
    peer=subprocess.Popen(['/usr/bin/python3','-I','-B','-c',program],user=1000,group=1000,extra_groups=(),env=ENV)
    while not (user/'peer-ready').exists()and peer.poll()is None:time.sleep(.05)
    assert peer.poll()is None
    denied(migration.inspect);peer.wait(timeout=5);time.sleep(1);proof['active_legacy_client_rejected']=True
    # Existing protected tool substitution is detected before any unit changes.
    fio=old/'runtime/build/fio';mode=fio.stat().st_mode;original=fio.read_bytes();fio.write_bytes(b'not fio')
    denied(migration.inspect);fio.write_bytes(original);fio.chmod(mode);proof['altered_deployment_rejected']=True
    if historical:
        # A legitimate operator process must not be mistaken for a dedicated
        # storage worker, but a pinned old bootstrap mapping must block.
        def process(program,ready):
            ready.unlink(missing_ok=True)
            p=subprocess.Popen(['/usr/bin/python3','-I','-B','-c',program],user=1000,group=1000,extra_groups=(),env=ENV,stdin=subprocess.PIPE)
            deadline=time.monotonic()+10
            while not ready.exists()and p.poll()is None:
                assert time.monotonic()<deadline;time.sleep(.05)
            assert p.poll()is None;return p
        ready=user/'ordinary-ready'
        ordinary=process("import sys;from pathlib import Path;Path('/control/user/ordinary-ready').touch();sys.stdin.buffer.read(1)",ready)
        migration.inspect();ordinary.stdin.close();ordinary.wait(timeout=5);proof['ordinary_operator_process_allowed']=True
        ready=user/'mapping-ready'
        program="import mmap,sys;from pathlib import Path;f=open("+repr(str(old/'runtime/build/storage_thermal_launch.so'))+",'rb');mapped=mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ);Path('/control/user/mapping-ready').touch();sys.stdin.buffer.read(1)"
        mapped=process(program,ready);denied(migration.inspect);mapped.stdin.close();mapped.wait(timeout=5);proof['escaped_bootstrap_mapping_rejected']=True
        tool=old/'runtime/build/storage_thermal_launch.so';v=tool.stat();kernel_identity=m.mapping_identity(tool)
        proof['mapping_identity']=dict(stat_device=v.st_dev,proc_device=kernel_identity[0],inode=v.st_ino,proc_inode=kernel_identity[1],carrier='Btrfs')
    if historical:
        # Real root-owned 0664 vendor unit: safe to observe, not executable trust.
        unrelated=Path('/usr/lib/systemd/system/lvs-unrelated-vendor.service')
        innocent=b'[Service]\nExecStart=/usr/bin/true\n';unrelated.write_bytes(innocent);unrelated.chmod(0o664)
        assert unrelated.stat().st_uid==0 and unrelated.stat().st_mode&0o777==0o664
        migration.inspect();proof['unrelated_vendor_mode664_accepted']=True
        unrelated.write_text('[Service]\nExecStart=/usr/bin/python3 '+str(old/'launch.py')+'\n')
        denied(migration.inspect);unrelated.write_bytes(innocent)
        fragment=unrelated.parent/'lvs-unrelated-vendor.service.d';fragment.mkdir()
        (fragment/'override.conf').write_text('[Service]\nExecStart='+str(old/'launch.py')+'\n')
        denied(migration.inspect);(fragment/'override.conf').unlink();fragment.rmdir()
        alias=Path('/usr/lib/systemd/system')/unit
        alias.symlink_to(m.TRANSIENT_UNITS/unit);denied(migration.inspect);alias.unlink()
        proof['alternate_writable_vendor_and_alias_rejected']=True
    approval=migration.inspect()['approval_sha256'];proof['inspection']=migration.inspect()
    if historical and Path('/vendor-dropin-proof').exists():
        # Exact global vendor bytes are qualified in this guest only. No host
        # config or active raw worker is changed by these negative controls.
        vendor=m.VENDOR_DROPIN;data=vendor.read_bytes()
        vendor.chmod(0o664);denied(migration.inspect);vendor.chmod(0o644)
        vendor.write_bytes(data+b'\n[Service]\nExecStop=/unqualified\n');denied(migration.inspect);vendor.write_bytes(data)
        systemctl('daemon-reload')
        extra=Path('/etc/systemd/system')/(unit+'.d');extra.mkdir()
        (extra/'90-extra.conf').write_text('[Service]\nNice=1\n');systemctl('daemon-reload');denied(migration.inspect)
        (extra/'90-extra.conf').unlink();extra.rmdir();systemctl('daemon-reload')
        approval=migration.inspect()['approval_sha256']
        vendor_abnormal_stop(migration,approval,unit,marker,proof)
        start_historical();approval=migration.inspect()['approval_sha256'];proof['inspection']=migration.inspect()
        proof['vendor_negative_controls']=True

    # Crash a separate administrator process after each durable phase. Resume
    # and roll back without restarting anything; preserve all old material.
    phases=('PREPARED','MASKED','STOPPED','SOCKET_RECONCILED','RETIRED')
    failures=[];direct_rollbacks=[]
    cases=[(p,op)for p in phases for op in (('resume','rollback')if historical else('resume',))]
    for phase,operation in cases:
        def crash(point):
            if point==phase:
                if point=='PREPARED':
                    code="import sys;from pathlib import Path;sys.path.insert(0,'/lvs');from scripts.storage_thermal_install import Installer;Installer(base=Path('/var/opt/lvs-thermal')).rollback(1000)"
                    blocked=subprocess.run(['/usr/bin/python3','-I','-B','-c',code],env=ENV,capture_output=True,text=True)
                    assert blocked.returncode and 'Resource temporarily unavailable'in blocked.stderr,blocked.stderr
                    Path('/control/installer-lock-proven').touch()
                    # The real new bootstrap must contend on that SAME lock,
                    # before identity reservation or service creation.
                    code="import sys;from pathlib import Path;sys.path.insert(0,'/lvs');from Modules.lvs_storage_thermal_transient import bootstrap,digest;p=Path("+repr(str(bundle.resolve()))+");bootstrap(p,digest(p/'manifest.json'))"
                    blocked=subprocess.run(['/usr/bin/python3','-I','-B','-c',code],env=ENV,capture_output=True,text=True)
                    assert blocked.returncode and 'Resource temporarily unavailable'in blocked.stderr,blocked.stderr
                    Path('/control/startup-lock-proven').touch()
                os._exit(77)
        pid=os.fork()
        if pid==0:
            migration.checkpoint=crash;migration.retire(approval);os._exit(2)
        _,status=os.waitpid(pid,0);assert os.waitstatus_to_exitcode(status)==77,(phase,status)
        if historical and phase=='MASKED'and operation=='resume':
            # Idle historical service death bypasses Python socket unlink. The
            # preserved approved inode must be reconciled, never blindly erased.
            systemctl('kill',unit,'--kill-whom=main','--signal=SIGKILL')
            deadline=time.monotonic()+10
            while systemctl('show',unit,'--property=MainPID','--value')!='0':
                assert time.monotonic()<deadline;time.sleep(.1)
            assert Path('/run/lvs-thermal/1000.sock').exists()
            proof['known_legacy_stale_socket_created']=True
        fresh=m.Migration(1000,historical_ea60=historical)
        try:
            if operation=='resume':fresh.retire(approval)
        except BaseException:
            Path('/control/retire-manager-state.json').write_text(json.dumps(m.properties(unit),indent=2));raise
        if operation=='resume':assert m.retired_record(1000)
        if historical and phase=='MASKED'and operation=='resume':
            assert not Path('/run/lvs-thermal/1000.sock').exists();proof['known_legacy_stale_socket_reconciled']=True
        fresh.rollback(approval);assert systemctl('is-active',unit,check=False)!='active'
        if historical:
            assert not(m.STATE/'installation-1000.json').exists()and not(Path('/etc/systemd/system')/unit).exists()
        else:
            assert json.loads((m.STATE/'installation-1000.json').read_text())['phase']=='active'
            assert systemctl('is-enabled',unit,check=False)=='disabled'
        if operation=='resume':failures.append(phase)
        else:direct_rollbacks.append(phase)
        # Only this fixture explicitly restarts the known old deployment to set
        # up the NEXT interruption case. Production rollback never starts it.
        if historical:start_historical()  # explicit fixture re-creation, never rollback
        elif phase!=phases[-1]:
            systemctl('start',unit);installer.health(old,json.loads((old/'manifest.json').read_text()))
        # Each exact PID/socket generation requires fresh administrator approval.
        # Archive remains; a rolled-back identical approval is intentionally not
        # recycled. Runtime PID or restored enablement changes the approval.
        approval=migration.inspect()['approval_sha256']
    proof['interrupted_phases_resumed_and_rolled_back']=failures
    if historical:proof['interrupted_phases_direct_rollback']=direct_rollbacks
    proof['concurrent_installer_lock_rejected']=Path('/control/installer-lock-proven').exists()
    proof['concurrent_startup_lock_rejected']=Path('/control/startup-lock-proven').exists()
    # Final retirement from stopped/disabled legacy service uses current approval.
    final=migration.retire(approval);proof['retirement']=final
    assert marker.read_bytes()==before and Path(str(marker)+'.scope').stat().st_ino==anchor
    for name,h in saved.items():assert digest(name)==h
    for name,raw in worker_db.items():assert Path(name).read_bytes()==raw
    proof['legacy_tree_worker_and_recovery_preserved']=True
    # Previously accepted installer/rollback code must fail on the tombstone.
    denied(lambda:installer.install(previous,digest(previous/'manifest.json')))
    denied(lambda:installer.rollback(1000));proof['old_installer_and_rollback_blocked']=True
    if Path('/on-demand-proof-only').exists():
        return dict(contract='lvs.storage_thermal.migration_lock_vm.v1',source=json.loads((bundle/'manifest.json').read_text())['source'],results=proof)
    # Current source snapshot, fixture-only sensor injection independently hashed.
    launcher=bundle/'launch.py';text=launcher.read_text();needle='if integrated_serve or integrated_client:\n'
    injection='''if integrated_serve or integrated_client:
 from Modules.lvs_storage_thermal_service import RuntimePolicy
 original=RuntimePolicy.runner
 def fixture(self):
  runner=original(self);runner.temperature=lambda row:dict(value_c=30.,critical_c=70.,warning_c=55.,complete=True,synthetic_VM_sensor=True);return runner
 RuntimePolicy.runner=fixture
'''
    assert needle in text;launcher.write_text(text.replace(needle,injection))
    manifest=json.loads((bundle/'manifest.json').read_text());manifest['files']['launch.py']=digest(launcher)
    (bundle/'manifest.json').write_text(json.dumps(manifest));approved=digest(bundle/'manifest.json')
    source=Path('/control/new-source');shutil.copytree(bundle,source)
    for p in (source,*source.rglob('*')):os.chown(p,1000,1000)
    def startup():
        r=subprocess.run(['/usr/bin/python3','-I','-B','-c',ROOT_STAGER,str(source),approved,'1000'],env=dict(ENV,SUDO_UID='1000'),capture_output=True,text=True,timeout=90)
        assert r.returncode==0,r.stderr[-5000:];return json.loads(r.stdout)
    def until(check,seconds=70):
        end=time.monotonic()+seconds
        while not check():
            if time.monotonic()>end:raise RuntimeError('migration fixture deadline')
            time.sleep(.2)
    # Unknown stale socket is never erased by startup.
    stale=Path('/run/lvs-thermal/1000.sock');s=socket.socket(socket.AF_UNIX);s.bind(str(stale));s.close();inode=stale.stat().st_ino
    r=subprocess.run(['/usr/bin/python3','-I','-B','-c',ROOT_STAGER,str(source),approved,'1000'],env=dict(ENV,SUDO_UID='1000'),capture_output=True,text=True,timeout=90)
    assert r.returncode and stale.stat().st_ino==inode;stale.unlink();proof['unknown_stale_socket_rejected']=True
    started=startup();until(lambda:stale.exists());first=Path(started['root'])
    # Competing migration/rollback cannot interrupt an active transient helper.
    denied(lambda:migration.rollback(approval));proof['rollback_while_transient_rejected']=True
    Path('/control/user').mkdir(exist_ok=True);os.chown('/control/user',1000,1000)
    cmd=['/usr/bin/python3','-B','/lvs/scripts/storage_thermal_transient_probe.py','--client',identity]
    with Path('/control/client.stdout').open('w')as out,Path('/control/client.stderr').open('w')as err:
        child=subprocess.Popen(cmd,user=1000,group=1000,extra_groups=(),env=dict(PATH='/usr/bin:/bin',PYTHONPATH='/lvs'),stdout=out,stderr=err)
        until(lambda:Path('/control/user/phase1.json').exists()or child.poll()is not None,150)
        assert child.poll()is None,Path('/control/client.stderr').read_text()[-6000:]
        until(lambda:not first.exists());started2=startup();until(lambda:stale.exists())
        Path('/control/user/restart-ready').touch();child.wait(timeout=30)
        assert child.returncode==0,Path('/control/client.stderr').read_text()[-6000:]
    proof['client']=json.loads(Path('/control/user/client.json').read_text())
    until(lambda:not Path(started2['root']).exists());assert read_state(marker)['state']=='CLEAN'
    proof['canonical_CLEAN']=True;proof['idle_cleanup']=True;proof['private_identity_static_db_unchanged']=all(Path(p).read_bytes()==raw for p,raw in worker_db.items())
    # A separately approved source generation can start after idle cleanup;
    # an old frontend must fail source reconciliation against it.
    from Modules.lvs_source_provenance import _source_snapshot
    changed=source/'runtime/Modules/lvs_cli_run.py';changed.write_bytes(changed.read_bytes()+b'\n# sealed VM source-update qualification\n');os.chown(changed,1000,1000)
    updated=json.loads((source/'manifest.json').read_text());updated['files']['runtime/Modules/lvs_cli_run.py']=digest(changed);updated['source']=_source_snapshot(source/'runtime')[0]
    preparation=source/'preparation.json';v=json.loads(preparation.read_text());v['source']=updated['source'];preparation.write_text(json.dumps(v));updated['files']['preparation.json']=digest(preparation)
    (source/'manifest.json').write_text(json.dumps(updated));approved=digest(source/'manifest.json')
    upgraded=startup();until(lambda:stale.exists())
    program="import sys,json;sys.path.insert(0,'/lvs');from Modules.lvs_storage_thermal_runtime import rpc;print(json.dumps(rpc('health')))"
    h=subprocess.run(['/usr/bin/python3','-I','-B','-c',program],env=ENV,user=1000,group=1000,extra_groups=(),capture_output=True,text=True,check=True)
    assert json.loads(h.stdout)['source']==updated['source']and updated['source']!=manifest['source'];proof['approved_source_update']=updated['source']
    until(lambda:not Path(upgraded['root']).exists())
    # A genuine unresolved durable obligation survives a fresh process and may
    # never be erased or rolled back to restart the legacy service.
    unresolved=RecoveryScope(marker);unresolved.enter(evidence_directory='/control/unconfirmed');unresolved.close()
    denied(lambda:migration.rollback(approval))
    r=subprocess.run(['/usr/bin/python3','-I','-B','-c',ROOT_STAGER,str(source),approved,'1000'],env=dict(ENV,SUDO_UID='1000'),capture_output=True,text=True,timeout=90)
    assert r.returncode
    fresh=subprocess.check_output(['/usr/bin/python3','-I','-B','-c',"import sys,json;from pathlib import Path;sys.path.insert(0,'/lvs');from Modules.lvs_storage_thermal_recovery import read_state;print(json.dumps(read_state(Path('/var/lib/lvs-thermal/storage_thermal_recovery_required.json'))))"],env=ENV,text=True)
    proof['fresh_final_recovery']=json.loads(fresh);assert proof['fresh_final_recovery']['state']=='ARMED'
    proof['ARMED_blocks_rollback_and_startup']=True
    proof['old_unit_masked']=m.masked(unit);proof['old_installed_source']=legacy_source
    return dict(contract='lvs.storage_thermal.migration_vm.v1',source=manifest['source'],results=proof)
