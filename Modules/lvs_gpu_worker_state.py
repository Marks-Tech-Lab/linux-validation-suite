#!/usr/bin/env python3
"""Projected internal GPU worker state helpers."""

from __future__ import annotations

from typing import Any, Dict, Optional


INTERNAL_GPU_BACKENDS = {
    "python_egl_gles2",
    "python_opencl_compute",
    "python_opencl",
    "python_vulkan_transfer",
    "python_vulkan_compute",
}


def current_internal_load_fraction(settings: Any, stage_elapsed_seconds: float) -> float:
    if not bool(getattr(settings, "gpu_safe_mode", False)):
        return 1.0
    ramp_step = max(0.0, float(getattr(settings, "gpu_internal_ramp_step_seconds", 0.0) or 0.0))
    if ramp_step <= 0:
        return 1.0
    start_fraction = max(0.15, min(1.0, float(getattr(settings, "gpu_safe_start_load_fraction", 1.0) or 1.0)))
    progress = min(1.0, max(0.0, float(stage_elapsed_seconds or 0.0)) / max(0.001, ramp_step * 3.0))
    return min(1.0, start_fraction + (1.0 - start_fraction) * progress)


def planned_internal_gpu_worker_state(
    settings: Any,
    spec: Optional[Any],
    stage_elapsed_seconds: float,
) -> Dict[str, Any]:
    if spec is None or getattr(spec, "backend", None) not in INTERNAL_GPU_BACKENDS:
        return {}
    load_fraction = current_internal_load_fraction(settings, stage_elapsed_seconds)
    planned: Dict[str, Any] = {
        "active_load_fraction": round(load_fraction, 3),
    }
    if getattr(spec, "workload", "") == "gpu_3d":
        if getattr(spec, "draw_count", 0):
            planned["active_draw_count"] = max(1, int(round(int(spec.draw_count) * load_fraction)))
        if getattr(spec, "clear_passes", 0):
            planned["active_clear_passes"] = max(1, int(round(int(spec.clear_passes) * load_fraction)))
        if getattr(spec, "backend", "") in {"python_vulkan_transfer", "python_vulkan_compute"} and getattr(spec, "target_vram_bytes", 0):
            target_vram_bytes = int(spec.target_vram_bytes)
            planned["active_buffer_bytes"] = max(
                4 * 1024 * 1024,
                min(target_vram_bytes, int(round(target_vram_bytes * load_fraction))),
            )
        if getattr(spec, "backend", "") == "python_vulkan_compute" and getattr(spec, "shader_iterations", 0):
            planned["active_compute_rounds"] = int(spec.shader_iterations)
    if getattr(spec, "workload", "") == "vram" and getattr(spec, "target_vram_bytes", 0):
        phase = "verify"
        if bool(getattr(settings, "gpu_safe_mode", False)):
            ramp_step = max(0.0, float(getattr(settings, "gpu_internal_ramp_step_seconds", 0.0) or 0.0))
            allocation_window = max(5.0, ramp_step)
            fill_window = max(10.0, ramp_step * 2.0)
            device_class = str(getattr(spec, "device_class", "") or "").lower()
            if device_class == "discrete":
                allocation_window = max(12.0, ramp_step * 1.35)
                fill_window = max(allocation_window + 18.0, ramp_step * 3.5)
            if stage_elapsed_seconds < allocation_window:
                phase = "allocation_only"
            elif stage_elapsed_seconds < fill_window:
                phase = "fill"
        planned["active_phase"] = phase
        target_vram_bytes = int(spec.target_vram_bytes)
        planned["active_target_vram_bytes"] = max(
            64 * 1024 * 1024,
            min(target_vram_bytes, int(round(target_vram_bytes * load_fraction))),
        )
    return planned
