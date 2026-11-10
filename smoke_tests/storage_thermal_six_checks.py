"""Exact independent-audit counterexamples; synthetic files/processes only."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import errno
import fcntl
import inspect
import json
import os
import signal
import subprocess
import sys
import tempfile
import time

from Modules.lvs_storage_thermal_launch import OwnedProcess,prepare
from Modules.lvs_storage_thermal_stage import ThermalStageSession,StageChannel,stage_config
from Modules.lvs_storage_thermal_recovery import RecoveryScope,read_state,blocker
from Modules.lvs_storage_thermal_results import normalize,summarize_run
from smoke_tests.storage_thermal_stage_checks import stage,_run_primary_with_aux,_auxiliary_cases,_primary_publication_fixture


def run_thermal_owned_creation_checks():
    sessions=[]
    with tempfile.TemporaryDirectory() as root:
        def factory(s,plan,run_dir,**kw):
            obj=ThermalStageSession(s,{'status':'READY'},root,recovery_marker=Path(root)/'intent',launch_delay_ms=3000,**kw)
            sessions.append(obj);return obj
        result,args,_=_run_primary_with_aux(None,session_factory=factory,real_clock=True)
        assert 2<=result.stage_elapsed<2.8 and len(args['telemetry_times'])>=2,(result.stage_elapsed,args['telemetry_times'])
        assert result.stage_verdict=='pass' and sessions[-1].process.poll() is not None
        assert not sessions[-1].admitted
        print('  owned creation: primary',result.stage_elapsed,'telemetry',args['telemetry_times'],'child',sessions[-1].process.returncode)
        begin=time.monotonic()
        result,args,_=_run_primary_with_aux(None,session_factory=factory,real_clock=True,telemetry_interval=.1,cancel_check=lambda:time.monotonic()-begin>.3)
        assert result.stage_aborted and result.stage_elapsed<1 and len(args['telemetry_times'])>=2
        assert sessions[-1].process.poll() is not None
        # The exact old injection surface cannot execute arbitrary factories on
        # the timed primary thread. It fails closed before creating a child.
        invoked=[]
        def old(*a,**k):invoked.append(True);time.sleep(3)
        def refused(s,plan,run_dir,**kw):return ThermalStageSession(s,{'status':'READY'},root,popen=old,**kw)
        result,args,_=_run_primary_with_aux(None,session_factory=refused,real_clock=True)
        assert not invoked and 2<=result.stage_elapsed<2.8 and len(args['telemetry_times'])>=2
        # No target or unrelated fd is inherited through the owned bootstrap.
        with (Path(root)/'unapproved').open('w') as sentinel:
            p=OwnedProcess([sys.executable,'-c','pass'],delay_ms=3000)
            try:
                end=time.monotonic()+1
                while time.monotonic()<end:
                    paths=[]
                    for fd in Path(f'/proc/{p.pid}/fd').iterdir():
                        try:paths.append(os.readlink(fd))
                        except FileNotFoundError:pass
                    if str(Path(root)/'unapproved') not in paths:break
                    time.sleep(.01)
                assert str(Path(root)/'unapproved') not in paths
            finally:p.kill();p.wait(timeout=1)


def run_thermal_kernel_backpressure_checks():
    a,b=StageChannel.pair();b.setblocking(False);os.set_blocking(a.read_fd,False)
    fcntl.fcntl(b.write_fd,fcntl.F_SETPIPE_SZ,4096)
    try:
        assert not os.get_blocking(b.write_fd) and not os.get_blocking(b.read_fd)
        data=b'x'*30000;start=time.monotonic();sent=b.send(data)
        assert 0<sent<len(data) and time.monotonic()-start<.2
        try:b.send(data[sent:]);raise AssertionError('full channel accepted unbounded write')
        except BlockingIOError:pass
        received=bytearray()
        while len(received)<len(data):
            try:received.extend(os.read(a.read_fd,65536))
            except BlockingIOError:pass
            if sent<len(data):
                try:sent+=b.send(data[sent:])
                except BlockingIOError:pass
        assert bytes(received)==data
        a.close()
        try:b.send(b'x');raise AssertionError('broken peer hidden')
        except (BrokenPipeError,OSError):pass
    finally:
        a.close();b.close()
    # Independent slow writer is bounded even at 4 KiB kernel capacity.
    a,b=StageChannel.pair();fcntl.fcntl(b.write_fd,fcntl.F_SETPIPE_SZ,4096)
    code="from Modules.lvs_storage_thermal_stage import StageChannel;import sys,os,json;s=StageChannel(*map(int,sys.argv[1].split(':')));s.setblocking(False);print(json.dumps({'blocking':os.get_blocking(s.write_fd),'sent':s.send(b'x'*30000)}))"
    p=subprocess.Popen([sys.executable,'-B','-c',code,f'{b.read_fd}:{b.write_fd}'],pass_fds=(b.read_fd,b.write_fd),stdout=subprocess.PIPE,text=True)
    b.close()
    try:
        output,_=p.communicate(timeout=1);record=json.loads(output)
        assert not record['blocking'] and record['sent']==4096
    finally:
        if p.poll() is None:p.kill();p.wait(timeout=1)
        a.close()


def run_thermal_ready_flood_checks():
    with tempfile.TemporaryDirectory() as root:
        s=ThermalStageSession(stage(),{'status':'READY'},root,stage_deadline=time.monotonic()+3600)
        a,b=StageChannel.pair();a.setblocking(False);b.setblocking(False);s.channel=a
        frame=(json.dumps(dict(ready=True,lease=s.lease_id))+'\n').encode()
        try:
            b.send(frame*64);start=time.monotonic();s._channel_poll()
            assert time.monotonic()-start<.2 and s.stopping and len(s.pending)<128
            assert s.ready_seen and s.admitted  # exactly one RUN queued
            assert 'Duplicate READY' in s.fault
        finally:
            if s.channel:s.channel.close()
            b.close()
    # Nonreading/rapid READY peer alongside a real two-second primary.
    with tempfile.TemporaryDirectory() as root:
        code=r'''import os,sys,json,time
from Modules.lvs_storage_thermal_stage import StageChannel
c=StageChannel(*map(int,sys.argv[1].split(':')));b=b''
while b'\n' not in b:b+=c.recv(65536)
r=json.loads(b.split(b'\n')[0]);c.setblocking(False)
frame=(json.dumps(dict(ready=True,lease=r['stage_lease_id']))+'\n').encode()
while True:
 try:c.send(frame*64)
 except (BlockingIOError,InterruptedError):pass
 time.sleep(.01)
'''
        sessions=[]
        def factory(st,p,rd,**kw):
            obj=ThermalStageSession(st,{'status':'READY'},root,launch_args=[sys.executable,'-c',code,'{channel}'],recovery_marker=Path(root)/'intent',**kw)
            sessions.append(obj);return obj
        result,args,_=_run_primary_with_aux(None,session_factory=factory,real_clock=True,telemetry_interval=.1)
        assert 2<=result.stage_elapsed<2.8 and len(args['telemetry_times'])>=15
        assert sessions[0].process.poll() is not None and len(sessions[0].pending)<128
        assert result.stage_verdict=='pass' and not result.stage_failure_reasons


def run_thermal_recovery_authority_checks():
    from Modules import lvs_storage_thermal_recovery as r
    def contender(marker):
        code="from Modules.lvs_storage_thermal_recovery import RecoveryScope;from pathlib import Path;import sys;\ntry:s=RecoveryScope(Path(sys.argv[1])).enter();print('ENTERED',flush=True);s.close()\nexcept (OSError,ValueError):print('DENIED',flush=True)"
        return subprocess.check_output([sys.executable,'-B','-c',code,str(marker)],text=True).strip()
    for phase in ('armed','admission','cleanup','clean'):
        with tempfile.TemporaryDirectory() as root:
            marker=Path(root)/'intent';initial=RecoveryScope(marker).enter();initial.resolve(cleanup_confirmed=True);initial.close()
            scope=RecoveryScope(marker);original=r.durable_json;injected=[]
            def lose_public():
                fd=scope.fd;os.close(fd);assert os.open(r.anchor_path(marker),os.O_RDWR|os.O_CLOEXEC)==fd
                assert contender(marker)=='DENIED';injected.append(True)
            def publish(path,record):
                if phase=='armed' and record['state']=='ARMED':lose_public()
                if phase=='clean' and record['state']=='CLEAN':lose_public()
                return original(path,record)
            with patch.object(r,'durable_json',side_effect=publish):
                scope.enter()
                if phase in ('admission','cleanup'):lose_public()
                scope._authority()
                try:scope.resolve();raise AssertionError('CLEAN without certificate')
                except ValueError:pass
                assert read_state(marker)['state']=='ARMED'
                scope.resolve(cleanup_confirmed=True)
            assert injected;scope.close();assert not blocker(marker)
    # A forked Python object must not treat the inherited shared description as
    # a new recovery owner, even though flock itself is inherited across fork.
    with tempfile.TemporaryDirectory() as root:
        marker=Path(root)/'intent';scope=RecoveryScope(marker).enter()
        pid=os.fork()
        if pid==0:
            try:scope.resolve(cleanup_confirmed=True)
            except (OSError,ValueError):os._exit(0)
            os._exit(1)
        assert os.waitpid(pid,0)[1]==0
        assert read_state(marker)['state']=='ARMED' and contender(marker)=='DENIED'
        scope.resolve(cleanup_confirmed=True);scope.close()
    # Working private descriptor loss cannot release the lifetime reference.
    with tempfile.TemporaryDirectory() as root:
        marker=Path(root)/'intent';scope=RecoveryScope(marker).enter();fd=scope._pin
        os.close(fd);assert os.open(r.anchor_path(marker),os.O_RDWR|os.O_CLOEXEC)==fd
        assert contender(marker)=='DENIED'
        try:scope.resolve(cleanup_confirmed=True);raise AssertionError('replacement private description accepted')
        except (OSError,ValueError):pass
        assert read_state(marker)['state']=='ARMED'
        try:scope.close();raise AssertionError('uncertain references silently closed')
        except OSError:pass
        _release_fixture_scope(scope)
    # Explicit lost lock is rejected, never automatically reacquired.
    with tempfile.TemporaryDirectory() as root:
        marker=Path(root)/'intent';scope=RecoveryScope(marker).enter();fcntl.flock(scope._pin,fcntl.LOCK_UN)
        try:scope.resolve(cleanup_confirmed=True);raise AssertionError('lost lock accepted')
        except (OSError,ValueError):pass
        assert read_state(marker)['state']=='ARMED'
        try:scope.close();raise AssertionError('lost ownership cleanup hidden')
        except OSError:pass
        _release_fixture_scope(scope);assert blocker(marker)


def _release_fixture_scope(scope):
    # Test-only, after proving retention; all referenced files are disposable.
    from Modules.lvs_storage_thermal_recovery import _UNCERTAIN_SCOPES
    for name in ('fd','_probe','_reference','_pin'):
        fd=getattr(scope,name)
        if fd is not None:
            try:os.close(fd)
            except OSError:pass
            setattr(scope,name,None)
    if scope in _UNCERTAIN_SCOPES:_UNCERTAIN_SCOPES.remove(scope)


def run_thermal_session_binding_checks():
    with tempfile.TemporaryDirectory() as root:
        payload=deepcopy(_auxiliary_cases()['COMPLETED']);plan=deepcopy(payload['readiness'])
        teststage=stage();teststage.duration_seconds=2
        plan['configuration']=stage_config(teststage).to_dict();s=ThermalStageSession(teststage,plan,root)
        s.process=SimpleNamespace(poll=lambda:0)
        s.directory.mkdir(parents=True)
        locals_outer={}
        def accept(value):
            (s.directory/'completion.json').write_text(json.dumps(value))
            if 'authority' in locals_outer:(s.directory/'launch_ownership.json').write_text(json.dumps(locals_outer['authority']))
            s.fault='';s._read_terminal();return s.evidence
        old=accept(payload)
        assert old['auxiliary_outcome']=='ERROR' and old['session_errors']
        # Valid current execution identity, with all independently required fields.
        now=time.monotonic();s.context['started_ns']=int((now-3)*1e9)
        payload.update(execution_context=deepcopy(s.context),configuration=plan['configuration'])
        payload['devices'][0].update(pid=12345,guard_evidence=dict(payload['devices'][0]['guard_evidence'],pid=12345),started_monotonic=now-2.1,ended_monotonic=now-.1)
        payload['stage_launch_ownership']=dict(protocol='lvs-storage-thermal-stage-admission-v2',cleanup_confirmed=True,lease_identity=s.context['lease_identity'],workers=[dict(pid=12345,cleanup_confirmed=True,reaped=True,exit_code=0,phase='committed',group_ready=True,descriptor_offered=True,io_admission='committed',committed_monotonic_ns=int((now-2.2)*1e9))])
        locals_outer['authority']=deepcopy(payload['stage_launch_ownership'])
        assert accept(payload)['auxiliary_outcome']=='COMPLETED'
        changed=deepcopy(plan);changed['devices'][0].update(device_id='current-device',identity={'stable':'current-device'})
        s.plan=changed
        assert accept(payload)['auxiliary_outcome']=='ERROR'
        s.plan=plan
        replay=deepcopy(payload);replay['execution_context']['session_id']='another-session'
        assert accept(replay)['auxiliary_outcome']=='ERROR'
        replay=deepcopy(payload);replay['stage_launch_ownership']['workers'][0]['pid']=54321
        assert accept(replay)['auxiliary_outcome']=='ERROR'
        replay=deepcopy(payload);replay['configuration']=dict(plan['configuration'],intensity_percent=100)
        assert accept(replay)['auxiliary_outcome']=='ERROR'
        replay=deepcopy(payload);replay['stage_launch_ownership']['cleanup_confirmed']=False
        rejected=accept(replay)
        assert rejected['auxiliary_outcome']=='ERROR' and rejected['cleanup_confirmed'] is False
        replay=deepcopy(payload);replay['stage_launch_ownership']['workers'][0]['cleanup_confirmed']=False
        assert accept(replay)['auxiliary_outcome']=='ERROR'



def run_thermal_execution_fact_checks():
    for requested in (True,False):
        for verdict in ('BLOCKED','FAIL','INCOMPLETE','unavailable'):
            payload=deepcopy(_auxiliary_cases()['COMPLETED']);payload.update(requested=requested,verdict=verdict,execution_started=False,executed_devices=[])
            payload['devices'][0].update(state='failed',exit_code=7)
            r=normalize(payload);assert r['auxiliary_outcome']=='ERROR'
            result=summarize_run([SimpleNamespace(stage_id='s',display_name='CPU',storage_thermal_summary=r)])
            assert result['auxiliary_outcome']=='ERROR'
    for facts in (dict(read_ios=15),dict(pid=1234),dict(guard_evidence={'pid':1234}),dict(exit_code=7)):
        raw=dict(verdict='unavailable',requested=False,devices=[dict(device_id='fact',cleanup_confirmed=True,terminal_published=True,**facts)])
        assert normalize(raw)['auxiliary_outcome']=='ERROR'
    for name,payload in _auxiliary_cases().items():assert normalize(payload)['auxiliary_outcome']==name
    with tempfile.TemporaryDirectory() as root:
        payload=deepcopy(_auxiliary_cases()['COMPLETED']);payload.update(requested=False,verdict='BLOCKED',execution_started=False,executed_devices=[])
        payload['devices'][0].update(state='failed',exit_code=7)
        result=_primary_publication_fixture(Path(root),payload)
        m=json.loads((Path(root)/'run_manifest.json').read_text())
        assert result.overall_verdict=='pass' and m['storage_thermal_summary']['auxiliary_outcome']=='ERROR'
        assert not m['error_events']
