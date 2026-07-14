#!/usr/bin/env python3
"""OpenCL internal GPU worker spec builders."""

from __future__ import annotations

from typing import Any, Dict, Optional

from Modules.lvs_gpu_worker_plan import GpuWorkerSpec


def build_python_opencl_compute_worker(
    runner: Any,
    target: Optional[Dict[str, Any]],
    tuning_step: int = 0,
    result_file: str = "",
    profile_mode: str = "steady",
    profile_intensity: str = "extreme",
    compute_variant: str = "baseline",
) -> GpuWorkerSpec:
    runtime = runner._python_runtime() or "python3"
    backend_details = runner._opencl_gpu_backend()
    matched_device = runner._opencl_device_for_target(target)
    selected_env = dict(
        (matched_device.get("required_env") if matched_device else None)
        or backend_details.get("selected_env")
        or {}
    )
    selected_env = runner._opencl_target_env(target, selected_env)
    params = runner._gpu_worker_tuned_params(
        target,
        tuning_step,
        backend="python_opencl_compute",
        workload="gpu_3d",
        profile_intensity=profile_intensity,
        profile_mode=profile_mode,
    )
    ramp_params = runner._gpu_internal_ramp_params()
    capability = dict(params.get("capability") or {})
    target_vendor = str(target.get("vendor", "") if target else "")
    target_vendor_id = str(target.get("vendor_id", "") if target else "")
    target_name = str(target.get("name", "") if target else "")
    target_card = str(target.get("card", "") if target else "")
    target_slot = str(target.get("slot", "") if target else "")
    target_id = str(target.get("target_id", "") if target else "")
    target_gpu_index = int(target.get("gpu_index", 0)) if target else 0
    target_vram_total = int(target.get("vram_total") or 0) if target else 0
    normalized_compute_variant = runner._normalize_opencl_compute_variant(compute_variant)
    command = runner._wrap_gpu_command(
        [
            runtime,
            "-c",
            runner._opencl_compute_workload_script(
                target_vendor=target_vendor,
                target_vendor_id=target_vendor_id,
                target_name=target_name,
                target_card=target_card,
                target_slot=target_slot,
                target_id=target_id,
                target_gpu_index=target_gpu_index,
                target_vram_total=target_vram_total,
                worker_params={
                    "surface_size": params["surface_size"],
                    "draw_count": params["draw_count"],
                    "shader_iterations": params["shader_iterations"],
                    "compute_units": int(capability.get("compute_units", 0) or 0),
                    "max_work_group_size": int(capability.get("max_work_group_size", 0) or 0),
                    "max_clock_mhz": int(capability.get("max_clock_mhz", 0) or 0),
                    "device_class": str(capability.get("device_class", "") or ""),
                    "parallelism_hint": int(capability.get("parallelism_hint", 1) or 1),
                    "ramp_step_seconds": ramp_params["ramp_step_seconds"],
                    "start_load_fraction": ramp_params["start_load_fraction"],
                    "safe_mode_enabled": runner._gpu_safe_mode_enabled(),
                    "safe_max_load_scale": max(0.75, float(runner._settings.gpu_safe_max_load_scale or 1.0)),
                    "compute_variant": normalized_compute_variant,
                    "result_file": result_file,
                },
            ),
        ],
        target,
        selected_env,
    )
    return GpuWorkerSpec(
        workload="gpu_3d",
        backend="python_opencl_compute",
        gpu_index=target_gpu_index,
        card=target_card,
        slot=target_slot,
        target_id=target_id,
        command=command,
        env_overrides=selected_env,
        surface_size=params["surface_size"],
        draw_count=params["draw_count"],
        shader_iterations=params["shader_iterations"],
        tuning_step=tuning_step,
        backend_api_family="OpenCL",
        suite_scaling_mode="parametric",
        suite_verification="compute_readback",
        device_class=str(capability.get("device_class", "") or ""),
        profile_mode=str(profile_mode or ""),
        profile_intensity=runner._normalize_gpu_3d_intensity(profile_intensity),
        compute_variant=normalized_compute_variant,
    )


def build_python_opencl_vram_worker(
    runner: Any,
    target: Optional[Dict[str, Any]],
    target_vram_bytes: int,
    tuning_step: int = 0,
    result_file: str = "",
) -> GpuWorkerSpec:
    runtime = runner._python_runtime() or "python3"
    backend_details = runner._opencl_gpu_backend()
    matched_device = runner._opencl_device_for_target(target)
    selected_env = dict(
        (matched_device.get("required_env") if matched_device else None)
        or backend_details.get("selected_env")
        or {}
    )
    selected_env = runner._opencl_target_env(target, selected_env)
    capability = runner._gpu_capability_profile(target)
    ramp_params = runner._gpu_internal_ramp_params()
    capped_target_vram_bytes = runner._cap_gpu_vram_target_bytes(target, target_vram_bytes)
    target_vendor = str(target.get("vendor", "") if target else "")
    target_vendor_id = str(target.get("vendor_id", "") if target else "")
    target_name = str(target.get("name", "") if target else "")
    target_card = str(target.get("card", "") if target else "")
    target_slot = str(target.get("slot", "") if target else "")
    target_id = str(target.get("target_id", "") if target else "")
    target_gpu_index = int(target.get("gpu_index", 0)) if target else 0
    target_vram_total = int(target.get("vram_total") or 0) if target else 0
    command = runner._wrap_gpu_command(
        [
            runtime,
            "-c",
            runner._opencl_vram_workload_script(
                target_vram_bytes=capped_target_vram_bytes,
                target_vendor=target_vendor,
                target_vendor_id=target_vendor_id,
                target_name=target_name,
                target_card=target_card,
                target_slot=target_slot,
                target_id=target_id,
                target_gpu_index=target_gpu_index,
                target_vram_total=target_vram_total,
                worker_params={
                    "compute_units": int(capability.get("compute_units", 0) or 0),
                    "max_work_group_size": int(capability.get("max_work_group_size", 0) or 0),
                    "max_clock_mhz": int(capability.get("max_clock_mhz", 0) or 0),
                    "device_class": str(capability.get("device_class", "") or ""),
                    "parallelism_hint": int(capability.get("parallelism_hint", 1) or 1),
                    "ramp_step_seconds": ramp_params["ramp_step_seconds"],
                    "start_load_fraction": ramp_params["start_load_fraction"],
                    "safe_mode_enabled": runner._gpu_safe_mode_enabled(),
                },
                result_file=result_file,
            ),
        ],
        target,
        selected_env,
    )
    return GpuWorkerSpec(
        workload="vram",
        backend="python_opencl",
        gpu_index=target_gpu_index,
        card=target_card,
        slot=target_slot,
        target_id=target_id,
        command=command,
        env_overrides=selected_env,
        target_vram_bytes=capped_target_vram_bytes,
        texture_side=0,
        clear_passes=0,
        tuning_step=tuning_step,
        backend_api_family="OpenCL",
        suite_scaling_mode="parametric",
        suite_verification="memory_readback",
        device_class=str(capability.get("device_class", "") or ""),
    )
