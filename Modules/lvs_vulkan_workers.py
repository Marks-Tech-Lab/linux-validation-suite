#!/usr/bin/env python3
"""Vulkan internal GPU worker spec builders."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, Optional

from Modules.lvs_gpu_worker_plan import GpuWorkerSpec

DEFAULT_NATIVE_DIR = Path("native")


def build_python_vulkan_transfer_worker(
    runner: Any,
    target: Optional[Dict[str, Any]],
    tuning_step: int = 0,
    result_file: str = "",
    profile_mode: str = "steady",
    profile_intensity: str = "extreme",
) -> GpuWorkerSpec:
    runtime = runner._python_runtime() or "python3"
    worker_path = DEFAULT_NATIVE_DIR / "vulkan_transfer_worker.py"
    params = runner._gpu_worker_tuned_params(
        target,
        tuning_step,
        backend="python_vulkan_transfer",
        workload="gpu_3d",
        profile_intensity=profile_intensity,
        profile_mode=profile_mode,
    )
    ramp_params = runner._gpu_internal_ramp_params()
    capability = dict(params.get("capability") or {})
    target_vendor = str(target.get("vendor", "") if target else "")
    target_vendor_id = str(target.get("vendor_id", "") if target else "")
    target_device_id = str(target.get("device", "") if target else "")
    target_card = str(target.get("card", "") if target else "")
    target_slot = str(target.get("slot", "") if target else "")
    target_id = str(target.get("target_id", "") if target else "")
    target_gpu_index = int(target.get("gpu_index", 0)) if target else 0
    target_vram_total = int(target.get("vram_total") or 0) if target else 0
    buffer_bytes = runner._vulkan_transfer_buffer_bytes(target, params)
    target_env = runner._vulkan_target_env(target)
    command = runner._wrap_gpu_command(
        [
            runtime,
            str(worker_path),
            "--target-vendor",
            target_vendor,
            "--target-vendor-id",
            target_vendor_id,
            "--target-device-id",
            target_device_id,
            "--target-card",
            target_card,
            "--target-slot",
            target_slot,
            "--target-id",
            target_id,
            "--target-gpu-index",
            str(target_gpu_index),
            "--target-vram-total",
            str(target_vram_total),
            "--buffer-bytes",
            str(buffer_bytes),
            "--ramp-step-seconds",
            str(ramp_params["ramp_step_seconds"]),
            "--start-load-fraction",
            str(ramp_params["start_load_fraction"]),
            "--result-file",
            result_file,
            "--device-class",
            str(capability.get("device_class", "") or ""),
            "--profile-mode",
            str(profile_mode or ""),
            "--profile-intensity",
            runner._normalize_gpu_3d_intensity(profile_intensity),
            "--tuning-step",
            str(tuning_step),
        ],
        target,
        target_env,
    )
    return GpuWorkerSpec(
        workload="gpu_3d",
        backend="python_vulkan_transfer",
        gpu_index=target_gpu_index,
        card=target_card,
        slot=target_slot,
        target_id=target_id,
        command=command,
        env_overrides=target_env,
        surface_size=0,
        draw_count=0,
        shader_iterations=0,
        target_vram_bytes=buffer_bytes,
        tuning_step=tuning_step,
        backend_api_family="Vulkan",
        suite_scaling_mode="parametric",
        suite_verification="transfer_readback",
        device_class=str(capability.get("device_class", "") or ""),
        profile_mode=str(profile_mode or ""),
        profile_intensity=runner._normalize_gpu_3d_intensity(profile_intensity),
    )


def build_python_vulkan_compute_worker(
    runner: Any,
    target: Optional[Dict[str, Any]],
    tuning_step: int = 0,
    result_file: str = "",
    profile_mode: str = "steady",
    profile_intensity: str = "extreme",
    compute_variant: str = "hash",
    allocation_percent: int = 0,
    buffer_bytes_override: int = 0,
) -> GpuWorkerSpec:
    runtime = runner._python_runtime() or "python3"
    worker_path = DEFAULT_NATIVE_DIR / "vulkan_compute_worker.py"
    params = runner._gpu_worker_tuned_params(
        target,
        tuning_step,
        backend="python_vulkan_compute",
        workload="gpu_3d",
        profile_intensity=profile_intensity,
        profile_mode=profile_mode,
    )
    ramp_params = runner._gpu_internal_ramp_params()
    capability = dict(params.get("capability") or {})
    target_vendor = str(target.get("vendor", "") if target else "")
    target_vendor_id = str(target.get("vendor_id", "") if target else "")
    target_device_id = str(target.get("device", "") if target else "")
    target_card = str(target.get("card", "") if target else "")
    target_slot = str(target.get("slot", "") if target else "")
    target_id = str(target.get("target_id", "") if target else "")
    target_gpu_index = int(target.get("gpu_index", 0)) if target else 0
    target_vram_total = int(target.get("vram_total") or 0) if target else 0
    normalized_compute_variant = runner._normalize_vulkan_compute_variant(compute_variant)
    buffer_bytes = int(buffer_bytes_override or 0)
    if buffer_bytes <= 0:
        buffer_bytes = runner._vulkan_compute_buffer_bytes(
            target,
            params,
            normalized_compute_variant,
            allocation_percent=allocation_percent,
        )
    compute_rounds = runner._vulkan_compute_rounds(target, params, profile_intensity, normalized_compute_variant)
    dispatch_repeats = runner._vulkan_compute_dispatch_repeats(target, normalized_compute_variant)
    target_env = runner._vulkan_target_env(target)
    command = runner._wrap_gpu_command(
        [
            runtime,
            str(worker_path),
            "--target-vendor",
            target_vendor,
            "--target-vendor-id",
            target_vendor_id,
            "--target-device-id",
            target_device_id,
            "--target-card",
            target_card,
            "--target-slot",
            target_slot,
            "--target-id",
            target_id,
            "--target-gpu-index",
            str(target_gpu_index),
            "--target-vram-total",
            str(target_vram_total),
            "--buffer-bytes",
            str(buffer_bytes),
            "--ramp-step-seconds",
            str(ramp_params["ramp_step_seconds"]),
            "--start-load-fraction",
            str(ramp_params["start_load_fraction"]),
            "--result-file",
            result_file,
            "--device-class",
            str(capability.get("device_class", "") or ""),
            "--profile-mode",
            str(profile_mode or ""),
            "--profile-intensity",
            runner._normalize_gpu_3d_intensity(profile_intensity),
            "--tuning-step",
            str(tuning_step),
            "--compute-rounds",
            str(compute_rounds),
            "--kernel-variant",
            normalized_compute_variant,
            "--dispatch-repeats",
            str(dispatch_repeats),
        ],
        target,
        target_env,
    )
    return GpuWorkerSpec(
        workload="gpu_3d",
        backend="python_vulkan_compute",
        gpu_index=target_gpu_index,
        card=target_card,
        slot=target_slot,
        target_id=target_id,
        command=command,
        env_overrides=target_env,
        target_vram_bytes=buffer_bytes,
        shader_iterations=compute_rounds,
        tuning_step=tuning_step,
        backend_api_family="Vulkan",
        suite_scaling_mode="parametric",
        suite_verification="compute_readback",
        device_class=str(capability.get("device_class", "") or ""),
        profile_mode=str(profile_mode or ""),
        profile_intensity=runner._normalize_gpu_3d_intensity(profile_intensity),
        compute_variant=normalized_compute_variant,
    )


def build_python_vulkan_vram_worker(
    runner: Any,
    target: Optional[Dict[str, Any]],
    target_vram_bytes: int,
    tuning_step: int = 0,
    result_file: str = "",
) -> GpuWorkerSpec:
    spec = build_python_vulkan_compute_worker(
        runner,
        target,
        tuning_step=tuning_step,
        result_file=result_file,
        profile_mode="steady",
        profile_intensity="extreme",
        compute_variant="stateful_memory",
        buffer_bytes_override=target_vram_bytes,
    )
    return GpuWorkerSpec(
        **{
            **asdict(spec),
            "workload": "vram",
            "backend": "python_vulkan_compute",
            "target_vram_bytes": int(target_vram_bytes),
            "backend_api_family": "Vulkan",
            "suite_scaling_mode": "parametric",
            "suite_verification": "memory_readback",
            "compute_variant": "stateful_memory",
        }
    )
