#!/usr/bin/env python3
"""Shared stage run context and start-line suffix helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass(frozen=True)
class StageRunContext:
    cpu_backend: str = ""
    gpu_3d_backend_resolved: str = ""
    vram_backend_resolved: str = ""
    cpu_mode_requested: str = ""
    cpu_mode_resolved: str = ""
    cpu_kernel_flavor: str = ""
    cpu_tuning_policy: str = ""
    gpu_3d_backend_preference: str = ""
    vram_backend_preference: str = ""
    gpu_target_mode: str = ""
    gpu_3d_mode: str = ""
    gpu_3d_intensity: str = ""
    gpu_3d_compute_variant: str = ""
    gpu_targets_requested: List[str] = field(default_factory=list)
    gpu_targets: List[str] = field(default_factory=list)
    gpu_excluded_targets: Dict[str, List[str]] = field(default_factory=dict)
    gpu_workers_initial: List[Dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class CpuTuningContext:
    cpu_backend: str
    cpu_mode_requested: str
    cpu_mode_resolved: str
    cpu_kernel_flavor: str
    cpu_tuning_policy: str
    cpu_tuned_avg_power_w: Any
    cpu_tune_results: List[Dict[str, Any]]


def stage_run_context_from_plan(stage_plan: Dict[str, Any]) -> StageRunContext:
    backend_usage = dict(stage_plan.get("backend_usage", {}) or {})
    gpu_backend_preferences = dict(stage_plan.get("gpu_backend_preferences", {}) or {})
    gpu_targets_requested = [str(target) for target in stage_plan.get("gpu_targets", [])]
    gpu_targets = [str(target) for target in stage_plan.get("gpu_effective_targets", [])] or list(gpu_targets_requested)
    gpu_excluded_targets = {
        str(kind): [str(target) for target in targets]
        for kind, targets in dict(stage_plan.get("gpu_excluded_targets", {}) or {}).items()
    }
    return StageRunContext(
        cpu_backend=str(backend_usage.get("cpu", "") or ""),
        gpu_3d_backend_resolved=str(backend_usage.get("gpu_3d", "") or ""),
        vram_backend_resolved=str(backend_usage.get("vram", "") or ""),
        cpu_mode_requested=str(stage_plan.get("cpu_mode_requested", "") or ""),
        cpu_mode_resolved=str(stage_plan.get("cpu_mode_resolved", "") or ""),
        cpu_kernel_flavor=str(stage_plan.get("cpu_kernel_flavor", "") or ""),
        cpu_tuning_policy=str(stage_plan.get("cpu_tuning_policy", "") or ""),
        gpu_3d_backend_preference=str(gpu_backend_preferences.get("gpu_3d", "") or ""),
        vram_backend_preference=str(gpu_backend_preferences.get("vram", "") or ""),
        gpu_target_mode=str(stage_plan.get("gpu_target_mode", "") or ""),
        gpu_3d_mode=str(stage_plan.get("gpu_3d_mode", "") or ""),
        gpu_3d_intensity=str(stage_plan.get("gpu_3d_intensity", "") or ""),
        gpu_3d_compute_variant=str(stage_plan.get("gpu_3d_compute_variant", "") or ""),
        gpu_targets_requested=gpu_targets_requested,
        gpu_targets=gpu_targets,
        gpu_excluded_targets=gpu_excluded_targets,
        gpu_workers_initial=list(stage_plan.get("gpu_workers", [])),
    )


def apply_cpu_tuning_execution(stage_plan: Dict[str, Any], cpu_execution: Dict[str, Any]) -> CpuTuningContext:
    context = CpuTuningContext(
        cpu_backend=cpu_execution["backend"],
        cpu_mode_requested=cpu_execution["requested_mode"],
        cpu_mode_resolved=cpu_execution["resolved_mode"],
        cpu_kernel_flavor=cpu_execution["kernel_flavor"],
        cpu_tuning_policy=cpu_execution["tuning_policy"],
        cpu_tuned_avg_power_w=cpu_execution["tuned_avg_power_w"],
        cpu_tune_results=cpu_execution["candidate_results"],
    )
    stage_plan["cpu_mode_requested"] = context.cpu_mode_requested
    stage_plan["cpu_mode_resolved"] = context.cpu_mode_resolved
    stage_plan["cpu_kernel_flavor"] = context.cpu_kernel_flavor
    stage_plan["cpu_tuning_policy"] = context.cpu_tuning_policy
    stage_plan["cpu_tune_results"] = context.cpu_tune_results
    stage_plan["cpu_tuned_avg_power_w"] = context.cpu_tuned_avg_power_w
    return context


def cpu_tune_summary_suffix(cpu_tune_results: List[Dict[str, Any]]) -> str:
    if not cpu_tune_results:
        return ""
    return " | " + ", ".join(
        f"{result['kernel_flavor']}={result['avg_cpu_power_w']}W"
        if result.get("avg_cpu_power_w") is not None
        else f"{result['kernel_flavor']}=n/a"
        for result in cpu_tune_results
    )


def cpu_stage_start_suffix(
    *,
    cpu_backend: str,
    cpu_mode_requested: str,
    cpu_mode_resolved: str,
    cpu_kernel_flavor: str,
    cpu_tuned_avg_power_w: Any,
) -> str:
    if not cpu_backend:
        return ""
    suffix = f" | cpu={cpu_backend}"
    if cpu_mode_requested:
        suffix += f" ({cpu_mode_requested}"
        if cpu_mode_resolved:
            suffix += f" -> {cpu_mode_resolved}"
        suffix += ")"
    if cpu_kernel_flavor:
        suffix += f" | kernel={cpu_kernel_flavor}"
    if cpu_tuned_avg_power_w is not None:
        suffix += f" | tuned={cpu_tuned_avg_power_w}W"
    return suffix


def gpu_stage_start_suffix(stage: Any, context: StageRunContext) -> str:
    gpu_parts: List[str] = []
    if stage.modules.gpu_3d.enabled:
        gpu_label = context.gpu_3d_backend_resolved or "none"
        if context.gpu_3d_backend_preference:
            gpu_label = f"{context.gpu_3d_backend_preference}->{gpu_label}"
        if context.gpu_3d_mode or context.gpu_3d_intensity:
            gpu_label += f" ({context.gpu_3d_mode or 'steady'}/{context.gpu_3d_intensity or 'extreme'})"
        if context.gpu_3d_backend_resolved == "python_opencl_compute" and context.gpu_3d_compute_variant:
            gpu_label += f"/{context.gpu_3d_compute_variant}"
        gpu_parts.append(f"3d={gpu_label}")
    if stage.modules.vram.enabled:
        gpu_label = context.vram_backend_resolved or "none"
        if context.vram_backend_preference:
            gpu_label = f"{context.vram_backend_preference}->{gpu_label}"
        gpu_parts.append(f"vram={gpu_label}")

    suffix = ""
    if gpu_parts:
        suffix = " | gpu=" + ",".join(gpu_parts)
    if context.gpu_target_mode:
        suffix += f" | gpu_targets={context.gpu_target_mode}"
    if context.gpu_targets and sorted(context.gpu_targets) != sorted(context.gpu_targets_requested):
        suffix += f" | gpu_effective={','.join(context.gpu_targets)}"
    excluded_targets_flat = sorted(
        {
            target
            for targets in context.gpu_excluded_targets.values()
            for target in targets
            if target
        }
    )
    if excluded_targets_flat:
        suffix += f" | gpu_skipped={','.join(excluded_targets_flat)}"
    return suffix


def internal_gpu_backend_set(*backends: str) -> set[str]:
    internal_backends = {
        "python_opencl_compute",
        "python_opencl",
        "python_egl_gles2",
        "python_vulkan_transfer",
        "python_vulkan_compute",
    }
    return {backend for backend in backends if backend in internal_backends}
