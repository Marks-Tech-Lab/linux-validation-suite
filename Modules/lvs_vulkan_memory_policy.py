"""Generic Vulkan stateful-memory capacity and chunk-count policy."""

from __future__ import annotations

import math


def stateful_memory_capacity_basis(target_vram_total: int, device_local_heap_bytes: int, device_class: str) -> int:
    # Integrated/UMA devices can expose a small carved-out DRM VRAM value
    # alongside the larger Vulkan device-local system heap.  The unified plan
    # already assigns their system-memory target, so that carve-out must not
    # cap the worker below its assignment.
    if str(device_class or "").strip().lower() != "discrete":
        return int(device_local_heap_bytes or 0) or int(target_vram_total or 0)
    return int(target_vram_total or 0) or int(device_local_heap_bytes or 0)


def stateful_memory_buffer_cap(target_vram_total: int, device_local_heap_bytes: int, device_class: str) -> int:
    memory_total = stateful_memory_capacity_basis(target_vram_total, device_local_heap_bytes, device_class)
    if memory_total >= 32 * 1024 ** 3:
        return 3584 * 1024 * 1024
    if memory_total >= 24 * 1024 ** 3:
        return 3 * 1024 * 1024 * 1024
    if memory_total >= 12 * 1024 ** 3:
        return 1536 * 1024 * 1024
    if memory_total >= 8 * 1024 ** 3:
        return 1024 * 1024 * 1024
    if memory_total >= 2 * 1024 ** 3:
        return 512 * 1024 * 1024
    if memory_total >= 1024 ** 3:
        return 256 * 1024 * 1024
    return 128 * 1024 * 1024


def stateful_memory_total_cap(target_vram_total: int, device_local_heap_bytes: int, device_class: str) -> int:
    memory_total = stateful_memory_capacity_basis(target_vram_total, device_local_heap_bytes, device_class)
    if memory_total > 0:
        return max(64 * 1024 * 1024, int(memory_total * 0.9))
    return 512 * 1024 * 1024


def stateful_memory_buffer_count_limit(
    requested_total_size: int,
    per_buffer_cap_bytes: int,
    max_memory_allocation_count: int,
) -> int:
    required = max(1, int(math.ceil(int(requested_total_size) / float(max(1, int(per_buffer_cap_bytes))))))
    limit = max(32, min(256, required))
    if int(max_memory_allocation_count or 0) > 0:
        limit = max(1, min(limit, int(max_memory_allocation_count) - 4))
    return limit
