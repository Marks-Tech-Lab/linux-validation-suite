#!/usr/bin/env python3
"""Architecture-neutral GPU memory classification and capacity semantics."""

from __future__ import annotations

from typing import Any, Dict, Optional


_GIB = 1024 ** 3


def _normalized_text(*values: Any) -> str:
    return " ".join(str(value or "").strip().lower() for value in values if str(value or "").strip())


def classify_gpu_memory(
    *,
    target: Optional[Dict[str, Any]],
    device_class: str,
    system_total_bytes: int,
    opencl_global_mem_bytes: int = 0,
    vulkan_device_local_heap_bytes: int = 0,
) -> Dict[str, Any]:
    """Describe memory semantics without treating every capacity as dedicated VRAM.

    ``vram_total`` remains an input for compatibility, but its meaning is qualified by
    device classification before it is allowed to influence allocation policy.
    """

    target_data = dict(target or {})
    target_total = max(0, int(target_data.get("vram_total") or 0))
    opencl_global = max(0, int(opencl_global_mem_bytes or 0))
    vulkan_heap = max(0, int(vulkan_device_local_heap_bytes or 0))
    system_total = max(0, int(system_total_bytes or 0))
    normalized_class = str(device_class or "").strip().lower()
    identity = _normalized_text(
        target_data.get("vendor"),
        target_data.get("name"),
        target_data.get("driver"),
        target_data.get("platform_gpu_driver"),
        " ".join(target_data.get("platform_gpu_compatible") or []),
        target_data.get("target_id"),
    )
    driver = str(target_data.get("driver", "") or "").strip().lower()
    vendor = str(target_data.get("vendor", "") or "").strip().lower()
    slot = str(target_data.get("slot", "") or "").strip().lower()

    shared_evidence = ""
    dedicated_evidence = ""
    if normalized_class in {"integrated", "apu", "uma"}:
        shared_evidence = f"device_class:{normalized_class}"
    elif normalized_class == "discrete":
        dedicated_evidence = "device_class:discrete"
    elif driver == "i915":
        shared_evidence = "intel_integrated_driver"
    elif any(token in identity for token in ("adreno", "snapdragon", "qualcomm")):
        shared_evidence = "platform_identity"
    elif any(token in identity for token in ("radeon graphics", "amd apu")):
        shared_evidence = "apu_identity"
    elif vendor == "intel" and any(token in identity for token in ("iris", "uhd", "hd graphics")):
        shared_evidence = "intel_integrated_identity"
    elif not slot and driver and driver not in {"nvidia", "nouveau"}:
        shared_evidence = "non_pci_platform_device"
    elif vendor == "nvidia" or driver in {"nvidia", "nouveau"}:
        dedicated_evidence = "nvidia_identity"
    elif target_total > 0:
        # Preserve existing dedicated-GPU behavior when evidence is ambiguous.
        dedicated_evidence = "explicit_capacity_compatibility"
    elif system_total > 0 and opencl_global >= int(system_total * 0.75):
        shared_evidence = "opencl_system_memory_ratio"

    memory_kind = "shared" if shared_evidence else "dedicated" if dedicated_evidence else "unknown"
    dedicated_capacity = target_total if memory_kind == "dedicated" else 0
    # API heaps/global memory are addressable upper bounds, not current free
    # memory.  MemTotal is only a system-safety ceiling and must never be
    # presented as a proven GPU capability.
    shared_candidates = [value for value in (opencl_global, vulkan_heap) if value > 0]
    shared_capacity = min(shared_candidates) if memory_kind == "shared" and shared_candidates else 0
    shared_source = ""
    if shared_capacity > 0:
        if opencl_global > 0 and shared_capacity == opencl_global:
            shared_source = "opencl_global_memory"
        elif vulkan_heap > 0 and shared_capacity == vulkan_heap:
            shared_source = "vulkan_device_local_heap"
    shared_status = (
        "api_addressable_upper_bound"
        if shared_capacity > 0
        else "unknown_bounded_by_system_pool"
        if memory_kind == "shared"
        else "not_applicable"
    )

    ambiguous_or_stolen = target_total if memory_kind == "shared" and target_total > 0 else 0
    current_used_value = target_data.get("vram_used")
    current_used = int(current_used_value) if current_used_value is not None else None
    return {
        "memory_kind": memory_kind,
        "classification_source": shared_evidence or dedicated_evidence or "insufficient_evidence",
        "dedicated_vram_capacity_bytes": dedicated_capacity,
        "dedicated_vram_capacity_source": str(target_data.get("vram_total_source") or "reported_vram_total") if dedicated_capacity else "",
        "shared_addressable_capacity_bytes": shared_capacity,
        "shared_addressable_capacity_source": shared_source,
        "shared_addressable_capacity_status": shared_status,
        "api_addressable_capacity_bytes": shared_capacity,
        "api_addressable_capacity_source": shared_source,
        "total_capacity_trust": (
            "trusted_dedicated_capacity"
            if dedicated_capacity
            else shared_status
            if memory_kind == "shared"
            else "unknown"
        ),
        "reported_vram_total_bytes": target_total,
        "reported_vram_total_semantics": (
            "dedicated_capacity"
            if dedicated_capacity
            else "ambiguous_integrated_or_firmware_preallocated"
            if ambiguous_or_stolen
            else "unknown"
        ),
        # This value is deliberately not called firmware/stolen memory: the DRM
        # number is retained as ambiguous unless the driver exposes that provenance.
        "ambiguous_integrated_vram_report_bytes": ambiguous_or_stolen,
        "opencl_global_memory_bytes": opencl_global,
        "vulkan_device_local_heap_bytes": vulkan_heap,
        "system_memory_pool_ceiling_bytes": system_total if memory_kind == "shared" else 0,
        "current_gpu_memory_used_bytes": current_used,
        "current_gpu_memory_used_source": str(target_data.get("vram_used_source") or "") if current_used is not None else "",
        "current_gpu_memory_available_bytes": None,
        "current_gpu_memory_available_source": "",
        "firmware_preallocated_or_stolen_bytes": None,
        "firmware_preallocated_or_stolen_source": "",
    }


def gpu_memory_capacity_for_percentage(profile: Dict[str, Any]) -> int:
    if str(profile.get("memory_kind") or "") == "shared":
        return max(0, int(profile.get("shared_addressable_capacity_bytes") or 0))
    return max(0, int(profile.get("dedicated_vram_capacity_bytes") or 0))
