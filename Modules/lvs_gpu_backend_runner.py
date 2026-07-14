#!/usr/bin/env python3
"""Workload-runner GPU backend resolution glue."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from Modules.lvs_gpu_backend_catalog import (
    GpuBackendAvailabilityContext,
    allow_per_target_auto_gpu_3d_backends,
    gpu_3d_backend_available_from_context,
    gpu_3d_backend_candidates as gpu_3d_backend_candidates_policy,
    prefer_graphics_backend_for_mixed_stage as prefer_graphics_backend_for_mixed_stage_policy,
    vram_backend_available_from_context,
)
from Modules.lvs_gpu_backend_resolver import (
    gpu_backend_support_summary as resolve_gpu_backend_support_summary,
    resolve_gpu_backend_for_targets as resolve_gpu_backend_for_targets_policy,
)
from Modules.lvs_gpu_backend_support import (
    egl_backend_target_support,
    gpu_backend_target_support as build_gpu_backend_target_support,
    opencl_backend_target_support,
    vulkan_backend_target_support,
    vulkan_nvidia_dropout_reason,
)


def prefer_graphics_backend_for_mixed_stage(runner: Any, gpu: Any, stage: Optional[Any]) -> bool:
    return prefer_graphics_backend_for_mixed_stage_policy(
        gpu_backend_preference=gpu.backend_preference,
        safe_mode_enabled=runner._gpu_safe_mode_enabled(),
        vram_enabled=bool(stage and stage.modules.vram.enabled),
        vram_backend_name=runner._vram_backend_name(stage.modules.vram) if stage else "",
    )


def gpu_3d_backend_candidates(runner: Any, gpu: Any, stage: Optional[Any] = None) -> List[str]:
    return gpu_3d_backend_candidates_policy(
        gpu.backend_preference,
        prefer_graphics_mixed_stage=runner._prefer_graphics_backend_for_mixed_stage(gpu, stage),
    )


def allow_per_target_auto_gpu_3d_backends_for_runner(runner: Any, gpu: Any, stage: Optional[Any]) -> bool:
    return allow_per_target_auto_gpu_3d_backends(
        gpu_backend_preference=gpu.backend_preference,
        stage_present=stage is not None,
        stage_vram_enabled=bool(stage and stage.modules.vram.enabled),
        stage_vram_backend_name=runner._vram_backend_name(stage.modules.vram) if stage else "",
    )


def gpu_backend_availability_context(runner: Any) -> GpuBackendAvailabilityContext:
    return GpuBackendAvailabilityContext(
        command_exists=runner._command_exists,
        python_runtime_available=lambda: bool(runner._python_runtime()),
        egl_available=lambda: bool(runner._egl_gpu_backend()["available"]),
        opencl_available=lambda: bool(runner._opencl_gpu_backend()["available"]),
        vulkan_compute_available=lambda: bool(runner._vulkan_native_backend()["available"]),
        vulkan_transfer_available=lambda: bool(runner._vulkan_transfer_backend()["available"]),
    )


def gpu_3d_backend_available(runner: Any, backend: str) -> bool:
    return gpu_3d_backend_available_from_context(backend, runner._gpu_backend_availability_context())


def vram_backend_available(runner: Any, backend: str) -> bool:
    return vram_backend_available_from_context(backend, runner._gpu_backend_availability_context())


def gpu_target_cache_key(target: Optional[Dict[str, Any]]) -> str:
    if not target:
        return "default"
    return str(target.get("target_id") or target.get("slot") or target.get("card") or "default")


def gpu_backend_target_support(
    runner: Any,
    backend: str,
    target: Optional[Dict[str, Any]],
    workload: str,
) -> Dict[str, Any]:
    cache_key = (backend, workload, runner._gpu_target_cache_key(target))
    cached = runner._gpu_backend_target_support_cache.get(cache_key)
    if cached is not None:
        return dict(cached)

    def opencl_support() -> Dict[str, Any]:
        return opencl_backend_target_support(
            backend=backend,
            target=target,
            workload=workload,
            matched_device=runner._opencl_device_for_target(target),
            all_devices=list((runner._opencl_gpu_backend().get("devices") or [])),
        )

    def vulkan_support() -> Dict[str, Any]:
        nvidia_slots = {
            runner._normalize_pci_slot(str(gpu.get("slot", "") or "")).lower()
            for gpu in runner._discover_nvidia_smi_gpus()
            if str(gpu.get("slot", "") or "").strip()
        }
        dropout_reason = vulkan_nvidia_dropout_reason(
            target=target,
            nvidia_smi_available=runner._command_exists("nvidia-smi"),
            nvidia_slots=nvidia_slots,
        )
        return vulkan_backend_target_support(
            backend=backend,
            target=target,
            workload=workload,
            vulkan_match={} if dropout_reason else runner._vulkan_device_for_target(target),
            nvidia_dropout_reason=dropout_reason,
        )

    def egl_support() -> Dict[str, Any]:
        return egl_backend_target_support(
            backend=backend,
            target=target,
            workload=workload,
            egl_probe=runner._egl_gpu_backend_for_target(target),
        )

    payload = build_gpu_backend_target_support(
        backend=backend,
        target=target,
        workload=workload,
        opencl_support=opencl_support,
        vulkan_support=vulkan_support,
        egl_support=egl_support,
    )

    runner._gpu_backend_target_support_cache[cache_key] = payload
    return dict(payload)


def gpu_backend_support_summary(
    runner: Any,
    backend: str,
    targets: List[Dict[str, Any]],
    workload: str,
) -> Dict[str, Any]:
    return resolve_gpu_backend_support_summary(
        backend=backend,
        targets=targets,
        workload=workload,
        target_support=runner._gpu_backend_target_support,
    )


def resolve_gpu_backend_for_targets(
    runner: Any,
    *,
    candidates: List[str],
    targets: List[Dict[str, Any]],
    workload: str,
) -> Dict[str, Any]:
    return resolve_gpu_backend_for_targets_policy(
        candidates=candidates,
        targets=targets,
        workload=workload,
        backend_available=lambda backend, selected_workload: (
            runner._gpu_3d_backend_available(backend)
            if selected_workload == "gpu_3d"
            else runner._vram_backend_available(backend)
        ),
        support_summary=runner._gpu_backend_support_summary,
    )


def gpu_3d_backend_name(runner: Any, gpu: Any, stage: Optional[Any] = None) -> str:
    targets = runner._gpu_targets(gpu.gpus)
    resolution = runner._resolve_gpu_backend_for_targets(
        candidates=runner._gpu_3d_backend_candidates(gpu, stage),
        targets=targets,
        workload="gpu_3d",
    )
    return str(resolution.get("backend") or "none")


def vram_backend_name(runner: Any, vram: Any) -> str:
    targets = runner._gpu_targets(vram.gpus)
    resolution = runner._resolve_gpu_backend_for_targets(
        candidates=runner._vram_backend_candidates(vram),
        targets=targets,
        workload="vram",
    )
    return str(resolution.get("backend") or "none")


def effective_gpu_targets(
    targets: List[Dict[str, Any]],
    resolution: Optional[Dict[str, Any]],
) -> List[Optional[Dict[str, Any]]]:
    if not targets:
        return [None]
    support = (resolution or {}).get("support") or {}
    supported_targets = support.get("supported_targets") or []
    if supported_targets:
        filtered: List[Dict[str, Any]] = []
        for entry in supported_targets:
            target = entry.get("target")
            if isinstance(target, dict):
                filtered.append(target)
        if filtered:
            return filtered
        return []
    backend = str((resolution or {}).get("backend") or "none")
    if backend and backend != "none":
        return list(targets)
    return []

