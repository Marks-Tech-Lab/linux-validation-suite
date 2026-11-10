"""Adversarial auxiliary isolation/ownership/evidence fixtures; never block devices."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import errno
import json
import os
import signal
import subprocess
import sys
import tempfile
import time

from Modules.lvs_storage_thermal_recovery import RecoveryScope, blocker, anchor_path, read_state
from Modules.lvs_storage_thermal_stage import ThermalStageSession, StageChannel
from Modules.lvs_storage_thermal_results import normalize, summarize_run
from smoke_tests.storage_thermal_stage_checks import stage, _auxiliary_cases, _run_primary_with_aux, _primary_publication_fixture


def run_thermal_adversarial_monitor_isolation_checks():
    """Reproduce blocked read/publication/persistence without delaying real telemetry."""
    for operation in ('read', 'publication', 'recovery', 'repeated_read'):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root);sessions=[]
            code=r'''
import json,os,sys,time,signal
from pathlib import Path
signal.signal(signal.SIGTERM,lambda *_:None)  # blocked Python I/O can survive TERM
r,w=map(int,sys.argv[1].split(':'));b=b''
while b'\n' not in b:b+=os.read(r,65536)
request=json.loads(b.split(b'\n')[0]);operation=sys.argv[2]
# Inject storage latency only in the disposable supervised initializer.
if operation in ('read','repeated_read'):
    original=Path.read_text
    calls=0
    def delayed(self,*a,**k):
        global calls
        calls+=1;Path(sys.argv[3]+'.attempts').write_text(str(calls))
        time.sleep(.6 if operation=='repeated_read' else 3)
        return original(self,*a,**k)
    Path.read_text=delayed
    while True:
        Path(sys.argv[3]).read_text()
elif operation=='publication':
    from Modules.lvs_profile_report_artifacts import atomic_preflight_json
    def delayed(*a):time.sleep(3);atomic_preflight_json(*a)
    delayed(Path(sys.argv[3]),{'fixture':True})
else:
    from Modules.lvs_storage_thermal_recovery import RecoveryScope
    import Modules.lvs_storage_thermal_recovery as recovery
    original=recovery.durable_json
    def delayed(*a):time.sleep(3);original(*a)
    recovery.durable_json=delayed
    scope=RecoveryScope(Path(sys.argv[3]));scope.enter()
'''
            (root/'fixture').write_text('{}')
            def factory(s,plan,run_dir,**kw):
                def popen(argv,**options):
                    return subprocess.Popen([sys.executable,'-B','-c',code,argv[-1],operation,str(root/'fixture' if operation!='recovery' else root/'recovery')],**options)
                session=ThermalStageSession(s,{'status':'READY'},root,launch_args=[sys.executable,'-B','-c',code,'{channel}',operation,str(root/'fixture' if operation!='recovery' else root/'recovery')],recovery_marker=root/'recovery',**kw)
                sessions.append(session);return session
            # Any accidental primary-path metadata/read/publication call fails.
            with patch.object(Path,'read_text',side_effect=AssertionError('primary filesystem read')),patch('Modules.lvs_storage_thermal_stage.recovery_blocker',side_effect=AssertionError('primary recovery I/O')):
                result,args,calls=_run_primary_with_aux(None,session_factory=factory,real_clock=True)
            assert 2<=result.stage_elapsed<2.8,(operation,result.stage_elapsed)
            assert len(args['telemetry_times'])>=2,args['telemetry_times']
            assert result.stage_verdict=='pass' and not result.stage_failure_reasons
            assert sessions[0].process.poll() is not None
            assert sessions[0].last_live is None  # no fabricated auxiliary observations
            if operation=='repeated_read':assert int((root/'fixture.attempts').read_text())>=2
            if operation=='recovery':
                assert result.stage_completion.stage_window.storage_thermal_summary['persistent_recovery_required']
            print('  monitor isolation',operation,round(result.stage_elapsed,4),args['telemetry_times'])
    # Cancellation of blocked evidence I/O remains bounded and admits no storage.
    with tempfile.TemporaryDirectory() as root:
        root=Path(root);sessions=[]
        def factory(s,plan,run_dir,**kw):
            def popen(argv,**options):
                return subprocess.Popen([sys.executable,'-B','-c',
                    'import time,signal;from pathlib import Path;signal.signal(signal.SIGTERM,lambda *_:None);'
                    'Path.read_text=lambda self:(time.sleep(10),\"unavailable\")[1];Path(\"disposable observation\").read_text()'],**options)
            session=ThermalStageSession(s,{'status':'READY'},root,launch_args=[sys.executable,'-B','-c','import time;time.sleep(10)'],recovery_marker=root/'intent',**kw);sessions.append(session);return session
        begin=time.monotonic()
        result,args,_=_run_primary_with_aux(None,session_factory=factory,real_clock=True,telemetry_interval=.1,cancel_check=lambda:time.monotonic()-begin>.3)
        assert result.stage_aborted and result.stage_elapsed<1 and len(args['telemetry_times'])>=2
        assert sessions[0].process.poll() is not None and not sessions[0].admitted


def run_thermal_snapshot_failure_checks():
    with tempfile.TemporaryDirectory() as root:
        s=ThermalStageSession(stage(),{'status':'READY'},root,recovery_marker=Path(root)/'intent')
        parent,peer=StageChannel.pair();parent.setblocking(False);s.channel=parent
        s.process=SimpleNamespace(poll=lambda:None,send_signal=lambda sig:None,pid=99999999)
        try:
            message={'lease':s.lease_id,'snapshot':dict(monotonic=time.monotonic()-10,devices=[dict(device_id='fixture',state='running')])}
            peer.sendall((json.dumps(message)+'\n').encode());s.poll()
            assert 'STALE' in s.live_summary() and len(s.live_summary())<=512
            peer.sendall(b'{invalid}\n');s.poll();assert s.stopping and s.fault
        finally:
            peer.close()
            if s.channel:s.channel.close()
    # Established evidence policy: no sample => no validated sustained performance.
    from Modules.lvs_analysis_quality import evaluate_analysis_evidence,telemetry_recommendation_suppression_reason
    window=SimpleNamespace(analysis_intent='sustained',analysis_minimum_usable_seconds=2,
        started_monotonic=0,ended_monotonic=2,trim_start_seconds=0,trim_end_seconds=0,verdict='pass')
    evidence=evaluate_analysis_evidence(window,[],1)
    assert evidence['quality']=='insufficient' and evidence['usable_sample_count']==0
    assert telemetry_recommendation_suppression_reason(evidence)
    window.analysis_intent='threshold'
    threshold=evaluate_analysis_evidence(window,[],1)
    assert threshold['quality']=='insufficient'
    assert 'row count' in telemetry_recommendation_suppression_reason(threshold)


def run_thermal_durable_intent_checks():
    from Modules import lvs_storage_thermal_recovery as recovery
    with tempfile.TemporaryDirectory() as root:
        marker=Path(root)/'intent';scope=RecoveryScope(marker)
        with patch.object(recovery,'durable_json',side_effect=OSError(errno.ENOSPC,'injected full filesystem')):
            try:scope.enter();raise AssertionError('admission allowed without durable intent')
            except OSError:pass
        assert anchor_path(marker).exists() and not marker.exists()
        assert _fresh_blocker(marker)
    with tempfile.TemporaryDirectory() as root:
        marker=Path(root)/'intent';scope=RecoveryScope(marker).enter()
        assert _fresh_blocker(marker)  # real independent process conflicts on flock
        with patch.object(recovery,'durable_json',side_effect=OSError(errno.ENOSPC,'injected finalization failure')):
            try:scope.resolve(cleanup_confirmed=True);raise AssertionError('failed finalization concealed')
            except OSError:pass
        scope.close();assert read_state(marker)['state']=='ARMED' and _fresh_blocker(marker)
    with tempfile.TemporaryDirectory() as root:
        marker=Path(root)/'intent';scope=RecoveryScope(marker).enter();scope.resolve(cleanup_confirmed=True);scope.close()
        assert not _fresh_blocker(marker)
        next_scope=RecoveryScope(marker).enter();next_scope.resolve(cleanup_confirmed=True);next_scope.close()
        # Missing state, corrupt state, orphan state all fail closed.
        saved=marker.read_bytes();marker.unlink();assert _fresh_blocker(marker)
        marker.write_text('{broken');assert _fresh_blocker(marker)
        marker.write_bytes(saved);anchor_path(marker).unlink();assert _fresh_blocker(marker)
    with tempfile.TemporaryDirectory() as root:
        marker=Path(root)/'intent';scope=RecoveryScope(marker).enter();scope.resolve(cleanup_confirmed=True);scope.close()
        with patch.object(recovery.os,'open',side_effect=PermissionError('fixture denied')):assert blocker(marker)
        if os.geteuid()!=0:
            marker.chmod(0)
            try:assert _fresh_blocker(marker)
            finally:marker.chmod(0o600)
        state=json.loads(marker.read_text());state['cleanup_confirmed']=False;marker.write_text(json.dumps(state));assert _fresh_blocker(marker)

    # Integrate initial persistence failure with the actual authoritative runner:
    # no descriptor open or native worker may be reached.
    from smoke_tests.storage_thermal_runner_checks import RunnerFixture
    from smoke_tests.storage_thermal_stage_checks import fixture_stage_worker
    from Modules.lvs_storage_thermal_stage import stage_config,decision_key
    from Modules.lvs_storage_thermal_launch import provenance as owned_provenance
    with tempfile.TemporaryDirectory() as root:
        root=Path(root);fixture=RunnerFixture(root);s=stage();s.duration_seconds=1
        plan=fixture.plan(stage_config(s));plan['backend']=dict(plan['backend'],stage_admission_protocol='v2',owned_launcher=owned_provenance())
        plan.update(requires_consent=False,decision_key=decision_key(plan))
        directory=root/'stage';directory.mkdir()
        (directory/'request.json').write_text(json.dumps(dict(plan,supervisor_parent_pid=os.getppid(),recovery_marker=str(root/'intent'))))
        with patch('Modules.lvs_storage_thermal_stage.default_runner',return_value=fixture.runner),patch('Modules.lvs_storage_thermal_runner.capability',return_value=fixture.backend),patch.object(recovery,'durable_json',side_effect=OSError(errno.ENOSPC,'full filesystem')),fixture.context():
            assert fixture_stage_worker(directory,fixture)==1
        assert not fixture.children and _fresh_blocker(root/'intent')


def _fresh_blocker(marker):
    code='from pathlib import Path;from Modules.lvs_storage_thermal_recovery import blocker;import sys;print(blocker(Path(sys.argv[1])))'
    return subprocess.check_output([sys.executable,'-B','-c',code,str(marker)],text=True).strip()


def run_thermal_recovery_crash_and_concurrency_checks():
    with tempfile.TemporaryDirectory() as root:
        marker=Path(root)/'intent'
        code=r'''
from pathlib import Path
import sys,time
from Modules.lvs_storage_thermal_recovery import RecoveryScope
scope=RecoveryScope(Path(sys.argv[1])).enter()
print('ADMITTED',flush=True)
time.sleep(30)
'''
        owner=subprocess.Popen([sys.executable,'-B','-c',code,str(marker)],stdout=subprocess.PIPE,text=True)
        try:
            assert owner.stdout.readline().strip()=='ADMITTED'
            assert _fresh_blocker(marker)
            attempt='from pathlib import Path;import sys;from Modules.lvs_storage_thermal_recovery import RecoveryScope;RecoveryScope(Path(sys.argv[1])).enter()'
            contender=subprocess.run([sys.executable,'-B','-c',attempt,str(marker)],capture_output=True,text=True,timeout=3)
            assert contender.returncode!=0
            owner.kill();owner.wait(timeout=3)
            assert _fresh_blocker(marker)  # lock released, ARMED obligation survives
            assert read_state(marker)['state']=='ARMED'
        finally:
            if owner.poll() is None:owner.kill();owner.wait(timeout=3)
            owner.stdout.close()

    with tempfile.TemporaryDirectory() as root:
        marker=Path(root)/'native-intent'
        code=r'''from pathlib import Path
import sys,time
from Modules.lvs_storage_thermal_recovery import RecoveryScope
from smoke_tests.storage_thermal_foundation_checks import compile_guard
from smoke_tests.storage_thermal_stage_checks import NativeAdmissionFixture
root=Path(sys.argv[1]);scope=RecoveryScope(root/'native-intent').enter()
guard=compile_guard(root)
f=NativeAdmissionFixture(root/'native',guard)
p=f.launch();p.wait(timeout=3)
assert any(r['io_admission']=='committed' for r in f.launches.owned)
print('NATIVE_ADMITTED',flush=True)
time.sleep(30)
'''
        owner=subprocess.Popen([sys.executable,'-B','-c',code,root],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            line=owner.stdout.readline().strip()
            assert line=='NATIVE_ADMITTED',(line,owner.stderr.read() if owner.poll() is not None else '')
            owner.kill();owner.wait(timeout=3)
            assert _fresh_blocker(marker) and read_state(marker)['state']=='ARMED'
        finally:
            if owner.poll() is None:owner.kill();owner.wait(timeout=3)
            owner.stdout.close();owner.stderr.close()


def run_thermal_strict_terminal_checks():
    mutations=[lambda p:p['devices'][0].update(state='failed'),lambda p:p['devices'][0].update(read_ios=0,read_bytes=0),
        lambda p:p['devices'][0].update(duration_completed=False),lambda p:p['devices'][0].update(guard_confirmed=False),
        lambda p:p['devices'][0].update(identity_unchanged=False),lambda p:p['devices'][0].update(provenance_confirmed=False),
        lambda p:p.update(executed_devices=[]),lambda p:p.update(executed_devices=['other']),
        lambda p:p.update(requested_devices=['other']),lambda p:p['devices'].append(deepcopy(p['devices'][0])),
        lambda p:p.update(requested=False),lambda p:p.update(execution_started=False),
        lambda p:p['devices'][0].update(terminal_published=False),lambda p:p['devices'][0].update(cleanup_confirmed=False)]
    for change in mutations:
        p=deepcopy(_auxiliary_cases()['COMPLETED']);change(p);result=normalize(p)
        assert result['auxiliary_outcome']=='ERROR' and result['verdict']=='PASS'
        assert result['evidence_errors']
        summary=summarize_run([SimpleNamespace(stage_id='s',display_name='CPU',storage_thermal_summary=p)])
        assert summary['auxiliary_outcome']=='ERROR'
    for outcome,payload in _auxiliary_cases().items():assert normalize(payload)['auxiliary_outcome']==outcome
    partial=deepcopy(_auxiliary_cases()['COMPLETED']);partial['verdict']='WARN'
    partial['requested_devices'].append('blocked');partial['readiness']['devices'].append(dict(device_id='blocked',identity={},state='blocked',selected=True,reasons=['active']))
    assert normalize(partial)['auxiliary_outcome']=='COMPLETED_WITH_WARNINGS'
    skipped=deepcopy(partial);skipped['readiness']['devices'][-1].update(state='skipped',reasons=[])
    assert normalize(skipped)['auxiliary_outcome']=='COMPLETED_WITH_WARNINGS'
    with tempfile.TemporaryDirectory() as root:
        payload=deepcopy(_auxiliary_cases()['COMPLETED']);payload['devices'][0].update(read_ios=0)
        result=_primary_publication_fixture(Path(root),payload)
        manifest=json.loads((Path(root)/'run_manifest.json').read_text())
        assert result.overall_verdict=='pass' and manifest['storage_thermal_summary']['auxiliary_outcome']=='ERROR'
        assert not manifest['error_events'] and (Path(root)/'run_summary.txt').exists()


def run_thermal_auxiliary_publication_latency_checks():
    """A hung auxiliary-only export cannot prevent primary artifact publication."""
    from Modules.lvs_storage_thermal_recovery import _IO_UNCONFIRMED
    from Modules.lvs_storage_thermal_launch import OwnedProcess
    children=[]
    def popen(argv,**options):
        if '--publish-summary' in argv:options['delay_ms']=3000
        child=OwnedProcess(argv,**options);children.append(child);return child
    with tempfile.TemporaryDirectory() as root,patch('Modules.lvs_storage_thermal_launch.OwnedProcess',side_effect=popen):
        begin=time.monotonic();result=_primary_publication_fixture(Path(root),_auxiliary_cases()['COMPLETED'])
        elapsed=time.monotonic()-begin
        manifest=json.loads((Path(root)/'run_manifest.json').read_text())
        assert 2<=elapsed<3.5,elapsed
        assert result.overall_verdict=='pass' and (Path(root)/'run_summary.txt').exists()
        assert manifest['storage_thermal_summary']['auxiliary_outcome']=='ERROR'
        assert not manifest['storage_thermal_summary']['publication_integrity']
        assert not manifest['error_events'] and children and all(p.poll() is not None for p in children)
        assert not _IO_UNCONFIRMED

    # Explicit ownership also survives a failed signal/reap, using no real child.
    from Modules.lvs_storage_thermal_recovery import evidence_operation
    class Unreapable:
        returncode=None
        def communicate(self,*a,**k):raise subprocess.TimeoutExpired('evidence fixture',2)
        def kill(self):raise PermissionError('injected signal denial')
        def poll(self):return None
    child=Unreapable()
    with patch('Modules.lvs_storage_thermal_launch.OwnedProcess',return_value=child):
        try:evidence_operation('--publish-json','/not-used',payload={})
        except subprocess.TimeoutExpired:pass
        else:raise AssertionError('unconfirmed helper cleanup hidden')
    try:
        assert child in _IO_UNCONFIRMED
        try:evidence_operation('--publish-json','/not-used',payload={})
        except OSError:pass
        else:raise AssertionError('new helper launched while prior cleanup unknown')
    finally:_IO_UNCONFIRMED.remove(child)


def run_thermal_shared_entrypoint_scope_checks():
    from lvs_storage_thermal_assist import ThermalMenu
    from Modules.lvs_storage_thermal import ThermalConfig
    from smoke_tests.storage_thermal_runner_checks import RunnerFixture
    with tempfile.TemporaryDirectory() as root:
        root=Path(root);fixture=RunnerFixture(root);marker=root/'intent'
        owner=RecoveryScope(marker).enter()
        menu=ThermalMenu(fixture.runner,ThermalConfig(duration_seconds=1),root/'out',
            screens=SimpleNamespace(write=lambda *a:None,confirm=lambda *a:True),recovery_marker=marker)
        try:
            with patch('Modules.lvs_storage_thermal_runner.capability',return_value=fixture.backend):
                try:menu.start();raise AssertionError('standalone bypassed occupied profile scope')
                except BlockingIOError:pass
            assert not fixture.children
        finally:owner.resolve(cleanup_confirmed=True);owner.close()
