#!/usr/bin/env python3
"""Shared post-worker-stop stage evaluation helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Tuple

from Modules.lvs_stage_completion import build_stage_check_window, serialize_final_gpu_workers
from Modules.lvs_stage_event_state import apply_stage_events


@dataclass(frozen=True)
class StageEvaluationResult:
    stage_verdict: str
    stage_aborted: bool
    stage_abort_reason: str
    stage_worker_results: List[Dict[str, Any]]
    gpu_workers_final: List[Dict[str, Any]]


def evaluate_completed_stage(
    *,
    stage_window_cls: Callable[..., Any],
    stage: Any,
    display_name: str,
    stage_started_iso: str,
    stage_ended_iso: str,
    stage_start: float,
    stage_end: float,
    stage_elapsed: float,
    stage_processes: List[Any],
    serialize_gpu_worker: Callable[[Any], Dict[str, Any]],
    operator_stop_requested: bool,
    abort_on_worker_error: bool,
    abort_on_fail_threshold: bool,
    stage_verdict: str,
    stage_aborted: bool,
    stage_abort_reason: str,
    stage_error_events: List[Dict[str, Any]],
    stage_failure_reasons: List[str],
    gpu_target_mode: str,
    gpu_targets: List[str],
    gpu_workers_initial: List[Dict[str, Any]],
    gpu_3d_backend_preference: str,
    gpu_3d_backend_resolved: str,
    vram_backend_preference: str,
    vram_backend_resolved: str,
    worker_result_events_func: Callable[[List[Any], str], Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]],
    sensor_events_func: Callable[[Any], List[Dict[str, Any]]],
    utilization_events_func: Callable[[Any], List[Dict[str, Any]]],
    backend_effectiveness_events_func: Callable[[Any], List[Dict[str, Any]]],
    vram_attainment_events_func: Callable[[Any], List[Dict[str, Any]]],
) -> StageEvaluationResult:
    stage_worker_results, worker_result_events = worker_result_events_func(stage_processes, display_name)
    if worker_result_events and not operator_stop_requested:
        event_state = apply_stage_events(
            worker_result_events,
            stage_error_events,
            stage_failure_reasons,
            stage_verdict,
            aborted=stage_aborted,
            abort_reason=stage_abort_reason,
            abort_on_error=abort_on_worker_error,
            abort_only_from_pass=True,
            abort_reason_from_first_event=True,
            fail_only_from_pass=True,
        )
        stage_verdict = event_state.verdict
        stage_aborted = event_state.aborted
        stage_abort_reason = event_state.abort_reason

    base_window = build_stage_check_window(
        stage_window_cls=stage_window_cls,
        stage=stage,
        display_name=display_name,
        started_iso=stage_started_iso,
        ended_iso=stage_ended_iso,
        started_monotonic=stage_start,
        ended_monotonic=stage_end,
        duration_seconds=stage_elapsed,
    )
    stage_sensor_events = sensor_events_func(base_window)
    if stage_sensor_events:
        event_state = apply_stage_events(
            stage_sensor_events,
            stage_error_events,
            stage_failure_reasons,
            stage_verdict,
            aborted=stage_aborted,
            abort_reason=stage_abort_reason,
            abort_on_error=abort_on_fail_threshold,
            abort_only_from_pass=True,
            fail_only_from_pass=True,
        )
        stage_verdict = event_state.verdict
        stage_aborted = event_state.aborted
        stage_abort_reason = event_state.abort_reason

    gpu_workers_final = serialize_final_gpu_workers(stage_processes, serialize_gpu_worker)
    gpu_window = build_stage_check_window(
        stage_window_cls=stage_window_cls,
        stage=stage,
        display_name=display_name,
        started_iso=stage_started_iso,
        ended_iso=stage_ended_iso,
        started_monotonic=stage_start,
        ended_monotonic=stage_end,
        duration_seconds=stage_elapsed,
        gpu_target_mode=gpu_target_mode,
        gpu_targets=gpu_targets,
        gpu_workers_initial=gpu_workers_initial,
        gpu_workers_final=gpu_workers_final,
    )

    stage_utilization_events = [] if operator_stop_requested else utilization_events_func(gpu_window)
    if stage_utilization_events:
        event_state = apply_stage_events(
            stage_utilization_events,
            stage_error_events,
            stage_failure_reasons,
            stage_verdict,
            aborted=stage_aborted,
            abort_reason=stage_abort_reason,
            fail_only_from_pass=True,
        )
        stage_verdict = event_state.verdict
        stage_aborted = event_state.aborted
        stage_abort_reason = event_state.abort_reason

    backend_window = build_stage_check_window(
        stage_window_cls=stage_window_cls,
        stage=stage,
        display_name=display_name,
        started_iso=stage_started_iso,
        ended_iso=stage_ended_iso,
        started_monotonic=stage_start,
        ended_monotonic=stage_end,
        duration_seconds=stage_elapsed,
        gpu_3d_backend_preference=gpu_3d_backend_preference,
        gpu_3d_backend_resolved=gpu_3d_backend_resolved,
        vram_backend_preference=vram_backend_preference,
        vram_backend_resolved=vram_backend_resolved,
        gpu_target_mode=gpu_target_mode,
        gpu_targets=gpu_targets,
        gpu_workers_initial=gpu_workers_initial,
        gpu_workers_final=gpu_workers_final,
    )
    stage_backend_effectiveness_events = [] if operator_stop_requested else backend_effectiveness_events_func(backend_window)
    if stage_backend_effectiveness_events:
        event_state = apply_stage_events(
            stage_backend_effectiveness_events,
            stage_error_events,
            stage_failure_reasons,
            stage_verdict,
            aborted=stage_aborted,
            abort_reason=stage_abort_reason,
            fail_only_from_pass=True,
        )
        stage_verdict = event_state.verdict
        stage_aborted = event_state.aborted
        stage_abort_reason = event_state.abort_reason

    vram_window = build_stage_check_window(
        stage_window_cls=stage_window_cls,
        stage=stage,
        display_name=display_name,
        started_iso=stage_started_iso,
        ended_iso=stage_ended_iso,
        started_monotonic=stage_start,
        ended_monotonic=stage_end,
        duration_seconds=stage_elapsed,
        gpu_3d_backend_preference=gpu_3d_backend_preference,
        gpu_3d_backend_resolved=gpu_3d_backend_resolved,
        vram_backend_preference=vram_backend_preference,
        vram_backend_resolved=vram_backend_resolved,
        gpu_target_mode=gpu_target_mode,
        gpu_targets=gpu_targets,
        gpu_workers_initial=gpu_workers_initial,
        gpu_workers_final=gpu_workers_final,
        worker_results=stage_worker_results,
    )
    stage_vram_attainment_events = [] if operator_stop_requested else vram_attainment_events_func(vram_window)
    if stage_vram_attainment_events:
        event_state = apply_stage_events(
            stage_vram_attainment_events,
            stage_error_events,
            stage_failure_reasons,
            stage_verdict,
            aborted=stage_aborted,
            abort_reason=stage_abort_reason,
            fail_only_from_pass=True,
        )
        stage_verdict = event_state.verdict
        stage_aborted = event_state.aborted
        stage_abort_reason = event_state.abort_reason

    return StageEvaluationResult(
        stage_verdict=stage_verdict,
        stage_aborted=stage_aborted,
        stage_abort_reason=stage_abort_reason,
        stage_worker_results=stage_worker_results,
        gpu_workers_final=gpu_workers_final,
    )
