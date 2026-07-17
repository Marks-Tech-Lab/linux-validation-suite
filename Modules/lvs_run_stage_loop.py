#!/usr/bin/env python3
"""Shared run-level stage-loop orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from Modules.lvs_stage_adapter import run_stage_adapter
from Modules.lvs_profile_models import stage_execution_mode


@dataclass(frozen=True)
class StageLoopResult:
    run_aborted: bool


def run_effective_stages(
    *,
    profile_name: str,
    effective_profile: Any,
    labels: List[str],
    preflight_plan: List[Dict[str, Any]],
    stage_window_cls: Callable[..., Any],
    run_dir: Path,
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
    strict_threshold_recommendation_warnings: Callable[[Any], Optional[bool]],
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
    maybe_retune_gpu_processes: Callable[[List[Any], str, List[Dict[str, Any]], float, float], List[Any]],
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
    print_cpu_tune_start: Callable[[str, str, str], None],
    print_cpu_tune_end: Callable[[str, str, float, str, str], None],
    print_stage_start: Callable[[str, str, str, str, str, str, str], None],
    print_stage_abort: Callable[[str, str, str], None],
    print_stage_end: Callable[[str, str, float, str, int], None],
    print_progress: Callable[[str], None],
    operator_stop_source: str,
    on_operator_stop: Callable[[str, Dict[str, Any]], None],
    cancel_check: Optional[Callable[[], bool]] = None,
    completion_stage_runner: Optional[Callable[..., Any]] = None,
) -> StageLoopResult:
    current_run_aborted = bool(run_aborted)
    for idx, stage in enumerate(effective_profile.stages):
        if not stage.enabled:
            continue
        display_name = labels[idx] if idx < len(labels) else stage.name
        stage_plan = dict(preflight_plan[idx]) if idx < len(preflight_plan) else {}
        execution_mode = stage_execution_mode(stage)
        if execution_mode == "completion":
            if completion_stage_runner is None:
                raise RuntimeError(f"completion-based stage runner is unavailable for {display_name}")
            completion = completion_stage_runner(
                stage=stage,
                display_name=display_name,
                stage_plan=stage_plan,
            )
            current_run_aborted = bool(completion.run_aborted)
            if completion.should_break_run:
                break
            continue
        if execution_mode == "mixed":
            raise RuntimeError(f"mixed duration/completion stage reached execution: {display_name}")
        stage_adapter = run_stage_adapter(
            profile_name=profile_name,
            stage_window_cls=stage_window_cls,
            stage=stage,
            display_name=display_name,
            run_dir=run_dir,
            stage_plan=stage_plan,
            stage_windows=stage_windows,
            executed_plan=executed_plan,
            run_aborted=current_run_aborted,
            abort_on_worker_error=abort_on_worker_error,
            abort_on_system_fault=abort_on_system_fault,
            abort_run_on_stage_abort=abort_run_on_stage_abort,
            abort_on_fail_threshold=abort_on_fail_threshold,
            telemetry_interval_seconds=telemetry_interval_seconds,
            progress_interval_seconds=progress_interval_seconds,
            cpu_tuning_policy_for_stage=cpu_tuning_policy_for_stage,
            resolve_cpu_execution=resolve_cpu_execution,
            strict_threshold_recommendation_warnings=lambda current_stage=stage: strict_threshold_recommendation_warnings(current_stage),
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
            maybe_retune_gpu_processes=lambda processes, elapsed, duration, retune_events, current_display_name=display_name: maybe_retune_gpu_processes(
                processes,
                current_display_name,
                retune_events,
                elapsed,
                duration,
            ),
            stage_target_gpu_progress_summary=stage_target_gpu_progress_summary,
            effective_gpu_retune_cooldown_seconds=effective_gpu_retune_cooldown_seconds,
            serialize_gpu_worker=serialize_gpu_worker,
            worker_result_events_func=worker_result_events_func,
            utilization_events_func=utilization_events_func,
            backend_effectiveness_events_func=backend_effectiveness_events_func,
            vram_attainment_events_func=vram_attainment_events_func,
            collect_stage_faults=collect_stage_faults,
            capture_stage_start=capture_stage_start,
            capture_stage_end=capture_stage_end,
            now_local_iso=now_local_iso,
            monotonic=monotonic,
            sleep=sleep,
            future_local_iso=future_local_iso,
            format_duration_hms=format_duration_hms,
            print_cpu_tune_start=lambda timestamp, policy, current_display_name=display_name: print_cpu_tune_start(
                current_display_name,
                timestamp,
                policy,
            ),
            print_cpu_tune_end=lambda timestamp, tune_elapsed, selected, tune_summary_suffix, current_display_name=display_name: print_cpu_tune_end(
                current_display_name,
                timestamp,
                tune_elapsed,
                selected,
                tune_summary_suffix,
            ),
            print_stage_start=lambda timestamp, stage_type, planned, expected_end, cpu_suffix, gpu_suffix, current_display_name=display_name: print_stage_start(
                current_display_name,
                timestamp,
                stage_type,
                planned,
                expected_end,
                cpu_suffix,
                gpu_suffix,
            ),
            print_stage_abort=lambda timestamp, reason, current_display_name=display_name: print_stage_abort(
                current_display_name,
                timestamp,
                reason,
            ),
            print_stage_end=lambda timestamp, stage_elapsed, verdict, issue_count, current_display_name=display_name: print_stage_end(
                current_display_name,
                timestamp,
                stage_elapsed,
                verdict,
                issue_count,
            ),
            print_progress=print_progress,
            operator_stop_source=operator_stop_source,
            on_operator_stop=lambda stop_event, current_display_name=display_name: on_operator_stop(
                current_display_name,
                stop_event,
            ),
            cancel_check=cancel_check,
        )
        current_run_aborted = stage_adapter.run_aborted
        if stage_adapter.should_break_run:
            break
    return StageLoopResult(run_aborted=current_run_aborted)
