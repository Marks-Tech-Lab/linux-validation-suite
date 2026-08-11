#!/usr/bin/env python3
"""Read-only EDAC telemetry discovery for explicitly identified system caches."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


ReadText = Callable[[Path], Optional[str]]


def _read_nonnegative_counter(path: Path, read_text: ReadText) -> Optional[int]:
    raw = read_text(path)
    if raw is None:
        return None
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


def discover_llcc_edac_sources(
    edac_root: Path = Path("/sys/devices/system/edac/qcom-llcc"),
    read_text: ReadText | None = None,
) -> List[Dict[str, Any]]:
    """Discover aggregate Qualcomm LLCC counters, deliberately excluding bank aliases."""
    if read_text is None:
        read_text = lambda path: path.read_text(encoding="utf-8", errors="ignore").strip()
    controllers = sorted(path for path in edac_root.glob("qcom-llcc*") if path.is_dir())
    if not controllers:
        return []
    metric_specs = (
        ("ce_count", "llcc_correctable_error_count", "correctable_error_count"),
        ("ue_count", "llcc_uncorrectable_error_count", "uncorrectable_error_count"),
    )
    sources: List[Dict[str, Any]] = []
    for filename, key, metric in metric_specs:
        paths = [controller / filename for controller in controllers]
        readable_paths = [path for path in paths if _read_nonnegative_counter(path, read_text) is not None]
        if len(readable_paths) != len(paths):
            continue
        bank_count = sum(len(list(controller.glob("bank*"))) for controller in controllers)
        sources.append(
            {
                "kind": "llcc_edac",
                "path": ", ".join(str(path) for path in readable_paths),
                "paths": [str(path) for path in readable_paths],
                "label": f"Qualcomm LLCC aggregate {metric.replace('_', ' ')}",
                "key": key,
                "metric": metric,
                "aggregation": "sum" if len(readable_paths) > 1 else "direct",
                "controller_count": len(controllers),
                "bank_count": bank_count,
                "error_scope": "last_level_cache",
            }
        )
    return sources


def read_llcc_edac_counters(
    sources: List[Dict[str, Any]],
    read_text: ReadText,
) -> Dict[str, Optional[float]]:
    """Read cumulative LLCC error counters; missing components remain unavailable."""
    values: Dict[str, Optional[float]] = {}
    for source in sources:
        paths = [Path(str(path)) for path in source.get("paths", [])]
        counters = [_read_nonnegative_counter(path, read_text) for path in paths]
        if paths and all(value is not None for value in counters):
            values[str(source["key"])] = float(sum(int(value) for value in counters if value is not None))
    return values
