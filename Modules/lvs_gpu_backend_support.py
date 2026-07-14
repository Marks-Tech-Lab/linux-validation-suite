#!/usr/bin/env python3
"""Backend-specific GPU target support payload builders."""

from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, List, Optional

from .lvs_gpu_identity import normalize_pci_id, normalize_pci_slot
from .lvs_opencl_targeting import gpu_vendor_matches_text

GpuBackendSupportProvider = Callable[[], Dict[str, Any]]

OPENCL_BACKENDS = {"python_opencl_compute", "python_opencl"}
VULKAN_BACKENDS = {"python_vulkan_transfer", "python_vulkan_compute", "vkmark", "vkcube"}
EGL_BACKENDS = {"python_egl_gles2", "glmark2", "glxgears"}


def base_gpu_backend_target_support(
    *,
    backend: str,
    target: Optional[Dict[str, Any]],
    workload: str,
) -> Dict[str, Any]:
    target_label = str((target or {}).get("target_id") or (target or {}).get("card") or "default")
    return {
        "backend": backend,
        "workload": workload,
        "target": dict(target) if target else None,
        "target_label": target_label,
        "supported": False,
        "reason": "",
        "resolved_device_name": "",
    }


def opencl_backend_target_support(
    *,
    backend: str,
    target: Optional[Dict[str, Any]],
    workload: str,
    matched_device: Optional[Dict[str, Any]],
    all_devices: List[Dict[str, Any]],
) -> Dict[str, Any]:
    payload = base_gpu_backend_target_support(backend=backend, target=target, workload=workload)
    if not target:
        payload["supported"] = True
        return payload
    if matched_device:
        payload["supported"] = True
        payload["resolved_device_name"] = str(matched_device.get("name", "") or "")
        return payload

    target_vendor = str((target or {}).get("vendor", "") or "").strip().lower()
    target_vendor_id = normalize_pci_id(str((target or {}).get("vendor_id", "") or ""))
    same_vendor = [
        d for d in all_devices
        if (
            target_vendor_id
            and target_vendor_id == normalize_pci_id(str(d.get("vendor_id", "") or ""))
        )
        or (
            target_vendor
            and gpu_vendor_matches_text(
                target_vendor,
                str(d.get("vendor", "") or ""),
                str(d.get("platform_vendor", "") or ""),
                str(d.get("name", "") or ""),
            )
        )
    ]
    if not all_devices:
        payload["reason"] = "no OpenCL GPU devices found at all; check that an OpenCL runtime is installed"
    elif not same_vendor:
        found_vendors = list(dict.fromkeys(
            str(d.get("vendor", "") or d.get("platform_vendor", "") or "unknown").split("(")[0].strip()
            for d in all_devices
        ))
        if target_vendor == "intel":
            probe_text = "native, Intel ICD, and Rusticl iris probes"
        elif target_vendor == "amd":
            probe_text = "native, AMD ICD, and Rusticl radeonsi probes"
        elif target_vendor == "nvidia":
            probe_text = "native and NVIDIA ICD probes"
        else:
            probe_text = "native and vendor ICD probes"
        payload["reason"] = (
            f"no {target_vendor or 'matching'} OpenCL device found after {probe_text}; "
            f"found {len(all_devices)} OpenCL GPU(s) from: {', '.join(found_vendors[:4])}"
        )
    else:
        payload["reason"] = "OpenCL devices exist for this vendor, but no device matched the target GPU"
    return payload


def vulkan_nvidia_dropout_reason(
    *,
    target: Optional[Dict[str, Any]],
    nvidia_smi_available: bool,
    nvidia_slots: Iterable[str],
) -> str:
    if not target:
        return ""
    target_vendor = str((target or {}).get("vendor", "") or "").strip().lower()
    target_driver = str((target or {}).get("driver", "") or "").strip().lower()
    target_slot = normalize_pci_slot(
        str((target or {}).get("slot", "") or (target or {}).get("target_id", "") or "")
    ).lower()
    normalized_nvidia_slots = {
        normalize_pci_slot(str(slot or "")).lower()
        for slot in nvidia_slots
        if str(slot or "").strip()
    }
    if (
        target_vendor == "nvidia"
        and target_driver == "nvidia"
        and nvidia_smi_available
        and target_slot
        and target_slot not in normalized_nvidia_slots
    ):
        return (
            f"NVIDIA target {target_slot} is not visible to nvidia-smi; "
            "the card may be dropped/offline, so Vulkan stress is skipped for this target"
        )
    return ""


def vulkan_backend_target_support(
    *,
    backend: str,
    target: Optional[Dict[str, Any]],
    workload: str,
    vulkan_match: Optional[Dict[str, Any]],
    nvidia_dropout_reason: str = "",
) -> Dict[str, Any]:
    payload = base_gpu_backend_target_support(backend=backend, target=target, workload=workload)
    if not target:
        payload["supported"] = True
        return payload
    if nvidia_dropout_reason:
        payload["reason"] = nvidia_dropout_reason
        return payload

    match = dict(vulkan_match or {})
    device = match.get("device") or {}
    if match.get("available"):
        payload["supported"] = True
        payload["resolved_device_name"] = str(device.get("deviceName", "") or "")
    else:
        payload["reason"] = "no matching Vulkan GPU device found for this target"
    return payload


def egl_backend_target_support(
    *,
    backend: str,
    target: Optional[Dict[str, Any]],
    workload: str,
    egl_probe: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    payload = base_gpu_backend_target_support(backend=backend, target=target, workload=workload)
    if not target:
        payload["supported"] = True
        return payload

    probe = dict(egl_probe or {})
    if backend == "python_egl_gles2":
        payload["egl_device_exact_match"] = bool(probe.get("egl_device_exact_match"))
        payload["egl_selected_device"] = dict(probe.get("egl_selected_device") or {})
        selected_env = dict(probe.get("selected_env") or {})
        payload["selected_env"] = {
            key: value
            for key, value in selected_env.items()
            if str(key).startswith("LVS_EGL_") or str(key) == "__EGL_VENDOR_LIBRARY_FILENAMES"
        }
    if probe.get("available"):
        payload["supported"] = True
        payload["resolved_device_name"] = str(probe.get("renderer", "") or "")
    else:
        payload["reason"] = str(probe.get("reason", "") or "targeted EGL renderer unavailable")
    return payload


def gpu_backend_target_support(
    *,
    backend: str,
    target: Optional[Dict[str, Any]],
    workload: str,
    opencl_support: Optional[GpuBackendSupportProvider] = None,
    vulkan_support: Optional[GpuBackendSupportProvider] = None,
    egl_support: Optional[GpuBackendSupportProvider] = None,
) -> Dict[str, Any]:
    payload = base_gpu_backend_target_support(backend=backend, target=target, workload=workload)
    if not target:
        payload["supported"] = True
        return payload
    if backend in OPENCL_BACKENDS and opencl_support:
        return dict(opencl_support())
    if backend in VULKAN_BACKENDS and vulkan_support:
        return dict(vulkan_support())
    if backend in EGL_BACKENDS and egl_support:
        return dict(egl_support())

    payload["supported"] = True
    return payload
