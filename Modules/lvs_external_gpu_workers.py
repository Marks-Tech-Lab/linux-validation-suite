#!/usr/bin/env python3
"""External GPU backend worker construction helpers."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from Modules.lvs_external_gpu_supervisor import build_external_gpu_supervisor_script
from Modules.lvs_gpu_worker_plan import GpuWorkerSpec


def vulkan_gpu_number_for_target(runner: Any, target: Optional[Dict[str, Any]]) -> Optional[int]:
    match = runner._vulkan_device_for_target(target)
    device = match.get("device") or {}
    try:
        index = int(device.get("index", -1))
    except Exception:
        index = -1
    return index if index >= 0 else None


def external_gpu_backend_command(
    runner: Any,
    backend: str,
    target: Optional[Dict[str, Any]] = None,
) -> List[str]:
    if backend == "glmark2":
        return ["glmark2", "--off-screen", "--reuse-context", "--run-forever"]
    if backend == "vkmark":
        return ["vkmark"]
    if backend == "vkcube":
        command = ["vkcube", "--suppress_popups", "--present_mode", "0", "--width", "256", "--height", "256"]
        gpu_number = vulkan_gpu_number_for_target(runner, target)
        if gpu_number is not None:
            command.extend(["--gpu_number", str(gpu_number)])
        return command
    if backend == "glxgears":
        return ["glxgears"]
    return [backend] if backend else []


def gpu_external_target_env(
    target: Optional[Dict[str, Any]],
    backend: str,
) -> Dict[str, str]:
    env: Dict[str, str] = {}
    if backend not in {"vkmark", "vkcube"}:
        return env
    if not target:
        return env
    vendor_id = str(target.get("vendor_id", "") or "").strip().lower().removeprefix("0x")
    device_id = str(target.get("device", "") or "").strip().lower().removeprefix("0x")
    if vendor_id and device_id:
        env["MESA_VK_DEVICE_SELECT"] = f"{vendor_id}:{device_id}"
    return env


def gpu_external_process_count(
    runner: Any,
    target: Optional[Dict[str, Any]],
    backend: str,
) -> int:
    capability = runner._gpu_capability_profile(target)
    parallelism_hint = max(1, int(capability.get("parallelism_hint", 1) or 1))
    load_scale = max(1.0, float(capability.get("load_scale", 1.0) or 1.0))
    device_class = str(capability.get("device_class", "integrated") or "integrated")
    if backend == "glmark2":
        desired = 1 if load_scale < 2.1 else 2
    elif backend == "vkmark":
        desired = 2 if device_class == "discrete" and load_scale >= 1.1 else 1
    elif backend == "vkcube":
        desired = 2 if device_class == "discrete" else (2 if parallelism_hint >= 3 else 1)
    elif backend == "glxgears":
        desired = 1 + min(3, max(0, parallelism_hint))
    else:
        desired = 1
    if device_class != "discrete":
        desired = min(desired, 1 if backend in {"glmark2", "vkmark"} else 2)
    safe_cap = max(1, int((runner._settings.gpu_external_max_processes if runner._settings else 2) or 2))
    if runner._gpu_safe_mode_enabled():
        safe_cap = min(safe_cap, 2)
    return max(1, min(desired, safe_cap))


def external_gpu_supervisor_script(
    runner: Any,
    *,
    backend: str,
    child_command: List[str],
    child_env: Optional[Dict[str, str]],
    target: Optional[Dict[str, Any]],
    target_process_count: int,
    result_file: str = "",
) -> str:
    ramp_params = runner._gpu_internal_ramp_params()
    resolved_device_name = ""
    selection_ambiguous = False
    if backend in {"vkmark", "vkcube"}:
        vulkan_match = runner._vulkan_device_for_target(target)
        matched_device = vulkan_match.get("device") or {}
        resolved_device_name = str(matched_device.get("deviceName", "") or "")
        selection_ambiguous = bool(vulkan_match.get("ambiguous"))
    return build_external_gpu_supervisor_script(
        backend=backend,
        child_command=child_command,
        child_env=child_env,
        target=target,
        target_process_count=target_process_count,
        ramp_step_seconds=float(ramp_params["ramp_step_seconds"]),
        start_load_fraction=float(ramp_params["start_load_fraction"]),
        resolved_device_name=resolved_device_name,
        selection_ambiguous=selection_ambiguous,
        result_file=result_file,
    )


def build_supervised_external_gpu_command(
    runner: Any,
    *,
    backend: str,
    target: Optional[Dict[str, Any]],
    process_count: int,
    result_file: str = "",
) -> List[str]:
    child_command = external_gpu_backend_command(runner, backend, target)
    target_env = gpu_external_target_env(target, backend)
    runtime = runner._python_runtime()
    if runtime:
        return runner._wrap_gpu_command(
            [
                runtime,
                "-c",
                external_gpu_supervisor_script(
                    runner,
                    backend=backend,
                    child_command=child_command,
                    child_env=target_env,
                    target=target,
                    target_process_count=process_count,
                    result_file=result_file,
                ),
            ],
            target,
        )
    return runner._wrap_gpu_command(child_command, target, target_env)


def external_gpu_worker_spec(
    runner: Any,
    *,
    workload: str,
    backend: str,
    target: Optional[Dict[str, Any]],
    result_file: str = "",
    profile_mode: str = "",
    profile_intensity: str = "",
) -> GpuWorkerSpec:
    backend_meta = runner._gpu_3d_backend_catalog_entry(backend)
    process_count = gpu_external_process_count(runner, target, backend)
    resolved_device_name = ""
    selection_ambiguous = False
    if backend in {"vkmark", "vkcube"}:
        vulkan_match = runner._vulkan_device_for_target(target)
        matched_device = vulkan_match.get("device") or {}
        resolved_device_name = str(matched_device.get("deviceName", "") or "")
        selection_ambiguous = bool(vulkan_match.get("ambiguous"))
    command = build_supervised_external_gpu_command(
        runner,
        backend=backend,
        target=target,
        process_count=process_count,
        result_file=result_file,
    )
    return GpuWorkerSpec(
        workload=workload,
        backend=backend,
        gpu_index=int(target.get("gpu_index", 0)) if target else 0,
        card=target.get("card", "") if target else "",
        slot=target.get("slot", "") if target else "",
        target_id=target.get("target_id", "") if target else "",
        command=command,
        backend_api_family=str(backend_meta.get("api_family", "") or ""),
        suite_scaling_mode=str(backend_meta.get("suite_scaling_mode", "") or ""),
        suite_verification=str(backend_meta.get("suite_verification", "") or ""),
        process_count=process_count,
        resolved_device_name=resolved_device_name,
        selection_ambiguous=selection_ambiguous,
        device_class=str(runner._gpu_capability_profile(target).get("device_class", "") or "") if target else "",
        profile_mode=str(profile_mode or ""),
        profile_intensity=runner._normalize_gpu_3d_intensity(profile_intensity) if profile_intensity else "",
    )

