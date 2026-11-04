"""Effective setup evidence, including preflight-only blocked attempts."""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from Modules.lvs_cpu_targeting import select_common_kernel
from Modules.lvs_profile_loader import ProfileLoader
from Modules.lvs_profile_models import ValidationProfile, StageConfig
from Modules.lvs_profile_report_artifacts import ProfileReportArtifactWriter, atomic_preflight_json
from Modules.lvs_profile_validation import ProfileValidator
from Modules.lvs_run_flow import RunFlowCoordinator
from Modules.lvs_run_metadata import RunMetadata
from Modules.lvs_run_preflight import RunPreflightManager
from Modules.lvs_service_models import RunSetupState
from Modules.lvs_service_profile_readiness import SuiteProfileReadinessServiceMixin
from Modules.lvs_tui_run_setup_flow import run_setup_readiness_text


def fixture(root):
    loader = ProfileLoader(root/'profiles')
    original = ValidationProfile(profile_name='Effective readiness', stages=[
        StageConfig(id='one',name='CPU',duration_seconds=120),
        StageConfig(id='two',name='CPU 2',duration_seconds=120),
    ])
    for stage in original.stages:
        stage.modules.cpu.enabled = True
        stage.modules.cpu.instruction_set = 'sve'
    path = root/'profiles'/'test.json'
    path.write_text(json.dumps(loader.profile_payload(original,['CPU','CPU 2'])))
    class Directories:
        def new_report_dir(self,suffix):
            p=root/'results'/suffix;p.mkdir(parents=True,exist_ok=True);return p
    writer=ProfileReportArtifactWriter(loader,Directories())
    reports=SimpleNamespace(save_cli_preflight_report=writer.save_cli_preflight_report,
                            preflight_summary_text=lambda r:json.dumps(r))
    class Orchestrator:
        validator=ProfileValidator()
        def dry_run(self,path,profile,labels):
            plan=[]
            for stage in profile.stages:
                isa=stage.modules.cpu.instruction_set
                selected=select_common_kernel(architecture='arm64',requested_mode=isa,
                                               common_flavors=['scalar','neon_fp32_fma'])
                commands=[['native-helper','--kernel-flavor',selected]] if selected and stage.enabled else []
                issues=[] if selected else [f"CPU instruction set '{isa}' is not supported across the complete target CPU set {list(range(8))}",
                                            'enabled workloads produced no runnable commands']
                plan.append(dict(stage_id=stage.id,enabled=stage.enabled,runnable=bool(commands),commands=commands,
                                 cpu_mode_requested=isa,issues=issues,warnings=['retained warning'],
                                 cpu_targeting={'target_cpu_ids':list(range(8)),'capability_scope':'linux_aarch64_hwcap_common_set',
                                     'per_cpu_capabilities':{str(i):['scalar','neon_fp32_fma'] for i in range(8)}}))
            runnable=any(s['runnable'] for s in plan if s['enabled'])
            return dict(profile_name=profile.profile_name,runnable=runnable,plan=plan,
                        enabled_stage_count=sum(s['enabled'] for s in plan),runnable_stage_count=sum(s['runnable'] for s in plan),
                        validation={'errors':[e for s in plan if s['enabled'] for e in s['issues']], 'warnings':['retained warning']},
                        backend_details={'cpu_native_helper':{'available':True,'sve_i8mm_build':{'status':'compiled'},
                            'isa_capabilities':{'sve_i8mm_available':False,'hwcap2':0}}})
    manager=RunPreflightManager(profile_loader=loader,orchestrator=Orchestrator(),profile_reports=reports)
    setup=RunSetupState(profile_path=path,profile=deepcopy(original),labels=['CPU','CPU 2'],metadata=RunMetadata(),
                        original_profile=deepcopy(original),original_labels=['CPU','CPU 2'])
    return loader,writer,manager,RunFlowCoordinator(manager),setup


def prepare(manager,flow,setup):
    readiness=manager.inspect_profile_context(setup.profile_path,setup.profile,setup.labels)
    return flow.prepare_setup_run(readiness,setup,save_blocked_report=False)


def run_effective_preflight_blocked_checks():
    from Modules.lvs_stage_diagnostics import complete_cpu_diagnostic_preview
    from Modules.lvs_workload_cpu_memory import WorkloadCpuMemoryMixin
    from Modules.lvs_profile_models import ModuleCpu
    class NonSve(WorkloadCpuMemoryMixin):
        def _cpu_machine(self):return 'arm64'
        def _cpu_target_plan(self,cpu):return {'target_cpu_ids':list(range(8))}
        def _cpu_helper_supported_kernel_flavors(self,cpu_id=None):return ['scalar','neon','neon_fp32_fma']
    cpu=ModuleCpu(enabled=True,instruction_set='sve_i8mm')
    evidence=complete_cpu_diagnostic_preview(NonSve(),cpu,{})
    assert evidence['target_cpu_ids']==list(range(8)) and evidence['selected_kernel_flavor']==''
    assert "'sve_i8mm'" in evidence['unavailable_reason']
    assert complete_cpu_diagnostic_preview(None,cpu,evidence) is evidence
    failed=SimpleNamespace(_cpu_capability_plan=lambda cpu:(_ for _ in ()).throw(OSError('probe unavailable')))
    assert complete_cpu_diagnostic_preview(failed,cpu,{})=={'diagnostic_capability_error':'probe unavailable'}
    for debug in [False,True]:
        with TemporaryDirectory() as tmp:
            root=Path(tmp);loader,writer,manager,flow,setup=fixture(root)
            setup.metadata.advanced_debug_logging=debug
            for s in setup.profile.stages:s.modules.cpu.instruction_set='sve_i8mm'
            prepared=prepare(manager,flow,setup);directory=prepared.preflight_action.report_dir
            assert prepared.preflight_action.blocked and directory.is_dir()
            payload=json.loads((directory/'preflight_report.json').read_text())
            assert payload['status']=='BLOCKED' and payload['result']=='Blocked' and payload['execution_started'] is False
            assert payload['advanced_debug_logging'] is debug and payload['preflight']['runnable_stage_count']==0
            assert all(s['commands']==[] for s in payload['preflight']['plan'])
            assert 'sve_i8mm' in str(payload['preflight']['validation']['errors'])
            assert payload['preflight']['plan'][0]['cpu_targeting']['target_cpu_ids']==list(range(8))
            assert payload['source_provenance']['source']['status']=='complete'
            assert payload['hardware_identity']['architecture']
            assert payload['backend_details']['cpu_native_helper']['sve_i8mm_build']['status']=='compiled'
            assert len(payload['run_local_overrides'])==2
            assert json.loads((directory/'original_profile.json').read_text())==payload['original_profile']
            assert json.loads((directory/'profile_used.json').read_text())==payload['effective_profile']
            assert prepare(manager,flow,setup).preflight_action.report_dir==directory
            assert not list(directory.glob('run_manifest.json')) and not list(directory.glob('worker*'))
            assert 'PASS' not in (directory/'preflight_summary.txt').read_text()
            assert loader.load_profile(setup.profile_path).stages[0].modules.cpu.instruction_set=='sve'


def run_effective_preflight_ready_checks():
    with TemporaryDirectory() as tmp:
        loader,writer,manager,flow,setup=fixture(Path(tmp))
        first=prepare(manager,flow,setup).preflight_action.report_dir
        setup.profile.stages[0].modules.cpu.instruction_set='scalar'
        setup.profile.stages[1].modules.cpu.instruction_set='neon_fp32_fma'
        setup.profile.stages[1].enabled=False
        setup.labels[0]='Run-local label'
        ready=prepare(manager,flow,setup);p=ready.preflight_action.report_dir
        assert p!=first and (first/'preflight_report.json').exists()
        d=json.loads((p/'preflight_report.json').read_text())
        assert d['status']=='READY' and d['result']=='Ready' and not ready.preflight_action.blocked
        assert d['completion_scope']=='readiness_only_not_workload_execution'
        assert d['preflight']['plan'][0]['commands']==[['native-helper','--kernel-flavor','scalar']]
        assert d['preflight']['plan'][1]['commands']==[] and d['preflight']['plan'][1]['enabled'] is False
        assert d['original_profile']['segment_labels'][0]=='CPU' and d['effective_profile']['segment_labels'][0]=='Run-local label'
        assert len(d['run_local_overrides'])==5 # two ISA selections, enabled, label, embedded labels
        # Independent original-profile diagnostics stay original and labelled.
        original=manager.inspect_profile(setup.profile_path)
        report=manager.run_preflight(original).report
        dry=writer.save_dry_run_report(setup.profile_path,report)
        assert json.loads((dry/'dry_run_diagnostics.json').read_text())['diagnostic_scope']=='original_profile_dry_run'
        assert json.loads((dry/'profile_used.json').read_text())!=d['effective_profile']


def run_effective_preflight_frontend_checks():
    with TemporaryDirectory() as tmp:
        loader,writer,manager,flow,setup=fixture(Path(tmp))
        for s in setup.profile.stages:s.modules.cpu.instruction_set='sve_i8mm'
        class Service(SuiteProfileReadinessServiceMixin):pass
        service=Service();service.run_preflight_manager=manager;service.run_flow=flow
        text=run_setup_readiness_text(service,setup)
        assert 'Status: blocked' in text and 'Preflight report:' in text
        assert service.run_setup_preflight_decision(setup).report_dir.is_dir()
        assert service.prepare_setup_run_flow(setup).preflight_action.blocked
        # CLI shares this same coordinator; no launch method is needed or invoked.
        assert prepare(manager,flow,setup).preflight_action.runnable_stage_count==0


def run_effective_preflight_publication_checks():
    with TemporaryDirectory() as tmp:
        root=Path(tmp);path=root/'preflight_report.json';atomic_preflight_json(path,{'status':'BLOCKED'})
        with patch('Modules.lvs_profile_report_artifacts.os.replace',side_effect=OSError('injected persistence failure')):
            try:atomic_preflight_json(path,{'status':'READY'})
            except OSError:pass
            else:raise AssertionError('publication error hidden')
        assert json.loads(path.read_text())=={'status':'BLOCKED'} and list(root.iterdir())==[path]
        loader,writer,manager,flow,setup=fixture(root)
        with patch('Modules.lvs_profile_report_artifacts.atomic_preflight_json',side_effect=OSError('disk full')):
            text=run_setup_readiness_text(SimpleNamespace(prepare_setup_run_flow=lambda setup,**kw:prepare(manager,flow,setup)),setup)
            assert 'preview unavailable' in text and 'disk full' in text
