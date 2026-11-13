"""Shared profile integration fixtures. No host block devices or thermal workers."""
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import datetime
import inspect
import json
import os
import signal
import sys
import subprocess
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from Modules.lvs_profile_models import StageConfig, StageModules, ModuleCpu, ModuleStorageThermal, ValidationProfile, stage_execution_mode
from Modules.lvs_profile_validation import ProfileValidator
from Modules.lvs_profile_loader import ProfileLoader
from Modules.lvs_profile_editor import ProfileEditor
from Modules.lvs_profile_edit_controller import ProfileEditController
from Modules.lvs_service_models import ProfileEditState
from Modules.lvs_stage_configuration import apply_stage_setting, stage_settings
from Modules.lvs_storage_thermal_stage import (stage_config, preview, decision_key, consent_requests,
    approve_coverage, consent_valid, apply_profile_decisions, ThermalStageSession, worker, record_unmonitored_decision, StageLease, StageLeaseExpired, LeaseTargets, StageChannel, SharedAdmission, StageLaunches, inspect_stage, ofd_lock)
from smoke_tests.storage_thermal_runner_checks import RunnerFixture

from Modules.lvs_storage_thermal_launch import prepare as prepare_owned_launch, provenance as owned_provenance
_LAUNCH_FIXTURE=tempfile.TemporaryDirectory(prefix='lvs-owned-launch-tests-')
prepare_owned_launch(_LAUNCH_FIXTURE.name)

ROOT=Path(__file__).resolve().parents[1]
PROFILES={'PL Validation.json':4,'PL Validation 4hr.json':4,'PL Validation 6hr.json':4,
          'PL Validation 12hr.json':8,'PL Validation 24hr.json':16,'QA System Test Short v2.json':4,'Power Test 5hr.json':1}


def stage():
    return StageConfig('s1','CPU',120,modules=StageModules(cpu=ModuleCpu(enabled=True),storage_thermal=ModuleStorageThermal(enabled=True)))


def blocked(stage_arg=None):
    with tempfile.TemporaryDirectory() as root:
        f=RunnerFixture(root);f.rows[0].update(eligible=False,reasons=['active system disk'])
        with patch('Modules.lvs_storage_thermal_runner.capability',return_value=f.backend):
            return preview(stage_arg or stage(),f.runner)


def unmonitored(s=None):
    s=s or stage();s.modules.storage_thermal.monitoring='approved_unmonitored'
    with tempfile.TemporaryDirectory() as root:
        f=RunnerFixture(root);f.temp=None
        with patch('Modules.lvs_storage_thermal_runner.capability',return_value=f.backend):return preview(s,f.runner)


def run_thermal_stage_settings_checks():
    s=stage();s.modules.storage_thermal.enabled=False
    edit=ProfileEditState(Path('fixture.json'),ValidationProfile('fixture',stages=[s]),['CPU'])
    controller=ProfileEditController(ProfileEditor());validator=ProfileValidator()
    def change(key,value):return apply_stage_setting(edit,0,key,value,controller,validator)
    assert [v.key for v in stage_settings(s,controller.profile_editor) if v.key.startswith('thermal_')]==['thermal_enabled']
    change('thermal_enabled','true');change('thermal_intensity_percent','40');change('thermal_system_intensity_percent','20')
    change('thermal_device_ids','["wwn:one"]');change('thermal_selection','individual')
    change('thermal_per_device_percent','{"wwn:one": 30}')
    change('thermal_rates','{"rate_mode":"advanced","iops":10,"bandwidth_bytes_per_second":1048576}')
    previous=asdict(edit.profile)
    for key,value in [('thermal_block_size','123'),('thermal_enabled','"false"'),('thermal_intensity_percent','101'),('thermal_scheduling','fifo')]:
        try:change(key,value)
        except ValueError:pass
        else:raise AssertionError('invalid thermal setting accepted')
        assert asdict(edit.profile)==previous
    change('thermal_enabled','false')
    assert not edit.profile.stages[0].modules.storage_thermal.enabled
    assert stage_config(edit.profile.stages[0]).duration_seconds==120


def run_thermal_stage_persistence_checks():
    s=stage();profile=ValidationProfile('fixture',stages=[s]);plan=blocked(s)
    approve_coverage(profile,[plan])
    payload=ProfileLoader.profile_payload(profile,['CPU'])
    assert '_thermal_consents' not in payload and 'coverage_consent' not in json.dumps(payload)
    with tempfile.TemporaryDirectory() as root:
        path=Path(root)/'fixture.json';path.write_text(json.dumps(payload))
        restored=ProfileLoader(Path(root)).load_profile(path)
        assert asdict(restored.stages[0].modules.storage_thermal)==asdict(s.modules.storage_thermal)
        copied=ProfileEditor().copy_profile(restored,'copy',[0])
        assert copied.stages[0].modules.storage_thermal.enabled
        copied.stages[0].modules.storage_thermal.intensity_percent=10
        assert restored.stages[0].modules.storage_thermal.intensity_percent==50
    from Modules.lvs_run_execution_context import build_profile_run_context
    from Modules.lvs_run_metadata import RunMetadata
    original=deepcopy(profile)
    profile.stages[0].modules.storage_thermal.enabled=False
    setup=SimpleNamespace(profile=profile,labels=['CPU'],original_profile=original,original_labels=['CPU'])
    context=build_profile_run_context(Path('fixture.json'),RunMetadata(),setup,
        settings=SimpleNamespace(suite_department='QA'),profile_loader=ProfileLoader,
        default_run_metadata=lambda p:RunMetadata())
    assert context.profile._run_original_profile['stages'][0]['modules']['storage_thermal']['enabled']
    assert not context.profile.stages[0].modules.storage_thermal.enabled
    assert '_run_original_profile' not in ProfileLoader.profile_payload(context.profile)
    s.modules.storage_thermal.enabled=True
    assert stage_execution_mode(s)=='duration'
    s.modules.storage_benchmark.enabled=True
    assert stage_execution_mode(s)=='mixed'
    assert ProfileValidator().validate(ValidationProfile('mixed',stages=[s]),['CPU'])['errors']


def run_thermal_stage_consent_checks():
    s=stage();plan=blocked(s);profile=ValidationProfile('fixture',stages=[s,deepcopy(s)])
    plans=[dict(enabled=True,issues=[],warnings=[],runnable=True,storage_thermal=deepcopy(plan)) for _ in range(2)]
    apply_profile_decisions(profile,plans)
    assert not consent_requests(dict(plan=plans),profile)
    assert all(p['runnable'] and not p['issues'] and not p['warnings'] for p in plans)
    assert all(p['storage_thermal']['auxiliary_prediction']=='NOT_RUN' for p in plans)
    plan=unmonitored(s);profile=ValidationProfile('fixture',stages=[s,deepcopy(s)])
    plans=[dict(enabled=True,issues=[],warnings=[],runnable=True,storage_thermal=deepcopy(plan)) for _ in range(2)]
    apply_profile_decisions(profile,plans);report=dict(plan=plans)
    assert len(consent_requests(report,profile))==2 and all(p['runnable'] for p in plans)
    approve_coverage(profile,consent_requests(report,profile));plan=plans[0]['storage_thermal']
    assert consent_valid(plan,profile._thermal_consents) and not consent_requests(report,profile)
    for field,value in [('intensity_percent',25),('duration_seconds',3600),('monitoring','required')]:
        changed=deepcopy(plan);changed['configuration'][field]=value
        assert not consent_valid(changed,profile._thermal_consents)
    changed=deepcopy(plan);changed['devices'][0]['identity']['size_bytes']=1
    assert not consent_valid(changed,profile._thermal_consents)
    unselected=deepcopy(plan);unselected['devices'].append(dict(device_id='usb:excluded',selected=False,identity={},state='discovered'))
    assert decision_key(unselected)==decision_key(plan)
    records=deepcopy(profile._thermal_consents)
    for r in records.values():r['expires_unix']=time.time()-1
    assert not consent_valid(plan,records)
    profile.stages.append(deepcopy(s))
    changed=[dict(enabled=True,issues=[],warnings=[],runnable=True,storage_thermal=deepcopy(plan))]
    apply_profile_decisions(profile,changed)
    assert changed[0]['runnable'] and not changed[0]['storage_thermal']['execution_permitted']


def run_thermal_stage_blocked_session_checks():
    s=stage();plan=blocked(s)
    with tempfile.TemporaryDirectory() as root, patch('Modules.lvs_storage_thermal_stage.preview',return_value=plan):
        session=ThermalStageSession(s,plan,root,recovery_marker=Path(root)/'recovery.json',popen=lambda *a,**k:(_ for _ in ()).throw(AssertionError('blocked worker launched')))
        session.start();result=session.finish()
        assert result['auxiliary_outcome']=='NOT_RUN' and not result['executed_devices']
        assert json.loads((session.directory/'adapter_result.json').read_text())['cleanup_confirmed']
    changed=deepcopy(plan);changed['devices'][0]['reasons']=['topology changed']
    with tempfile.TemporaryDirectory() as root,patch('Modules.lvs_storage_thermal_stage.preview',return_value=changed):
        session=ThermalStageSession(s,plan,root,recovery_marker=Path(root)/'recovery.json')
        session.start();assert session.finish()['auxiliary_outcome']=='NOT_RUN'


def fixture_stage_worker(directory, fixture):
    """Mock only the OS admission transport in legacy supervisor unit fixtures.

    The real cross-process/native transport has dedicated regressions below.
    """
    class FixtureLaunches:
        def __init__(self,runner,*args):
            self.original=runner.popen;self.cleanup_confirmed=True;self.publication_error='';self.owned=[]
        def authority(self,p):return p
        def launch(self,*args,**kwargs):
            p=self.original(*args,**kwargs)
            self.owned.append(dict(process=p,pid=p.pid,phase='committed',group_ready=True,
                descriptor_offered=True,io_admission='committed',committed_monotonic_ns=int(fixture.clock()*1e9)))
            return p
        def finish(self):
            for row in self.owned:
                code=row['process'].poll();row.update(exit_code=code,reaped=code is not None,cleanup_confirmed=code is not None)
        def snapshot(self):return dict(protocol='lvs-storage-thermal-stage-admission-v2',test_fixture=True,workers=[{k:v for k,v in row.items() if k!='process'} for row in self.owned],cleanup_confirmed=True)
    with patch('Modules.lvs_storage_thermal_stage.StageLaunches',FixtureLaunches):
        return worker(directory,gate=lambda:True,lease=StageLease(100,os.getppid(),clock=fixture.clock))


def run_thermal_stage_worker_reuse_checks():
    # The adapter delegates to the real supervisor using only mock temp files.
    with tempfile.TemporaryDirectory() as root:
        f=RunnerFixture(root);s=stage();s.duration_seconds=1
        plan=f.plan(stage_config(s));plan['backend']=dict(plan['backend'],stage_admission_protocol='v2',owned_launcher=owned_provenance());plan.update(requires_consent=False,decision_key=decision_key(plan))
        directory=Path(root)/'stage';directory.mkdir();(directory/'request.json').write_text(json.dumps(dict(plan,supervisor_parent_pid=os.getppid(),recovery_marker=str(Path(root)/"recovery.json"))))
        with patch('Modules.lvs_storage_thermal_stage.default_runner',return_value=f.runner),patch('Modules.lvs_storage_thermal_runner.capability',return_value=f.backend),f.context():
            assert fixture_stage_worker(directory,f)==0
        result=json.loads((directory/'completion.json').read_text())
        assert result['verdict']=='PASS' and result['devices'][0]['cleanup_confirmed']
        assert result['configuration']['duration_seconds']==1
        assert (directory/'stage_monitoring.jsonl').is_file()
    with tempfile.TemporaryDirectory() as root:
        f=RunnerFixture(root);s=stage();s.duration_seconds=1
        c=replace(stage_config(s),monitoring='approved_unmonitored',unmonitored_approval='pending')
        from Modules.lvs_storage_thermal_runner import approve_unmonitored
        c=approve_unmonitored(c,[f.rows[0]['device_id']],'fixture approval')
        plan=f.plan(c);plan['backend']=dict(plan['backend'],stage_admission_protocol='v2',owned_launcher=owned_provenance());plan.update(requires_consent=True,decision_key=decision_key(plan))
        directory=Path(root)/'unapproved';directory.mkdir();(directory/'request.json').write_text(json.dumps(dict(plan,supervisor_parent_pid=os.getppid(),recovery_marker=str(Path(root)/"recovery.json"))))
        with patch('Modules.lvs_storage_thermal_stage.default_runner',return_value=f.runner):
            assert fixture_stage_worker(directory,f)==1
        assert not f.children
        plan['supervisor_parent_pid']=999999999
        plan['recovery_marker']=str(Path(root)/'recovery.json')
        (directory/'request.json').write_text(json.dumps(plan))
        with patch('Modules.lvs_storage_thermal_stage.default_runner',return_value=f.runner):
            assert fixture_stage_worker(directory,f)==1
        assert 'parent identity' in json.loads((directory/'completion.json').read_text())['reasons'][0]
        assert not f.children
    with tempfile.TemporaryDirectory() as root:
        f=RunnerFixture(root,2);s=stage();s.duration_seconds=1
        f.rows[1].update(eligible=False,reasons=['active system disk'])
        plan=f.plan(stage_config(s));plan['backend']=dict(plan['backend'],stage_admission_protocol='v2',owned_launcher=owned_provenance());plan.update(requires_consent=False,decision_key=decision_key(plan))
        directory=Path(root)/'partial';directory.mkdir()
        (directory/'request.json').write_text(json.dumps(dict(plan,supervisor_parent_pid=os.getppid(),recovery_marker=str(Path(root)/'recovery.json'))))
        with patch('Modules.lvs_storage_thermal_stage.default_runner',return_value=f.runner),patch('Modules.lvs_storage_thermal_runner.capability',return_value=f.backend),f.context():
            assert fixture_stage_worker(directory,f)==0
        from Modules.lvs_storage_thermal_results import normalize
        result=normalize(json.loads((directory/'completion.json').read_text()),readiness=plan)
        assert result['auxiliary_outcome']=='COMPLETED_WITH_WARNINGS' and len(result['coverage']['exercised'])==1
        assert len(result['coverage']['excluded'])==1


def run_thermal_stage_session_cleanup_checks():
    s=stage();plan=blocked(s);plan.update(status='READY',requires_consent=False)
    # Popen here is a fake supervisor only, never fio or an actual block opener.
    class Process:
        pid=200000001
        returncode=None
        def __init__(self):self.signals=[]
        def poll(self):return self.returncode
        def send_signal(self,sig):self.signals.append(sig)
        def group_cleanup_confirmed(self):return True
        def kill(self):self.send_signal(signal.SIGKILL)
        def wait(self,timeout=None):self.returncode=1;return 1
    with tempfile.TemporaryDirectory() as root,patch('Modules.lvs_storage_thermal_stage.preview',return_value=plan):
        proc=Process();session=ThermalStageSession(s,plan,root,recovery_marker=Path(root)/'recovery.json',signal_group=lambda pid,sig:proc.send_signal(sig),group_reaped=lambda pid:True)
        with patch('Modules.lvs_storage_thermal_launch.OwnedProcess',return_value=proc):session.start()
        result=session.finish(cancelled=True)
        assert proc.signals and result['auxiliary_outcome']=='NOT_RUN'
    class Stuck(Process):
        def group_cleanup_confirmed(self):return False
        def wait(self,timeout=None):raise subprocess.TimeoutExpired('fixture',timeout)
    with tempfile.TemporaryDirectory() as root,patch('Modules.lvs_storage_thermal_stage.preview',return_value=plan):
        session=ThermalStageSession(s,plan,root,recovery_marker=Path(root)/'recovery.json',signal_group=lambda *a:None,group_reaped=lambda pid:False)
        with patch('Modules.lvs_storage_thermal_launch.OwnedProcess',return_value=Stuck()):session.start()
        result=session.finish()
        assert result['auxiliary_outcome']=='ERROR' and not result['cleanup_confirmed']
        marker=Path(root)/'recovery.json';assert marker.exists()
        from Modules.lvs_storage_thermal_stage import recovery_blocker,_UNCONFIRMED
        assert recovery_blocker(marker)
        _UNCONFIRMED.pop(str(marker),None)
        assert recovery_blocker(marker)  # fresh process does not need Python latch


def run_thermal_stage_safety_propagation_checks():
    from Modules.lvs_stage_live_loop import run_stage_live_loop
    from smoke_tests.storage_thermal_runner_checks import Clock
    clock=Clock();s=stage();s.duration_seconds=2
    args={}
    for key,param in inspect.signature(run_stage_live_loop).parameters.items():
        if param.default is inspect.Parameter.empty:args[key]=lambda *a,**k:None
    args.update(stage=s,display_name='CPU',stage_started_iso='fixture',stage_start=0,stage_processes=[],stage_error_events=[],stage_failure_reasons=[],
        stage_verdict='pass',stage_aborted=False,stage_abort_reason='',abort_on_worker_error=False,abort_on_fail_threshold=False,
        gpu_retune_events=[],progress_interval_seconds=30,telemetry_interval_seconds=1,now_local_iso=lambda:'now',monotonic=clock,sleep=clock.sleep,
        poll_stage_process_failures=lambda *a:[],stage_sensor_events=lambda *a:[],stage_target_gpu_progress_summary=lambda *a:'',thermal_poll=lambda:'local drive stop')
    result=run_stage_live_loop(**args)
    assert not result.stage_aborted and result.stage_verdict=='pass' and not args['stage_error_events']
    args['thermal_poll']=lambda:dict(system_wide_safety_emergency=True,reason='verified platform emergency',evidence={'provider':'fixture_platform_safety','critical':True})
    result=run_stage_live_loop(**args)
    assert result.stage_aborted and result.stage_verdict=='aborted' and result.system_safety_interruption
    assert not args['stage_failure_reasons'] and all(e['severity']!='error' for e in args['stage_error_events'])
    from Modules.lvs_stage_postprocess import apply_completed_stage_bookkeeping
    window=SimpleNamespace(verdict='pass',system_faults=[],storage_thermal_summary=dict(auxiliary_outcome='ERROR'))
    kwargs=dict(stage_window=window,stage_plan={},stage_windows=[],executed_plan=[],stage_failure_reasons=[],run_aborted=False,stage_aborted=False,
        stage_abort_reason='',operator_stop_requested=False,abort_run_on_stage_abort=False,abort_on_system_fault=False,stage_id='s',stage_name='CPU',
        stage_started_iso='now',stage_ended_iso='then',collect_stage_faults=lambda w:[],capture_stage_end=lambda **k:None)
    result=apply_completed_stage_bookkeeping(**kwargs);assert not result.should_break_run and not result.run_aborted
    kwargs['stage_plan']={'system_wide_safety_interruption':True};window.verdict='aborted'
    result=apply_completed_stage_bookkeeping(**kwargs);assert result.should_break_run and result.run_aborted


def run_thermal_stage_profile_inventory_checks():
    total=0
    for name,count in PROFILES.items():
        path=ROOT/'profiles'/name;current=json.loads(path.read_text())
        before=json.loads(subprocess.check_output(['git','show','75c7ce439e26720a8aec9a73923248901fe42ea2:profiles/'+name]))
        assert len(current['stages'])==count
        stripped=deepcopy(current)
        for s in stripped['stages']:
            thermal=s['modules'].pop('storage_thermal')
            assert thermal==dict(enabled=True,selection='all_internal',intensity_percent=50,system_intensity_percent=25)
            total+=1
        assert stripped==before,(name,'existing profile configuration changed')
        loader=ProfileLoader(ROOT/'profiles');profile=loader.load_profile(path)
        assert not ProfileValidator().validate(profile,loader.load_segment_labels(path,profile))['errors']
        assert all(stage_config(s).duration_seconds==s.duration_seconds for s in profile.stages)
    assert total==41


def _run_primary_with_aux(payload, fault=None, emergency=None, session_factory=None, real_clock=False, cancel_check=None, telemetry_interval=1):
    from Modules.lvs_stage_execution import execute_stage_runtime
    from Modules.lvs_run_models import StageWindow
    from smoke_tests.storage_thermal_runner_checks import Clock
    clock=time.monotonic if real_clock else Clock();calls=[];s=stage();s.duration_seconds=2
    s.normalization.trim_start_seconds=0;s.normalization.trim_end_seconds=0
    timestamp=lambda:datetime.now().astimezone().isoformat()
    started_iso=timestamp() if real_clock else '2026-11-05T00:00:00'
    origin=clock();telemetry_times=[]
    class Session:
        def __init__(self,*a,**k):calls.append('storage_created')
        def start(self):
            calls.append('storage_started')
            if fault=='start':raise OSError('injected auxiliary launch failure')
        def poll(self):
            calls.append('storage_polled')
            if fault=='poll':raise OSError('injected auxiliary monitor failure')
            return emergency
        def live_summary(self):return ' | storage fixture'
        def revoke_admission(self):calls.append('storage_admission_revoked')
        def request_stop(self,reason):calls.append('storage_stop_requested')
        def _latch_cleanup(self,reason):calls.append('storage_recovery_required')
        def finish(self,cancelled=False):
            calls.append('storage_finished');clock.sleep(5)
            if fault=='finish':raise OSError('injected auxiliary cleanup failure')
            return deepcopy(payload)
    args={}
    for key,param in inspect.signature(execute_stage_runtime).parameters.items():
        if param.default is inspect.Parameter.empty:args[key]=lambda *a,**k:None
    for key in ('profile_name','display_name','stage_started_iso','cpu_kernel_flavor','cpu_backend','cpu_mode_requested','cpu_mode_resolved',
                'cpu_tuning_policy','gpu_3d_backend_preference','gpu_3d_backend_resolved','vram_backend_preference','vram_backend_resolved','gpu_target_mode','operator_stop_source'):
        args[key]=''
    args.update(stage_window_cls=StageWindow,stage=s,run_dir=Path('/not-used'),stage_plan=dict(storage_thermal={'fixture':True}),stage_start=origin,stage_started_iso=started_iso,
        cpu_tuned_avg_power_w=None,gpu_targets=[],gpu_workers_initial=[],gpu_lifecycle_backends=set(),gpu_retune_events=[],stage_error_events=[],stage_failure_reasons=[],
        stage_verdict='pass',stage_aborted=False,stage_abort_reason='',run_aborted=False,abort_on_worker_error=False,abort_on_fail_threshold=False,
        telemetry_interval_seconds=telemetry_interval,progress_interval_seconds=30,strict_threshold_recommendation_warnings=False,
        launch_stage_processes=lambda *a:calls.append('cpu_started') or [],stop_stage_processes=lambda p:calls.append('cpu_stopped'),
        telemetry_collect_once=lambda:(calls.append('telemetry'),telemetry_times.append(clock()-origin)),poll_stage_process_failures=lambda *a:[],stage_sensor_events=lambda *a:[],
        maybe_retune_gpu_processes=lambda p,*a:p,stage_target_gpu_progress_summary=lambda *a:'',effective_gpu_retune_cooldown_seconds=lambda *a:20,
        worker_result_events_func=lambda *a:([],[]),utilization_events_func=lambda *a:[],backend_effectiveness_events_func=lambda *a:[],vram_attainment_events_func=lambda *a:[],
        now_local_iso=timestamp if real_clock else lambda:'2026-11-05T00:00:00',monotonic=clock,sleep=time.sleep if real_clock else clock.sleep,cancel_check=cancel_check)
    with patch('Modules.lvs_storage_thermal_stage.ThermalStageSession',session_factory or Session):
        result=execute_stage_runtime(**args)
    args['telemetry_times']=telemetry_times
    return result,args,calls


def _auxiliary_cases():
    from Modules.lvs_storage_thermal_results import not_run
    from Modules.lvs_storage_thermal import ThermalResult,ThermalConfig,pilot_rate
    config=ThermalConfig(duration_seconds=2).to_dict();source={'source':{'status':'complete','digest':'fixture'}}
    rate=pilot_rate(ThermalConfig(**config),'fixture','hdd')
    drive=ThermalResult('fixture',{'stable':'fixture'},state='completed',source_provenance=source,
        executable_provenance={'fio':'fixture'},effective_rate=rate,
        started_monotonic=.1,ended_monotonic=2.1,duration_completed=True,cleanup_confirmed=True,
        terminal_published=True,identity_unchanged=True,guard_confirmed=True,provenance_confirmed=True,
        exit_code=0,read_ios=15,read_bytes=15*65536,temperature_status='monitored').to_dict()
    drive.update(fio_activity={'active_seconds':2},configured_duration_seconds=2,pid=12345,
        guard_evidence=dict(contract_id='lvs.storage_thermal.guard',contract_version=1,pid=12345,
            readonly_direct=True,seccomp=2,capabilities=0,no_new_privs=1,uid=1000,gid=1000))
    readiness={'source_provenance':source,'configuration':config,'devices':[dict(device_id='fixture',identity=drive['identity'],selected=True,state='ready',rate=rate)]}
    complete=dict(configuration=config,source_provenance=source,contract_id='lvs.storage_thermal.manifest',contract_version=1,verdict='PASS',status='completed',
        parent_finalization_complete=True,requested=True,execution_started=True,cleanup_confirmed=True,terminal_published=True,requested_devices=['fixture'],readiness=readiness,
        executed_devices=['fixture'],devices=[drive])
    warnings=deepcopy(complete);warnings['verdict']='WARN'
    stopped=deepcopy(complete);stopped['verdict']='FAIL';stopped['devices'][0].update(state='failed',safety_stop=True,stop_reason='temperature stop limit reached')
    error=deepcopy(complete);error['verdict']='FAIL';error['devices'][0].update(state='failed',errors=5,stop_reason='I/O error')
    return dict(COMPLETED=complete,COMPLETED_WITH_WARNINGS=warnings,NOT_RUN=not_run('No eligible storage'),STOPPED=stopped,ERROR=error)


def run_thermal_stage_concurrent_runtime_checks():
    for outcome,payload in _auxiliary_cases().items():
        result,args,calls=_run_primary_with_aux(payload)
        assert calls.index('cpu_started')<calls.index('storage_started')<calls.index('storage_polled')<calls.index('cpu_stopped')<calls.index('storage_finished')
        assert result.stage_verdict=='pass' and not result.run_aborted and not result.stage_aborted,outcome
        assert not result.stage_failure_reasons and not result.stage_error_events,outcome
        summary=result.stage_completion.stage_window.storage_thermal_summary
        assert summary['auxiliary_outcome']==outcome,(outcome,summary)
        assert result.stage_elapsed==2 and summary['post_primary_shutdown_seconds']==5
    for fault in ('start','poll','finish'):
        result,args,calls=_run_primary_with_aux(_auxiliary_cases()['COMPLETED'],fault=fault)
        assert result.stage_verdict=='pass' and not result.stage_failure_reasons and not result.stage_error_events,fault
        assert result.stage_completion.stage_window.storage_thermal_summary['auxiliary_outcome']=='ERROR'
    emergency=dict(system_wide_safety_emergency=True,reason='verified platform emergency',evidence={'authoritative_provider':'fixture_platform_safety','critical':True})
    result,args,calls=_run_primary_with_aux(_auxiliary_cases()['STOPPED'],emergency=emergency)
    assert result.stage_verdict=='aborted' and result.run_aborted and result.stage_aborted
    assert not result.stage_failure_reasons and all(e['severity']!='error' for e in result.stage_error_events)


def run_thermal_stage_frontend_parity_checks():
    import asyncio,io
    from contextlib import redirect_stdout
    from Modules.lvs_profile_cli_editor import ProfileCliEditor
    from Modules.lvs_service_profiles import SuiteProfileServiceMixin
    from Modules.lvs_tui_stage_configuration import TuiStageConfigurationMixin
    from Modules.lvs_stage_configuration import setting_value_text
    assert json.loads(setting_value_text({'iops':None}))=={'iops':None}
    profile=ValidationProfile('fixture',stages=[stage()]);original=deepcopy(profile)
    editor=ProfileEditor();controller=ProfileEditController(editor)
    fields=stage_settings(profile.stages[0],editor)
    index=next(i+1 for i,s in enumerate(fields) if s.key=='thermal_enabled')
    answers=iter([str(index),'false','b'])
    host=SimpleNamespace(profile_editor=editor,profile_edit_controller=controller,
        profile_save=SimpleNamespace(validator=ProfileValidator()),_input=lambda _:next(answers))
    with redirect_stdout(io.StringIO()):ProfileCliEditor(host).configure_stage_workloads(profile,0,['CPU'],run_only=True)
    assert not profile.stages[0].modules.storage_thermal.enabled and original.stages[0].modules.storage_thermal.enabled
    edit=ProfileEditState(Path('fixture.json'),deepcopy(original),['CPU'])
    class Service(SuiteProfileServiceMixin):pass
    service=Service();service.profile_editor=editor;service.profile_edit_controller=controller;service.profile_save=host.profile_save
    assert [f.key for f in service.stage_configuration_settings(edit,0)]==[f.key for f in fields]
    class App(TuiStageConfigurationMixin):
        async def _show_stage_configuration(self,detail=''):self.detail=detail
        def _stage_configuration_edit(self):return edit
    app=App();app.service=service;app.stage_configuration_index=0;app.stage_configuration_key='thermal_enabled'
    app.stage_configuration_for_run=True;app.confirm_run=True
    app.run_setup=SimpleNamespace(profile=edit.profile,labels=['CPU'])
    asyncio.run(app._commit_stage_configuration('false'))
    assert asdict(app.run_setup.profile)==asdict(profile) and not app.confirm_run


def run_thermal_stage_unmonitored_scope_checks():
    from Modules.lvs_storage_thermal_runner import approve_unmonitored
    with tempfile.TemporaryDirectory() as root:
        f=RunnerFixture(root);f.temp=None;s=stage();s.duration_seconds=1;s.modules.storage_thermal.monitoring='approved_unmonitored'
        with patch('Modules.lvs_storage_thermal_runner.capability',return_value=f.backend):plan=preview(s,f.runner)
        assert plan['status']=='READY' and plan['requires_consent']
        profile=ValidationProfile('fixture',stages=[s]);approve_coverage(profile,[plan])
        items=[dict(issues=[],warnings=[],runnable=True,storage_thermal=plan)];apply_profile_decisions(profile,items)
        directory=Path(root)/'approved';directory.mkdir();(directory/'request.json').write_text(json.dumps(dict(plan,supervisor_parent_pid=os.getppid(),recovery_marker=str(Path(root)/"recovery.json"))))
        with patch('Modules.lvs_storage_thermal_stage.default_runner',return_value=f.runner),patch('Modules.lvs_storage_thermal_runner.capability',return_value=f.backend),f.context():
            assert fixture_stage_worker(directory,f)==0
        result=json.loads((directory/'completion.json').read_text())
        assert result['verdict']=='WARN' and result['devices'][0]['temperature_status']=='unmonitored'
        changed=deepcopy(plan);changed['configuration']['duration_seconds']=3600
        assert not consent_valid(changed,profile._thermal_consents)
        # Fresh preview tokens have different timestamps but never widen consent.
        with patch('Modules.lvs_storage_thermal_runner.capability',return_value=f.backend):fresh=preview(s,f.runner)
        fresh['schedule_scope'] = plan.get('schedule_scope')
        assert decision_key(fresh)==decision_key(plan)
        fresh['targets'][0]['initial_temperature']['critical_c']=40
        assert not consent_valid(fresh,profile._thermal_consents)


def run_thermal_stage_readiness_and_terminal_checks():
    from Modules.lvs_dry_run import build_dry_run_report
    s=stage();profile=ValidationProfile('fixture',stages=[s]);p=blocked(s)
    plan=dict(enabled=True,label='CPU',workloads=['cpu','storage_thermal'],storage_thermal=p,
              issues=[],warnings=[],runnable=True,backend_usage={'cpu':'suite_native'})
    apply_profile_decisions(profile,[plan])
    # No hardware/backends queried by this report fixture.
    settings=SimpleNamespace(runtime_environment='native',privileged_helper_enabled=False,gpu_safe_mode=False)
    work=SimpleNamespace(backend_details=lambda:{},detect_backends=lambda:{},runtime_environment=lambda:{})
    orchestrator=SimpleNamespace(validator=ProfileValidator(),workload_runner=work,settings=settings,
        _build_gpu_recovery_report=lambda:{},_stage_strict_threshold_recommendation_warnings=lambda *a:False,_strict_threshold_warning_scope=lambda p:'profile')
    cap={k:{'available':True} for k in ('cpu_temp_c','cpu_power_w','memory_used_gb','gpu_temp_c','gpu_power_w','gpu_vram_used_gb')}
    telemetry=SimpleNamespace(detect_capabilities=lambda:cap,close=lambda:None)
    # Another stage could be runnable: unapproved thermal coverage still blocks
    # the schedule instead of silently skipping its requested storage stage.
    other=deepcopy(plan);other.update(thermal_approval_required=False,runnable=True,issues=[],storage_thermal=None)
    with patch('Modules.lvs_dry_run.TelemetryCollector',return_value=telemetry),patch('Modules.lvs_dry_run.build_dry_run_plan',return_value=[plan,other]):
        report=build_dry_run_report(orchestrator,Path('fixture.json'),profile,['CPU'])
    assert report['runnable'] and not report['validation']['profile_errors']
    from Modules.lvs_cli_preflight_summary import compact_cli_preflight_summary
    from Modules.lvs_tui_run_setup_flow import prepared_run_readiness_text
    from Modules.lvs_profile_report_text import preflight_summary_text
    assert 'non-gating' in compact_cli_preflight_summary(report) and 'active system disk' in compact_cli_preflight_summary(report)
    prepared=SimpleNamespace(readiness=SimpleNamespace(validation={}),preflight_decision=SimpleNamespace(report=report,runnable=True),preflight_action=SimpleNamespace(blocked=False))
    text=prepared_run_readiness_text(prepared)
    assert 'non-gating' in text and 'NOT_RUN' in text
    assert 'NOT_RUN' in preflight_summary_text(report)
    # Malformed auxiliary settings cannot execute, but do not gate valid primary
    # workloads. Authoring/saving such settings still fails strict validation.
    invalid=stage();invalid.modules.storage_thermal.intensity_percent=101
    validation=ProfileValidator().validate(ValidationProfile('invalid auxiliary',stages=[invalid]),['CPU'])
    assert not validation['errors'] and validation['auxiliary_errors']
    assert preview(invalid)['status']=='BLOCKED'
    from Modules.lvs_profile_save import ProfileSaveController
    save=ProfileSaveController(ProfileEditor(),ProfileLoader,ProfileValidator())
    assert not save.prepare(ValidationProfile('invalid auxiliary',stages=[invalid]),['CPU']).save_allowed
    assert not plan['issues'] and not plan['warnings']
    class Process:
        returncode=0
        def poll(self):return 0
        def wait(self,timeout=None):return 0
    with tempfile.TemporaryDirectory() as root:
        session=ThermalStageSession(s,p,root,recovery_marker=Path(root)/'recovery.json');session.directory.mkdir(parents=True);session.process=Process();session.admitted=True
        # Previously cached PASS must not survive corruption of the final record.
        session.evidence=dict(verdict='PASS',executed_devices=['fixture'])
        (session.directory/'completion.json').write_text('{broken')
        result=session.finish()
        assert result['auxiliary_outcome']=='ERROR'
    disabled=stage();disabled.modules.storage_thermal.enabled=False;disabled.duration_seconds=100000
    assert stage_config(disabled).duration_seconds==120


def run_thermal_stage_one_run_consent_checks():
    from Modules.lvs_run_orchestration import execute_validation_run
    s=stage();plan=unmonitored(s);profile=ValidationProfile('fixture',stages=[s]);approve_coverage(profile,[plan])
    item=dict(enabled=True,issues=[],warnings=[],runnable=True,storage_thermal=plan);apply_profile_decisions(profile,[item])
    assert consent_valid(plan,profile._thermal_consents)
    # Stop before any actual collector or execution; assert the captured plan
    # keeps consent while the reusable setup no longer authorizes another run.
    class Halt(Exception):pass
    def collector(**kwargs):raise Halt('fixture: no host telemetry or worker')
    with tempfile.TemporaryDirectory() as root:
        orchestrator=SimpleNamespace(dry_run=lambda *a:dict(runnable=True,plan=[item],backend_details={}),
            settings=SimpleNamespace(abort_on_worker_error=False,abort_on_system_fault=False,abort_run_on_stage_abort=False,runtime_environment="native",privileged_helper_enabled=False))
        with patch('Modules.lvs_run_orchestration.TelemetryCollector',side_effect=collector):
            try:execute_validation_run(orchestrator,profile_path=Path('fixture.json'),profile=profile,labels=['CPU'],metadata=None,stage_window_cls=None,run_dir=Path(root))
            except Halt:pass
            else:raise AssertionError('fixture collector did not stop execution')
    assert not profile._thermal_consents
    assert consent_valid(plan,{decision_key(plan):plan['coverage_consent']})


def run_thermal_stage_tui_consent_checks():
    import asyncio
    from Modules.lvs_tui_run_execution_adapter import TuiRunExecutionAdapterMixin
    from Modules.lvs_tui_event_adapter import TuiEventAdapterMixin
    from Modules.lvs_service_models import FrontendActionSpec
    s=stage();p=unmonitored(s);profile=ValidationProfile('fixture',stages=[s]);report={'plan':[dict(enabled=True,storage_thermal=p)]}
    class App(TuiRunExecutionAdapterMixin):
        def __init__(self):
            self.view_mode='setup';self.run_in_progress=False;self.confirm_run=False
            self.selected_profile=SimpleNamespace(name='fixture',path=Path('fixture.json'))
            self.run_setup=SimpleNamespace(profile_path=self.selected_profile.path,profile=profile)
            self.service=SimpleNamespace(setup_action_specs=lambda setup:[FrontendActionSpec('u','run_selected')],run_setup_summary_text=lambda setup:'fixture')
        def _handle_sync_run_setup_action(self,action):pass
        def _prepare_run_confirmation_flow(self,**kwargs):
            return SimpleNamespace(preflight_decision=SimpleNamespace(report=report),preflight_action=SimpleNamespace(blocked=bool(consent_requests(report,profile))))
        def _prepared_run_readiness_text(self,prepared):return 'fixture readiness'
        def _apply_input_state(self,state):self.pending_input_field=state.pending_field;self.input_state=state
        def _clear_setup_input(self,**kwargs):self.pending_input_field=None
        def _set_detail(self,detail):self.detail=detail
        def query_one(self,selector):return SimpleNamespace(value=self.answer)
    app=App();app.action_run_selected()
    assert app.pending_input_field=='__thermal_coverage' and not app.confirm_run
    app.answer='';asyncio.run(TuiEventAdapterMixin._commit_setup_input(app))
    assert not consent_valid(p,profile._thermal_consents) and app.confirm_run
    assert not consent_requests(report,profile)
    profile._thermal_consents={};app.confirm_run=False
    app.action_run_selected();app.answer='1';asyncio.run(TuiEventAdapterMixin._commit_setup_input(app))
    assert app.confirm_run and not consent_requests(report,profile)


def run_thermal_stage_auxiliary_reporting_checks():
    from Modules.lvs_storage_thermal_results import normalize, summarize_run, summary_text, publish_run_summary, not_run
    from Modules.lvs_run_completion_evidence import execution_completion, with_completion
    from Modules.lvs_run_verdict import combine_run_verdict
    windows=[]
    for expected,payload in _auxiliary_cases().items():
        result,args,calls=_run_primary_with_aux(payload)
        window=result.stage_completion.stage_window
        assert window.storage_thermal_summary['auxiliary_outcome']==expected
        # Raw failure is still raw failure, but never a primary worker result.
        assert window.storage_thermal_summary['verdict']==payload['verdict']
        completion=execution_completion(dict(verdict='pass',ended=window.ended_iso,stage_windows=[asdict(window)]))
        assert completion['status']=='completed'
        assert with_completion({'Result':'PASS'},completion)['Result']=='PASS'
        windows.append(window)
    assert combine_run_verdict(w.verdict for w in windows)=='pass'
    summary=summarize_run(windows)
    assert summary['auxiliary_outcome']=='ERROR' and summary['stage_outcome_counts']['NOT_RUN']==1
    assert summary['stage_outcome_counts']['ERROR']==4  # unregistered windows cannot authorize run coverage
    assert 'independent auxiliary' in summary_text(summary)
    assert all('source_provenance' not in d['execution'] for s in summary['stages'] for d in s['result']['drive_outcomes'])
    with tempfile.TemporaryDirectory() as root:
        published=publish_run_summary(root,summary)
        assert published['publication_integrity'] and json.loads((Path(root)/'storage_thermal_summary.json').read_text())['auxiliary_outcome']=='ERROR'
        failed=publish_run_summary(root,summary,publish=lambda *a:(_ for _ in ()).throw(OSError('injected auxiliary publication failure')))
        assert failed['auxiliary_outcome']=='ERROR' and not failed['publication_integrity']
    assert all(w.verdict=='pass' and not w.error_events for w in windows)
    class Process:
        returncode=0
        def poll(self):return 0
        def wait(self,timeout=None):return 0
    with tempfile.TemporaryDirectory() as root:
        plan=blocked();session=ThermalStageSession(stage(),plan,root,recovery_marker=Path(root)/'recovery.json')
        session.directory.mkdir(parents=True);session.process=Process();session.admitted=True
        payload=deepcopy(_auxiliary_cases()['ERROR']);payload['failure']='exact native failure details retained'
        (session.directory/'completion.json').write_text(json.dumps(payload))
        result=session.finish()
        assert result['auxiliary_outcome']=='ERROR' and result['failure']=='exact native failure details retained'
        assert result['adapter_error']

    from Modules.lvs_run_progress import RunStatusTracker, progress_line
    tracker=RunStatusTracker()
    tracker.update_line(progress_line('now','run-end',verdict='pass',elapsed='00:00:02'))
    tracker.update_line(progress_line('now','storage-thermal-summary',auxiliary_outcome='ERROR',primary_validation_gating='false'))
    assert tracker.snapshot.verdict=='pass' and tracker.snapshot.status=='run_complete'
    # A genuine local safety stop is STOPPED; missing monitoring and cleanup are ERROR.
    lost=deepcopy(_auxiliary_cases()['STOPPED']);lost['devices'][0]['stop_reason']='temperature provider unavailable'
    assert normalize(lost)['auxiliary_outcome']=='ERROR'
    unknown=deepcopy(_auxiliary_cases()['COMPLETED']);unknown['devices'][0]['cleanup_confirmed']=False
    assert normalize(unknown)['auxiliary_outcome']=='ERROR'
    disabled=not_run('disabled',requested=False)
    assert disabled['auxiliary_outcome']=='NOT_RUN' and not disabled['requested']


def run_thermal_stage_startup_isolation_checks():
    """Two-second primary, ten-second initializer: real sampling, no late I/O."""
    from Modules.lvs_storage_thermal_runner import group_gone
    sessions=[]
    with tempfile.TemporaryDirectory() as root:
        root=Path(root); marker=root/'recovery.json'; escaped=root/'late-io'
        # Disposable Python initializer only. It cannot open a host block device.
        # Its sole simulated I/O marker is reachable only after a matching RUN.
        code='''import json,os,sys,time
rfd,wfd=map(int,sys.argv[1].split(':'));b=b''
while b'\\n' not in b:b+=os.read(rfd,65536)
r=json.loads(b.split(b'\\n')[0]);time.sleep(10)
os.write(wfd,(json.dumps(dict(ready=True,lease=r['stage_lease_id']))+'\\n').encode())
b=os.read(rfd,4096)
if b and json.loads(b)['run']:open(sys.argv[2],'w').write('unexpected late I/O')
'''
        def factory(s,plan,run_dir,**kwargs):
            def popen(argv,**options):
                return subprocess.Popen([sys.executable,'-c',code,argv[-1],str(escaped)],**options)
            session=ThermalStageSession(s,dict(status='READY',requires_consent=False),root,
                recovery_marker=marker,launch_args=[sys.executable,'-c',code,'{channel}',str(escaped)],**kwargs)
            sessions.append(session);return session
        started=time.monotonic()
        result,args,calls=_run_primary_with_aux(None,session_factory=factory,real_clock=True)
        elapsed=time.monotonic()-started
        summary=result.stage_completion.stage_window.storage_thermal_summary
        assert 2<=result.stage_elapsed<3,(result.stage_elapsed,elapsed)
        window=result.stage_completion.stage_window
        wall_seconds=(datetime.fromisoformat(window.ended_iso)-datetime.fromisoformat(window.started_iso)).total_seconds()
        assert 2<=wall_seconds<3,wall_seconds
        assert len(args['telemetry_times'])>=2 and args['telemetry_times'][1]>=.9,args['telemetry_times']
        assert result.stage_verdict=='pass' and not result.stage_error_events and not result.stage_failure_reasons
        assert summary['auxiliary_outcome']=='NOT_RUN' and not summary['io_admission_granted'],summary
        assert summary['cleanup_confirmed'] and group_gone(sessions[-1].process.pid)
        assert not summary['initializer_permission_granted'] and summary['io_admission_state']=='not_admitted'
        assert not escaped.exists() and not marker.exists()
        print(f'  primary timing: {result.stage_elapsed:.6f}s; telemetry at {args["telemetry_times"]}; auxiliary cleanup {summary["post_primary_shutdown_seconds"]:.6f}s')
        # Early operator cancellation revokes the same channel, never grants a
        # new stage's permission to an old initializer, and reaps its process.
        begin=time.monotonic()
        result,args,calls=_run_primary_with_aux(None,session_factory=factory,real_clock=True,
            cancel_check=lambda:time.monotonic()-begin>=.3)
        assert result.stage_aborted and result.stage_elapsed<2
        assert not escaped.exists() and group_gone(sessions[-1].process.pid)
        assert not sessions[-1].admitted and sessions[-1].channel is None
        # A ready message received after expiry cannot grant execution either.
        from smoke_tests.storage_thermal_runner_checks import Clock
        clock=Clock();s=stage();session=ThermalStageSession(s,{'status':'READY'},root,
            stage_deadline=2,clock=clock,recovery_marker=marker)
        parent,peer=StageChannel.pair();parent.setblocking(False);session.channel=parent
        peer.sendall((json.dumps(dict(ready=True,lease=session.lease_id))+'\n').encode())
        clock.sleep(10);session.poll()  # no process: explicit channel poll below
        session._channel_poll();assert session.stopping and not session.admitted
        assert peer.recv(4096)==b'';peer.close()
        # Revoke during authoritative open: close the returned descriptor.
        fd=os.open(root/'descriptor',os.O_CREAT|os.O_RDWR,0o600)
        lease=StageLease(20,os.getppid(),clock=clock)
        def opened(row):clock.sleep(11);return fd
        targets=LeaseTargets(SimpleNamespace(open=opened),lease)
        try:targets.open({});raise AssertionError('expired open accepted')
        except StageLeaseExpired:pass
        try:os.fstat(fd);raise AssertionError('expired descriptor leaked')
        except OSError:pass
        # Do not replace a precise pre-admission rejection with a generic expiry.
        from Modules.lvs_storage_thermal_results import not_run
        class Exited:
            pid=200000002;returncode=1
            def poll(self):return 1
            def wait(self,timeout=None):return 1
            def group_cleanup_confirmed(self):return True
        finished=ThermalStageSession(stage(),{'status':'READY'},root,recovery_marker=marker,
            group_reaped=lambda pid:True)
        finished.directory.mkdir(parents=True)
        (finished.directory/'completion.json').write_text(json.dumps(dict(not_run('readiness changed; device replaced'),execution_context=finished.context)))
        finished.process=Exited()
        final=finished.finish()
        assert final['auxiliary_outcome']=='NOT_RUN' and final['reasons']==['readiness changed; device replaced']
    print('  isolation evidence: primary 2s, >=2 real telemetry samples; 10s initializer reaped without admission')


def _primary_publication_fixture(root, payload, *, summary=None, exporter=None, registration=None):
    from Modules.lvs_run_artifacts import write_final_run_artifacts
    from Modules.lvs_run_models import StageWindow
    from Modules.lvs_summary_text import SummaryTextBuilder
    window=StageWindow(stage_id='s1',stage_type='CPU Load',display_name='Primary CPU',
        started_iso='2026-11-05T00:00:00',ended_iso='2026-11-05T00:00:02',
        started_monotonic=0,ended_monotonic=2,duration_seconds=2,trim_start_seconds=0,trim_end_seconds=0,verdict='pass')
    window.storage_thermal_summary=payload
    if registration is not None:
        from Modules.lvs_storage_thermal_results import register_stage
        register_stage(window,registration)
    parser=SimpleNamespace(summarize=lambda *a:dict(Segments=[dict(Label='Primary CPU',StorageThermal=window.storage_thermal_summary)]))
    default_exporter=SimpleNamespace(build=lambda *a:dict(Result='PASS',Segments=a[5]['Segments']))
    return write_final_run_artifacts(run_dir=root,manifest_payload={},app_name='LVS',app_version='test',
        profile=ValidationProfile('isolation'),metadata=ValidationProfile('isolation'),
        started_iso=window.started_iso,ended_iso=window.ended_iso,total_elapsed=2,
        system_info={'Hardware':{'Gpu':[],'Cpu':{}}},telemetry=SimpleNamespace(samples=[],interval_seconds=1),
        stage_windows=[window],executed_plan=[dict(stage_id='s1',storage_thermal_result=payload)],
        recovery_report={},skipped_stages=[],run_aborted=False,keep_raw_telemetry=False,
        export_compatibility_json=True,export_extended_json=True,segment_parser=parser,
        exporter=exporter or default_exporter,summary_exporter=summary or SummaryTextBuilder(),
        stage_sensor_events=lambda w:[],stage_faults=lambda w:[],capture_run_end=lambda **k:None)


def run_thermal_stage_publication_isolation_checks():
    """Auxiliary faults cannot prevent independently justified primary artifacts."""
    from contextlib import nullcontext
    from Modules.lvs_storage_thermal_results import summarize_run
    failure=lambda *a,**k:(_ for _ in ()).throw(RuntimeError('injected auxiliary failure'))
    cases={
        'aggregation':patch('Modules.lvs_storage_thermal_results.summarize_run',side_effect=failure),
        'normalization':patch('Modules.lvs_storage_thermal_results.normalize',side_effect=failure),
        'serialization':patch('Modules.lvs_storage_thermal_results.summarize_run',return_value={'bad':object()}),
        'publication':patch('Modules.lvs_storage_thermal_results.publish_run_summary',side_effect=failure),
        'rendering':patch('Modules.lvs_storage_thermal_results.summary_text',side_effect=failure),
        # Isolate combined-summary rendering from earlier auxiliary text export.
        'combined_rendering':patch('Modules.lvs_storage_thermal_results.publish_run_summary',side_effect=lambda p,s:s),
        'stage_serialization':nullcontext(),
    }
    accepted_payload=_auxiliary_cases()['COMPLETED']
    for name,context in cases.items():
        with tempfile.TemporaryDirectory() as directory,context:
            root=Path(directory);payload=deepcopy(accepted_payload)
            if name=='stage_serialization':payload['corrupt_auxiliary']=object()
            extra=patch('Modules.lvs_storage_thermal_results.summary_text',side_effect=failure) if name=='combined_rendering' else nullcontext()
            with extra:result=_primary_publication_fixture(root,payload)
            manifest=json.loads((root/'run_manifest.json').read_text())
            compat=json.loads((root/'parsed_results_custom.json').read_text())
            text=(root/'run_summary.txt').read_text()
            assert manifest['verdict']=='pass' and result.overall_verdict=='pass',name
            assert compat['Result']=='PASS' and 'Result: PASS' in text,name
            assert manifest['execution_completion']['status']=='completed'
            assert manifest['storage_thermal_summary']['auxiliary_outcome']=='ERROR',name
            assert not manifest['storage_thermal_summary']['publication_integrity'],name
            assert 'ERROR' in text and not manifest['error_events'] and not result.error_events,name
            assert compat['StorageThermalSummary']==manifest['storage_thermal_summary']
            assert not list(root.glob('tmp*'))
    for outcome,payload in _auxiliary_cases().items():
        with tempfile.TemporaryDirectory() as directory:
            result=_primary_publication_fixture(Path(directory),payload)
            assert result.overall_verdict=='pass',outcome
            assert (Path(directory)/'run_summary.txt').exists()
    # Genuine primary exporter and primary renderer errors MUST remain failures.
    for options in (dict(exporter=SimpleNamespace(build=failure)),dict(summary=SimpleNamespace(build=failure))):
        with tempfile.TemporaryDirectory() as directory:
            try:_primary_publication_fixture(Path(directory),_auxiliary_cases()['NOT_RUN'],**options)
            except RuntimeError:pass
            else:raise AssertionError('primary publication error swallowed')
    print('  publication evidence: primary manifest/summary PASS with aggregation, normalization, serialization and rendering faults; auxiliary ERROR retained')


class NativeAdmissionFixture:
    """Actual native gate; only a private regular file and policy-test mode."""
    def __init__(self, root, guard, seconds=3):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        self.data=self.root/'disposable-regular-file';self.data.write_bytes(bytes(4096))
        self.target=os.open(self.data,os.O_RDONLY|os.O_DIRECT)
        self.executable=os.open('/bin/true',os.O_RDONLY)
        self.out=(self.root/'out').open('wb');self.err=(self.root/'err').open('wb')
        self.state=SharedAdmission.create()
        self.lease=StageLease(time.monotonic()+seconds,os.getppid(),admission=self.state)
        self.before_spawn=lambda:None;self.after_spawn=lambda p:None
        self.processes=[];self.options=[]
        def spawn(argv,**kwargs):
            self.options.append(kwargs)
            self.before_spawn()
            argv=list(argv);assert argv[1]=='--stage-fio-fd'
            # The production gate is unchanged; its target proof is restricted
            # to a regular file and existing mutating-syscall negative controls.
            argv[1]='--stage-policy-test'
            from Modules.lvs_storage_thermal_launch import OwnedProcess
            p=OwnedProcess(argv,**kwargs);self.processes.append(p)
            self.after_spawn(p)
            return p
        from Modules.lvs_storage_thermal_launch import prepare
        prepare(self.root/"bootstrap")
        self.launches=StageLaunches(SimpleNamespace(popen=spawn),self.lease,self.root,owned_launch=spawn)
        uid=os.getuid() or 65534;gid=os.getgid() or 65534
        self.argv=[str(guard),'--fio-fd',str(self.executable),*map(str,(uid,gid,0,0,4096,4096,1,1))]
    def launch(self):
        return self.launches.launch(self.argv,stdin=self.target,pass_fds=(self.executable,),
            stdout=self.out,stderr=self.err,start_new_session=True)
    def text(self):
        self.err.flush();return (self.root/'err').read_text()
    def close(self):
        self.state.revoke();self.launches.finish()
        assert self.launches.cleanup_confirmed,self.launches.snapshot()
        for p in self.processes:assert p.poll() is not None
        self.out.close();self.err.close();self.state.close()
        os.close(self.target);os.close(self.executable)


def run_thermal_stage_admission_race_checks():
    from smoke_tests.storage_thermal_foundation_checks import compile_guard
    with tempfile.TemporaryDirectory(prefix='lvs-admission-races-') as root:
        guard=compile_guard(root)
        for scenario in ('revocation','deadline','during_creation','after_creation','after_ready','after_offer','after_commit','publication'):
            f=NativeAdmissionFixture(Path(root)/scenario,guard)
            try:
                if scenario=='revocation':f.before_spawn=f.state.revoke
                elif scenario=='deadline':
                    # Same original Python check-to-launch boundary; the real
                    # clock expires before the original launcher creates a child.
                    f.lease.deadline=time.monotonic()+1.05;f.lease.deadline_ns=int(f.lease.deadline*1e9)
                    f.before_spawn=lambda:time.sleep(max(0,f.lease.deadline-time.monotonic())+.02)
                elif scenario=='during_creation':f.after_spawn=lambda p:f.state.revoke()
                else:
                    publish=f.launches.publish
                    def injected():
                        row=f.launches.owned[-1]
                        if (scenario=='after_creation' and row['phase']=='created'
                            or scenario=='after_ready' and row['phase']=='owned'
                            or scenario=='after_offer' and row['phase']=='offering'
                            or scenario=='after_commit' and row['phase']=='committed'):
                            assert row['process'] in f.processes
                            f.state.revoke()
                        if scenario=='publication' and row['phase']=='created':
                            f.launches.publication_error='injected ownership publication failure'
                            raise OSError(f.launches.publication_error)
                        publish()
                    f.launches.publish=injected
                try:f.launch();raise AssertionError('closed/failed admission returned as runnable')
                except (StageLeaseExpired,ValueError,OSError):pass
                assert len(f.processes)==1
                assert f.launches.owned[0]['pid']==f.processes[0].pid
                assert f.options[0]['stdin']==subprocess.DEVNULL
                assert f.target not in f.options[0]['pass_fds']
                if scenario!='after_commit':
                    assert 'COMMITTED' not in f.text(),(scenario,f.text())
                    assert f.launches.owned[0]['descriptor_offered']==(scenario=='after_offer'),scenario
                else:
                    assert f.launches.owned[0]['committed_monotonic_ns']<f.lease.deadline_ns
                assert f.launches.cleanup_confirmed and all(p.poll() is not None for p in f.processes)
            finally:f.close()
        # Repeated races at the old boundary never transfer a target descriptor.
        for index in range(8):
            f=NativeAdmissionFixture(Path(root)/f'repeat-{index}',guard)
            try:
                if index%2:f.before_spawn=f.state.revoke
                else:f.before_spawn=lambda:setattr(f.lease,'clock',lambda:f.lease.deadline+1)
                try:f.launch();raise AssertionError('late I/O admission')
                except (StageLeaseExpired,ValueError):pass
                assert 'COMMITTED' not in f.text()
            finally:f.close()
    print('  native race evidence: revocation/expiry at old boundary, creation/ready cancellation, owned in-flight commit and eight repeated races PASS')


def run_thermal_stage_native_admission_checks():
    import array,fcntl,socket
    from smoke_tests.storage_thermal_foundation_checks import compile_guard
    with tempfile.TemporaryDirectory(prefix='lvs-native-gate-') as root:
        guard=compile_guard(root)
        config=stage_config(stage())
        backend=dict(status='available')
        existing=dict(status='READY',backend=backend,configuration=config.to_dict(),commands=[{'device_id':'fixture'}],
            runnable_devices=['fixture'],blocked_devices=[],reasons=[],targets=[],
            devices=[dict(device_id='fixture',selected=True,state='ready',reasons=[])])
        old=SimpleNamespace(guard=guard,inspect=lambda c:deepcopy(existing))
        with patch('Modules.lvs_storage_thermal_stage.subprocess.run',return_value=subprocess.CompletedProcess([],125,'','unknown option')):
            blocked=inspect_stage(old,config)
        assert blocked['status']=='BLOCKED' and blocked['blocked_devices']==['fixture']
        assert not blocked['commands'] and not blocked['runnable_devices'] and backend=={'status':'available'}
        with patch('Modules.lvs_storage_thermal_stage.subprocess.run',side_effect=subprocess.TimeoutExpired('guard probe',2)):
            blocked=inspect_stage(old,config)
        assert blocked['status']=='BLOCKED' and not blocked['commands'] and 'probe failed' in blocked['reasons'][-1]
        leaked=[]
        def failed_write(fd,data):leaked.append(fd);raise OSError('injected low-memory lease failure')
        with patch('Modules.lvs_storage_thermal_stage.os.write',side_effect=failed_write):
            try:SharedAdmission.create();raise AssertionError('failed lease accepted')
            except OSError:pass
        assert len(leaked)==1
        try:os.fstat(leaked[0]);raise AssertionError('failed lease descriptor leaked')
        except OSError:pass
        # Positive native protocol and existing kernel mutation restrictions.
        f=NativeAdmissionFixture(Path(root)/'positive',guard)
        try:
            p=f.launch();assert p.wait(timeout=2)==0
            assert 'COMMITTED' in f.text()
            assert '"policy_test":"PASS"' in (f.root/'out').read_text()
            assert f.launches.owned[0]['phase']=='committed'
        finally:f.close()
        f=NativeAdmissionFixture(Path(root)/'revocation-error',guard)
        try:
            process=f.launch();process.wait(timeout=2)
            with patch.object(f.state,'revoke',side_effect=OSError('injected shared-gate failure')):
                f.launches.finish()
            assert not f.launches.cleanup_confirmed
            assert 'injected shared-gate failure' in f.launches.snapshot()['revocation_error']
            assert all(p.poll() is not None for p in f.processes)
        finally:f.close()
        # Failure of revocation itself must still persist recovery protection.
        from Modules.lvs_storage_thermal_stage import recovery_blocker,_UNCONFIRMED
        marker=Path(root)/'revocation-recovery.json'
        session=ThermalStageSession(stage(),{'status':'READY'},root,recovery_marker=marker)
        session.admission=SharedAdmission.create()
        try:
            with patch.object(session.admission,'revoke',side_effect=OSError('injected shared-gate failure')):
                result=session.finish()
            assert result['auxiliary_outcome']=='ERROR' and not result['cleanup_confirmed']
            assert not result['admission_revocation_confirmed'] and marker.exists() and recovery_blocker(marker)
        finally:
            session.admission.close();session.admission=None;_UNCONFIRMED.pop(str(marker),None)
        directory=Path(root)/'escaped-finalization';directory.mkdir()
        marker=directory/'recovery.json'
        program="import sys;import Modules.lvs_storage_thermal_stage as m;defect=lambda *a,**k:(_ for _ in ()).throw(RuntimeError('injected finalization failure'));m.worker=defect;raise SystemExit(m.channel_worker(sys.argv[1]))"
        def failing_worker(argv,**options):return subprocess.Popen([sys.executable,'-c',program,argv[-1]],**options)
        session=ThermalStageSession(stage(),dict(status='READY'),directory,recovery_marker=marker,launch_args=[sys.executable,'-c',program,'{channel}'])
        try:
            session.start()
            until=time.monotonic()+3
            while session.process.poll() is None and time.monotonic()<until:
                session.poll();time.sleep(.01)
            result=session.finish()
            assert result['auxiliary_outcome']=='ERROR' and not result['cleanup_confirmed']
            assert 'injected finalization failure' in result['failure']
            assert marker.exists() and recovery_blocker(marker)
        finally:
            if session.process.poll() is None:session.process.kill();session.process.wait(timeout=2)
            if session.admission is not None:session.admission.close();session.admission=None
            _UNCONFIRMED.pop(str(marker),None)
        for scenario in ('queued_then_revoked','queued_then_expired'):
            f=NativeAdmissionFixture(Path(root)/scenario,guard)
            parent,child=socket.socketpair(socket.AF_UNIX,socket.SOCK_SEQPACKET)
            parent.settimeout(3)
            ofd_lock(f.state._pin)
            p=None
            try:
                deadline=time.monotonic()+1
                argv=[str(guard),'--stage-policy-test',str(f.executable),str(child.fileno()),
                    str(f.state.fd),str(int(deadline*1e9)),str(os.getpid()),*map(str,f.state.identity),*f.argv[3:]]
                p=subprocess.Popen(argv,stdin=subprocess.DEVNULL,stdout=f.out,stderr=f.err,
                    pass_fds=(child.fileno(),f.state.fd,f.executable))
                child.close()
                # Ownership before OWN; native child cannot leave the owner group
                # until this PID is known. It has no target descriptor yet.
                parent.sendall(b'OWN');assert parent.recv(128)==b'R'
                parent.sendmsg([b'F'],[(socket.SOL_SOCKET,socket.SCM_RIGHTS,array.array('i',[f.target]))])
                if scenario=='queued_then_revoked':
                    os.pwrite(f.state._pin,b'R',5)
                    ofd_lock(f.state._pin,unlock=True)
                    f.state.revoke()  # False means nonblocking closure is still pending.
                    assert os.pread(f.state._pin,1,5)==b'R'
                else:
                    time.sleep(max(0,deadline-time.monotonic())+.02)
                    ofd_lock(f.state._pin,unlock=True)
                assert p.wait(timeout=2)!=0 and 'COMMITTED' not in f.text()
                if scenario=='queued_then_revoked':
                    deadline_close=time.monotonic()+1
                    while not f.state.revoke() and time.monotonic()<deadline_close:time.sleep(.001)
                    assert os.pread(f.state._pin,6,0)==b'LVS1CR'
            finally:
                ofd_lock(f.state._pin,unlock=True);parent.close();child.close()
                if p is not None and p.poll() is None:p.kill();p.wait(timeout=2)
                f.close()
        # A different process holds the exact lock used by native admission.
        # Revocation requests never block the primary thread on that lock.
        state=SharedAdmission.create();ready_r,ready_w=os.pipe();release_r,release_w=os.pipe()
        pid=os.fork()
        if pid==0:
            try:
                os.close(ready_r);os.close(release_w)
                attached=SharedAdmission(state.fd,state.identity)
                ofd_lock(attached._pin)
                os.write(ready_w,b'L');os.read(release_r,1)
            finally:os._exit(0)
        try:
            os.close(ready_w);os.close(release_r);assert os.read(ready_r,1)==b'L'
            begin=time.monotonic();assert state.revoke() is False
            assert time.monotonic()-begin<.1
            assert state.closed()  # closure requested; native denies new entrants
            os.write(release_w,b'X');os.waitpid(pid,0);pid=None
            assert state.revoke() and os.pread(state.fd,6,0)==b'LVS1CR'
        finally:
            if pid is not None:os.kill(pid,signal.SIGKILL);os.waitpid(pid,0)
            os.close(ready_r);os.close(release_w);state.close()
    print('  native gate evidence: positive admission, queued-fd revocation, real deadline expiry, cross-process lock and bounded revocation PASS')


def run_thermal_stage_launch_timeout_checks():
    from smoke_tests.storage_thermal_foundation_checks import compile_guard
    from Modules.lvs_storage_thermal_stage import _UNCONFIRMED,recovery_blocker
    with tempfile.TemporaryDirectory(prefix='lvs-launch-timeout-') as root:
        root=Path(root);guard=compile_guard(root);sessions=[];marker=root/'recovery.json'
        # No host device, arbitrary argv or physical activity: only a private file.
        code='''import json,os,signal,subprocess,sys,time
from pathlib import Path
from types import SimpleNamespace
from Modules.lvs_storage_thermal_stage import StageChannel,StageLease,StageLaunches,SharedAdmission
r,w=map(int,sys.argv[1].split(':'));c=StageChannel(r,w);b=b''
while b'\\n' not in b:b+=c.recv(65536)
request=json.loads(b.split(b'\\n')[0]);signal.signal(signal.SIGTERM,lambda *_:None)
c.sendall((json.dumps(dict(ready=True,lease=request['stage_lease_id']))+'\\n').encode())
b=b''
while b'\\n' not in b:b+=c.recv(65536)
permission=json.loads(b.split(b'\\n')[0]);assert permission['run']
d=Path(request['directory']);d.mkdir(parents=True)
data=d/'fixture';data.write_bytes(bytes(4096));fd=os.open(data,os.O_RDONLY|os.O_DIRECT);exe=os.open('/bin/true',os.O_RDONLY)
lease=StageLease(request['stage_deadline'],os.getppid(),admission=SharedAdmission(request['admission_fd'],request['admission_identity']))
def stalled(*a,**k):time.sleep(30);raise AssertionError('launcher should be cancelled before returning')
l=StageLaunches(SimpleNamespace(popen=stalled),lease,d,owned_launch=stalled)
uid=os.getuid() or 65534;gid=os.getgid() or 65534
l.launch([sys.argv[2],'--fio-fd',str(exe),*map(str,(uid,gid,0,0,4096,4096,1,1))],stdin=fd,pass_fds=(exe,),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
'''
        def factory(s,plan,run_dir,**kwargs):
            def spawn(argv,**options):return subprocess.Popen([sys.executable,'-c',code,argv[-1],str(guard)],**options)
            session=ThermalStageSession(s,dict(status='READY',requires_consent=False),root,
                recovery_marker=marker,launch_args=[sys.executable,'-c',code,'{channel}',str(guard)],**kwargs);sessions.append(session);return session
        try:
            result,args,calls=_run_primary_with_aux(None,session_factory=factory,real_clock=True,telemetry_interval=.1)
            summary=result.stage_completion.stage_window.storage_thermal_summary
            assert result.stage_verdict=='pass' and 2<=result.stage_elapsed<3
            assert len(args['telemetry_times'])>=2
            assert summary['auxiliary_outcome']=='ERROR' and not summary['cleanup_confirmed'],summary
            assert summary['supervisor_forced_kill'] and sessions[0].process.poll() is not None
            assert marker.exists() and recovery_blocker(marker)
            assert summary['initializer_permission_granted'] and summary['io_admission_state']=='unconfirmed'
            ownership=json.loads((sessions[0].directory/'launch_ownership.json').read_text())
            assert ownership['workers'][0]['phase']=='bootstrap_launch_pending'
            assert ownership['workers'][0]['pid'] is None and not ownership['workers'][0]['descriptor_offered']
            assert os.pread(sessions[0].admission.fd,6,0)==b'LVS1CR'
        finally:
            # Test-only recovery, after proving the persistent latch. This group
            # contains only our disposable stalled Python launcher, never fio.
            for session in sessions:
                if session.process is not None and session.process.poll() is None:
                    os.killpg(session.process.pid,signal.SIGKILL);session.process.wait(timeout=2)
                if session.admission is not None:session.admission.close();session.admission=None
            _UNCONFIRMED.pop(str(marker),None)
    print('  timeout evidence: primary 2s/normal sampling, stalled launcher bounded, shared admission closed and persistent recovery latch PASS')


def _restore_test_lease(fixture):
    """Test-only recovery after all children are gone; never repin new authority."""
    os.dup2(fixture.state._pin,fixture.state.fd,inheritable=False)


def _native_gate_command(f,guard,channel,*,lease_fd=None,deadline=None):
    return [str(guard),'--stage-policy-test',str(f.executable),str(channel),
        str(f.state.fd if lease_fd is None else lease_fd),
        str(f.lease.deadline_ns if deadline is None else int(deadline*1e9)),str(os.getpid()),
        *map(str,f.state.identity),*f.argv[3:]]


def run_thermal_stage_lease_identity_checks():
    import socket
    from smoke_tests.storage_thermal_foundation_checks import compile_guard
    with tempfile.TemporaryDirectory(prefix='lvs-lease-identity-') as root:
        guard=compile_guard(root)
        for scenario in ('original_closed','deadline','repeat_closed_1','repeat_closed_2'):
            f=NativeAdmissionFixture(Path(root)/scenario,guard)
            transport=os.dup(f.state.fd)
            primary=SharedAdmission(transport,f.state.identity)
            original=f.state.identity
            parent,child=socket.socketpair(socket.AF_UNIX,socket.SOCK_SEQPACKET)
            process=None;replacement=None
            try:
                # A different process still owns the original inode; closure of
                # this supervisor's transport cannot change its authority.
                pid=os.fork()
                if pid==0:
                    try:
                        authority=SharedAdmission(primary.fd,primary.identity)
                        assert authority.revoke()
                    except BaseException:os._exit(1)
                    os._exit(0)
                _,status=os.waitpid(pid,0);assert status==0
                assert os.pread(primary.fd,6,0)==b'LVS1CR'
                number=f.state.fd;os.close(number)
                replacement=SharedAdmission.create()
                assert replacement.fd==number
                assert replacement.identity!=original and os.pread(number,6,0)==b'LVS1OO'
                try:SharedAdmission(number,original);raise AssertionError('replacement established new authority')
                except OSError:pass
                # Bypass Python's rejection to exercise the actual native gate:
                # present the valid-looking replacement with PRIMARY identity.
                deadline=time.monotonic()-.1 if scenario=='deadline' else None
                argv=_native_gate_command(f,guard,child.fileno(),deadline=deadline)
                process=subprocess.Popen(argv,stdin=subprocess.DEVNULL,stdout=f.out,stderr=f.err,
                    pass_fds=(child.fileno(),number,f.executable))
                child.close();assert process.wait(timeout=2)!=0
                assert 'authoritative lease identity mismatch' in f.text() and 'COMMITTED' not in f.text()
                try:f.state.closed();raise AssertionError('supervisor silently accepted replacement')
                except OSError:pass
                assert os.pread(primary.fd,6,0)==b'LVS1CR'
                assert f.state.identity==original
            finally:
                parent.close();child.close()
                if process is not None and process.poll() is None:process.kill();process.wait(timeout=2)
                if replacement is not None:replacement.close()
                _restore_test_lease(f);f.close();primary.close()
        # Cancellation uses its private original pin even after transport reuse;
        # it reports the mismatch instead of silently closing the replacement.
        f=NativeAdmissionFixture(Path(root)/'cancel_reuse',guard)
        try:
            original=f.state.identity;number=f.state.fd;os.close(number)
            replacement=SharedAdmission.create();assert replacement.fd==number
            try:f.state.revoke();raise AssertionError('mismatch not reported')
            except OSError:pass
            assert os.pread(f.state._pin,6,0)==b'LVS1CR'
            assert os.pread(replacement.fd,6,0)==b'LVS1OO'
            try:f.state.close();raise AssertionError('unrelated replacement closed')
            except OSError:pass
            assert replacement.identity!=original and os.fstat(replacement.fd)
            replacement.close()
        finally:_restore_test_lease(f);f.close()
        f=NativeAdmissionFixture(Path(root)/'during_revocation',guard)
        replacements=[];real_lock=ofd_lock
        def change_at_lock(fd,unlock=False):
            real_lock(fd,unlock)
            if not unlock and not replacements:
                os.close(f.state.fd)
                replacements.append(SharedAdmission.create())
        try:
            with patch('Modules.lvs_storage_thermal_stage.ofd_lock',side_effect=change_at_lock):
                try:f.state.revoke();raise AssertionError('critical-section replacement not reported')
                except OSError:pass
            assert replacements[0].fd==f.state.fd
            assert os.pread(f.state._pin,6,0)==b'LVS1CR'
            assert os.pread(replacements[0].fd,6,0)==b'LVS1OO'
            replacements[0].close()
        finally:_restore_test_lease(f);f.close()
        from Modules.lvs_storage_thermal_stage import recovery_blocker,_UNCONFIRMED
        marker=Path(root)/'identity-recovery.json'
        session=ThermalStageSession(stage(),{'status':'READY'},root,recovery_marker=marker)
        session.admission=SharedAdmission.create();session.admission_identity=session.admission.identity
        number=session.admission.fd;os.close(number);replacement=SharedAdmission.create()
        assert replacement.fd==number
        try:
            result=session.finish()
            assert result['auxiliary_outcome']=='ERROR' and not result['cleanup_confirmed']
            assert marker.exists() and recovery_blocker(marker)
            assert os.pread(session.admission._pin,6,0)==b'LVS1CR'
            retry=ThermalStageSession(stage(),{'status':'READY'},root,recovery_marker=marker,
                popen=lambda *a,**k:(_ for _ in ()).throw(AssertionError('unsafe retry')))
            retry.start();assert retry.finish()['auxiliary_outcome']=='NOT_RUN'
        finally:
            replacement.close()
            os.dup2(session.admission._pin,session.admission.fd,inheritable=False)
            session.admission.close();session.admission=None;_UNCONFIRMED.pop(str(marker),None)
    print('  identity evidence: original CLOSED + same-number/different-inode OPEN replacement REJECTED by supervisor and native gate; original authority retained')


def _child_lock_probe(fd,identity,*,expect_blocked):
    """A genuine independent OFD in a different process, never a mock lock."""
    pid=os.fork()
    if pid==0:
        code=0
        try:
            contender=SharedAdmission(fd,identity)
            with contender._operation() as operation:
                try:ofd_lock(operation);blocked=False;ofd_lock(operation,unlock=True)
                except OSError as exc:
                    if exc.errno not in (11,13):raise
                    blocked=True
            if blocked!=expect_blocked:code=1
        except BaseException:code=2
        os._exit(code)
    _,status=os.waitpid(pid,0);assert status==0,(expect_blocked,status)


def run_thermal_stage_ofd_kernel_checks():
    import fcntl
    state=SharedAdmission.create()
    try:
        opened=[];real_open=os.open
        def observed_open(*args,**kwargs):
            fd=real_open(*args,**kwargs);opened.append(fd);return fd
        with patch('Modules.lvs_storage_thermal_stage.os.open',side_effect=observed_open),patch('Modules.lvs_storage_thermal_stage.os.dup',side_effect=OSError(24,'injected descriptor exhaustion')):
            try:state.closed();raise AssertionError('failed lifetime pin accepted')
            except OSError:pass
        assert len(opened)==1
        try:os.fstat(opened[0]);raise AssertionError('failed operation OFD leaked')
        except OSError:pass
        assert not state.closed()
        # Show the traditional POSIX close-any-alias behavior independently.
        alias=os.dup(state.fd)
        fcntl.lockf(state.fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        _child_lock_probe(state.fd,state.identity,expect_blocked=True)
        os.close(alias)  # POSIX lock is released even though state.fd is open.
        _child_lock_probe(state.fd,state.identity,expect_blocked=False)
        # The new operation OFD conflicts with independently opened contenders.
        with state._operation() as operation:
            ofd_lock(operation)
            for _ in range(3):_child_lock_probe(state.fd,state.identity,expect_blocked=True)
            go_r,go_w=os.pipe();children=[]
            for _ in range(3):
                pid=os.fork()
                if pid==0:
                    try:
                        os.close(go_w);assert os.read(go_r,1)==b'X'
                        contender=SharedAdmission(state.fd,state.identity)
                        with contender._operation() as independent:
                            try:ofd_lock(independent)
                            except OSError as exc:
                                if exc.errno in (11,13):os._exit(0)
                                raise
                        os._exit(1)
                    except BaseException:os._exit(2)
                children.append(pid)
            os.close(go_r);os.write(go_w,b'XXX');os.close(go_w)
            statuses=[os.waitpid(pid,0)[1] for pid in children]
            assert all(code==0 for code in statuses),statuses
            same_description=os.dup(operation);os.close(same_description)
            different_description=os.open(f'/proc/self/fd/{state.fd}',os.O_RDWR|os.O_CLOEXEC)
            os.close(different_description)
            _child_lock_probe(state.fd,state.identity,expect_blocked=True)
            # An independently opened OFD in the SAME process also conflicts.
            with state._operation() as other:
                try:ofd_lock(other);raise AssertionError('operation descriptions share lock ownership')
                except OSError as exc:assert exc.errno in (11,13)
            # Closing a retained handle cannot release the operation's own pin.
            os.close(state._pin)
            _child_lock_probe(state.fd,state.identity,expect_blocked=True)
            state._pin=os.open(f'/proc/self/fd/{state.fd}',os.O_RDWR|os.O_CLOEXEC)
            ofd_lock(operation,unlock=True)
        for _ in range(3):_child_lock_probe(state.fd,state.identity,expect_blocked=False)
        # Inherited Python objects cannot use their parent's open descriptions.
        pid=os.fork()
        if pid==0:
            try:state.revoke()
            except OSError:os._exit(0)
            os._exit(1)
        assert os.waitpid(pid,0)[1]==0
        assert not state.closed()
    finally:state.close()
    print('  kernel evidence: POSIX alias-close releases old lock; OFD aliases retain lock; independent process/operation descriptions conflict; inherited actor rejected')


def _compile_lease_fault_shim(root):
    """Test-only syscall interposition; production guard_environment removes it."""
    source=Path(root)/'lease_fault.c';library=Path(root)/'lease_fault.so'
    source.write_text(r'''
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/socket.h>
#include <unistd.h>
static int locked=-1,used=0;
static int (*real_fcntl)(int,int,...);
int fcntl(int fd,int command,...) {
    if(!real_fcntl)real_fcntl=dlsym(RTLD_NEXT,"fcntl");
    if(command==F_GETFL || command==F_GETFD)return real_fcntl(fd,command);
    va_list ap;va_start(ap,command);
    if(command==F_SETFD || command==F_SETFL || command==F_DUPFD || command==F_DUPFD_CLOEXEC) {
        int value=va_arg(ap,int);va_end(ap);return real_fcntl(fd,command,value);
    }
    struct flock *lock=va_arg(ap,struct flock *);va_end(ap);
    const char *mode=getenv("LVS_LEASE_FAULT");
    if(command==F_OFD_SETLK && lock->l_type==F_WRLCK && mode && !strcmp(mode,"fail_lock")) {
        errno=EIO;return -1;
    }
    int result=real_fcntl(fd,command,lock);
    if(command==F_OFD_SETLK && lock->l_type==F_WRLCK && result==0)locked=fd;
    return result;
}
static void replace_fd(int fd) {
    close(fd);int other=memfd_create("valid-looking-replacement",MFD_CLOEXEC);
    if(other<0 || write(other,"LVS1OO",6)!=6)_exit(122);
    if(other!=fd) { if(dup2(other,fd)!=fd)_exit(123);close(other); }
}
ssize_t recvmsg(int fd,struct msghdr *msg,int flags) {
    ssize_t (*real_recvmsg)(int,struct msghdr *,int)=dlsym(RTLD_NEXT,"recvmsg");
    ssize_t result=real_recvmsg(fd,msg,flags);
    const char *mode=getenv("LVS_LEASE_FAULT");
    if(result<=0 || used || !mode)return result;
    used=1;int anchor=atoi(getenv("LVS_LEASE_ANCHOR"));
    if(!strcmp(mode,"replace_anchor"))replace_fd(anchor);
    if(!strcmp(mode,"replace_pin"))replace_fd(locked);
    if(!strcmp(mode,"same_inode_pin")) {
        char path[64];snprintf(path,sizeof(path),"/proc/self/fd/%d",anchor);
        int other=open(path,O_RDWR|O_CLOEXEC);if(other<0)_exit(124);
        close(locked);if(dup2(other,locked)!=locked)_exit(124);close(other);
    }
    if(!strcmp(mode,"unlock")) {
        struct flock unlock={.l_type=F_UNLCK,.l_whence=SEEK_SET,.l_start=0,.l_len=0};
        if(real_fcntl(locked,F_OFD_SETLK,&unlock))_exit(124);
    }
    if(!strcmp(mode,"share_description") && dup2(locked,anchor)<0)_exit(124);
    if(!strcmp(mode,"alias_close")) { int alias=dup(locked);if(alias<0)_exit(124);close(alias); }
    if(!strcmp(mode,"same_inode_close")) {
        char path[64];snprintf(path,sizeof(path),"/proc/self/fd/%d",anchor);
        int alias=open(path,O_RDWR|O_CLOEXEC);if(alias<0)_exit(124);close(alias);
    }
    int ready=atoi(getenv("LVS_LEASE_READY")),resume=atoi(getenv("LVS_LEASE_RESUME"));
    if(write(ready,"H",1)!=1)_exit(124);
    struct pollfd p={.fd=resume,.events=POLLIN};
    if(poll(&p,1,2000)!=1)_exit(124);
    char ack;if(read(resume,&ack,1)!=1)_exit(124);
    return result;
}
''')
    from Modules.lvs_native_helpers import find_c_compiler,native_helper_build_command
    compiler=find_c_compiler();assert compiler
    command=native_helper_build_command(compiler,source,library)
    subprocess.run(command+['-shared','-fPIC','-ldl','-Wall','-Wextra','-Werror'],capture_output=True,check=True)
    return library


def run_thermal_stage_native_identity_fault_checks():
    import array,select,socket
    from smoke_tests.storage_thermal_foundation_checks import compile_guard
    with tempfile.TemporaryDirectory(prefix='lvs-native-identity-fault-') as root:
        guard=compile_guard(root);library=_compile_lease_fault_shim(root)
        for mode in ('replace_anchor','replace_pin','same_inode_pin','unlock','share_description','alias_close','same_inode_close','deadline','terminate','fail_lock'):
            f=NativeAdmissionFixture(Path(root)/mode,guard)
            parent,child=socket.socketpair(socket.AF_UNIX,socket.SOCK_SEQPACKET);parent.settimeout(2)
            ready_r,ready_w=os.pipe();resume_r,resume_w=os.pipe();process=None
            try:
                env=dict(os.environ,LD_PRELOAD=str(library),LVS_LEASE_FAULT=mode,LVS_LEASE_ANCHOR=str(f.state.fd),
                    LVS_LEASE_READY=str(ready_w),LVS_LEASE_RESUME=str(resume_r))
                deadline=time.monotonic()+.5 if mode=='deadline' else None
                argv=_native_gate_command(f,guard,child.fileno(),deadline=deadline)
                process=subprocess.Popen(argv,stdin=subprocess.DEVNULL,stdout=f.out,stderr=f.err,env=env,
                    pass_fds=(child.fileno(),f.state.fd,f.executable,ready_w,resume_r))
                child.close();os.close(ready_w);ready_w=None;os.close(resume_r);resume_r=None
                # Register the actual PID before OWN and descriptor offer.
                assert process.pid>0
                parent.sendall(b'OWN');assert parent.recv(128)==b'R'
                parent.sendmsg([b'F'],[(socket.SOL_SOCKET,socket.SCM_RIGHTS,array.array('i',[f.target]))])
                if mode!='fail_lock':
                    assert select.select([ready_r],[],[],2)[0],(mode,f.text())
                    assert os.read(ready_r,1)==b'H'
                    held=mode!='unlock'
                    _child_lock_probe(f.state.fd,f.state.identity,expect_blocked=held)
                    if mode=='replace_anchor':
                        # The original OFD is still held, despite the child's
                        # transport now referencing a different valid-looking file.
                        assert not f.state.revoke()
                    if mode=='deadline':time.sleep(max(0,deadline-time.monotonic())+.02)
                    if mode=='terminate':process.kill()
                    else:os.write(resume_w,b'X')
                code=process.wait(timeout=2)
                if mode in ('alias_close','same_inode_close'):
                    assert code==0 and 'COMMITTED' in f.text(),(mode,code,f.text())
                else:
                    assert code!=0 and 'COMMITTED' not in f.text(),(mode,code,f.text())
                    assert (mode=='terminate' or 'lease identity' in f.text() or 'OFD lock' in f.text() or 'stage admission lock' in f.text() or 'stage deadline' in f.text()),(mode,f.text())
                assert process.poll() is not None
                if mode=='terminate':assert f.state.revoke()
            finally:
                parent.close();child.close()
                for fd in (ready_r,ready_w,resume_r,resume_w):
                    if fd is not None:os.close(fd)
                if process is not None and process.poll() is None:process.kill();process.wait(timeout=2)
                f.close()
    print('  native critical-section evidence: transport/private-pin replacement, lost/failed/ambiguous locks REJECTED; both alias closures preserve kernel OFD ownership')


def _fresh_recovery_blocker(marker):
    reply=subprocess.run([sys.executable,'-B','-c',
        'import sys;from Modules.lvs_storage_thermal_recovery import blocker;print(blocker(sys.argv[1]))',str(marker)],
        capture_output=True,text=True,check=True,timeout=5)
    return reply.stdout.strip()


def run_thermal_production_lease_journal_checks():
    """Actual worker entrypoint, genuine kernel lease; no target access permitted."""
    from Modules.lvs_storage_thermal import canonical_lease_identity
    from Modules.lvs_storage_thermal_recovery import RecoveryScope,read_state
    with tempfile.TemporaryDirectory() as work:
        root=Path(work);state=SharedAdmission.create()
        try:
            expected=list(state.identity)
            for bad in ([],[1],[1,2,3],[True,2],[1,False],[-1,2],[1,-1],['1',2],{'dev':1,'ino':2},[1,2**64]):
                try:canonical_lease_identity(bad)
                except ValueError:pass
                else:raise AssertionError(('invalid identity accepted',bad))
            for kind,value in [('tuple',state.identity),('list',list(state.identity))]:
                marker=root/kind/'intent';scope=RecoveryScope(marker)
                scope.enter(lease_identity=value,admission=state)
                assert read_state(marker)['lease_identity']==expected
                assert read_state(marker)['state']=='ARMED' and _fresh_recovery_blocker(marker)
                scope.resolve(cleanup_confirmed=True);scope.close()
                assert read_state(marker)['state']=='CLEAN' and not _fresh_recovery_blocker(marker)
                scope=RecoveryScope(marker).enter(lease_identity=value,admission=state)
                scope.resolve(cleanup_confirmed=True);scope.close()
            marker=root/'mismatch'/'intent'
            try:RecoveryScope(marker).enter(lease_identity=[expected[0],expected[1]+1],admission=state)
            except ValueError:pass
            else:raise AssertionError('substituted authority accepted')
            assert not marker.exists()
            # Actual production worker receives tuple identity from SharedAdmission.
            # The synthetic runner checks durable protection before returning; target
            # opening is forbidden. Native admission itself is separately exercised
            # by NativeAdmissionFixture using the unchanged policy-test gate.
            for uncertain in (False,True):
                base=root/('uncertain' if uncertain else 'normal');base.mkdir()
                f=RunnerFixture(base);st=stage();st.duration_seconds=2
                lease=StageLease(10,os.getppid(),clock=f.clock,admission=state)
                directory=base/'worker';directory.mkdir();marker=base/'intent';calls=[]
                def gate():
                    assert read_state(marker)['state']=='ARMED'
                    calls.append('authorized');return True
                def synthetic_run(config,plan,output,**kwargs):
                    assert calls==['authorized'] and read_state(marker)['lease_identity']==expected
                    assert _fresh_recovery_blocker(marker)
                    if uncertain:f.runner.unconfirmed.append('synthetic unresolved ownership')
                    return output,dict(verdict='WARN',devices=[],executed_devices=[],cleanup_confirmed=not uncertain)
                with patch('Modules.lvs_storage_thermal_stage.default_runner',return_value=f.runner),patch.object(f.runner,'run',side_effect=synthetic_run),patch.object(f.targets,'open',side_effect=AssertionError('target open')),patch('Modules.lvs_storage_thermal_runner.capability',return_value=f.backend):
                    plan=inspect_stage(f.runner,stage_config(st));plan['decision_key']=decision_key(plan)
                    (directory/'request.json').write_text(json.dumps(dict(plan,supervisor_parent_pid=os.getppid(),recovery_marker=str(marker))))
                    assert worker(directory,gate=gate,lease=lease)==0
                assert calls==['authorized'] and not f.fd_open
                assert read_state(marker)['state']==('ARMED' if uncertain else 'CLEAN')
                assert bool(_fresh_recovery_blocker(marker))==uncertain
                # Each worker finalizes/revokes its lease; next case gets fresh authority.
                state.close();state=SharedAdmission.create();expected=list(state.identity)
        finally:state.close()
    print('  production lease: tuple/list ARMED read-back, actual worker gate, CLEAN/reentry and independent unresolved inspection PASS')


def run_thermal_native_registry_authority_checks():
    """Real children, both pidfd and sole-reaper fallback; never target devices."""
    from contextlib import nullcontext
    from Modules.lvs_storage_thermal_launch import OwnedProcess
    from Modules.lvs_storage_thermal_recovery import RecoveryScope,read_state
    with tempfile.TemporaryDirectory() as work:
        root=Path(work)
        for fallback in (False,True):
            for mode in ('public_pid','public_handle','pidfd_loss'):
                if mode=='pidfd_loss' and fallback:continue
                base=root/f'{fallback}-{mode}';base.mkdir();state=SharedAdmission.create()
                registry=StageLaunches(None,StageLease(time.monotonic()+10,os.getppid(),admission=state),base)
                marker=base/'intent';scope=RecoveryScope(marker).enter(lease_identity=state.identity,admission=state)
                victim=subprocess.Popen([sys.executable,'-B','-c','import time;time.sleep(30)'])
                row=dict(process=None,pid=None,phase='creation',cleanup_confirmed=False)
                registry.owned.append(row);process=None;held=None
                class Registration:
                    @property
                    def process(self):return row['process']
                    @process.setter
                    def process(self,p):registry._register(row,p)
                context=patch('os.pidfd_open',side_effect=OSError('forced fallback')) if fallback and hasattr(os,'pidfd_open') else nullcontext()
                try:
                    with context:
                        process=OwnedProcess([sys.executable,'-B','-c','import time;time.sleep(30)'],stage_bootstrap=True,start_new_session=False,owner=Registration())
                    real=process.authority_pid
                    assert row['pid']==real and real!=victim.pid
                    if mode=='public_pid':process.pid=victim.pid
                    elif mode=='public_handle':row['process']=victim
                    elif process.pidfd is not None:
                        held=process.pidfd;process.pidfd=None
                    else:continue
                    registry.stop(row,signal.SIGTERM)
                    if held is not None:
                        assert process.returncode is None and not registry._reconcile(row)
                        assert victim.poll() is None and _fresh_recovery_blocker(marker)
                        process.pidfd=held;held=None
                        registry.stop(row,signal.SIGTERM)
                    process.wait(timeout=3)
                    assert victim.poll() is None,'unrelated child signaled or reaped'
                    clean=registry._reconcile(row)
                    assert clean==(mode!='public_handle'),registry.snapshot()
                    if clean:
                        scope.resolve(cleanup_confirmed=True)
                    scope.close()
                    assert read_state(marker)['state']==('CLEAN' if clean else 'ARMED')
                    assert bool(_fresh_recovery_blocker(marker))!=clean
                    if mode=='public_handle':
                        # Explicit reconciliation can use the original private handle,
                        # but ambiguity is monotonic for this session's certificate.
                        row['process']=process
                        assert not registry._reconcile(row)
                    # Repeated cancellation after reap cannot affect the victim.
                    registry.stop(row,signal.SIGKILL);assert victim.poll() is None
                finally:
                    if process is not None:
                        if held is not None:process.pidfd=held
                        process.kill();process.wait(timeout=3)
                    victim.terminate();victim.wait(timeout=3)
                    if scope.fd is not None:scope.close()
                    state.close()
    print('  native registry: correct child signaled/reaped on pidfd/fallback, handle/pidfd loss stays ARMED, victim untouched PASS')


def run_thermal_native_registry_commit_checks():
    """The actual native policy-test bootstrap retains stable identity after OWN."""
    from contextlib import nullcontext
    from smoke_tests.storage_thermal_foundation_checks import compile_guard
    from Modules.lvs_storage_thermal_recovery import RecoveryScope,read_state
    with tempfile.TemporaryDirectory() as work:
        root=Path(work);guard=compile_guard(root)
        for fallback in (False,True):
            f=NativeAdmissionFixture(root/str(fallback),guard,seconds=8)
            victim=subprocess.Popen([sys.executable,'-B','-c','import time;time.sleep(30)'])
            marker=f.root/'intent';scope=RecoveryScope(marker).enter(lease_identity=f.state.identity,admission=f.state)
            try:
                # Substitution occurs at creation, before OWN, native setsid,
                # descriptor offer, admission and native policy-test execution.
                f.after_spawn=lambda p:setattr(p,'pid',victim.pid)
                context=patch('os.pidfd_open',side_effect=OSError('fallback')) if fallback and hasattr(os,'pidfd_open') else nullcontext()
                with context:p=f.launch()
                assert p.authority_pid!=p.pid and p.pid==victim.pid
                assert p.wait(timeout=3)==0 and 'COMMITTED' in f.text()
                f.launches.finish()
                assert f.launches.cleanup_confirmed and victim.poll() is None,f.launches.snapshot()
                assert f.launches.snapshot()['workers'][0]['pid']==p.authority_pid
                scope.resolve(cleanup_confirmed=f.launches.cleanup_confirmed);scope.close()
                assert read_state(marker)['state']=='CLEAN' and not _fresh_recovery_blocker(marker)
            finally:
                victim.terminate();victim.wait(timeout=3)
                if scope.fd is not None:scope.close()
                f.close()
    print('  native OWN/R/COMMITTED policy-test: public PID substitution cannot redirect child/group actions or reap; durable CLEAN is genuine PASS')
