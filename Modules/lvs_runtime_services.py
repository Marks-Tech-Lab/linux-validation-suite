#!/usr/bin/env python3
"""Shared backend service graph construction for CLI and UI frontends."""

from __future__ import annotations

from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, Callable, Optional, Type

from .lvs_dependency_reports import DependencyReportManager
from .lvs_option_defaults import DEFAULT_CASE_OPTIONS, DEFAULT_CPU_COOLER_OPTIONS, DEFAULT_PSU_RATING_OPTIONS
from .lvs_post_run import PostRunManager
from .lvs_pre_import_sanity import PreImportSanityFacade
from .lvs_profile_creation import ProfileCreationController
from .lvs_profile_edit_controller import ProfileEditController
from .lvs_profile_editor import ProfileEditor
from .lvs_profile_loader import ProfileLoader
from .lvs_profile_reports import ProfileReportManager
from .lvs_profile_save import ProfileSaveController
from .lvs_result_artifacts import ResultArtifactFacade
from .lvs_result_comparison import ResultComparisonFacade
from .lvs_result_reports import ResultReportManager
from .lvs_result_validation import ResultValidationFacade
from .lvs_run_executor import RunExecutor
from .lvs_run_flow import RunFlowCoordinator
from .lvs_run_launch import RunLaunchCoordinator
from .lvs_run_preflight import RunPreflightManager
from .lvs_run_setup import RunSetupManager
from .lvs_summary_text import SummaryTextBuilder


def normalize_runtime_settings(
    settings: Any,
    *,
    normalize_text_list: Callable[[list[str], list[str]], list[str]],
    profile_loader_type: Type[ProfileLoader] = ProfileLoader,
) -> None:
    settings.case_options = normalize_text_list(settings.case_options, DEFAULT_CASE_OPTIONS)
    settings.psu_rating_options = normalize_text_list(settings.psu_rating_options, DEFAULT_PSU_RATING_OPTIONS)
    settings.cpu_cooler_options = normalize_text_list(settings.cpu_cooler_options, DEFAULT_CPU_COOLER_OPTIONS)
    if not str(settings.suite_department or "").strip():
        settings.suite_department = "Production"
    settings.profile_menu_groups = profile_loader_type.normalize_menu_groups(settings.profile_menu_groups)


@dataclass
class RuntimeServices:
    profile_loader: Any
    orchestrator: Any
    workload_runner: Any
    summary_exporter: Any
    result_reports: ResultReportManager
    result_validation: ResultValidationFacade
    result_comparison: ResultComparisonFacade
    pre_import_sanity: PreImportSanityFacade
    result_artifacts: ResultArtifactFacade
    profile_reports: ProfileReportManager
    profile_editor: ProfileEditor
    profile_edit_controller: ProfileEditController
    profile_creation: ProfileCreationController
    profile_save: ProfileSaveController
    post_run_manager: PostRunManager
    dependency_reports: DependencyReportManager
    run_preflight_manager: RunPreflightManager
    run_flow: RunFlowCoordinator
    run_setup_manager: RunSetupManager
    run_executor: RunExecutor
    run_launcher: RunLaunchCoordinator

    def bind_to(self, target: Any) -> None:
        for field in fields(self):
            setattr(target, field.name, getattr(self, field.name))


def build_runtime_services(
    *,
    settings: Any,
    orchestrator_factory: Callable[[Any], Any],
    ensure_ready: Callable[[], bool],
    run_heatsoak_if_requested: Callable[..., Any],
    environment_mode_label: Callable[[], str],
    profile_loader_type: Type[ProfileLoader] = ProfileLoader,
    summary_exporter: Optional[Any] = None,
    ensure_example_profile: bool = False,
) -> RuntimeServices:
    profile_loader = profile_loader_type(Path(settings.profiles_dir), settings.profile_menu_groups)
    if ensure_example_profile:
        profile_loader.ensure_example_profile()
    orchestrator = orchestrator_factory(settings)
    selected_summary_exporter = summary_exporter
    if selected_summary_exporter is None:
        selected_summary_exporter = getattr(orchestrator, "summary_exporter", None) or SummaryTextBuilder()
    workload_runner = getattr(orchestrator, "workload_runner", None)

    result_reports = ResultReportManager(Path(settings.results_dir), selected_summary_exporter)
    result_validation = ResultValidationFacade(Path(settings.results_dir))
    result_comparison = ResultComparisonFacade()
    pre_import_sanity = PreImportSanityFacade(
        Path(settings.results_dir),
        result_validation,
        selected_summary_exporter,
    )
    result_artifacts = ResultArtifactFacade(Path(settings.results_dir))
    profile_reports = ProfileReportManager(profile_loader, orchestrator.validator, result_reports)
    profile_editor = ProfileEditor()
    profile_edit_controller = ProfileEditController(profile_editor)
    profile_creation = ProfileCreationController(profile_editor)
    profile_save = ProfileSaveController(profile_editor, profile_loader, orchestrator.validator)
    post_run_manager = PostRunManager(settings, selected_summary_exporter)
    dependency_reports = DependencyReportManager(
        settings,
        orchestrator,
        post_run_manager.google_drive_readiness,
    )
    run_preflight_manager = RunPreflightManager(
        profile_loader=profile_loader,
        orchestrator=orchestrator,
        profile_reports=profile_reports,
        ensure_ready=ensure_ready,
    )
    run_flow = RunFlowCoordinator(run_preflight_manager)
    run_setup_manager = RunSetupManager(lambda: settings, profile_loader, environment_mode_label)
    run_executor = RunExecutor(
        settings=settings,
        profile_loader=profile_loader,
        orchestrator=orchestrator,
        default_run_metadata=run_setup_manager.default_run_metadata,
        ensure_enhanced_telemetry_ready=ensure_ready,
        run_heatsoak_if_requested=run_heatsoak_if_requested,
    )
    run_launcher = RunLaunchCoordinator(run_executor)
    return RuntimeServices(
        profile_loader=profile_loader,
        orchestrator=orchestrator,
        workload_runner=workload_runner,
        summary_exporter=selected_summary_exporter,
        result_reports=result_reports,
        result_validation=result_validation,
        result_comparison=result_comparison,
        pre_import_sanity=pre_import_sanity,
        result_artifacts=result_artifacts,
        profile_reports=profile_reports,
        profile_editor=profile_editor,
        profile_edit_controller=profile_edit_controller,
        profile_creation=profile_creation,
        profile_save=profile_save,
        post_run_manager=post_run_manager,
        dependency_reports=dependency_reports,
        run_preflight_manager=run_preflight_manager,
        run_flow=run_flow,
        run_setup_manager=run_setup_manager,
        run_executor=run_executor,
        run_launcher=run_launcher,
    )
