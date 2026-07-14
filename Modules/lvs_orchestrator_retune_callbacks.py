#!/usr/bin/env python3
"""Frontend-neutral GPU retune callbacks for validation runs."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from Modules.lvs_gpu_progress import latest_sample_value
from Modules.lvs_gpu_retune import (
    effective_gpu_retune_cooldown_seconds as build_effective_gpu_retune_cooldown_seconds,
    effective_gpu_retune_warmup_seconds as build_effective_gpu_retune_warmup_seconds,
    minimum_gpu_retune_remaining_seconds as build_minimum_gpu_retune_remaining_seconds,
    recent_metric_values,
    worker_retune_count as count_worker_retunes,
)
from Modules.lvs_gpu_retune_policy import gpu_worker_retune_decision
from Modules.lvs_gpu_retune_process import replace_gpu_process_for_retune
from Modules.lvs_gpu_worker_plan import GpuWorkerSpec
from Modules.lvs_stage_process_control import StageProcess
from Modules.lvs_telemetry_collector import (
    GPU_HOTSPOT_WARN_C,
    GPU_MEMORY_TEMP_WARN_C,
    GPU_TEMP_WARN_C,
    TelemetryCollector,
)


def latest_sample_metric_value(telemetry: TelemetryCollector, key: str) -> Optional[float]:
    return latest_sample_value(telemetry, key)


def recent_metric_values_for_telemetry(
    telemetry: TelemetryCollector,
    key: str,
    window_seconds: float,
) -> List[float]:
    return recent_metric_values(telemetry.samples, key, window_seconds)


def gpu_is_thermally_safe_to_retune(
    telemetry: TelemetryCollector,
    gpu_index: int,
) -> bool:
    temp_key = f"gpu_{gpu_index}_temp_core_c"
    hotspot_key = f"gpu_{gpu_index}_temp_hotspot_c"
    memory_key = f"gpu_{gpu_index}_temp_memory_c"
    temp = latest_sample_metric_value(telemetry, temp_key)
    hotspot = latest_sample_metric_value(telemetry, hotspot_key)
    memory = latest_sample_metric_value(telemetry, memory_key)
    if temp is not None:
        info = telemetry.metric_thresholds(temp_key)
        warn_c = float((info or {}).get("warn_c") or GPU_TEMP_WARN_C)
        if temp >= warn_c - 5.0:
            return False
    if hotspot is not None:
        info = telemetry.metric_thresholds(hotspot_key)
        warn_c = float((info or {}).get("warn_c") or GPU_HOTSPOT_WARN_C)
        if hotspot >= warn_c - 5.0:
            return False
    if memory is not None:
        info = telemetry.metric_thresholds(memory_key)
        warn_c = float((info or {}).get("warn_c") or GPU_MEMORY_TEMP_WARN_C)
        if memory >= warn_c - 4.0:
            return False
    return True


def worker_retune_count(
    retune_events: Optional[List[Dict[str, Any]]],
    spec: GpuWorkerSpec,
) -> int:
    return count_worker_retunes(retune_events, spec)


def effective_gpu_retune_warmup_seconds(orchestrator: Any, stage_duration_seconds: float) -> float:
    return build_effective_gpu_retune_warmup_seconds(
        orchestrator.settings.gpu_retune_warmup_seconds,
        orchestrator.settings.gpu_safe_mode,
        stage_duration_seconds,
    )


def effective_gpu_retune_cooldown_seconds(orchestrator: Any, stage_duration_seconds: float) -> float:
    return build_effective_gpu_retune_cooldown_seconds(
        orchestrator.settings.gpu_retune_cooldown_seconds,
        orchestrator.settings.gpu_safe_mode,
        stage_duration_seconds,
    )


def minimum_gpu_retune_remaining_seconds(orchestrator: Any, stage_duration_seconds: float) -> float:
    return build_minimum_gpu_retune_remaining_seconds(
        orchestrator.settings.gpu_internal_ramp_step_seconds,
        stage_duration_seconds,
    )


def maybe_retune_gpu_processes(
    orchestrator: Any,
    stage_processes: List[StageProcess],
    telemetry: TelemetryCollector,
    display_name: str,
    retune_events: Optional[List[Dict[str, Any]]] = None,
    stage_elapsed_seconds: float = 0.0,
    stage_duration_seconds: float = 0.0,
) -> List[StageProcess]:
    updated = list(stage_processes)
    for index, entry in enumerate(updated):
        spec = entry.gpu_spec
        decision = gpu_worker_retune_decision(
            spec,
            settings=orchestrator.settings,
            retune_events=retune_events,
            stage_elapsed_seconds=stage_elapsed_seconds,
            stage_duration_seconds=stage_duration_seconds,
            latest_metric_value=lambda key: latest_sample_metric_value(telemetry, key),
            recent_metric_values_for_key=lambda key, window_seconds: recent_metric_values_for_telemetry(
                telemetry,
                key,
                window_seconds,
            ),
            thermal_safe_for_gpu=lambda gpu_index: gpu_is_thermally_safe_to_retune(telemetry, gpu_index),
        )
        if not decision.should_retune:
            continue
        new_spec = orchestrator.workload_runner.retune_gpu_worker(spec)
        if not new_spec:
            continue
        new_spec = orchestrator.workload_runner._materialize_gpu_worker(new_spec, entry.result_path)
        metric_summary = ""
        if spec.workload == "gpu_3d":
            metric_summary = f"busy={decision.busy_percent}%"
        else:
            latest_used_gb = latest_sample_metric_value(telemetry, f"gpu_{spec.gpu_index}_vram_used_gb")
            used_text = "unknown" if latest_used_gb is None else str(round(float(latest_used_gb), 2))
            metric_summary = f"vram={used_text}GB/{round(spec.target_vram_bytes / (1024 ** 3), 2)}GB"
        replacement, event = replace_gpu_process_for_retune(
            entry=entry,
            new_spec=new_spec,
            display_name=display_name,
            metric_summary=metric_summary,
            command_env=orchestrator.workload_runner._command_env(),
            serialize_worker=orchestrator.workload_runner.serialize_gpu_worker,
        )
        if replacement is None or event is None:
            continue
        if retune_events is not None:
            retune_events.append(event)
        updated[index] = replacement
    return updated

