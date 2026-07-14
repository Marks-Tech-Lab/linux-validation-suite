#!/usr/bin/env python3
"""EGL/GLES internal GPU worker spec builders."""

from __future__ import annotations

from typing import Any, Dict, Optional

from Modules.lvs_gpu_worker_plan import GpuWorkerSpec


def build_python_gpu_3d_worker(
    runner: Any,
    target: Optional[Dict[str, Any]],
    tuning_step: int = 0,
    result_file: str = "",
    profile_mode: str = "steady",
    profile_intensity: str = "extreme",
    compute_variant: str = "baseline",
) -> GpuWorkerSpec:
    runtime = runner._python_runtime() or "python3"
    params = runner._gpu_worker_tuned_params(
        target,
        tuning_step,
        backend="python_egl_gles2",
        workload="gpu_3d",
        profile_intensity=profile_intensity,
        profile_mode=profile_mode,
    )
    ramp_params = runner._gpu_internal_ramp_params()
    selected_env = dict(runner._egl_gpu_backend_for_target(target).get("selected_env") or {}) if target else {}
    target_vendor = str(target.get("vendor", "") if target else "")
    target_name = str(target.get("name", "") if target else "")
    target_slot = str(target.get("slot", "") if target else "")
    target_id = str(target.get("target_id", "") if target else "")
    command = runner._wrap_gpu_command(
        [
            runtime,
            "-c",
            runner._egl_gles_workload_script(
                "gpu_3d",
                worker_params={
                    "target_vendor": target_vendor,
                    "target_name": target_name,
                    "target_slot": target_slot,
                    "target_id": target_id,
                    "surface_size": params["surface_size"],
                    "draw_count": params["draw_count"],
                    "shader_iterations": params["shader_iterations"],
                    "ramp_step_seconds": ramp_params["ramp_step_seconds"],
                    "start_load_fraction": ramp_params["start_load_fraction"],
                    "result_file": result_file,
                },
            ),
        ],
        target,
        selected_env,
    )
    return GpuWorkerSpec(
        workload="gpu_3d",
        backend="python_egl_gles2",
        gpu_index=int(target.get("gpu_index", 0)) if target else 0,
        card=target.get("card", "") if target else "",
        slot=target.get("slot", "") if target else "",
        target_id=target.get("target_id", "") if target else "",
        command=command,
        env_overrides=selected_env,
        surface_size=params["surface_size"],
        draw_count=params["draw_count"],
        shader_iterations=params["shader_iterations"],
        tuning_step=tuning_step,
        backend_api_family="EGL/GLES2",
        suite_scaling_mode="parametric",
        suite_verification="render_readback",
        device_class=str(runner._gpu_capability_profile(target).get("device_class", "") or "") if target else "",
        profile_mode=str(profile_mode or ""),
        profile_intensity=runner._normalize_gpu_3d_intensity(profile_intensity),
    )


def build_python_vram_worker(
    runner: Any,
    target: Optional[Dict[str, Any]],
    target_vram_bytes: int,
    tuning_step: int = 0,
    result_file: str = "",
) -> GpuWorkerSpec:
    runtime = runner._python_runtime() or "python3"
    params = runner._gpu_worker_tuned_params(target, tuning_step, backend="python_egl_gles2", workload="vram")
    ramp_params = runner._gpu_internal_ramp_params()
    selected_env = dict(runner._egl_gpu_backend_for_target(target).get("selected_env") or {}) if target else {}
    capped_target_vram_bytes = runner._cap_gpu_vram_target_bytes(target, target_vram_bytes)
    target_vendor = str(target.get("vendor", "") if target else "")
    target_name = str(target.get("name", "") if target else "")
    target_slot = str(target.get("slot", "") if target else "")
    target_id = str(target.get("target_id", "") if target else "")
    surface_size = max(512, params["surface_size"] // 2)
    draw_count = max(8, params["draw_count"] // 8)
    shader_iterations = max(12, params["shader_iterations"] // 2)
    command = runner._wrap_gpu_command(
        [
            runtime,
            "-c",
            runner._egl_gles_workload_script(
                "vram",
                capped_target_vram_bytes,
                worker_params={
                    "target_vendor": target_vendor,
                    "target_name": target_name,
                    "target_slot": target_slot,
                    "target_id": target_id,
                    "surface_size": surface_size,
                    "draw_count": draw_count,
                    "shader_iterations": shader_iterations,
                    "texture_side": params["texture_side"],
                    "clear_passes": params["clear_passes"],
                    "ramp_step_seconds": ramp_params["ramp_step_seconds"],
                    "start_load_fraction": ramp_params["start_load_fraction"],
                    "result_file": result_file,
                },
            ),
        ],
        target,
        selected_env,
    )
    return GpuWorkerSpec(
        workload="vram",
        backend="python_egl_gles2",
        gpu_index=int(target.get("gpu_index", 0)) if target else 0,
        card=target.get("card", "") if target else "",
        slot=target.get("slot", "") if target else "",
        target_id=target.get("target_id", "") if target else "",
        command=command,
        env_overrides=selected_env,
        surface_size=surface_size,
        draw_count=draw_count,
        shader_iterations=shader_iterations,
        target_vram_bytes=capped_target_vram_bytes,
        texture_side=params["texture_side"],
        clear_passes=params["clear_passes"],
        tuning_step=tuning_step,
        backend_api_family="EGL/GLES2",
        suite_scaling_mode="parametric",
        suite_verification="render_readback",
        device_class=str(runner._gpu_capability_profile(target).get("device_class", "") or "") if target else "",
    )

