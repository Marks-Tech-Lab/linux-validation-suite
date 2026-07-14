#!/usr/bin/env python3
"""Top-level validation run orchestration."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .lvs_core import APP_NAME, APP_VERSION, format_duration_hms, now_local_iso
from .lvs_run_bootstrap import bootstrap_run_artifacts
from .lvs_run_completion import complete_validation_run
from .lvs_run_event_presenter import CliRunEventPresenter
from .lvs_run_lifecycle import future_local_iso
from .lvs_run_stage_loop import run_effective_stages
from .lvs_settings import DEFAULT_STAGE_PROGRESS_INTERVAL_SECONDS
from .lvs_system_info import SystemInfoCollector
from .lvs_telemetry_collector import TelemetryCollector


def execute_validation_run(
    orchestrator: Any,
    *,
    profile_path: Path,
    profile: Any,
    labels: List[str],
    metadata: Any,
    stage_window_cls: Callable[..., Any],
    run_dir: Optional[Path] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
    operator_stop_source: str = "cli",
) -> Path:
    preflight = orchestrator.dry_run(profile_path, profile, labels)
    if not preflight["runnable"]:
        raise RuntimeError("preflight failed; fix diagnostics before running")

    run_dir = Path(run_dir) if run_dir is not None else orchestrator.make_run_dir(profile.profile_name)
    abort_on_worker_error = bool(orchestrator.settings.abort_on_worker_error)
    abort_on_system_fault = bool(orchestrator.settings.abort_on_system_fault)
    abort_run_on_stage_abort = bool(orchestrator.settings.abort_run_on_stage_abort)

    started_iso = now_local_iso()
    started_monotonic = time.monotonic()
    telemetry = TelemetryCollector(
        interval_seconds=profile.defaults.telemetry_interval_seconds,
        runtime_environment=orchestrator.settings.runtime_environment,
        privileged_helper_enabled=orchestrator.settings.privileged_helper_enabled,
    )
    stage_windows: List[Any] = []
    executed_plan: List[Dict[str, Any]] = []
    run_aborted = False
    recovery_report = preflight.get("gpu_recovery") or orchestrator._build_gpu_recovery_report()
    run_events = CliRunEventPresenter(started_iso=started_iso)
    bootstrap = bootstrap_run_artifacts(
        app_name=APP_NAME,
        app_version=APP_VERSION,
        profile_path=profile_path,
        profile=profile,
        labels=labels,
        metadata=metadata,
        preflight=preflight,
        run_dir=run_dir,
        started_iso=started_iso,
        runtime_environment=orchestrator.workload_runner.runtime_environment(),
        backends=orchestrator.workload_runner.detect_backends(),
        backend_details=orchestrator.workload_runner.backend_details(),
        abort_on_fail_threshold=bool(orchestrator.settings.abort_on_fail_threshold),
        abort_on_worker_error=abort_on_worker_error,
        abort_on_system_fault=abort_on_system_fault,
        abort_run_on_stage_abort=abort_run_on_stage_abort,
        privileged_helper_enabled=orchestrator.settings.privileged_helper_enabled,
        recovery_report=recovery_report,
        collect_system_info=lambda profile_name, segment_labels, profile_file, run_metadata, privileged: SystemInfoCollector(
            privileged_helper_enabled=privileged
        ).collect(profile_name, segment_labels, profile_file, run_metadata),
        print_run_header=run_events.run_header,
        print_stage_skip=run_events.stage_skip,
        print_run_start=run_events.run_start,
    )
    run_dir = bootstrap.run_dir
    effective_profile = bootstrap.effective_profile
    skipped_stages = bootstrap.skipped_stages
    recovery_report = bootstrap.recovery_report
    system_info = bootstrap.system_info
    manifest_payload = bootstrap.manifest_payload
    advanced_debug = bootstrap.advanced_debug

    stage_loop = run_effective_stages(
        profile_name=profile.profile_name,
        effective_profile=effective_profile,
        labels=labels,
        preflight_plan=preflight["plan"],
        stage_window_cls=stage_window_cls,
        run_dir=run_dir,
        stage_windows=stage_windows,
        executed_plan=executed_plan,
        run_aborted=run_aborted,
        abort_on_worker_error=abort_on_worker_error,
        abort_on_system_fault=abort_on_system_fault,
        abort_run_on_stage_abort=abort_run_on_stage_abort,
        abort_on_fail_threshold=orchestrator.settings.abort_on_fail_threshold,
        telemetry_interval_seconds=profile.defaults.telemetry_interval_seconds,
        progress_interval_seconds=DEFAULT_STAGE_PROGRESS_INTERVAL_SECONDS,
        cpu_tuning_policy_for_stage=orchestrator.workload_runner._cpu_tuning_policy,
        resolve_cpu_execution=lambda cpu_module: orchestrator.workload_runner.resolve_cpu_execution(cpu_module, tune_max_power=True),
        strict_threshold_recommendation_warnings=lambda stage: orchestrator._stage_strict_threshold_recommendation_warnings(profile, stage),
        gpu_target_by_id=lambda target_id: orchestrator.workload_runner._gpu_target_by_id(target_id),
        write_gpu_safety_marker=orchestrator._write_gpu_safety_marker,
        start_intel_gpu_top_sidecar=orchestrator._start_intel_gpu_top_sidecar,
        stop_intel_gpu_top_sidecar=orchestrator._stop_intel_gpu_top_sidecar,
        clear_gpu_safety_marker=orchestrator._clear_gpu_safety_marker,
        launch_stage_processes=orchestrator.workload_runner.launch_stage_processes,
        stop_stage_processes=orchestrator.workload_runner.stop_stage_processes,
        telemetry_collect_once=telemetry.collect_once,
        poll_stage_process_failures=lambda processes, name: orchestrator._poll_stage_process_failures(processes, name),
        stage_sensor_events=lambda window: orchestrator._stage_sensor_events(window, telemetry),
        maybe_retune_gpu_processes=lambda processes, display_name, retune_events, elapsed, duration: orchestrator._maybe_retune_gpu_processes(
            processes,
            telemetry,
            display_name,
            retune_events,
            elapsed,
            duration,
        ),
        stage_target_gpu_progress_summary=lambda processes, elapsed: orchestrator._stage_target_gpu_progress_summary(
            telemetry,
            processes,
            elapsed,
        ),
        effective_gpu_retune_cooldown_seconds=lambda duration: orchestrator._effective_gpu_retune_cooldown_seconds(duration),
        serialize_gpu_worker=orchestrator.workload_runner.serialize_gpu_worker,
        worker_result_events_func=lambda processes, name: orchestrator._worker_result_events(processes, name),
        utilization_events_func=lambda window: orchestrator._stage_target_gpu_utilization_events(window, telemetry),
        backend_effectiveness_events_func=lambda window: orchestrator._stage_gpu_backend_effectiveness_events(window, telemetry),
        vram_attainment_events_func=lambda window: orchestrator._stage_vram_target_attainment_events(window, telemetry),
        collect_stage_faults=lambda started, ended, window: orchestrator._faults_for_stage(
            orchestrator.fault_collector.collect(started, ended),
            window,
        ),
        capture_stage_start=advanced_debug.capture_stage_start,
        capture_stage_end=advanced_debug.capture_stage_end,
        now_local_iso=now_local_iso,
        monotonic=time.monotonic,
        sleep=time.sleep,
        future_local_iso=future_local_iso,
        format_duration_hms=format_duration_hms,
        print_cpu_tune_start=run_events.cpu_tune_start,
        print_cpu_tune_end=run_events.cpu_tune_end,
        print_stage_start=run_events.stage_start,
        print_stage_abort=run_events.stage_abort,
        print_stage_end=run_events.stage_end,
        print_progress=print,
        operator_stop_source=operator_stop_source,
        on_operator_stop=run_events.operator_stop,
        cancel_check=cancel_check,
    )
    run_aborted = stage_loop.run_aborted

    complete_validation_run(
        run_dir=run_dir,
        manifest_payload=manifest_payload,
        app_name=APP_NAME,
        app_version=APP_VERSION,
        profile=profile,
        metadata=metadata,
        started_iso=started_iso,
        started_monotonic=started_monotonic,
        system_info=system_info,
        telemetry=telemetry,
        stage_windows=stage_windows,
        executed_plan=executed_plan,
        recovery_report=recovery_report,
        skipped_stages=skipped_stages,
        run_aborted=run_aborted,
        keep_raw_telemetry=orchestrator.settings.keep_raw_telemetry,
        export_compatibility_json=orchestrator.settings.export_compatibility_json,
        export_extended_json=orchestrator.settings.export_extended_json,
        segment_parser=orchestrator.segment_parser,
        exporter=orchestrator.exporter,
        summary_exporter=orchestrator.summary_exporter,
        stage_sensor_events=lambda window: orchestrator._stage_sensor_events(window, telemetry),
        collect_kernel_faults=orchestrator.fault_collector.collect,
        faults_for_stage=orchestrator._faults_for_stage,
        capture_run_end=advanced_debug.capture_run_end,
        run_events=run_events,
        now_local_iso=now_local_iso,
        monotonic=time.monotonic,
    )
    return run_dir
