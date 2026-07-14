from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, List


CPU_HELPER_PROBE_MODES = ("auto", "scalar", "sse", "avx", "avx2", "avx512")
BACKEND_COMMAND_NAMES = (
    "stress-ng",
    "glmark2",
    "vkmark",
    "vkcube",
    "glxgears",
    "nvidia-smi",
    "intel_gpu_top",
    "ipmitool",
    "ipmi-sensors",
)


def build_backend_availability(
    *,
    cpu_native_helper_available: bool,
    memory_native_helper_available: bool,
    command_available: Dict[str, bool],
    vulkaninfo_available: bool,
    python_vulkan_compute_available: bool,
    python_vulkan_transfer_available: bool,
    python_opencl_available: bool,
    python_egl_gles2_available: bool,
    python_runtime_available: bool,
) -> Dict[str, bool]:
    return {
        "cpu_native_helper": bool(cpu_native_helper_available),
        "memory_native_helper": bool(memory_native_helper_available),
        "stress_ng": bool(command_available.get("stress-ng")),
        "glmark2": bool(command_available.get("glmark2")),
        "vkmark": bool(command_available.get("vkmark")),
        "vkcube": bool(command_available.get("vkcube")),
        "vulkaninfo": bool(vulkaninfo_available),
        "python_vulkan_compute": bool(python_vulkan_compute_available),
        "python_vulkan_transfer": bool(python_vulkan_transfer_available),
        "glxgears": bool(command_available.get("glxgears")),
        "python_opencl_compute": bool(python_opencl_available),
        "python_opencl": bool(python_opencl_available),
        "python_egl_gles2": bool(python_egl_gles2_available),
        "nvidia_smi": bool(command_available.get("nvidia-smi")),
        "intel_gpu_top": bool(command_available.get("intel_gpu_top")),
        "ipmitool": bool(command_available.get("ipmitool")),
        "ipmi_sensors": bool(command_available.get("ipmi-sensors")),
        "python_fallback": bool(python_runtime_available),
    }


def build_backend_availability_from_probe_results(
    *,
    cpu_native_helper: Dict[str, Any],
    memory_native_helper: Dict[str, Any],
    command_available: Dict[str, bool],
    vulkaninfo: Dict[str, Any],
    python_vulkan_compute: Dict[str, Any],
    python_vulkan_transfer: Dict[str, Any],
    python_opencl: Dict[str, Any],
    python_egl_gles2: Dict[str, Any],
    python_runtime_available: bool,
) -> Dict[str, bool]:
    return build_backend_availability(
        cpu_native_helper_available=bool(cpu_native_helper.get("available")),
        memory_native_helper_available=bool(memory_native_helper.get("available")),
        command_available=command_available,
        vulkaninfo_available=bool(vulkaninfo.get("available")),
        python_vulkan_compute_available=bool(python_vulkan_compute.get("available")),
        python_vulkan_transfer_available=bool(python_vulkan_transfer.get("available")),
        python_opencl_available=bool(python_opencl.get("available")),
        python_egl_gles2_available=bool(python_egl_gles2.get("available")),
        python_runtime_available=bool(python_runtime_available),
    )


def collect_backend_availability_from_runner(
    runner: Any,
    command_names: Iterable[str] = BACKEND_COMMAND_NAMES,
) -> Dict[str, bool]:
    return build_backend_availability_from_probe_results(
        cpu_native_helper=runner._cpu_helper_status(),
        memory_native_helper=runner._memory_helper_status(),
        command_available={name: runner._command_exists(name) for name in command_names},
        vulkaninfo=runner._vulkan_runtime_details(),
        python_vulkan_compute=runner._vulkan_native_backend(),
        python_vulkan_transfer=runner._vulkan_transfer_backend(),
        python_opencl=runner._opencl_gpu_backend(),
        python_egl_gles2=runner._egl_gpu_backend(),
        python_runtime_available=bool(runner._python_runtime()),
    )


def probe_cpu_helper_modes(
    resolver: Callable[[str], str],
    modes: Iterable[str] = CPU_HELPER_PROBE_MODES,
) -> Dict[str, str]:
    return {mode: resolver(mode) for mode in modes}


def enrich_cpu_helper_backend_details(
    helper_details: Dict[str, Any],
    *,
    resolved_modes: Dict[str, str],
    default_kernel_flavors: Dict[str, str],
    supported_kernel_flavors: list[str],
) -> Dict[str, Any]:
    details = dict(helper_details)
    if not details.get("available"):
        return details
    details.update(
        {
            "resolved_modes": dict(resolved_modes),
            "default_kernel_flavors": dict(default_kernel_flavors),
            "supported_kernel_flavors": list(supported_kernel_flavors),
        }
    )
    return details


def build_backend_details_payload(
    *,
    cpu_native_helper: Dict[str, Any],
    memory_native_helper: Dict[str, Any],
    gpu_3d_catalog: Dict[str, Any],
    python_opencl_compute: Dict[str, Any],
    python_opencl: Dict[str, Any],
    python_egl_gles2: Dict[str, Any],
    python_vulkan_compute: Dict[str, Any],
    python_vulkan_transfer: Dict[str, Any],
    vulkaninfo: Dict[str, Any],
    nvidia_smi: Dict[str, Any],
    intel_gpu_top: Dict[str, Any],
    ipmi_sensors: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "cpu_native_helper": cpu_native_helper,
        "memory_native_helper": memory_native_helper,
        "gpu_3d_catalog": gpu_3d_catalog,
        "python_opencl_compute": python_opencl_compute,
        "python_opencl": python_opencl,
        "python_egl_gles2": python_egl_gles2,
        "python_vulkan_compute": python_vulkan_compute,
        "python_vulkan_transfer": python_vulkan_transfer,
        "vulkaninfo": vulkaninfo,
        "nvidia_smi": nvidia_smi,
        "intel_gpu_top": intel_gpu_top,
        "ipmi_sensors": ipmi_sensors,
    }


def build_backend_details_from_probe_results(
    *,
    cpu_native_helper: Dict[str, Any],
    memory_native_helper: Dict[str, Any],
    cpu_mode_resolver: Callable[[str], str],
    cpu_default_kernel_flavor_resolver: Callable[[str], str],
    cpu_supported_kernel_flavors: Callable[[], list[str]],
    gpu_3d_catalog: Dict[str, Any],
    python_opencl: Dict[str, Any],
    opencl_safety_profile: Dict[str, Any],
    python_egl_gles2: Dict[str, Any],
    python_vulkan_compute: Dict[str, Any],
    python_vulkan_transfer: Dict[str, Any],
    vulkaninfo: Dict[str, Any],
    nvidia_smi_available: bool,
    intel_gpu_top: Dict[str, Any],
    ipmi_sensors: Dict[str, Any],
) -> Dict[str, Any]:
    helper_details = dict(cpu_native_helper)
    helper_available = bool(helper_details.get("available"))
    helper_details = enrich_cpu_helper_backend_details(
        helper_details,
        resolved_modes=probe_cpu_helper_modes(cpu_mode_resolver) if helper_available else {},
        default_kernel_flavors=probe_cpu_helper_modes(cpu_default_kernel_flavor_resolver) if helper_available else {},
        supported_kernel_flavors=cpu_supported_kernel_flavors() if helper_available else [],
    )
    opencl_backend = dict(python_opencl)
    return build_backend_details_payload(
        cpu_native_helper=helper_details,
        memory_native_helper=dict(memory_native_helper),
        gpu_3d_catalog=dict(gpu_3d_catalog),
        python_opencl_compute={
            **opencl_backend,
            "safety_profile": dict(opencl_safety_profile),
        },
        python_opencl=opencl_backend,
        python_egl_gles2=dict(python_egl_gles2),
        python_vulkan_compute=dict(python_vulkan_compute),
        python_vulkan_transfer=dict(python_vulkan_transfer),
        vulkaninfo=dict(vulkaninfo),
        nvidia_smi={
            "available": bool(nvidia_smi_available),
            "path": "nvidia-smi" if nvidia_smi_available else "",
        },
        intel_gpu_top=dict(intel_gpu_top),
        ipmi_sensors=dict(ipmi_sensors),
    )


def collect_backend_details_from_runner(
    runner: Any,
    gpu_3d_backend_catalog: Iterable[str],
) -> Dict[str, Any]:
    return build_backend_details_from_probe_results(
        cpu_native_helper=runner._cpu_helper_status(),
        memory_native_helper=runner._memory_helper_status(),
        cpu_mode_resolver=runner._cpu_helper_resolved_mode,
        cpu_default_kernel_flavor_resolver=runner._cpu_helper_default_kernel_flavor,
        cpu_supported_kernel_flavors=runner._cpu_supported_kernel_flavors,
        gpu_3d_catalog={
            backend: runner._gpu_3d_backend_catalog_entry(backend)
            for backend in gpu_3d_backend_catalog
        },
        python_opencl=runner._opencl_gpu_backend(),
        opencl_safety_profile=runner._opencl_compute_safety_profile(),
        python_egl_gles2=runner._egl_gpu_backend(),
        python_vulkan_compute=runner._vulkan_native_backend(),
        python_vulkan_transfer=runner._vulkan_transfer_backend(),
        vulkaninfo=runner._vulkan_runtime_details(),
        nvidia_smi_available=runner._command_exists("nvidia-smi"),
        intel_gpu_top=runner._intel_gpu_top_details(),
        ipmi_sensors=runner._ipmi_sensor_details(),
    )


def build_opencl_backend_payload(
    *,
    selected_probe: Dict[str, Any],
    probe_attempts: Iterable[Dict[str, Any]],
    devices: Iterable[Dict[str, Any]],
) -> Dict[str, Any]:
    all_devices = [dict(device) for device in devices]
    for index, device in enumerate(all_devices):
        device["opencl_index"] = index
    device_contexts = sorted(
        {
            str(device.get("probe_context", "") or "native")
            for device in all_devices
        }
    )
    selected_context = (
        device_contexts[0]
        if len(device_contexts) == 1
        else (
            "mixed_per_target"
            if device_contexts
            else str(selected_probe.get("context", "native") or "native")
        )
    )
    return {
        **selected_probe,
        "devices": all_devices,
        "available": bool(all_devices),
        "selected_context": selected_context,
        "selected_env": dict(selected_probe.get("selected_env") or {}) if len(device_contexts) == 1 else {},
        "probe_attempts": [
            {
                "context": attempt.get("context", ""),
                "available": bool(attempt.get("available")),
                "reason": str(attempt.get("reason", "") or ""),
                "selected_env": dict(attempt.get("selected_env") or {}),
                "device_count": len(attempt.get("devices") or []),
                "platform_count": int(attempt.get("platform_count", 0) or 0),
                "platforms": attempt.get("platforms") or [],
            }
            for attempt in probe_attempts
        ],
    }


def build_egl_backend_payload(
    *,
    payload: Dict[str, Any],
    returncode: int,
    stdout: str,
    stderr: str,
    target: Dict[str, Any] | None,
    is_software_renderer: Callable[[str], bool],
) -> Dict[str, Any]:
    renderer = str(payload.get("renderer", "") or "")
    vendor = str(payload.get("vendor", "") or "")
    available = bool(payload.get("available")) and not is_software_renderer(renderer)
    reason = str(payload.get("reason", "") or "")
    if not available and not reason:
        if renderer:
            reason = f"software renderer detected: {renderer}"
        elif returncode != 0:
            reason = (stderr or stdout or "EGL probe failed").strip()
        else:
            reason = "EGL hardware renderer unavailable"
    return {
        "available": available,
        "renderer": renderer,
        "vendor": vendor,
        "reason": reason,
        "target_gpu": target["card"] if target else "",
        "target_dri_prime": target["dri_prime"] if target else "",
    }


def non_cpu_vulkan_gpu_devices(devices: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        device
        for device in devices
        if "cpu" not in str(device.get("deviceType", "")).lower()
        and "llvmpipe" not in str(device.get("deviceName", "")).lower()
    ]


def build_vulkan_native_backend_payload(
    *,
    runtime: Dict[str, Any],
    library: str,
    loader_version: str,
    loader_reason: str,
    native_inventory: Dict[str, Any],
    worker_path: Any,
) -> Dict[str, Any]:
    devices = list(runtime.get("devices") or [])
    if not devices and native_inventory.get("devices"):
        devices = list(native_inventory.get("devices") or [])
    gpu_devices = non_cpu_vulkan_gpu_devices(devices)
    worker_implemented = worker_path.exists()
    reason_parts: List[str] = []
    if not library:
        reason_parts.append(loader_reason or "Vulkan loader library not found")
    if not runtime.get("available") and not native_inventory.get("available"):
        reason_parts.append(str(runtime.get("reason") or native_inventory.get("reason") or "Vulkan runtime inventory unavailable"))
    elif not gpu_devices:
        reason_parts.append("no non-CPU Vulkan GPU devices found")
    if not worker_implemented:
        reason_parts.append(f"worker script not found: {worker_path}")
    available = bool(library) and bool(gpu_devices) and worker_implemented
    return {
        "available": available,
        "loader_available": bool(library),
        "library": library,
        "loader_version": loader_version,
        "runtime_available": bool(runtime.get("available")),
        "runtime_instance_version": str(runtime.get("instance_version", "") or ""),
        "native_inventory_available": bool(native_inventory.get("available")),
        "native_inventory_reason": str(native_inventory.get("reason", "") or ""),
        "runtime_device_count": len(devices),
        "runtime_gpu_device_count": len(gpu_devices),
        "worker_implemented": worker_implemented,
        "worker_path": str(worker_path),
        "planned_backend": "python_vulkan_compute",
        "target_api": "Vulkan compute",
        "target_verification": "compute_readback",
        "reason": "" if available else "; ".join(part for part in reason_parts if part),
        "devices": gpu_devices,
    }


def build_vulkan_transfer_backend_payload(
    native_details: Dict[str, Any],
    *,
    worker_path: Any,
) -> Dict[str, Any]:
    details = dict(native_details)
    gpu_device_count = int(details.get("runtime_gpu_device_count") or 0)
    available = bool(details.get("loader_available")) and gpu_device_count > 0
    reason_parts: List[str] = []
    if not details.get("loader_available"):
        reason_parts.append(str(details.get("reason") or "Vulkan loader library not found"))
    if gpu_device_count <= 0:
        reason_parts.append("no non-CPU Vulkan GPU devices found")
    if not worker_path.exists():
        available = False
        reason_parts.append(f"worker script not found: {worker_path}")
    return {
        **details,
        "available": available,
        "worker_implemented": True,
        "planned_backend": "python_vulkan_transfer",
        "worker_path": str(worker_path),
        "target_api": "Vulkan transfer",
        "target_verification": "transfer_readback",
        "reason": "" if available else "; ".join(part for part in reason_parts if part),
    }
