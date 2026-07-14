#!/usr/bin/env python3
"""Frontend-neutral stage analysis callbacks for validation runs."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from Modules.lvs_faults import faults_for_stage_window
from Modules.lvs_gpu_progress import (
    other_gpu_progress_summary,
    stage_gpu_progress_summary,
    target_gpu_metric_progress_parts,
    target_gpu_progress_summary,
    target_gpu_state_progress_parts,
)
from Modules.lvs_gpu_stage_events import (
    gpu_backend_effectiveness_events,
    target_gpu_utilization_events,
    vram_target_attainment_events,
)
from Modules.lvs_gpu_stage_targets import (
    stage_target_gpu_details_from_processes,
    stage_target_gpu_details_from_worker_dicts,
)
from Modules.lvs_gpu_worker_state import planned_internal_gpu_worker_state
from Modules.lvs_sensor_events import stage_sensor_events as build_stage_sensor_events
from Modules.lvs_segment_metric_helpers import SegmentMetricHelper
from Modules.lvs_stage_process_control import StageProcess
from Modules.lvs_stage_worker_evidence import poll_stage_process_failures, worker_result_events
from Modules.lvs_telemetry_collector import (
    GPU_HOTSPOT_FAIL_C,
    GPU_HOTSPOT_WARN_C,
    GPU_MEMORY_TEMP_FAIL_C,
    GPU_MEMORY_TEMP_WARN_C,
    GPU_THERMAL_THROTTLE_HINT_C,
    TelemetryCollector,
)


_SEGMENT_METRIC_HELPER = SegmentMetricHelper()


def samples_for_stage_window(samples: List[Any], window: Any) -> List[Any]:
    return _SEGMENT_METRIC_HELPER.samples_for_window(samples, window)


def stage_target_gpu_progress_summary(
    orchestrator: Any,
    telemetry: TelemetryCollector,
    stage_processes: List[StageProcess],
    stage_elapsed_seconds: float = 0.0,
) -> str:
    targets = stage_target_gpu_details_from_processes(stage_processes)
    if not targets:
        return ""

    summaries: List[str] = []
    for gpu_index in sorted(targets):
        target = targets[gpu_index]
        live_payloads = [
            payload
            for entry in stage_processes
            if entry.gpu_spec is not None and int(entry.gpu_spec.gpu_index) == gpu_index
            for payload in [orchestrator._read_worker_result(entry, allow_partial=True)]
            if payload
        ]
        planned_states = [
            planned_internal_gpu_worker_state(orchestrator.settings, entry.gpu_spec, stage_elapsed_seconds)
            for entry in stage_processes
            if entry.gpu_spec is not None and int(entry.gpu_spec.gpu_index) == gpu_index
        ]
        metrics = target_gpu_metric_progress_parts(telemetry, gpu_index)
        target_vram_total = max(
            [
                int(entry.gpu_spec.target_vram_bytes)
                for entry in stage_processes
                if entry.gpu_spec is not None
                and int(entry.gpu_spec.gpu_index) == gpu_index
                and int(entry.gpu_spec.target_vram_bytes or 0) > 0
            ]
            or [0]
        )
        state_details = target_gpu_state_progress_parts(
            live_payloads,
            planned_states,
            target_vram_total=target_vram_total,
        )
        summaries.append(target_gpu_progress_summary(gpu_index, target, metrics, state_details))
    other_summary = other_gpu_progress_summary(telemetry, targets)
    return stage_gpu_progress_summary(summaries, other_summary)


def stage_target_gpu_utilization_events(
    orchestrator: Any,
    window: Any,
    telemetry: TelemetryCollector,
) -> List[Dict[str, Any]]:
    target_gpus = stage_target_gpu_details_from_worker_dicts(window.gpu_workers_final or window.gpu_workers_initial)
    samples = samples_for_stage_window(telemetry.samples, window)
    return target_gpu_utilization_events(
        target_gpus=target_gpus,
        samples=samples,
        stage_name=window.display_name,
        telemetry_interval_seconds=telemetry.interval_seconds,
        target_busy_threshold=float(orchestrator.settings.target_gpu_busy_min_percent or 0.0),
        target_busy_sustain=float(orchestrator.settings.target_gpu_busy_sustain_seconds or 0.0),
        target_mem_busy_threshold=float(orchestrator.settings.target_gpu_memory_busy_min_percent or 0.0),
        target_mem_busy_sustain=float(orchestrator.settings.target_gpu_memory_busy_sustain_seconds or 0.0),
    )


def stage_gpu_backend_effectiveness_events(
    orchestrator: Any,
    window: Any,
    telemetry: TelemetryCollector,
) -> List[Dict[str, Any]]:
    target_gpus = stage_target_gpu_details_from_worker_dicts(window.gpu_workers_final or window.gpu_workers_initial)
    samples = samples_for_stage_window(telemetry.samples, window)
    return gpu_backend_effectiveness_events(
        target_gpus=target_gpus,
        samples=samples,
        stage_name=window.display_name,
        backend_profile_lookup=orchestrator.workload_runner._gpu_3d_backend_catalog_entry,
        gpu_3d_backend_preference=window.gpu_3d_backend_preference,
        gpu_3d_backend_resolved=window.gpu_3d_backend_resolved,
    )


def stage_vram_target_attainment_events(
    orchestrator: Any,
    window: Any,
    telemetry: TelemetryCollector,
) -> List[Dict[str, Any]]:
    samples = samples_for_stage_window(telemetry.samples, window)
    return vram_target_attainment_events(
        worker_results=window.worker_results,
        samples=samples,
        stage_name=window.display_name,
        stage_duration_seconds=window.duration_seconds,
    )


def stage_process_failure_events(
    orchestrator: Any,
    stage_processes: List[StageProcess],
    display_name: str,
) -> List[Dict[str, Any]]:
    return poll_stage_process_failures(
        stage_processes,
        display_name,
        orchestrator.workload_runner._gpu_3d_backend_catalog_entry,
    )


def stage_worker_result_events(
    orchestrator: Any,
    stage_processes: List[StageProcess],
    display_name: str,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    return worker_result_events(
        stage_processes,
        display_name,
        orchestrator.workload_runner._gpu_3d_backend_catalog_entry,
    )


def stage_sensor_events(
    orchestrator: Any,
    window: Any,
    telemetry: TelemetryCollector,
) -> List[Dict[str, Any]]:
    samples = samples_for_stage_window(telemetry.samples, window)
    return build_stage_sensor_events(
        samples=samples,
        stage_name=window.display_name,
        metric_thresholds=telemetry.metric_thresholds,
        abort_on_fail_threshold=orchestrator.settings.abort_on_fail_threshold,
        gpu_thermal_throttle_hint_c=GPU_THERMAL_THROTTLE_HINT_C,
        gpu_hotspot_warn_c=GPU_HOTSPOT_WARN_C,
        gpu_hotspot_fail_c=GPU_HOTSPOT_FAIL_C,
        gpu_memory_temp_warn_c=GPU_MEMORY_TEMP_WARN_C,
        gpu_memory_temp_fail_c=GPU_MEMORY_TEMP_FAIL_C,
    )


def faults_for_stage(faults: List[Dict[str, Any]], window: Any) -> List[Dict[str, Any]]:
    return faults_for_stage_window(faults, window)
