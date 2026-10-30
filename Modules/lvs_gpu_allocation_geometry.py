"""Backend execution geometry, not physical-residency or capacity attestation."""
from __future__ import annotations

from math import isqrt


EGL_TEXTURE_OBJECT_BUDGET = 512  # LVS bookkeeping/work-loop budget, not a GL limit.
OPENCL_READBACK_STAGING_LIMIT_BYTES = 3 * 1024 * 4  # Three bounded host sample slots.


def egl_texture_geometry(target_bytes: int, side_hint: int, max_texture_size: int) -> dict:
    target = max(0, int(target_bytes))
    hardware_max = max(0, int(max_texture_size))
    # Unknown discovery is provisional only; runtime must query GL successfully.
    limit = hardware_max or max(1, int(side_hint))
    side = max(1, min(int(side_hint), limit, isqrt(target // 4) if target >= 4 else 1))
    while side < limit and side * side * 4 * EGL_TEXTURE_OBJECT_BUDGET < target:
        candidate = min(limit, side * 2)
        if candidate * candidate * 4 > target:
            break
        side = candidate
    size = side * side * 4
    count = min(EGL_TEXTURE_OBJECT_BUDGET, target // size)
    return {
        "contract": "gpu_allocation_feasibility_v1", "backend": "python_egl_gles2",
        "assigned_target_bytes": target, "texture_side": side, "object_bytes": size,
        "max_texture_size": hardware_max, "max_allocation_count": EGL_TEXTURE_OBJECT_BUDGET,
        "count_limit_source": "lvs_software_object_budget", "planned_object_count": count,
        "backend_nominal_limit_bytes": size * EGL_TEXTURE_OBJECT_BUDGET,
        "planned_nominal_bytes": count * size, "shortfall_bytes": target - count * size,
        "status": ("conditional_runtime_gl_query" if not hardware_max else
                   "limited_by_software_object_budget" if target > size * EGL_TEXTURE_OBJECT_BUDGET else
                   "nominally_feasible_with_whole_object_rounding"),
        "physical_residency_established": False,
        "runtime_allocation_success_required": True,
    }


def opencl_buffer_count(target: int, chunk: int, device_class: str, safe: bool) -> int:
    count = max(32, (target + max(4096, chunk) - 1) // max(4096, chunk) + 8)
    return (min(2048, max(512, count)) if safe and device_class == "discrete" else
            min(1024, max(128, count)) if safe else min(4096, count))


def opencl_buffer_geometry(target_bytes: int, max_alloc: int, device_class: str, safe: bool) -> dict:
    """Bound object bookkeeping while sizing chunks from a positive API limit.

    Retain the established small-target geometry. Grow only enough to avoid the
    software count ceiling, never past CL_DEVICE_MAX_MEM_ALLOC_SIZE or target.
    An unknown API maximum does not authorize larger objects.
    """
    target = max(0, int(target_bytes))
    discrete = device_class == "discrete"
    cap = (128 if safe else 512) * 1024**2 if discrete else (64 if safe else 128) * 1024**2
    chunk = min(int(max_alloc) or target, cap, target)
    chunk -= chunk % 4096
    if chunk <= 0:
        chunk = min(int(max_alloc) or target, max(4096, target))
    object_budget = 2048 if safe and discrete else 1024 if safe else 4096
    if int(max_alloc) > 0 and target > chunk * object_budget:
        required = ((target + object_budget - 1) // object_budget + 4095) // 4096 * 4096
        api_limit = int(max_alloc) // 4096 * 4096
        chunk = max(chunk, min(required, api_limit, target // 4096 * 4096))
    count = opencl_buffer_count(target, chunk, device_class, safe)
    planned = min(target, chunk * count) if chunk >= 4096 else 0
    planned -= planned % 4096
    return {
        "contract": "gpu_allocation_feasibility_v1", "backend": "python_opencl",
        "assigned_target_bytes": target, "object_bytes": chunk, "max_allocation_count": count,
        "count_limit_source": "lvs_safe_mode_buffer_budget" if safe else "lvs_buffer_budget",
        "backend_nominal_limit_bytes": chunk * count,
        "planned_nominal_bytes": planned,
        "shortfall_bytes": max(0, target - planned),
        "status": ("limited_by_worker_allocation_granularity" if chunk < 4096 and target else
                   "limited_by_software_object_budget" if target > chunk * count else "nominally_feasible"),
        "api_max_allocation_known": int(max_alloc) > 0,
        "api_max_object_bytes": max(0, int(max_alloc)),
        "runtime_allocation_success_required": True, "physical_residency_established": False,
    }
