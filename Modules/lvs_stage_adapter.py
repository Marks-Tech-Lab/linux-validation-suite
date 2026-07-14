#!/usr/bin/env python3
"""Shared per-stage orchestration adapter."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from Modules.lvs_stage_execution import execute_stage_runtime
from Modules.lvs_stage_postprocess import apply_completed_stage_bookkeeping
from Modules.lvs_stage_run_context import (
    apply_cpu_tuning_execution,
    cpu_stage_start_suffix,
    cpu_tune_summary_suffix,
    gpu_stage_start_suffix,
    internal_gpu_backend_set,
    stage_run_context_from_plan,
)


@dataclass(frozen=True)
class StageAdapterResult:
    run_aborted: bool
    should_break_run: bool


def run_stage_adapter(
    *,
    profile_name: str,
    stage_window_cls: Callable[..., Any],
    stage: Any,
    display_name: str,
    run_dir: Path,
    stage_plan: Dict[str, Any],
    stage_windows: List[Any],
    executed_plan: List[Dict[str, Any]],
    run_aborted: bool,
    abort_on_worker_error: bool,
    abort_on_system_fault: bool,
    abort_run_on_stage_abort: bool,
    abort_on_fail_threshold: bool,
    telemetry_interval_seconds: float,
    progress_interval_seconds: float,
    cpu_tuning_policy_for_stage: Callable[[Any], str],
    resolve_cpu_execution: Callable[[Any], Dict[str, Any]],
    strict_threshold_recommendation_warnings: Callable[[], Optional[bool]],
    gpu_target_by_id: Callable[[str], Optional[Dict[str, Any]]],
    write_gpu_safety_marker: Callable[..., None],
    start_intel_gpu_top_sidecar: Callable[..., Optional[Dict[str, Any]]],
    stop_intel_gpu_top_sidecar: Callable[[Optional[Dict[str, Any]]], Optional[Dict[str, Any]]],
    clear_gpu_safety_marker: Callable[[], None],
    launch_stage_processes: Callable[[Any, str, Path], List[Any]],
    stop_stage_processes: Callable[[List[Any]], None],
    telemetry_collect_once: Callable[[], None],
    poll_stage_process_failures: Callable[[List[Any], str], List[Dict[str, Any]]],
    stage_sensor_events: Callable[[Any], List[Dict[str, Any]]],
    maybe_retune_gpu_processes: Callable[[List[Any], float, float, List[Dict[str, Any]]], List[Any]],
    stage_target_gpu_progress_summary: Callable[[List[Any], float], str],
    effective_gpu_retune_cooldown_seconds: Callable[[float], float],
    serialize_gpu_worker: Callable[[Any], Dict[str, Any]],
    worker_result_events_func: Callable[[List[Any], str], Any],
    utilization_events_func: Callable[[Any], List[Dict[str, Any]]],
    backend_effectiveness_events_func: Callable[[Any], List[Dict[str, Any]]],
    vram_attainment_events_func: Callable[[Any], List[Dict[str, Any]]],
    collect_stage_faults: Callable[[str, str, Any], List[Dict[str, Any]]],
    capture_stage_start: Callable[..., None],
    capture_stage_end: Callable[..., None],
    now_local_iso: Callable[[], str],
    monotonic: Callable[[], float],
    sleep: Callable[[float], None],
    future_local_iso: Callable[[float], str],
    format_duration_hms: Callable[[float], str],
    print_cpu_tune_start: Callable[[str, str], None],
    print_cpu_tune_end: Callable[[str, float, str, str], None],
    print_stage_start: Callable[[str, str, str, str, str, str], None],
    print_stage_abort: Callable[[str, str], None],
    print_stage_end: Callable[[str, float, str, int], None],
    print_progress: Callable[[str], None],
    operator_stop_source: str,
    on_operator_stop: Callable[[Dict[str, Any]], None],
    cancel_check: Optional[Callable[[], bool]] = None,
) -> StageAdapterResult:
    stage_context = stage_run_context_from_plan(stage_plan)
    cpu_backend = stage_context.cpu_backend
    gpu_3d_backend_resolved = stage_context.gpu_3d_backend_resolved
    vram_backend_resolved = stage_context.vram_backend_resolved
    cpu_mode_requested = stage_context.cpu_mode_requested
    cpu_mode_resolved = stage_context.cpu_mode_resolved
    cpu_kernel_flavor = stage_context.cpu_kernel_flavor
    cpu_tuning_policy = stage_context.cpu_tuning_policy
    cpu_tuned_avg_power_w = None
    gpu_3d_backend_preference = stage_context.gpu_3d_backend_preference
    vram_backend_preference = stage_context.vram_backend_preference
    gpu_target_mode = stage_context.gpu_target_mode
    gpu_targets = stage_context.gpu_targets
    gpu_workers_initial = stage_context.gpu_workers_initial
    gpu_retune_events: List[Dict[str, Any]] = []
    stage_error_events: List[Dict[str, Any]] = []
    stage_failure_reasons: List[str] = []
    stage_verdict = "pass"
    stage_aborted = False
    stage_abort_reason = ""

    if stage.modules.cpu.enabled:
        tune_started_iso = now_local_iso()
        tune_started_monotonic = monotonic()
        print_cpu_tune_start(tune_started_iso, cpu_tuning_policy_for_stage(stage.modules.cpu))
        cpu_tuning_context = apply_cpu_tuning_execution(
            stage_plan,
            resolve_cpu_execution(stage.modules.cpu),
        )
        cpu_backend = cpu_tuning_context.cpu_backend
        cpu_mode_requested = cpu_tuning_context.cpu_mode_requested
        cpu_mode_resolved = cpu_tuning_context.cpu_mode_resolved
        cpu_kernel_flavor = cpu_tuning_context.cpu_kernel_flavor
        cpu_tuning_policy = cpu_tuning_context.cpu_tuning_policy
        cpu_tuned_avg_power_w = cpu_tuning_context.cpu_tuned_avg_power_w
        tune_elapsed = monotonic() - tune_started_monotonic
        print_cpu_tune_end(
            now_local_iso(),
            tune_elapsed,
            cpu_kernel_flavor or "-",
            cpu_tune_summary_suffix(cpu_tuning_context.cpu_tune_results),
        )

    cpu_suffix = cpu_stage_start_suffix(
        cpu_backend=cpu_backend,
        cpu_mode_requested=cpu_mode_requested,
        cpu_mode_resolved=cpu_mode_resolved,
        cpu_kernel_flavor=cpu_kernel_flavor,
        cpu_tuned_avg_power_w=cpu_tuned_avg_power_w,
    )
    gpu_suffix = gpu_stage_start_suffix(stage, stage_context)
    stage_started_iso = now_local_iso()
    stage_start = monotonic()
    print_stage_start(
        stage_started_iso,
        stage.name,
        format_duration_hms(stage.duration_seconds),
        future_local_iso(stage.duration_seconds),
        cpu_suffix,
        gpu_suffix,
    )
    capture_stage_start(
        stage_name=display_name,
        stage_id=stage.id,
        timestamp_iso=stage_started_iso,
    )
    stage_execution = execute_stage_runtime(
        profile_name=profile_name,
        stage_window_cls=stage_window_cls,
        stage=stage,
        display_name=display_name,
        run_dir=run_dir,
        stage_plan=stage_plan,
        stage_started_iso=stage_started_iso,
        stage_start=stage_start,
        cpu_backend=cpu_backend,
        cpu_mode_requested=cpu_mode_requested,
        cpu_mode_resolved=cpu_mode_resolved,
        cpu_kernel_flavor=cpu_kernel_flavor,
        cpu_tuning_policy=cpu_tuning_policy,
        cpu_tuned_avg_power_w=cpu_tuned_avg_power_w,
        gpu_3d_backend_preference=gpu_3d_backend_preference,
        gpu_3d_backend_resolved=gpu_3d_backend_resolved,
        vram_backend_preference=vram_backend_preference,
        vram_backend_resolved=vram_backend_resolved,
        gpu_target_mode=gpu_target_mode,
        gpu_targets=gpu_targets,
        gpu_workers_initial=gpu_workers_initial,
        gpu_lifecycle_backends=internal_gpu_backend_set(gpu_3d_backend_resolved, vram_backend_resolved),
        gpu_retune_events=gpu_retune_events,
        stage_error_events=stage_error_events,
        stage_failure_reasons=stage_failure_reasons,
        stage_verdict=stage_verdict,
        stage_aborted=stage_aborted,
        stage_abort_reason=stage_abort_reason,
        run_aborted=run_aborted,
        abort_on_worker_error=abort_on_worker_error,
        abort_on_fail_threshold=abort_on_fail_threshold,
        telemetry_interval_seconds=telemetry_interval_seconds,
        progress_interval_seconds=progress_interval_seconds,
        strict_threshold_recommendation_warnings=strict_threshold_recommendation_warnings(),
        gpu_target_by_id=gpu_target_by_id,
        write_gpu_safety_marker=write_gpu_safety_marker,
        start_intel_gpu_top_sidecar=start_intel_gpu_top_sidecar,
        stop_intel_gpu_top_sidecar=stop_intel_gpu_top_sidecar,
        clear_gpu_safety_marker=clear_gpu_safety_marker,
        launch_stage_processes=launch_stage_processes,
        stop_stage_processes=stop_stage_processes,
        telemetry_collect_once=telemetry_collect_once,
        poll_stage_process_failures=poll_stage_process_failures,
        stage_sensor_events=stage_sensor_events,
        maybe_retune_gpu_processes=lambda processes, elapsed, duration: maybe_retune_gpu_processes(
            processes,
            elapsed,
            duration,
            gpu_retune_events,
        ),
        stage_target_gpu_progress_summary=stage_target_gpu_progress_summary,
        effective_gpu_retune_cooldown_seconds=effective_gpu_retune_cooldown_seconds,
        serialize_gpu_worker=serialize_gpu_worker,
        worker_result_events_func=worker_result_events_func,
        utilization_events_func=utilization_events_func,
        backend_effectiveness_events_func=backend_effectiveness_events_func,
        vram_attainment_events_func=vram_attainment_events_func,
        now_local_iso=now_local_iso,
        monotonic=monotonic,
        sleep=sleep,
        format_duration_hms=format_duration_hms,
        print_progress=print_progress,
        operator_stop_source=operator_stop_source,
        on_operator_stop=on_operator_stop,
        cancel_check=cancel_check,
    )
    stage_completion = stage_execution.stage_completion
    if stage_execution.stage_aborted:
        print_stage_abort(
            stage_execution.stage_ended_iso,
            stage_execution.stage_abort_reason or "abort condition triggered",
        )
    print_stage_end(
        stage_execution.stage_ended_iso,
        stage_execution.stage_elapsed,
        stage_execution.stage_verdict,
        stage_completion.issue_count,
    )
    post_stage = apply_completed_stage_bookkeeping(
        stage_window=stage_completion.stage_window,
        stage_plan=stage_plan,
        stage_windows=stage_windows,
        executed_plan=executed_plan,
        stage_failure_reasons=stage_execution.stage_failure_reasons,
        run_aborted=stage_execution.run_aborted,
        stage_aborted=stage_execution.stage_aborted,
        stage_abort_reason=stage_execution.stage_abort_reason,
        operator_stop_requested=stage_execution.operator_stop_requested,
        abort_run_on_stage_abort=abort_run_on_stage_abort,
        abort_on_system_fault=abort_on_system_fault,
        stage_id=stage.id,
        stage_name=display_name,
        stage_started_iso=stage_started_iso,
        stage_ended_iso=stage_execution.stage_ended_iso,
        collect_stage_faults=lambda window: collect_stage_faults(stage_started_iso, stage_execution.stage_ended_iso, window),
        capture_stage_end=capture_stage_end,
    )
    return StageAdapterResult(
        run_aborted=post_stage.run_aborted,
        should_break_run=post_stage.should_break_run,
    )
