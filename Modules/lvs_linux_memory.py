#!/usr/bin/env python3
"""Linux memory-accounting snapshots used by allocation safety policy."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict


def parse_meminfo_bytes(text: str) -> Dict[str, Any]:
    values: Dict[str, int] = {}
    for raw_line in str(text or "").splitlines():
        if ":" not in raw_line:
            continue
        name, raw_value = raw_line.split(":", 1)
        parts = raw_value.strip().split()
        if not parts:
            continue
        try:
            value = int(parts[0])
        except ValueError:
            continue
        multiplier = 1024 if len(parts) > 1 and parts[1].lower() == "kb" else 1
        values[name] = max(0, value * multiplier)

    total = int(values.get("MemTotal", 0))
    if "MemAvailable" in values:
        available = int(values.get("MemAvailable", 0))
        source = "kernel_reported_memavailable"
        fallback = False
    else:
        # This is only for older kernels. It is intentionally labeled as an
        # approximation and never added to a separately reported MemAvailable.
        available = max(
            0,
            int(values.get("MemFree", 0))
            + int(values.get("Cached", 0))
            + int(values.get("Buffers", 0))
            + int(values.get("SReclaimable", 0))
            - int(values.get("Shmem", 0)),
        )
        source = "derived_legacy_memavailable_approximation"
        fallback = True
    if total > 0:
        available = min(total, available)
    return {
        "mem_total_bytes": total,
        "mem_available_bytes": available,
        "mem_free_bytes": int(values.get("MemFree", 0)),
        "cached_bytes": int(values.get("Cached", 0)),
        "buffers_bytes": int(values.get("Buffers", 0)),
        "sreclaimable_bytes": int(values.get("SReclaimable", 0)),
        "shmem_bytes": int(values.get("Shmem", 0)),
        "swap_total_bytes": int(values.get("SwapTotal", 0)),
        "swap_free_bytes": int(values.get("SwapFree", 0)),
        "mem_available_source": source,
        "mem_available_fallback": fallback,
    }


def read_linux_memory_snapshot(path: Path | str = "/proc/meminfo") -> Dict[str, Any]:
    try:
        text = Path(path).read_text(encoding="utf-8", errors="ignore")
    except Exception:
        text = ""
    return parse_meminfo_bytes(text)
