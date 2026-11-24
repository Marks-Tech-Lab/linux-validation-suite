"""Foreground review through production adapters; no privilege or device access."""
import asyncio
from contextlib import contextmanager, redirect_stdout
from copy import deepcopy
import io
from itertools import product
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
from types import SimpleNamespace
from unittest.mock import Mock, patch

from Modules.lvs_run_launch import RunLaunchCoordinator, RunLaunchRequest
from Modules.lvs_storage_thermal_execution import key, schedule, preparation_text, release_preparation, execution_scope
from Modules.lvs_storage_thermal_stage import stage_config
from smoke_tests.storage_thermal_execution_checks import fixture


def plan_for(stage, status='READY', ready=('disk-a',), excluded=()):
    return dict(status=status, execution_ready=True, backend=dict(status='available'), configuration=stage_config(stage).to_dict(),
                runnable_devices=list(ready), blocked_devices=list(excluded), partial_coverage=bool(excluded),
                targets=[dict(device_id=d, rate=dict(effective_iops=8, effective_bps=524288)) for d in ready],
                devices=[dict(device_id=d, selected=True, reasons=['fixture blocker']) for d in excluded], reasons=[])


def run_thermal_access_presentation_checks():
    from Modules.lvs_profile_report_text import storage_thermal_request_text, storage_thermal_access_help
    from Modules.lvs_storage_thermal_results import readiness_lines
    from smoke_tests.configuration_workflow_checks import Service, _source
    from smoke_tests.cli_configuration_checks import Host
    profile, stage = fixture();config = stage.modules.storage_thermal
    assert 'exclusive' in storage_thermal_request_text(config) and 'inactive physical SATA/SAS HDDs only' in storage_thermal_request_text(config)
    exclusive = plan_for(stage)
    config.access_mode = 'shared_readonly_opt_in';config.aggregate_iops_limit = 8;config.aggregate_bps_limit = 524288
    shared = plan_for(stage)
    assert 'experimental shared read-only' in storage_thermal_request_text(config)
    assert 'mounted or unmounted' in storage_thermal_request_text(config)
    lines = readiness_lines(dict(plan=[dict(enabled=True, storage_thermal=p) for p in (exclusive, shared)]))
    assert sum('Access contract:' in s for s in lines) == 2
    assert any('exclusive' in s for s in lines) and any('shared read-only' in s for s in lines)
    with TemporaryDirectory() as name:
        service = Service(Path(name));source = _source(service);before = source.read_bytes()
        p = service.create_profile_edit(source).profile;p.stages[0].modules.storage_thermal.enabled = True
        host = Host(service, ['']);out = io.StringIO()
        with redirect_stdout(out):host.profile_cli.configure_stage_workloads(p, 0, ['CPU'], run_only=True)
        assert storage_thermal_access_help() in out.getvalue() and source.read_bytes() == before
    before = deepcopy(profile)
    for p, expected in ((shared, 'ELIGIBLE TARGETS'),
                        (dict(shared, blocked_devices=['disk-b'], partial_coverage=True), 'PARTIAL COVERAGE'),
                        (dict(exclusive, status='BLOCKED', runnable_devices=[]), 'ZERO ELIGIBLE DRIVES'),
                        (dict(shared, backend=dict(status='unavailable',reasons=['fio unavailable'])), 'PREPARATION FAILED / UNAVAILABLE'),
                        (dict(exclusive, execution_ready=False), 'PREPARATION FAILED / UNAVAILABLE')):
        text = preparation_text(profile, {key(stage): p})
        assert expected in text and 'no workloads started' in text and '1. Continue' in text and '2. Return to setup' in text
    assert profile == before


def run_thermal_preparation_review_checks():
    profile, stage = fixture();request = RunLaunchRequest(Path('fixture'), setup=SimpleNamespace(profile=profile))
    launcher = RunLaunchCoordinator(Mock());plans = {key(stage): plan_for(stage)}
    for outcome in ('return', 'exception', 'interrupt', 'continue'):
        lease = Mock();profile._thermal_execution_preparation = dict(stages=schedule(profile), plans=plans, lease=lease)
        def review(text):
            assert 'disk-a' in text and 'planned 8 IOPS' in text
            if outcome == 'exception':raise RuntimeError('display failed')
            if outcome == 'interrupt':raise KeyboardInterrupt()
            return outcome == 'continue'
        try:accepted = launcher.review_execution(request, plans, review=review)
        except (RuntimeError, KeyboardInterrupt):assert outcome in ('exception', 'interrupt')
        else:assert accepted is (outcome == 'continue')
        if outcome == 'continue':
            lease.close.assert_not_called()
            with execution_scope(profile):pass
        lease.close.assert_called_once();assert not hasattr(profile, '_thermal_execution_preparation')
        release_preparation(profile);lease.close.assert_called_once()
    stage.modules.storage_thermal.enabled = False
    review = Mock(side_effect=AssertionError('disabled prompt'))
    assert launcher.review_execution(request, {}, review=review);review.assert_not_called()
    stage.modules.storage_thermal.enabled = True
    # Failure after startup must release the acquired hold and leave a blocked,
    # configuration-bound ticket, allowing a truthful primary-only continuation.
    lease = Mock();manager = Mock();manager.sudo_noninteractive_ready.return_value = False
    with patch('Modules.lvs_storage_thermal_runtime.inspect', return_value=dict(status='DEFERRED', on_demand_startup=True)), \
         patch('Modules.lvs_storage_thermal_transient.prepare_candidate', return_value={}), \
         patch('Modules.lvs_storage_thermal_transient.approval_text', return_value='fixture approval'), \
         patch('Modules.lvs_storage_thermal_transient.start_and_hold', return_value=lease), \
         patch('Modules.lvs_storage_thermal_runtime.preview', side_effect=KeyError('incomplete response')):
        failed = launcher.prepare_execution(request, privilege_manager=manager, authorize=lambda:True)
    lease.close.assert_called_once();assert 'PREPARATION FAILED' in preparation_text(profile, failed)
    assert launcher.review_execution(request, failed, review=lambda text:True)
    with execution_scope(profile):pass
    lease = Mock();profile._thermal_execution_preparation = dict(stages=schedule(profile), plans=plans, lease=lease)
    stage.duration_seconds += 1
    def stale_review(text):
        assert 'PREPARATION FAILED' in text and 'ELIGIBLE TARGETS' not in text
        return True  # primary-only continuation; no stale preparation survives
    assert launcher.review_execution(request, plans, review=stale_review)
    lease.close.assert_called_once();assert not hasattr(profile, '_thermal_execution_preparation')
    stage.duration_seconds -= 1
    # Background review cannot prompt or discard a valid foreground hold.
    lease = Mock();profile._thermal_execution_preparation = dict(lease=lease);errors = []
    def background():
        try:launcher.review_execution(request, plans, review=review)
        except RuntimeError:errors.append(True)
    t = threading.Thread(target=background);t.start();t.join();assert errors == [True]
    review.assert_not_called();lease.close.assert_not_called();release_preparation(profile)


def run_thermal_review_frontend_checks():
    from Modules.lvs_cli_run import RunCliAdapter
    from Modules.lvs_tui_run_execution_adapter import TuiRunExecutionAdapterMixin
    from Modules.lvs_run_metadata import RunMetadata
    from Modules.lvs_service_models import FrontendActionSpec

    @contextmanager
    def runtime(profile, stage, lease, coverage='ready'):
        plan = dict(plan_for(stage), installed_runtime=dict(runtime_mode='lvs.thermal.transient.data.v1'))
        if coverage == 'partial':plan.update(blocked_devices=['disk-b'],partial_coverage=True)
        if coverage == 'zero':plan.update(status='BLOCKED',runnable_devices=[])
        if coverage == 'recovery':plan.update(status='BLOCKED',runnable_devices=[],eligibility_status='ELIGIBLE',reasons=['unresolved recovery obligation'])
        with patch('Modules.lvs_storage_thermal_runtime.inspect', return_value=dict(status='DEFERRED')), \
             patch('Modules.lvs_storage_thermal_runtime.preview', return_value=plan,
                   side_effect=OSError('authorization unavailable') if coverage=='failure' else None), \
             patch('Modules.lvs_storage_thermal_transient.Hold', return_value=lease):yield

    outcomes = dict(ready='ELIGIBLE TARGETS',partial='PARTIAL COVERAGE',zero='ZERO ELIGIBLE DRIVES',failure='PREPARATION FAILED / UNAVAILABLE',recovery='PREPARATION FAILED / UNAVAILABLE')
    for answer, coverage in product(('1', '2', ''), outcomes):
        profile, stage = fixture();lease = Mock();events = [];manager = Mock();manager.sudo_noninteractive_ready.return_value = True
        def execute(path, **kwargs):
            assert events == ['review'];events.append('primary')
            with execution_scope(kwargs['setup'].profile):pass
        coordinator = RunLaunchCoordinator(SimpleNamespace(run_profile_direct=execute))
        path = Path('fixture');readiness = SimpleNamespace(profile=profile, labels=['CPU'])
        def prepared(unused, setup, **kwargs):
            return SimpleNamespace(launch_request=RunLaunchRequest.from_setup(setup), preflight_decision=SimpleNamespace(report={}), preflight_action=SimpleNamespace(blocked=False, skip_notice=''))
        def get_input(prompt):
            if prompt.startswith('Choose [2]'):events.append('review');return answer
            return '1'
        owner = SimpleNamespace(_pending_heatsoak_minutes=0, profile_loader=SimpleNamespace(list_profiles=lambda:[path]),
            _input=get_input, _profile_choice_text=lambda p:'fixture', run_launcher=coordinator, privileged_telemetry=manager,
            run_flow=SimpleNamespace(inspect_profile=lambda p:SimpleNamespace(readiness=readiness, errors=[], warnings=[], blocked=False), prepare_setup_run=prepared))
        app = RunCliAdapter(owner);app._run_setup_review=lambda *args:RunMetadata()
        with runtime(profile, stage, lease, coverage), patch('Modules.lvs_cli_run.clear_cli_screen'), \
             patch('Modules.lvs_cli_run.compact_cli_preflight_summary', return_value=''), \
             patch('Modules.lvs_cli_run.cli_live_run_supported', return_value=False), redirect_stdout(io.StringIO()) as out:
            app.new_run()
        assert events == (['review', 'primary'] if answer == '1' else ['review'])
        assert outcomes[coverage] in out.getvalue()
        if coverage in ('ready','partial'):lease.close.assert_called_once()
        else:lease.close.assert_not_called()
        assert not hasattr(profile, '_thermal_execution_preparation')

    class App(TuiRunExecutionAdapterMixin):
        def _handle_sync_run_setup_action(self, action):pass
        def _prepare_run_confirmation_flow(self, **kwargs):return self.flow
        def _set_detail(self, value):self.detail=value
        def _set_status(self, value):pass
        def set_timer(self, *args):pass
        @contextmanager
        def suspend(self):yield
        async def _show_run_active_sidebar(self):pass
        def _run_profile_thread(self, profile):raise AssertionError('real execution forbidden')

    async def tui():
        for answer, coverage in product(('1', '2', '', 'eof'), outcomes):
            profile, stage = fixture();lease=Mock();events=[];manager=Mock();manager.sudo_noninteractive_ready.return_value=True
            coordinator=RunLaunchCoordinator(Mock());path=Path('fixture')
            setup=SimpleNamespace(profile_path=path, profile=profile, heatsoak_minutes=0)
            app=App();app.run_setup=setup;app.view_mode='setup';app.selected_profile=SimpleNamespace(path=path,name='fixture')
            app.confirm_run=True;app.run_in_progress=False;app.run_cancel_event=threading.Event();app.run_status_tracker=Mock()
            app.service=SimpleNamespace(run_launcher=coordinator, privileged_telemetry=manager,
                setup_action_specs=lambda s:[FrontendActionSpec('u','run_selected')])
            app.flow=SimpleNamespace(launch_request=RunLaunchRequest(path,setup=setup),preflight_action=SimpleNamespace(blocked=False))
            def get_input(prompt):
                events.append('review')
                if answer=='eof':raise EOFError()
                return answer
            with runtime(profile,stage,lease,coverage),patch('builtins.input',side_effect=get_input), \
                 patch('Modules.lvs_tui_run_execution_adapter.threading.Thread') as thread,redirect_stdout(io.StringIO())as out:
                app.action_run_selected();assert events==['review']
                if answer=='1':
                    thread.return_value.start.assert_called_once();lease.close.assert_not_called()
                    with execution_scope(profile):pass
                else:
                    thread.assert_not_called();assert not app.run_in_progress and not app.confirm_run
                    assert 'Run not started' in app.detail
                assert outcomes[coverage] in out.getvalue()
                if coverage in ('ready','partial'):lease.close.assert_called_once()
                else:lease.close.assert_not_called()
            await asyncio.sleep(0)
    asyncio.run(tui())
