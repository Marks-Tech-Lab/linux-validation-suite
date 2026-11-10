"""Authoritative acceptance regression fixtures: no physical device access."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import json
import os
import subprocess
import sys
import tempfile
from uuid import uuid4

from Modules.lvs_storage_thermal_results import (evidence_run,register_stage,normalize,
    validate_terminal,summarize_run,reporting_error)
from Modules.lvs_storage_thermal_launch import OwnedProcess
from smoke_tests.storage_thermal_stage_checks import _auxiliary_cases,_primary_publication_fixture,_run_primary_with_aux,stage
from Modules.lvs_storage_thermal_stage import ThermalStageSession


def fixture(root,run,*,stage_id='s1',start=0,seconds=2):
    """Synthetic evidence clock; genuine primary timing is tested separately."""
    p=deepcopy(_auxiliary_cases()['COMPLETED']);d=p['devices'][0]
    context=dict(version=1,run_id=run['run_id'],session_id=uuid4().hex,stage_id=stage_id,
        run_directory=os.path.abspath(root),started_ns=int(start*1e9),deadline_ns=int((start+seconds)*1e9),lease_identity=[10,20])
    p['configuration']=dict(p['configuration'],duration_seconds=seconds)
    d.update(pid=12345,started_monotonic=start+.1,ended_monotonic=start+seconds+.1,
             configured_duration_seconds=seconds,fio_activity={'active_seconds':seconds},guard_evidence=dict(p['devices'][0]['guard_evidence'],pid=12345))
    ownership=dict(protocol='lvs-storage-thermal-stage-admission-v2',lease_identity=[10,20],cleanup_confirmed=True,
        publication_error='',revocation_error='',workers=[dict(pid=12345,phase='committed',group_ready=True,
        descriptor_offered=True,io_admission='committed',cleanup_confirmed=True,reaped=True,exit_code=0,
        committed_monotonic_ns=int((start+.05)*1e9))])
    p.update(execution_context=context,stage_launch_ownership=ownership)
    plan=deepcopy(p['readiness']);plan['configuration']=deepcopy(p['configuration'])
    observation=dict(ownership=deepcopy(ownership),observed_ns=int((start+seconds+.2)*1e9),closed_ns=int((start+seconds)*1e9))
    w=SimpleNamespace(stage_id=stage_id,display_name='CPU',started_monotonic=start,ended_monotonic=start+seconds,storage_thermal_summary=p)
    authority=SimpleNamespace(context=context,plan=plan,terminal_observation=observation)
    return p,authority,w


def accepted(p,a):
    errors=validate_terminal(p,a.plan,a.context,a.terminal_observation)
    return normalize(dict(p,session_errors=errors),readiness=a.plan),errors


def run_thermal_authoritative_duration_checks():
    with tempfile.TemporaryDirectory() as root,evidence_run(root) as run:
        p,a,w=fixture(root,run,seconds=120)
        assert accepted(p,a)[0]['auxiliary_outcome']=='COMPLETED'
        for case in ('short','future','missing_start','nan','missing_fio','false_completion','start_before_commit'):
            bad=deepcopy(p);d=bad['devices'][0]
            if case=='short':d.update(ended_monotonic=.11,fio_activity={'active_seconds':.01})
            elif case=='future':d['ended_monotonic']=1120
            elif case=='missing_start':d.pop('started_monotonic')
            elif case=='nan':d['ended_monotonic']=float('nan')
            elif case=='missing_fio':d.pop('fio_activity')
            elif case=='false_completion':d['duration_completed']=False
            else:d['started_monotonic']=-1
            result,errors=accepted(bad,a);assert result['auxiliary_outcome']=='ERROR' and errors,case
        late=deepcopy(p);late['devices'][0].update(launch_requested_monotonic=0,started_monotonic=10,ended_monotonic=120.1)
        assert accepted(late,a)[0]['auxiliary_outcome']=='COMPLETED'  # native commit precedes delayed parent observation
        short=deepcopy(p);short['configuration']['duration_seconds']=60
        short['devices'][0].update(ended_monotonic=60.1,configured_duration_seconds=60,fio_activity={'active_seconds':60})
        assert accepted(short,a)[0]['auxiliary_outcome']=='ERROR'
        short['stage_window_shortened']=True
        assert accepted(short,a)[0]['auxiliary_outcome']=='COMPLETED_WITH_WARNINGS'
        delayed=deepcopy(p);delayed['devices'][0].update(started_monotonic=10,ended_monotonic=70,configured_duration_seconds=60,fio_activity={'active_seconds':60})
        delayed['configuration']['duration_seconds']=60;delayed['stage_window_shortened']=True
        assert accepted(delayed,a)[0]['auxiliary_outcome']=='COMPLETED_WITH_WARNINGS'
        early=deepcopy(a);early.terminal_observation['closed_ns']=int(.5*1e9)
        assert accepted(p,early)[0]['auxiliary_outcome']=='ERROR'
        stopped=deepcopy(p);stopped['verdict']='INCOMPLETE';stopped['devices'][0].update(state='cancelled',exit_code=-15,duration_completed=False,ended_monotonic=1,fio_activity={'active_seconds':.9})
        stopped['stage_launch_ownership']['workers'][0]['exit_code']=-15
        sa=deepcopy(a);sa.terminal_observation['ownership']=deepcopy(stopped['stage_launch_ownership'])
        assert accepted(stopped,sa)[0]['auxiliary_outcome']=='STOPPED'
        # Actual supervised file reader, not just the pure validator.
        for mode in ('short','future','valid'):
            value=deepcopy(p)
            if mode=='short':value['devices'][0].update(ended_monotonic=.11,fio_activity={'active_seconds':.01})
            if mode=='future':value['devices'][0]['ended_monotonic']=1120
            st=stage();st.duration_seconds=120
            session=ThermalStageSession(st,a.plan,root,clock=lambda:120.2)
            session.context=deepcopy(a.context);session.process=SimpleNamespace(poll=lambda:0)
            session.directory.mkdir(parents=True)
            (session.directory/'completion.json').write_text(json.dumps(value))
            (session.directory/'launch_ownership.json').write_text(json.dumps(a.terminal_observation['ownership']))
            session._read_terminal()
            assert session.evidence['auxiliary_outcome']==('COMPLETED' if mode=='valid' else 'ERROR')
        print('  duration: 0.01/120s, deadline+1000s and impossible timestamps ERROR; full COMPLETED; shortened WARN; early cancellation STOPPED')


def run_thermal_authoritative_ownership_checks():
    with tempfile.TemporaryDirectory() as root,evidence_run(root) as run:
        p,a,w=fixture(root,run)
        for case in ('exit7','extra_failure','duplicate','missing_result','missing_exit','not_reaped','guard_pid','registry_changed'):
            bad=deepcopy(p);workers=bad['stage_launch_ownership']['workers']
            if case=='exit7':workers[0]['exit_code']=7
            elif case=='extra_failure':workers.append(dict(pid=555,launch_failed=True,exit_code=7,cleanup_confirmed=True))
            elif case=='duplicate':workers.append(deepcopy(workers[0]))
            elif case=='missing_result':bad['devices']=[]
            elif case=='missing_exit':workers[0].pop('exit_code')
            elif case=='not_reaped':workers[0]['reaped']=False
            elif case=='guard_pid':bad['devices'][0]['guard_evidence']['pid']=999
            else:workers[0]['committed_monotonic_ns']+=1
            ba=deepcopy(a)
            if case!='registry_changed':ba.terminal_observation['ownership']=deepcopy(bad['stage_launch_ownership'])
            assert accepted(bad,ba)[0]['auxiliary_outcome']=='ERROR',case
            # Same authoritative validation is applied again to whole-run evidence.
            case_window=SimpleNamespace(**vars(w));case_window.storage_thermal_summary=bad;register_stage(case_window,ba)
            assert summarize_run([case_window],run_dir=root)['auxiliary_outcome']=='ERROR'
        partial=deepcopy(p);partial['verdict']='WARN';partial['requested_devices'].append('blocked')
        partial['readiness']['devices'].append(dict(device_id='blocked',selected=True,state='blocked',identity={},reasons=['active']))
        pa=deepcopy(a);pa.plan=deepcopy(partial['readiness']);pa.plan['configuration']=deepcopy(p['configuration'])
        assert accepted(partial,pa)[0]['auxiliary_outcome']=='COMPLETED_WITH_WARNINGS'
        mixed=deepcopy(p);mixed['verdict']='FAIL'
        failed=deepcopy(mixed['devices'][0]);failed.update(device_id='second',identity={'stable':'second'},pid=6789,state='failed',exit_code=7,errors=1,guard_evidence={'pid':6789})
        mixed['devices'].append(failed);mixed['executed_devices'].append('second');mixed['requested_devices'].append('second')
        owner=deepcopy(mixed['stage_launch_ownership']['workers'][0]);owner.update(pid=6789,exit_code=7)
        mixed['stage_launch_ownership']['workers'].append(owner)
        ma=deepcopy(a);ma.plan['devices'].append(dict(device_id='second',identity=failed['identity'],selected=True,state='ready'))
        ma.terminal_observation['ownership']=deepcopy(mixed['stage_launch_ownership'])
        result,errors=accepted(mixed,ma)
        assert result['auxiliary_outcome']=='ERROR' and not errors
        assert [d['auxiliary_outcome'] for d in result['drive_outcomes']]==['COMPLETED','ERROR']
        print('  ownership: committed exit 7/device exit 0 and extra failed bootstrap ERROR at stage and run; valid partial coverage WARN')


def run_thermal_authoritative_run_checks():
    with tempfile.TemporaryDirectory() as root,evidence_run(root) as run:
        alias=Path(root)/'child'/'..'
        with evidence_run(alias) as alias_run:
            from Modules.lvs_storage_thermal_stage import ThermalStageSession
            session=ThermalStageSession(stage(),{'status':'BLOCKED'},alias)
            from Modules.lvs_storage_thermal_results import not_run
            register_stage(SimpleNamespace(storage_thermal_summary=dict(not_run('alias scope; no execution'),execution_context=session.context)),session)
            assert session.context['run_directory']==os.path.abspath(root)
        p,a,w=fixture(root,run);register_stage(w,a)
        try:register_stage(w,a);raise AssertionError('authority overwrite allowed')
        except ValueError:pass
        p2,a2,w2=fixture(root,run,stage_id='s2',start=5);register_stage(w2,a2)
        assert summarize_run([w,w2],run_dir=root)['auxiliary_outcome']=='COMPLETED'
        assert summarize_run([w,w],run_dir=root)['auxiliary_outcome']=='ERROR'
        for case in ('old_run','old_stage','changed_config','missing_context'):
            bad=deepcopy(p)
            if case=='old_run':bad['execution_context']['run_id']='PREVIOUS_RUN'
            elif case=='old_stage':bad['execution_context']['stage_id']='PREVIOUS_STAGE'
            elif case=='changed_config':bad['configuration']['intensity_percent']=99
            else:bad.pop('execution_context')
            w.storage_thermal_summary=bad
            assert summarize_run([w,w2],run_dir=root)['auxiliary_outcome']=='ERROR',case
        w.storage_thermal_summary=deepcopy(p)
        with evidence_run(root):
            assert summarize_run([w],run_dir=root)['auxiliary_outcome']=='ERROR' # same path, new run
        w.storage_thermal_summary=dict(p,failure='execution failure',verdict='FAIL')
        assert summarize_run([w,w2],run_dir=root)['auxiliary_outcome']=='ERROR'
        fallback=SimpleNamespace(stage_id='report',display_name='report',storage_thermal_summary=reporting_error('renderer',RuntimeError('failed')))
        assert normalize(fallback.storage_thermal_summary)['auxiliary_outcome']=='ERROR'
        assert summarize_run([fallback],run_dir=root)['auxiliary_outcome']=='ERROR'
        # Real publication boundary preserves primary PASS and rejects replay.
        bad=deepcopy(p);bad['execution_context']['run_id']='PREVIOUS_RUN'
        result=_primary_publication_fixture(Path(root),bad,registration=a)
        manifest=json.loads((Path(root)/'run_manifest.json').read_text())
        assert result.overall_verdict=='pass' and manifest['storage_thermal_summary']['auxiliary_outcome']=='ERROR'
        assert (Path(root)/'run_summary.txt').exists()
        # Exercise the real stage-runtime registration hook, without I/O or
        # synthetic changes to the primary timing implementation.
        with evidence_run('/not-used') as runtime:
            def session_factory(st,plan,rd,**kw):
                start=kw['stage_deadline']-st.duration_seconds
                body,auth,_=fixture(rd,runtime,start=start,seconds=2)
                return SimpleNamespace(context=auth.context,plan=auth.plan,terminal_observation=auth.terminal_observation,
                    start=lambda:None,poll=lambda:None,revoke_admission=lambda:None,live_summary=lambda:'',finish=lambda **k:body,
                    request_stop=lambda *a:None,_latch_cleanup=lambda *a:None)
            completed,_,_=_run_primary_with_aux(None,session_factory=session_factory)
            win=completed.stage_completion.stage_window
            assert summarize_run([win],run_dir='/not-used')['auxiliary_outcome']=='COMPLETED'
        print('  run binding: previous run/stage, duplicated results and unregistered evidence ERROR; two current stages COMPLETED; primary PASS publication preserved')


def run_thermal_reaped_signal_checks():
    old=OwnedProcess([sys.executable,'-c','pass']);old.wait(timeout=2)
    victim=OwnedProcess([sys.executable,'-c','import time;time.sleep(10)'])
    try:
        # Deterministic stale numeric-ID replacement. Only our disposable victim
        # could be affected; the fixed code must not issue any signal at all.
        old.pid=victim.pid
        with patch('Modules.lvs_storage_thermal_launch.os.killpg') as group,patch('Modules.lvs_storage_thermal_launch.os.kill') as leader:
            old.kill();old.terminate();assert not group.called and not leader.called
        assert victim.poll() is None
    finally:victim.kill();victim.wait(timeout=2)
    assert victim.returncode is not None
    # A foreign reaper is outside the owner API. A stable pidfd must detect the
    # loss of parent reaping authority and refuse signaling rather than use PID.
    foreign=OwnedProcess([sys.executable,'-c','pass'])
    os.waitpid(foreign.pid,0)
    with patch('Modules.lvs_storage_thermal_launch.os.killpg') as group:
        try:foreign.kill();raise AssertionError('foreign-reaped identity accepted')
        except OSError:pass
        assert not group.called
    from Modules.lvs_storage_thermal_launch import _OWNED
    _OWNED.pop(foreign.pid,None)
    if foreign.pidfd is not None:os.close(foreign.pidfd);foreign.pidfd=None
    _pidfd_kernel_regression()
    print('  signaling: reaped owner with replacement numeric PID sends no signal; live disposable owner remains cancellable')

def _pidfd_kernel_regression():
    """Exercise a real pidfd-capable installed interpreter if available."""
    code=r'''
import os,sys,json,tempfile
from unittest.mock import patch
from Modules.lvs_storage_thermal_launch import prepare,OwnedProcess
if not all((hasattr(os,'pidfd_open'),hasattr(os,'P_PIDFD'))):
 print(json.dumps(dict(supported=False)));raise SystemExit(0)
with tempfile.TemporaryDirectory() as root:
 prepare(root)
 def pair():return [OwnedProcess([sys.executable,'-c','import time;time.sleep(10)']) for _ in range(2)]
 children=pair();p,v=children;slot=p.pidfd
 if slot is None:
  for x in children:x.kill();x.wait(timeout=2)
  print(json.dumps(dict(supported=False)));raise SystemExit(0)
 original=os.dup(slot)
 try:
  os.close(slot);os.dup2(v.pidfd,slot)
  try:p.terminate();raise AssertionError('substituted pidfd authorized')
  except OSError:pass
  assert v.poll() is None
 finally:
  os.dup2(original,slot);os.close(original)
  for x in children:x.kill();x.wait(timeout=2)
 children=pair();p,v=children;slot=p.pidfd;original=os.dup(slot);real=os.waitid;changed=[]
 def swapped(*a,**k):
  r=real(*a,**k)
  if not changed:
   os.close(slot);os.dup2(v.pidfd,slot);changed.append(True)
  return r
 try:
  with patch('Modules.lvs_storage_thermal_launch.os.waitid',side_effect=swapped):p.terminate()
  assert changed and v.poll() is None
 finally:
  os.dup2(original,slot);os.close(original)
  for x in children:x.kill();x.wait(timeout=2)
 print(json.dumps(dict(supported=True,replacement_rejected=True,private_reference_retained=True,victim_survived=True)))
'''
    for candidate in dict.fromkeys((sys.executable,'/usr/bin/python3')):
        if not Path(candidate).exists():continue
        result=subprocess.run([candidate,'-B','-c',code],text=True,capture_output=True,timeout=15)
        assert result.returncode==0,result.stderr
        report=json.loads(result.stdout)
        if report.get('supported'):
            assert report['replacement_rejected'] and report['private_reference_retained'] and report['victim_survived']
            print('  kernel pidfd:',candidate,report)
            return
    print('  kernel pidfd APIs/unique identity unavailable; sole-reaper fallback exercised')
