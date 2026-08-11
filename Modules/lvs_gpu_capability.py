#!/usr/bin/env python3
"""Shared GPU capability profiling and worker load-scaling policy."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

from Modules.lvs_gpu_memory_model import classify_gpu_memory


def gpu_capability_cache_key(target: Optional[Dict[str, Any]]) -> str:
    return str((target or {}).get("target_id", "") or (target or {}).get("card", "") or "default")


def likely_discrete_target_ids(cards: Iterable[Dict[str, Any]]) -> set[str]:
    return {
        str(card.get("target_id", "") or "").strip().lower()
        for card in cards
        if str(card.get("target_id", "") or "").strip()
    }


def build_gpu_capability_profile(
    *,
    target: Optional[Dict[str, Any]],
    likely_discrete_ids: Iterable[str],
    explicit_device_class: str,
    vulkan_device_class: str,
    opencl_device: Optional[Dict[str, Any]],
    vulkan_device: Optional[Dict[str, Any]] = None,
    egl_device: Optional[Dict[str, Any]] = None,
    system_total_bytes: int = 0,
) -> Dict[str, Any]:
    target_data = target or {}
    vram_total = int(target_data.get("vram_total") or 0)
    target_id = str(target_data.get("target_id", "") or "").strip().lower()
    discrete_ids = {str(value or "").strip().lower() for value in likely_discrete_ids}
    explicit_class = str(explicit_device_class or "")
    vulkan_class = str(vulkan_device_class or "").strip().lower()
    if vulkan_class not in {"integrated", "apu", "uma", "discrete", "virtual", "cpu"}:
        vulkan_class = ""
    identity_text = " ".join(
        str(target_data.get(key, "") or "").strip().lower()
        for key in ("vendor", "name", "driver", "platform_gpu_driver")
    )
    identity_text += " " + " ".join(str(value or "").lower() for value in target_data.get("platform_gpu_compatible", []))
    integrated_identity = bool(
        any(token in identity_text for token in ("radeon graphics", "amd apu", "adreno", "snapdragon", "qualcomm"))
        or str(target_data.get("driver", "") or "").strip().lower() == "i915"
        or (
            str(target_data.get("vendor", "") or "").strip().lower() == "intel"
            and any(token in identity_text for token in ("iris", "uhd", "hd graphics"))
        )
    )
    selection_discrete = bool(target_id and target_id in discrete_ids and vram_total > 0 and not integrated_identity)
    device_class = vulkan_class or explicit_class or ("integrated" if integrated_identity else "discrete" if selection_discrete else "unknown")
    profile: Dict[str, Any] = {
        "target_id": str(target_data.get("target_id", "") or ""),
        "vendor": str(target_data.get("vendor", "") or ""),
        "device_class": device_class,
        "device_class_source": (
            "vulkan"
            if vulkan_class
            else "driver"
            if explicit_class
            else "identity"
            if integrated_identity
            else "selection"
            if device_class == "discrete"
            else "unknown"
        ),
        "vram_total": vram_total,
        "vram_gib": round(vram_total / float(1024 ** 3), 2) if vram_total > 0 else 0.0,
        "compute_units": 0,
        "max_work_group_size": 0,
        "max_clock_mhz": 0,
        "opencl_index": -1,
        "source": "heuristic",
    }
    if opencl_device:
        opencl_index = opencl_device.get("opencl_index", -1)
        opencl_global_mem = int(opencl_device.get("global_mem_bytes", 0) or 0)
        if vram_total <= 0 and opencl_global_mem > 0:
            vram_total = opencl_global_mem
            profile["vram_total"] = vram_total
            profile["vram_gib"] = round(vram_total / float(1024 ** 3), 2)
        profile.update(
            {
                "compute_units": int(opencl_device.get("compute_units", 0) or 0),
                "max_work_group_size": int(opencl_device.get("max_work_group_size", 0) or 0),
                "max_clock_mhz": int(opencl_device.get("max_clock_mhz", 0) or 0),
                "opencl_index": int(opencl_index if opencl_index is not None else -1),
                "source": "opencl",
            }
        )

    memory_scale = 0.75
    if vram_total >= 20 * 1024 ** 3:
        memory_scale = 2.2
    elif vram_total >= 12 * 1024 ** 3:
        memory_scale = 1.8
    elif vram_total >= 8 * 1024 ** 3:
        memory_scale = 1.5
    elif vram_total >= 4 * 1024 ** 3:
        memory_scale = 1.2
    elif vram_total >= 2 * 1024 ** 3:
        memory_scale = 1.0
    compute_units = int(profile.get("compute_units", 0) or 0)
    compute_scale = min(3.0, max(0.7, compute_units / 24.0)) if compute_units > 0 else memory_scale
    max_clock_mhz = int(profile.get("max_clock_mhz", 0) or 0)
    clock_scale = min(1.3, max(0.85, max_clock_mhz / 2200.0)) if max_clock_mhz > 0 else 1.0
    load_scale = min(3.5, max(0.75, compute_scale * clock_scale))
    profile.update(
        {
            "memory_scale": round(memory_scale, 2),
            "compute_scale": round(compute_scale, 2),
            "clock_scale": round(clock_scale, 2),
            "load_scale": round(load_scale, 2),
            "parallelism_hint": max(1, min(8, int(round(load_scale)))),
        }
    )
    profile.update(
        classify_gpu_memory(
            target=target,
            device_class=device_class,
            system_total_bytes=system_total_bytes,
            opencl_global_mem_bytes=int((opencl_device or {}).get("global_mem_bytes", 0) or 0),
            vulkan_device_local_heap_bytes=int((vulkan_device or {}).get("device_local_heap_bytes", 0) or 0),
        )
    )
    opencl_max_alloc = max(0, int((opencl_device or {}).get("max_alloc_bytes", 0) or 0))
    vulkan_max_buffer = max(0, int((vulkan_device or {}).get("max_storage_buffer_range_bytes", 0) or 0))
    vulkan_max_count = max(0, int((vulkan_device or {}).get("max_memory_allocation_count", 0) or 0))
    egl_max_texture = max(0, int((egl_device or {}).get("max_texture_size", 0) or 0))
    egl_max_object = egl_max_texture * egl_max_texture * 4 if egl_max_texture else 0
    profile.update(
        {
            "opencl_max_single_allocation_bytes": opencl_max_alloc,
            "vulkan_max_storage_buffer_range_bytes": vulkan_max_buffer,
            "vulkan_max_memory_allocation_count": vulkan_max_count,
            "gles_max_texture_object_bytes": egl_max_object,
            # OpenCL exposes a maximum individual allocation. Vulkan core does
            # not expose an equivalent total VkDeviceMemory allocation size;
            # maxStorageBufferRange is instead an object/buffer-use limit.
            "max_single_allocation_bytes": opencl_max_alloc,
            "max_single_allocation_source": "opencl_max_mem_alloc_size" if opencl_max_alloc else "",
            "max_buffer_or_object_bytes": min(
                value for value in (opencl_max_alloc, vulkan_max_buffer, egl_max_object) if value > 0
            ) if any(value > 0 for value in (opencl_max_alloc, vulkan_max_buffer, egl_max_object)) else 0,
            "max_buffer_or_object_source": "minimum_known_backend_object_limit" if any(
                value > 0 for value in (opencl_max_alloc, vulkan_max_buffer, egl_max_object)
            ) else "",
            "max_allocation_count": vulkan_max_count,
            "max_allocation_count_source": "vulkan_max_memory_allocation_count" if vulkan_max_count else "",
            "allocation_granularity_bytes": 4096 if opencl_max_alloc else 1024 if vulkan_max_buffer else 1,
            "gles_max_texture_size": egl_max_texture,
        }
    )
    return profile
