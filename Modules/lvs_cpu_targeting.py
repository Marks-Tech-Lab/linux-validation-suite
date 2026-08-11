#!/usr/bin/env python3
"""Architecture-neutral Linux CPU targeting and common-capability policy."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Sequence


X86_KERNEL_PREFERENCE = (
    "avx512_fma",
    "avx512_int",
    "avx2_fma",
    "avx2",
    "avx_fma",
    "avx",
    "sse2",
    "sse2_int",
    "scalar",
)
ARM64_KERNEL_PREFERENCE = ("neon", "scalar")


def parse_linux_cpu_list(value: str) -> list[int]:
    """Parse Linux CPU-list syntax such as ``0-3,8,10-12``."""
    values: set[int] = set()
    for raw_part in str(value or "").strip().split(","):
        part = raw_part.strip()
        if not part:
            continue
        if "-" not in part:
            try:
                cpu_id = int(part, 10)
            except ValueError:
                continue
            if cpu_id >= 0:
                values.add(cpu_id)
            continue
        start_text, end_text = part.split("-", 1)
        try:
            start = int(start_text, 10)
            end = int(end_text, 10)
        except ValueError:
            continue
        if start < 0 or end < start:
            continue
        values.update(range(start, end + 1))
    return sorted(values)


def format_linux_cpu_list(cpu_ids: Iterable[int]) -> str:
    ordered = sorted({int(cpu_id) for cpu_id in cpu_ids if int(cpu_id) >= 0})
    if not ordered:
        return ""
    parts: list[str] = []
    start = previous = ordered[0]
    for cpu_id in ordered[1:]:
        if cpu_id == previous + 1:
            previous = cpu_id
            continue
        parts.append(str(start) if start == previous else f"{start}-{previous}")
        start = previous = cpu_id
    parts.append(str(start) if start == previous else f"{start}-{previous}")
    return ",".join(parts)


def _read_cpu_list(path: Path) -> list[int]:
    try:
        return parse_linux_cpu_list(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return []


def discover_linux_cpu_sets(
    *,
    cpu_root: Path = Path("/sys/devices/system/cpu"),
    affinity_getter: Optional[Callable[[int], Iterable[int]]] = None,
    cpu_count_getter: Callable[[], Optional[int]] = os.cpu_count,
) -> Dict[str, Any]:
    """Return present, online, allowed, and executable CPU IDs without contiguity assumptions."""
    present = _read_cpu_list(cpu_root / "present")
    online = _read_cpu_list(cpu_root / "online")
    if not present:
        present = sorted(
            int(path.name[3:])
            for path in cpu_root.glob("cpu[0-9]*")
            if path.name[3:].isdigit()
        )
    if not online:
        online = list(present)

    getter = affinity_getter
    if getter is None and hasattr(os, "sched_getaffinity"):
        getter = os.sched_getaffinity
    affinity_available = getter is not None
    allowed: list[int] = []
    if getter is not None:
        try:
            allowed = sorted({int(cpu_id) for cpu_id in getter(0) if int(cpu_id) >= 0})
        except Exception:
            affinity_available = False
    fallback_count = max(0, int(cpu_count_getter() or 0))
    if not present and fallback_count:
        present = list(range(fallback_count))
    if not online:
        online = list(present)
    if not allowed:
        allowed = list(online)
    executable = sorted(set(online).intersection(allowed))
    return {
        "available_cpu_ids": list(present),
        "online_cpu_ids": list(online),
        "allowed_cpu_ids": list(allowed),
        "executable_cpu_ids": executable,
        "affinity_query_available": affinity_available,
        "cpu_set_source": "linux_online_intersect_process_affinity" if affinity_available else "linux_online_fallback",
    }


def resolve_target_cpu_ids(cpu_sets: Mapping[str, Any], threads: str) -> Dict[str, Any]:
    executable = sorted({int(value) for value in cpu_sets.get("executable_cpu_ids", [])})
    normalized = str(threads or "all").strip().lower() or "all"
    requested_count: Optional[int]
    if normalized == "all":
        requested_count = None
        target = executable
    else:
        try:
            requested_count = max(1, int(normalized))
        except Exception:
            requested_count = None
        target = executable if requested_count is None else executable[:requested_count]
    return {
        **dict(cpu_sets),
        "requested_thread_count": "all" if requested_count is None else requested_count,
        "target_cpu_ids": target,
        "actual_worker_count": len(target),
        "target_cpu_list": format_linux_cpu_list(target),
    }


def common_kernel_capabilities(
    target_cpu_ids: Sequence[int],
    per_cpu_capabilities: Mapping[int, Iterable[str]],
) -> Dict[str, Any]:
    targets = [int(cpu_id) for cpu_id in target_cpu_ids]
    missing = [cpu_id for cpu_id in targets if cpu_id not in per_cpu_capabilities]
    if not targets or missing:
        common: set[str] = set()
    else:
        common = set(str(value) for value in per_cpu_capabilities[targets[0]])
        for cpu_id in targets[1:]:
            common.intersection_update(str(value) for value in per_cpu_capabilities[cpu_id])
    if targets and not missing:
        common.add("scalar")
    return {
        "target_cpu_ids": targets,
        "per_cpu_capabilities": {
            str(cpu_id): sorted({str(value) for value in per_cpu_capabilities.get(cpu_id, [])})
            for cpu_id in targets
        },
        "common_kernel_flavors": sorted(common),
        "capability_probe_failures": missing,
        "capability_intersection_complete": bool(targets) and not missing,
    }


def select_common_kernel(
    *,
    architecture: str,
    requested_mode: str,
    common_flavors: Iterable[str],
) -> str:
    common = {str(value) for value in common_flavors}
    requested = str(requested_mode or "auto").strip().lower() or "auto"
    family = {
        "scalar": ("scalar",),
        "sse": ("sse2", "sse2_int"),
        "avx": ("avx_fma", "avx"),
        "avx2": ("avx2_fma", "avx2"),
        "avx512": ("avx512_fma", "avx512_int"),
        "neon": ("neon",),
    }
    # Explicit profile modes are family requests, not exact internal kernel
    # names; FMA is preferred only when it survived the all-target intersection.
    candidates = (
        ARM64_KERNEL_PREFERENCE
        if requested == "auto" and str(architecture) == "arm64"
        else X86_KERNEL_PREFERENCE
        if requested == "auto"
        else family.get(requested, ())
    )
    return next((flavor for flavor in candidates if flavor in common), "")


def mode_for_common_kernel(flavor: str) -> str:
    value = str(flavor or "")
    if value.startswith("avx512"):
        return "avx512"
    if value.startswith("avx2"):
        return "avx2"
    if value.startswith("avx"):
        return "avx"
    if value.startswith("sse2"):
        return "sse"
    return "neon" if value == "neon" else "scalar" if value == "scalar" else ""
