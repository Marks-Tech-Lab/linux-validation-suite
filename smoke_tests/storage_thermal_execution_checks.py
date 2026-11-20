"""Foreground preparation and passive inspection; no sudo or device access."""
from contextlib import contextmanager
from copy import deepcopy
import stat
import threading
from types import SimpleNamespace
from unittest.mock import Mock, patch
from Modules.lvs_profile_models import StageConfig, StageModules, ModuleCpu, ModuleStorageThermal, ValidationProfile
from Modules.lvs_storage_thermal_execution import prepare, execution_scope, execution_plan
from Modules.lvs_storage_thermal_stage import preview
from Modules.lvs_run_launch import RunLaunchCoordinator, RunLaunchRequest


def fixture():
    stage=StageConfig('s1','CPU',60,modules=StageModules(cpu=ModuleCpu(enabled=True),storage_thermal=ModuleStorageThermal(enabled=True)))
    return ValidationProfile('boundary',stages=[stage]),stage


def run_thermal_passive_inspection_checks():
    from Modules.lvs_storage_thermal_runtime import inspect
    from Modules.lvs_storage_thermal_stage import stage_config
    from Modules.lvs_run_preflight import RunPreflightManager
    profile,stage=fixture()
    with patch('Modules.lvs_storage_thermal_runtime.owned_path'),patch('pathlib.Path.lstat',return_value=SimpleNamespace(st_mode=stat.S_IFSOCK|0o660,st_uid=0)),patch('Modules.lvs_storage_thermal_runtime.rpc',side_effect=AssertionError('preview RPC')),patch('Modules.lvs_storage_thermal_launch.prepare',side_effect=AssertionError('preview load')):
        result=inspect(stage_config(stage));assert result['inspection_only'] and result['status']=='DEFERRED' and not result['execution_ready']
    manager=RunPreflightManager(profile_loader=None,orchestrator=SimpleNamespace(dry_run=lambda *a:dict(validation={},enabled_stage_count=1,runnable_stage_count=1)),profile_reports=None,ensure_ready=lambda:(_ for _ in ()).throw(AssertionError('preflight authentication')))
    manager.run_preflight(SimpleNamespace(profile_path='fixture',profile=profile,labels=[],label_source_info={}))
    stage.modules.storage_thermal.enabled=False
    with patch('Modules.lvs_storage_thermal_runtime.inspect',side_effect=AssertionError('disabled probe')):
        assert preview(stage) is None


def run_thermal_execution_preparation_checks():
    profile,stage=fixture();manager=Mock();manager.sudo_noninteractive_ready.return_value=False
    passive=dict(status='DEFERRED',inspection_only=True,preparation_required=True,reasons=[])
    authoritative=dict(status='READY',configuration={},reasons=[])
    setup=SimpleNamespace(profile=profile);request=RunLaunchRequest('fixture',setup=setup)
    launcher=RunLaunchCoordinator(SimpleNamespace())
    with patch('Modules.lvs_storage_thermal_runtime.inspect',return_value=passive),patch('Modules.lvs_storage_thermal_runtime.preview',return_value=authoritative)as backend:
        denied=Mock(return_value=False)
        plans=launcher.prepare_execution(request,privilege_manager=manager,authorize=denied)
        refused=list(plans.values())[0]
        assert refused['status']=='BLOCKED' and not refused['inspection_only'] and not refused['preparation_required']
        denied.assert_called_once();backend.assert_not_called()
        manager.sudo_noninteractive_ready.return_value=True
        plans=launcher.prepare_execution(request,privilege_manager=manager,authorize=lambda:(_ for _ in ()).throw(AssertionError('cached readiness prompted')))
        assert list(plans.values())[0]['execution_ready'];backend.assert_called_once()
        with execution_scope(profile):assert execution_plan(stage)['execution_ready']
        with execution_scope(profile):assert execution_plan(stage)['status']=='BLOCKED'
        launcher.prepare_execution(request,privilege_manager=manager,authorize=None)
        stage.duration_seconds=61
        with execution_scope(profile):assert execution_plan(stage)['status']=='BLOCKED'
        stage.duration_seconds=60
        launcher.prepare_execution(request,privilege_manager=manager,authorize=None)
        profile.stages.append(deepcopy(stage))
        with execution_scope(profile):assert execution_plan(stage)['status']=='BLOCKED'
        profile.stages.pop();stage.enabled=False
        assert prepare(profile,manager,None)=={}
    stage.enabled=True
    with patch('Modules.lvs_storage_thermal_runtime.inspect',return_value=dict(status='BLOCKED',reasons=['missing runtime'])),patch('Modules.lvs_storage_thermal_runtime.preview')as backend:
        authorization=Mock();prepare(profile,manager,authorization);authorization.assert_not_called();backend.assert_not_called()
    errors=[]
    def worker():
        try:prepare(profile,manager,lambda:errors.append('prompt'))
        except RuntimeError:errors.append('blocked')
    t=threading.Thread(target=worker);t.start();t.join();assert errors==['blocked']


def run_thermal_frontend_authorization_checks():
    from Modules.lvs_cli_run import RunCliAdapter
    from Modules.lvs_tui_run_execution_adapter import TuiRunExecutionAdapterMixin
    from Modules.lvs_privileged import PrivilegedTelemetryManager
    manager=Mock();manager.prepare_session.return_value=True
    cli=RunCliAdapter(SimpleNamespace(privileged_telemetry=manager,_input=lambda *a:'y'))
    with patch('sys.stdin.isatty',return_value=True):assert cli._authorize_thermal_execution()
    events=[]
    @contextmanager
    def suspend():
        events.append('suspend')
        try:yield
        finally:events.append('restore')
    owner=SimpleNamespace(suspend=suspend,service=SimpleNamespace(privileged_telemetry=manager))
    with patch('builtins.input',return_value='y'):assert TuiRunExecutionAdapterMixin._authorize_thermal_execution(owner)
    assert events==['suspend','restore']
    settings=SimpleNamespace(privileged_helper_enabled=True)
    telemetry=PrivilegedTelemetryManager(settings)
    with patch('os.geteuid',return_value=1000),patch('shutil.which',return_value='/usr/bin/sudo'),patch.object(telemetry,'_sudo_noninteractive_ready',return_value=False),patch.object(telemetry,'_prepare_session',side_effect=AssertionError('background prompt')):
        assert not telemetry.ensure_ready(allow_prompt=False)


def run_thermal_prepared_executor_checks():
    from pathlib import Path
    from Modules.lvs_run_executor import RunExecutor
    from Modules.lvs_run_metadata import RunMetadata
    from Modules.lvs_storage_thermal_stage import stage_config, apply_profile_decisions
    profile,stage=fixture()
    plan=dict(status='READY',configuration=stage_config(stage).to_dict(),requires_consent=False,backend={},devices=[],targets=[],reasons=[])
    manager=Mock();manager.sudo_noninteractive_ready.return_value=True
    seen=[]
    def execute(path,p,labels,metadata,**kwargs):
        result=preview(p.stages[0])
        entries=[dict(storage_thermal=result)]
        apply_profile_decisions(p,entries)
        seen.append(result['execution_ready'])
        assert result['execution_permitted']
        return Path('/tmp/synthetic-boundary-result')
    executor=RunExecutor(settings=SimpleNamespace(),profile_loader=None,orchestrator=SimpleNamespace(run=execute),default_run_metadata=lambda path:RunMetadata(),ensure_enhanced_telemetry_ready=lambda:False,run_heatsoak_if_requested=lambda *a,**k:True)
    setup=SimpleNamespace(profile=profile,labels=['CPU'])
    request=RunLaunchRequest(Path('fixture'),setup=setup)
    launcher=RunLaunchCoordinator(executor)
    before=deepcopy(profile)
    for capture in (False,True):
        with patch('Modules.lvs_storage_thermal_runtime.inspect',return_value=dict(status='DEFERRED')),patch('Modules.lvs_storage_thermal_runtime.preview',return_value=plan):
            launcher.prepare_execution(request,privilege_manager=manager,authorize=None)
        result=launcher.run_prepared_capture(request) if capture else launcher.run_prepared_direct(request)
    assert seen==[True,True]
    assert profile.stages==before.stages
    # A heatsoak cancellation consumes the ticket without launching anything.
    profile._thermal_execution_preparation={'stale':{}}
    executor.run_heatsoak_if_requested=lambda *a,**k:False
    assert launcher.run_prepared_direct(request) is None
    assert not hasattr(profile,'_thermal_execution_preparation')
