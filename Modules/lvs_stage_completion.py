#!/usr/bin/env python3
"""Shared completed-stage record assembly helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional


@dataclass(frozen=True)
class StageCompletionRecord:
    stage_window: Any
    gpu_workers_final: List[Dict[str, Any]]
    issue_count: int


def serialize_final_gpu_workers(
    stage_processes: List[Any],
    serialize_gpu_worker: Callable[[Any], Dict[str, Any]],
) -> List[Dict[str, Any]]:
    return [
        serialize_gpu_worker(entry.gpu_spec)
        for entry in stage_processes
        if getattr(entry, "gpu_spec", None)
    ]


def stage_issue_count(error_events: List[Dict[str, Any]]) -> int:
    return sum(
        1
        for event in error_events
        if event.get("severity") in {"warning", "error"}
    )


def build_stage_check_window(
    *,
    stage_window_cls: Callable[..., Any],
    stage: Any,
    display_name: str,
    started_iso: str,
    ended_iso: str,
    started_monotonic: float,
    ended_monotonic: float,
    duration_seconds: float,
    trim_start_seconds: Optional[int] = None,
    trim_end_seconds: Optional[int] = None,
    gpu_3d_backend_preference: str = "",
    gpu_3d_backend_resolved: str = "",
    vram_backend_preference: str = "",
    vram_backend_resolved: str = "",
    gpu_target_mode: str = "",
    gpu_targets: Optional[List[str]] = None,
    gpu_workers_initial: Optional[List[Dict[str, Any]]] = None,
    gpu_workers_final: Optional[List[Dict[str, Any]]] = None,
    worker_results: Optional[List[Dict[str, Any]]] = None,
) -> Any:
    if trim_start_seconds is None:
        trim_start_seconds = stage.normalization.trim_start_seconds
    if trim_end_seconds is None:
        trim_end_seconds = stage.normalization.trim_end_seconds
    return stage_window_cls(
        stage_id=stage.id,
        stage_type=stage.name,
        display_name=display_name,
        started_iso=started_iso,
        ended_iso=ended_iso,
        started_monotonic=started_monotonic,
        ended_monotonic=ended_monotonic,
        duration_seconds=duration_seconds,
        trim_start_seconds=trim_start_seconds,
        trim_end_seconds=trim_end_seconds,
        gpu_3d_backend_preference=gpu_3d_backend_preference,
        gpu_3d_backend_resolved=gpu_3d_backend_resolved,
        vram_backend_preference=vram_backend_preference,
        vram_backend_resolved=vram_backend_resolved,
        gpu_target_mode=gpu_target_mode,
        gpu_targets=gpu_targets or [],
        gpu_workers_initial=gpu_workers_initial or [],
        gpu_workers_final=gpu_workers_final or [],
        worker_results=worker_results or [],
    )


def complete_stage_record(
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
    stage_plan: Dict[str, Any],
    cpu_backend: str,
    cpu_mode_requested: str,
    cpu_mode_resolved: str,
    cpu_kernel_flavor: str,
    cpu_tuning_policy: str,
    cpu_tuned_avg_power_w: Optional[float],
    gpu_3d_backend_preference: str,
    gpu_3d_backend_resolved: str,
    vram_backend_preference: str,
    vram_backend_resolved: str,
    gpu_target_mode: str,
    gpu_targets: List[str],
    gpu_workers_initial: List[Dict[str, Any]],
    gpu_retune_events: List[Dict[str, Any]],
    stage_verdict: str,
    stage_failure_reasons: List[str],
    stage_error_events: List[Dict[str, Any]],
    stage_worker_results: List[Dict[str, Any]],
    intel_gpu_top_sidecar_summary: Optional[Dict[str, Any]],
    strict_threshold_recommendation_warnings: Optional[bool],
    gpu_workers_final: Optional[List[Dict[str, Any]]] = None,
) -> StageCompletionRecord:
    if gpu_workers_final is None:
        gpu_workers_final = serialize_final_gpu_workers(stage_processes, serialize_gpu_worker)

    stage_plan["gpu_workers_initial"] = gpu_workers_initial
    stage_plan["gpu_workers_final"] = gpu_workers_final
    stage_plan["gpu_retune_events"] = gpu_retune_events
    if intel_gpu_top_sidecar_summary:
        stage_plan["intel_gpu_top_sidecar"] = intel_gpu_top_sidecar_summary
    stage_plan["worker_results"] = stage_worker_results
    stage_plan["error_events"] = stage_error_events
    stage_plan["verdict"] = stage_verdict

    stage_window = build_stage_check_window(
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
    stage_window.cpu_backend = cpu_backend
    stage_window.cpu_mode_requested = cpu_mode_requested
    stage_window.cpu_mode_resolved = cpu_mode_resolved
    stage_window.cpu_kernel_flavor = cpu_kernel_flavor
    stage_window.cpu_tuning_policy = cpu_tuning_policy
    stage_window.cpu_tuned_avg_power_w = cpu_tuned_avg_power_w
    stage_window.gpu_retune_events = gpu_retune_events
    stage_window.verdict = stage_verdict
    stage_window.failure_reasons = stage_failure_reasons
    stage_window.error_events = stage_error_events
    stage_window.intel_gpu_top_sidecar = intel_gpu_top_sidecar_summary
    stage_window.strict_threshold_recommendation_warnings = strict_threshold_recommendation_warnings
    return StageCompletionRecord(
        stage_window=stage_window,
        gpu_workers_final=gpu_workers_final,
        issue_count=stage_issue_count(stage_error_events),
    )
