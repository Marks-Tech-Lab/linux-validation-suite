#!/usr/bin/env python3
"""VRAM allocation and mixed-worker routing policy helpers."""

from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, List, Optional


def capacity_vram_request_cap_bytes(target_total: int) -> int:
    total = int(target_total or 0)
    if total <= 0:
        return 0
    if total <= 1024 ** 3:
        reserve = max(128 * 1024 * 1024, int(total * 0.25))
        return max(64 * 1024 * 1024, total - reserve)
    if total <= 2 * 1024 ** 3:
        reserve = max(256 * 1024 * 1024, int(total * 0.15))
        return max(128 * 1024 * 1024, total - reserve)
    return 0


def cap_gpu_vram_target_bytes(
    *,
    requested_bytes: int,
    target_total: int,
    safe_mode_enabled: bool,
    safe_max_vram_percent: float,
) -> int:
    capped = max(64 * 1024 * 1024, int(requested_bytes or 0))
    capacity_cap = capacity_vram_request_cap_bytes(target_total)
    if capacity_cap > 0:
        capped = min(capped, capacity_cap)
    if not safe_mode_enabled:
        return capped
    if int(target_total or 0) > 0:
        safe_percent = max(10.0, min(100.0, float(safe_max_vram_percent or 100.0)))
        safe_cap = max(64 * 1024 * 1024, int(int(target_total) * (safe_percent / 100.0)))
        capped = min(capped, safe_cap)
    return capped


def shared_memory_gpu_target_total_bytes(
    *,
    opencl_global_mem_bytes: int = 0,
    system_total: int,
    system_available: int,
    memory_allocation_percent: int = 0,
    concurrent_gpu_3d: bool = False,
    stage_duration_seconds: int = 0,
) -> int:
    system_total = max(0, int(system_total or 0))
    system_available = max(0, int(system_available or 0)) or system_total
    if system_total <= 0:
        return 512 * 1024 * 1024

    if memory_allocation_percent > 0:
        fraction_cap = 0.10
        hard_cap = 2 * 1024 ** 3
        available_cap = 0.35
    elif concurrent_gpu_3d and 0 < int(stage_duration_seconds or 0) < 180:
        fraction_cap = 0.15
        hard_cap = 4 * 1024 ** 3
        available_cap = 0.45
    else:
        fraction_cap = 0.25
        hard_cap = 8 * 1024 ** 3
        available_cap = 0.65

    candidates = [
        int(system_total * fraction_cap),
        int(system_available * available_cap),
        hard_cap,
    ]
    if opencl_global_mem_bytes > 0:
        candidates.append(int(opencl_global_mem_bytes))
    budget = min(value for value in candidates if value > 0)
    return max(256 * 1024 * 1024, budget)


def opencl_device_looks_like_shared_memory(
    *,
    device_class: str,
    opencl_global_mem_bytes: int,
    system_total: int,
    explicit_vram_total: int,
) -> bool:
    if str(device_class or "").strip().lower() == "integrated":
        return True
    return bool(
        int(explicit_vram_total or 0) <= 0
        and int(system_total or 0) > 0
        and int(opencl_global_mem_bytes or 0) >= int(int(system_total or 0) * 0.75)
    )


def fallback_vram_total_for_target(target: Optional[Dict[str, Any]]) -> int:
    target_name = str((target or {}).get("name", "") or "").strip().lower()
    target_vendor = str((target or {}).get("vendor", "") or "").strip().lower()
    if target_vendor == "nvidia":
        return 8 * 1024 ** 3
    if "arc" in target_name:
        return 4 * 1024 ** 3
    if target_vendor == "amd" and "radeon graphics" not in target_name:
        return 4 * 1024 ** 3
    return 2 * 1024 ** 3


def target_vram_allocation_bytes(
    *,
    allocation_percent: int,
    target: Optional[Dict[str, Any]],
    target_total: int,
    device_class: str,
    concurrent_gpu_3d: bool = False,
) -> int:
    percent = max(1, min(int(allocation_percent or 0), 95))
    target_total = int(target_total or 0)
    if target_total <= 0:
        return 512 * 1024 * 1024
    requested = int(target_total * (percent / 100.0))
    capacity_cap = capacity_vram_request_cap_bytes(target_total)
    if capacity_cap > 0:
        requested = min(requested, capacity_cap)
    if target is not None and concurrent_gpu_3d:
        normalized_class = str(device_class or "").strip().lower()
        if normalized_class in {"integrated", "apu"} and target_total <= 2 * 1024 ** 3:
            mixed_integrated_cap = min(
                768 * 1024 ** 2,
                max(256 * 1024 ** 2, int(target_total * 0.40)),
            )
            requested = min(requested, mixed_integrated_cap)
    return max(64 * 1024 * 1024, requested)


def target_is_amd_discrete(target: Optional[Dict[str, Any]], capability: Dict[str, Any]) -> bool:
    if target is None:
        return False
    device_class = str((capability or {}).get("device_class", "") or "").strip().lower()
    vendor = str(target.get("vendor", "") or "").strip().lower()
    vendor_id = str(target.get("vendor_id", "") or "").strip().lower()
    driver = str(target.get("driver", "") or "").strip().lower()
    return bool(device_class == "discrete" and (vendor == "amd" or vendor_id == "1002" or driver in {"amdgpu", "radeon"}))


def amd_discrete_target_count(targets_with_capabilities: Iterable[tuple[Optional[Dict[str, Any]], Dict[str, Any]]]) -> int:
    return sum(
        1
        for target, capability in targets_with_capabilities
        if target_is_amd_discrete(target, capability)
    )


def skip_concurrent_vram_worker_for_target(
    *,
    target: Optional[Dict[str, Any]],
    capability: Dict[str, Any],
    concurrent_gpu_3d: bool = False,
    concurrent_amd_discrete_target_count: int = 0,
    vram_backend: str = "",
) -> bool:
    if not concurrent_gpu_3d or target is None:
        return False
    device_class = str((capability or {}).get("device_class", "") or "").strip().lower()
    if (
        str(vram_backend or "").strip().lower() == "python_opencl"
        and int(concurrent_amd_discrete_target_count or 0) >= 2
        and target_is_amd_discrete(target, capability)
    ):
        return True
    if device_class not in {"integrated", "apu"}:
        return False
    target_total = int(target.get("vram_total") or 0)
    return 0 < target_total <= 2 * 1024 ** 3


def use_vulkan_vram_worker_for_target(
    *,
    target: Optional[Dict[str, Any]],
    capability: Dict[str, Any],
    concurrent_gpu_3d: bool = False,
    concurrent_amd_discrete_target_count: int = 0,
    resolved_vram_backend: str = "",
    vulkan_vram_backend_available: bool,
    vulkan_vram_target_supported: bool,
) -> bool:
    if not concurrent_gpu_3d or target is None:
        return False
    if str(resolved_vram_backend or "").strip().lower() != "python_opencl":
        return False
    if int(concurrent_amd_discrete_target_count or 0) < 2:
        return False
    if not target_is_amd_discrete(target, capability):
        return False
    if not vulkan_vram_backend_available:
        return False
    return bool(vulkan_vram_target_supported)


def resolve_target_vram_allocation_bytes(
    *,
    allocation_percent: int,
    target: Optional[Dict[str, Any]],
    memory_allocation_percent: int,
    concurrent_gpu_3d: bool,
    stage_duration_seconds: int,
    opencl_device_for_target: Callable[[Optional[Dict[str, Any]]], Optional[Dict[str, Any]]],
    capability_for_target: Callable[[Optional[Dict[str, Any]]], Dict[str, Any]],
    system_memory_total: Callable[[], int],
    system_memory_available: Callable[[], int],
    sysfs_vram_totals: Callable[[], Iterable[int]],
) -> int:
    percent = max(1, min(int(allocation_percent or 0), 95))
    target_total = int(target.get("vram_total") or 0) if target else 0
    if target is not None and target_total <= 0:
        opencl_device = opencl_device_for_target(target)
        if opencl_device:
            opencl_global = int(opencl_device.get("global_mem_bytes", 0) or 0)
            capability = capability_for_target(target)
            device_class = str(capability.get("device_class", "") or "").strip().lower()
            if opencl_device_looks_like_shared_memory(
                device_class=device_class,
                opencl_global_mem_bytes=opencl_global,
                system_total=system_memory_total(),
                explicit_vram_total=int(target.get("vram_total") or 0),
            ):
                total_memory = system_memory_total()
                target_total = shared_memory_gpu_target_total_bytes(
                    opencl_global_mem_bytes=opencl_global,
                    system_total=total_memory,
                    system_available=system_memory_available() or total_memory,
                    memory_allocation_percent=memory_allocation_percent,
                    concurrent_gpu_3d=concurrent_gpu_3d,
                    stage_duration_seconds=stage_duration_seconds,
                )
            else:
                target_total = opencl_global
        if target_total <= 0:
            target_total = fallback_vram_total_for_target(target)
    if target_total <= 0:
        totals = [int(value) for value in sysfs_vram_totals() if value and int(value) > 0]
        target_total = max(totals) if totals else 0
    if target_total <= 0:
        return 512 * 1024 * 1024
    capability = capability_for_target(target) if target is not None else {}
    return target_vram_allocation_bytes(
        allocation_percent=percent,
        target=target,
        target_total=target_total,
        device_class=str(capability.get("device_class", "") or "").strip().lower(),
        concurrent_gpu_3d=concurrent_gpu_3d,
    )


def route_vulkan_vram_worker_for_target(
    *,
    target: Optional[Dict[str, Any]],
    concurrent_gpu_3d: bool,
    concurrent_amd_discrete_target_count: int,
    resolved_vram_backend: str,
    capability_for_target: Callable[[Optional[Dict[str, Any]]], Dict[str, Any]],
    vram_backend_available: Callable[[str], bool],
    gpu_backend_target_supported: Callable[[str, Dict[str, Any], str], bool],
) -> bool:
    if not concurrent_gpu_3d or target is None:
        return False
    if str(resolved_vram_backend or "").strip().lower() != "python_opencl":
        return False
    if int(concurrent_amd_discrete_target_count or 0) < 2:
        return False
    capability = capability_for_target(target)
    if not use_vulkan_vram_worker_for_target(
        target=target,
        capability=capability,
        concurrent_gpu_3d=concurrent_gpu_3d,
        concurrent_amd_discrete_target_count=concurrent_amd_discrete_target_count,
        resolved_vram_backend=resolved_vram_backend,
        vulkan_vram_backend_available=True,
        vulkan_vram_target_supported=True,
    ):
        return False
    backend_available = vram_backend_available("python_vulkan_compute")
    target_supported = bool(
        gpu_backend_target_supported("python_vulkan_compute", target, "vram")
    ) if backend_available else False
    return use_vulkan_vram_worker_for_target(
        target=target,
        capability=capability,
        concurrent_gpu_3d=concurrent_gpu_3d,
        concurrent_amd_discrete_target_count=concurrent_amd_discrete_target_count,
        resolved_vram_backend=resolved_vram_backend,
        vulkan_vram_backend_available=backend_available,
        vulkan_vram_target_supported=target_supported,
    )


def concurrent_vram_skip_target_labels(
    *,
    targets: List[Optional[Dict[str, Any]]],
    concurrent_gpu_3d: bool,
    vram_backend: str,
    capability_for_target: Callable[[Optional[Dict[str, Any]]], Dict[str, Any]],
    vram_backend_available: Callable[[str], bool],
    gpu_backend_target_supported: Callable[[str, Dict[str, Any], str], bool],
) -> List[str]:
    labels: List[str] = []
    concurrent_amd_count = (
        amd_discrete_target_count(
            (target, capability_for_target(target) if target is not None else {})
            for target in targets
        )
        if concurrent_gpu_3d
        else 0
    )
    for target in targets:
        if route_vulkan_vram_worker_for_target(
            target=target,
            concurrent_gpu_3d=concurrent_gpu_3d,
            concurrent_amd_discrete_target_count=concurrent_amd_count,
            resolved_vram_backend=vram_backend,
            capability_for_target=capability_for_target,
            vram_backend_available=vram_backend_available,
            gpu_backend_target_supported=gpu_backend_target_supported,
        ):
            continue
        capability = capability_for_target(target) if target is not None else {}
        if not skip_concurrent_vram_worker_for_target(
            target=target,
            capability=capability,
            concurrent_gpu_3d=concurrent_gpu_3d,
            concurrent_amd_discrete_target_count=concurrent_amd_count,
            vram_backend=vram_backend,
        ):
            continue
        labels.append(
            str(
                (target or {}).get("target_id")
                or (target or {}).get("slot")
                or (target or {}).get("card")
                or (target or {}).get("name")
                or "integrated GPU"
            )
        )
    return labels
