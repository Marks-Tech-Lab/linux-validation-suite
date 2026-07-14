#!/usr/bin/env python3
"""Frontend-neutral GPU worker retune eligibility policy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, Optional

from Modules.lvs_gpu_retune import (
    effective_gpu_retune_cooldown_seconds,
    effective_gpu_retune_warmup_seconds,
    minimum_gpu_retune_remaining_seconds,
    worker_retune_count,
)


RETUNABLE_BACKENDS = {
    "gpu_3d": {"python_egl_gles2", "python_opencl_compute"},
    "vram": {"python_egl_gles2", "python_opencl"},
}


@dataclass(frozen=True)
class GpuRetuneDecision:
    should_retune: bool
    reason: str
    busy_percent: Optional[float] = None


def gpu_worker_retune_decision(
    spec: Any,
    *,
    settings: Any,
    retune_events: Optional[Iterable[Dict[str, Any]]],
    stage_elapsed_seconds: float,
    stage_duration_seconds: float,
    latest_metric_value: Callable[[str], Optional[float]],
    recent_metric_values_for_key: Callable[[str, float], list[float]],
    thermal_safe_for_gpu: Callable[[int], bool],
) -> GpuRetuneDecision:
    if not spec:
        return GpuRetuneDecision(False, "missing_spec")

    workload = getattr(spec, "workload", "")
    backend = getattr(spec, "backend", "")
    if backend not in RETUNABLE_BACKENDS.get(workload, set()):
        return GpuRetuneDecision(False, "unsupported_backend")

    safe_mode = bool(getattr(settings, "gpu_safe_mode", False))
    effective_warmup_seconds = effective_gpu_retune_warmup_seconds(
        getattr(settings, "gpu_retune_warmup_seconds", 0.0),
        safe_mode,
        stage_duration_seconds,
    )
    effective_cooldown_seconds = effective_gpu_retune_cooldown_seconds(
        getattr(settings, "gpu_retune_cooldown_seconds", 0.0),
        safe_mode,
        stage_duration_seconds,
    )
    minimum_remaining_seconds = minimum_gpu_retune_remaining_seconds(
        getattr(settings, "gpu_internal_ramp_step_seconds", 0.0),
        stage_duration_seconds,
    )

    if safe_mode:
        if stage_elapsed_seconds < effective_warmup_seconds:
            return GpuRetuneDecision(False, "warmup")
        if stage_duration_seconds > 0 and (stage_duration_seconds - stage_elapsed_seconds) < minimum_remaining_seconds:
            return GpuRetuneDecision(False, "stage_ending")
        max_retunes = max(0, int(getattr(settings, "gpu_max_retunes_per_worker", 0) or 0))
        if worker_retune_count(retune_events, spec) >= max_retunes:
            return GpuRetuneDecision(False, "max_retunes")
        if not thermal_safe_for_gpu(int(getattr(spec, "gpu_index", -1))):
            return GpuRetuneDecision(False, "thermal")

    if workload == "gpu_3d":
        key = f"gpu_{getattr(spec, 'gpu_index', 0)}_busy_percent"
        busy = latest_metric_value(key)
        if busy is None or busy >= 92.0:
            return GpuRetuneDecision(False, "busy_unavailable_or_high", busy)
        if safe_mode:
            recent_busy = recent_metric_values_for_key(key, max(10.0, effective_cooldown_seconds))
            if len(recent_busy) < 3 or any(value >= 90.0 for value in recent_busy):
                return GpuRetuneDecision(False, "recent_busy", busy)
        return GpuRetuneDecision(True, "retune", busy)

    if workload == "vram":
        return GpuRetuneDecision(False, "vram_stable")

    return GpuRetuneDecision(False, "unsupported_workload")
