"""Thermal-only normal-service regressions; no physical workload or root service."""
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
from unittest.mock import patch

from Modules.lvs_profile_models import ValidationProfile
from Modules.lvs_profile_validation import ProfileValidator
from Modules.lvs_workload_runner import WorkloadRunner
from Modules.lvs_dry_run import build_dry_run_plan
from smoke_tests.storage_thermal_stage_checks import stage, blocked, _run_primary_with_aux


def only_stage():
    s=stage();s.modules.cpu.enabled=False
    s.normalization.trim_start_seconds=s.normalization.trim_end_seconds=0
    return s


def ready(s):
    p=blocked(s);p.update(status='READY',requires_consent=False,reasons=[],runnable_devices=['fixture'])
    return p


def run_thermal_only_preflight_checks():
    runner=WorkloadRunner();s=only_stage();profile=ValidationProfile('thermal-only',stages=[s])
    for status in ('READY','BLOCKED','ERROR'):
        p=ready(s);p['status']=status
        with patch('Modules.lvs_storage_thermal_stage.preview',return_value=p):
            row=build_dry_run_plan(runner,profile,['fixture'])[0]
        assert not row['commands'] and row['workloads']==['storage_thermal']
        assert row['runnable']==(status=='READY'),row
        assert bool(row['issues'])==(status!='READY'),row
    s.modules.storage_thermal.enabled=False
    assert ProfileValidator().validate(profile,['fixture'])['errors']
    # A primary-enabled stage may continue when auxiliary readiness is blocked.
    s.modules.cpu.enabled=True;s.modules.storage_thermal.enabled=True
    with patch('Modules.lvs_storage_thermal_stage.preview',return_value=blocked(s)):
        row=build_dry_run_plan(runner,profile,['mixed'])[0]
    assert row['commands'] and row['runnable'],row
    s=only_stage();profile.stages=[s];p=ready(s);p['requires_consent']=True
    with patch('Modules.lvs_storage_thermal_stage.preview',return_value=p):
        assert not build_dry_run_plan(runner,profile,['pending consent'])[0]['runnable']


def run_thermal_only_lifecycle_checks():
    from Modules.lvs_storage_thermal_results import not_run
    with patch('smoke_tests.storage_thermal_stage_checks.stage',side_effect=only_stage):
        result,args,calls=_run_primary_with_aux(not_run('fixture unavailable'))
    assert result.stage_verdict=='not_applicable'
    assert result.stage_completion.stage_window.primary_workloads==[]
    assert result.stage_completion.stage_window.worker_results==[]
    assert result.stage_elapsed==2 and len(args['telemetry_times'])>=2
    assert calls.index('storage_admission_revoked')<calls.index('cpu_stopped')<calls.index('storage_finished')
    checks=[]
    def cancel():checks.append(1);return len(checks)>1
    with patch('smoke_tests.storage_thermal_stage_checks.stage',side_effect=only_stage):
        result,args,calls=_run_primary_with_aux(not_run('fixture stopped'),cancel_check=cancel)
    assert result.stage_aborted and result.stage_verdict=='aborted'
    assert result.stage_completion.stage_window.primary_workloads==[]


def run_thermal_only_service_checks():
    """Full ordinary run API/publication; injected unavailable auxiliary, no worker."""
    from Modules.linux_validation_suite_service import SuiteAppService
    from Modules.lvs_cli_compat import ValidationOrchestrator
    from Modules.lvs_settings import GlobalSettings
    from Modules.lvs_storage_thermal_results import error_result
    class Session:
        def __init__(self,*a,**k):pass
        def start(self):raise OSError('disposable unavailable-runtime fixture')
        def poll(self):return None
        def live_summary(self):return ''
        def revoke_admission(self):pass
        def request_stop(self,*a):pass
        def _latch_cleanup(self,*a):pass
        def finish(self,**k):return error_result('disposable unavailable-runtime fixture',cleanup_confirmed=True)
    with tempfile.TemporaryDirectory() as name:
        root=Path(name);s=only_stage();s.duration_seconds=1
        profile=ValidationProfile('Thermal only API',stages=[s]);profile.defaults.telemetry_interval_seconds=.1
        payload=asdict(profile)
        for stage_payload in payload['stages']:
            for key in ('analysis','gpu_evaluation'):
                if stage_payload.get(key) is None:stage_payload.pop(key,None)
        p=root/'profile.json';p.write_text(json.dumps(payload))
        settings=GlobalSettings();settings.settings_dir=str(root/'settings');settings.profiles_dir=str(root);settings.results_dir=str(root/'results');settings.keep_raw_telemetry=True
        cfg=root/'settings/global_settings.json';cfg.parent.mkdir();cfg.write_text(json.dumps(asdict(settings)))
        with patch('Modules.lvs_storage_thermal_stage.preview',side_effect=lambda stage:ready(stage)),patch('Modules.lvs_storage_thermal_stage.ThermalStageSession',Session):
            service=SuiteAppService(settings_path=cfg,orchestrator_factory=ValidationOrchestrator)
            setup=service.create_run_setup(p);setup.metadata.advanced_debug_logging=True
            result=service.run_profile_capture_output(p,setup=setup,metadata=setup.metadata,heatsoak_minutes=0)
        run=Path(result.run_dir);manifest=json.loads((run/'run_manifest.json').read_text());compat=json.loads((run/'parsed_results_custom.json').read_text())
        assert manifest['verdict']=='not_applicable',manifest['verdict']
        assert manifest['execution_completion']['complete']
        assert manifest['primary_validation']==compat['PrimaryValidation']
        assert compat['Result'].lower()=='not_applicable',compat['Result']
        assert compat['ReportSummary']['OutcomeClass']=='not_applicable'
        assert compat['ReportSummary']['DepartmentUseSummary']['Status']=='not_applicable'
        from Modules.lvs_report_helpers import clean_review_verdict_from_payload
        review=clean_review_verdict_from_payload(compat)
        assert review['EffectiveFinalVerdict']=='Not applicable' and review['RuleBasedVerdict']=='None',review
        assert manifest['stage_windows'][0]['worker_results']==[]
        assert manifest['storage_thermal_summary']['auxiliary_outcome']=='ERROR'
        assert (run/'raw_telemetry.csv').exists() and (run/'telemetry_source_map.json').exists()
        assert (run/'advanced_debug/advanced_debug_manifest.json').exists()
        text=(run/'run_summary.txt').read_text();assert 'verified_clean' not in text and 'No primary' in text,text


def run_thermal_only_verdict_checks():
    from Modules.lvs_run_verdict import combine_run_verdict
    from Modules.lvs_run_models import StageWindow
    from Modules.lvs_compat_export_helpers import compatibility_overall_result
    from Modules.lvs_run_completion_evidence import execution_completion
    assert combine_run_verdict(['not_applicable'])=='not_applicable'
    assert combine_run_verdict([' NOT_APPLICABLE '])=='not_applicable'
    for states,want in [(['not_applicable','pass'],'pass'),(['pass','not_applicable'],'pass'),(['not_applicable','fail'],'fail'),(['not_applicable','warning'],'warning')]:
        assert combine_run_verdict(states)==want
    assert combine_run_verdict(['not_applicable'],manual_abort=True)=='manually_aborted'
    w=StageWindow('s','Combined','thermal','2026-11-17T00:00:00','2026-11-17T00:00:02',0,2,2,0,0,verdict='not_applicable',primary_workloads=[])
    assert compatibility_overall_result([w])=='Not_Applicable'
    m=dict(verdict='not_applicable',ended=w.ended_iso,stage_windows=[asdict(w)])
    assert execution_completion(m)==dict(status='completed',complete=True,reason='Run endpoint and terminal stage evidence recorded.')
    m['stage_windows'][0]['worker_results']=[dict(status='failed',error_count=1)]
    assert execution_completion(m)['status']=='fail'  # contradictory failure is never erased
