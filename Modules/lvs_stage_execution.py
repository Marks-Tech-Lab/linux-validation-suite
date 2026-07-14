#!/usr/bin/env python3
"""Shared stage execution service shell."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from Modules.lvs_stage_completion import StageCompletionRecord, complete_stage_record
from Modules.lvs_stage_evaluation import evaluate_completed_stage
from Modules.lvs_stage_lifecycle import start_stage_lifecycle, stop_stage_lifecycle
from Modules.lvs_stage_live_loop import run_stage_live_loop
from Modules.lvs_stability_events import new_unique_events


@dataclass(frozen=True)
class StageExecutionResult:
    stage_completion: StageCompletionRecord
    stage_processes: List[Any]
    stage_ended_iso: str
    stage_end: float
    stage_elapsed: float
    stage_verdict: str
    stage_aborted: bool
    stage_abort_reason: str
    stage_error_events: List[Dict[str, Any]]
    stage_failure_reasons: List[str]
    operator_stop_requested: bool
    run_aborted: bool


def execute_stage_runtime(
    *,
    profile_name: str,
    stage_window_cls: Callable[..., Any],
    stage: Any,
    display_name: str,
    run_dir: Path,
    stage_plan: Dict[str, Any],
    stage_started_iso: str,
    stage_start: float,
    cpu_kernel_flavor: str,
    cpu_backend: str,
    cpu_mode_requested: str,
    cpu_mode_resolved: str,
    cpu_tuning_policy: str,
    cpu_tuned_avg_power_w: Optional[float],
    gpu_3d_backend_preference: str,
    gpu_3d_backend_resolved: str,
    vram_backend_preference: str,
    vram_backend_resolved: str,
    gpu_target_mode: str,
    gpu_targets: List[str],
    gpu_workers_initial: List[Dict[str, Any]],
    gpu_lifecycle_backends: Set[str],
    gpu_retune_events: List[Dict[str, Any]],
    stage_error_events: List[Dict[str, Any]],
    stage_failure_reasons: List[str],
    stage_verdict: str,
    stage_aborted: bool,
    stage_abort_reason: str,
    run_aborted: bool,
    abort_on_worker_error: bool,
    abort_on_fail_threshold: bool,
    telemetry_interval_seconds: float,
    progress_interval_seconds: float,
    strict_threshold_recommendation_warnings: Optional[bool],
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
    maybe_retune_gpu_processes: Callable[[List[Any], float, float], List[Any]],
    stage_target_gpu_progress_summary: Callable[[List[Any], float], str],
    effective_gpu_retune_cooldown_seconds: Callable[[float], float],
    serialize_gpu_worker: Callable[[Any], Dict[str, Any]],
    worker_result_events_func: Callable[[List[Any], str], Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]],
    utilization_events_func: Callable[[Any], List[Dict[str, Any]]],
    backend_effectiveness_events_func: Callable[[Any], List[Dict[str, Any]]],
    vram_attainment_events_func: Callable[[Any], List[Dict[str, Any]]],
    now_local_iso: Callable[[], str],
    monotonic: Callable[[], float],
    sleep: Callable[[float], None],
    format_duration_hms: Callable[[float], str],
    print_progress: Callable[[str], None],
    operator_stop_source: str,
    on_operator_stop: Callable[[Dict[str, Any]], None],
    cancel_check: Optional[Callable[[], bool]] = None,
) -> StageExecutionResult:
    operator_stop_requested = False
    stage_lifecycle = start_stage_lifecycle(
        profile_name=profile_name,
        stage_id=stage.id,
        stage_name=display_name,
        run_dir=run_dir,
        stage_plan=stage_plan,
        gpu_backends=gpu_lifecycle_backends,
        gpu_targets=gpu_targets,
        gpu_target_by_id=gpu_target_by_id,
        write_gpu_safety_marker=write_gpu_safety_marker,
        start_intel_gpu_top_sidecar=start_intel_gpu_top_sidecar,
    )
    stage_processes = launch_stage_processes(stage, cpu_kernel_flavor, run_dir)
    intel_gpu_top_sidecar_summary: Optional[Dict[str, Any]] = None
    try:
        live_loop_result = run_stage_live_loop(
            stage_window_cls=stage_window_cls,
            stage=stage,
            display_name=display_name,
            stage_started_iso=stage_started_iso,
            stage_start=stage_start,
            stage_processes=stage_processes,
            telemetry_collect_once=telemetry_collect_once,
            telemetry_interval_seconds=telemetry_interval_seconds,
            stage_error_events=stage_error_events,
            stage_failure_reasons=stage_failure_reasons,
            stage_verdict=stage_verdict,
            stage_aborted=stage_aborted,
            stage_abort_reason=stage_abort_reason,
            abort_on_worker_error=abort_on_worker_error,
            abort_on_fail_threshold=abort_on_fail_threshold,
            gpu_retune_events=gpu_retune_events,
            progress_interval_seconds=progress_interval_seconds,
            poll_stage_process_failures=poll_stage_process_failures,
            stage_sensor_events=stage_sensor_events,
            maybe_retune_gpu_processes=maybe_retune_gpu_processes,
            stage_target_gpu_progress_summary=stage_target_gpu_progress_summary,
            effective_gpu_retune_cooldown_seconds=effective_gpu_retune_cooldown_seconds,
            now_local_iso=now_local_iso,
            monotonic=monotonic,
            sleep=sleep,
            format_duration_hms=format_duration_hms,
            print_progress=print_progress,
            cancel_check=cancel_check,
        )
        stage_processes = live_loop_result.stage_processes
        stage_verdict = live_loop_result.stage_verdict
        stage_aborted = live_loop_result.stage_aborted
        stage_abort_reason = live_loop_result.stage_abort_reason
    except KeyboardInterrupt:
        operator_stop_requested = True
        stage_verdict = "aborted"
        stage_aborted = True
        run_aborted = True
        stage_abort_reason = "operator stop requested; saving partial run results"
        stop_event = {
            "timestamp": now_local_iso(),
            "category": "operator_stop",
            "severity": "warning",
            "stage": display_name,
            "source": operator_stop_source,
            "message": stage_abort_reason,
            "details": {
                "elapsed_seconds": round(max(0.0, monotonic() - stage_start), 2),
                "profile_name": profile_name,
            },
        }
        if new_unique_events([stop_event], stage_error_events):
            stage_error_events.append(stop_event)
        stage_failure_reasons.append(stage_abort_reason)
        on_operator_stop(stop_event)
    finally:
        stop_stage_processes(stage_processes)
        intel_gpu_top_sidecar_summary = stop_stage_lifecycle(
            stage_lifecycle,
            stop_intel_gpu_top_sidecar=stop_intel_gpu_top_sidecar,
            clear_gpu_safety_marker=clear_gpu_safety_marker,
        )

    stage_ended_iso = now_local_iso()
    stage_end = monotonic()
    stage_elapsed = stage_end - stage_start
    stage_evaluation = evaluate_completed_stage(
        stage_window_cls=stage_window_cls,
        stage=stage,
        display_name=display_name,
        stage_started_iso=stage_started_iso,
        stage_ended_iso=stage_ended_iso,
        stage_start=stage_start,
        stage_end=stage_end,
        stage_elapsed=stage_elapsed,
        stage_processes=stage_processes,
        serialize_gpu_worker=serialize_gpu_worker,
        operator_stop_requested=operator_stop_requested,
        abort_on_worker_error=abort_on_worker_error,
        abort_on_fail_threshold=abort_on_fail_threshold,
        stage_verdict=stage_verdict,
        stage_aborted=stage_aborted,
        stage_abort_reason=stage_abort_reason,
        stage_error_events=stage_error_events,
        stage_failure_reasons=stage_failure_reasons,
        gpu_target_mode=gpu_target_mode,
        gpu_targets=gpu_targets,
        gpu_workers_initial=gpu_workers_initial,
        gpu_3d_backend_preference=gpu_3d_backend_preference,
        gpu_3d_backend_resolved=gpu_3d_backend_resolved,
        vram_backend_preference=vram_backend_preference,
        vram_backend_resolved=vram_backend_resolved,
        worker_result_events_func=worker_result_events_func,
        sensor_events_func=stage_sensor_events,
        utilization_events_func=utilization_events_func,
        backend_effectiveness_events_func=backend_effectiveness_events_func,
        vram_attainment_events_func=vram_attainment_events_func,
    )
    stage_verdict = stage_evaluation.stage_verdict
    stage_aborted = stage_evaluation.stage_aborted
    stage_abort_reason = stage_evaluation.stage_abort_reason
    stage_completion = complete_stage_record(
        stage_window_cls=stage_window_cls,
        stage=stage,
        display_name=display_name,
        stage_started_iso=stage_started_iso,
        stage_ended_iso=stage_ended_iso,
        stage_start=stage_start,
        stage_end=stage_end,
        stage_elapsed=stage_elapsed,
        stage_processes=stage_processes,
        serialize_gpu_worker=serialize_gpu_worker,
        stage_plan=stage_plan,
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
        gpu_retune_events=gpu_retune_events,
        stage_verdict=stage_verdict,
        stage_failure_reasons=stage_failure_reasons,
        stage_error_events=stage_error_events,
        stage_worker_results=stage_evaluation.stage_worker_results,
        intel_gpu_top_sidecar_summary=intel_gpu_top_sidecar_summary,
        strict_threshold_recommendation_warnings=strict_threshold_recommendation_warnings,
        gpu_workers_final=stage_evaluation.gpu_workers_final,
    )
    return StageExecutionResult(
        stage_completion=stage_completion,
        stage_processes=stage_processes,
        stage_ended_iso=stage_ended_iso,
        stage_end=stage_end,
        stage_elapsed=stage_elapsed,
        stage_verdict=stage_verdict,
        stage_aborted=stage_aborted,
        stage_abort_reason=stage_abort_reason,
        stage_error_events=stage_error_events,
        stage_failure_reasons=stage_failure_reasons,
        operator_stop_requested=operator_stop_requested,
        run_aborted=run_aborted,
    )
