#!/usr/bin/env python3
"""Pure GPU worker retune decision helpers."""

from __future__ import annotations

import time
from typing import Any, Dict, Iterable


def recent_metric_values(
    samples: Iterable[Any],
    key: str,
    window_seconds: float,
    *,
    now_monotonic: float | None = None,
) -> list[float]:
    if window_seconds <= 0:
        return []
    cutoff = (time.monotonic() if now_monotonic is None else float(now_monotonic)) - window_seconds
    values: list[float] = []
    for sample in samples:
        if getattr(sample, "timestamp", 0.0) < cutoff:
            continue
        sample_values = getattr(sample, "values", {})
        value = sample_values.get(key) if isinstance(sample_values, dict) else None
        if value is None:
            continue
        values.append(float(value))
    return values


def worker_retune_count(retune_events: Iterable[Dict[str, Any]] | None, spec: Any) -> int:
    if not retune_events:
        return 0
    target = getattr(spec, "target_id", None) or getattr(spec, "card", None)
    workload = getattr(spec, "workload", None)
    return sum(
        1
        for event in retune_events
        if str(event.get("target_id") or "") == str(target)
        and str(event.get("workload") or "") == str(workload)
    )


def effective_gpu_retune_warmup_seconds(
    configured_seconds: float,
    gpu_safe_mode: bool,
    stage_duration_seconds: float,
) -> float:
    configured = max(0.0, float(configured_seconds or 0.0))
    if not gpu_safe_mode or stage_duration_seconds <= 0:
        return configured
    return min(configured, max(10.0, stage_duration_seconds * 0.35))


def effective_gpu_retune_cooldown_seconds(
    configured_seconds: float,
    gpu_safe_mode: bool,
    stage_duration_seconds: float,
) -> float:
    configured = max(0.0, float(configured_seconds or 0.0))
    if not gpu_safe_mode or stage_duration_seconds <= 0:
        return configured
    return min(configured, max(10.0, stage_duration_seconds * 0.2))


def minimum_gpu_retune_remaining_seconds(
    ramp_step_seconds: float,
    stage_duration_seconds: float,
) -> float:
    ramp_window = max(20.0, float(ramp_step_seconds or 0.0) * 3.0)
    if stage_duration_seconds <= 0:
        return ramp_window
    return min(max(25.0, ramp_window), max(25.0, stage_duration_seconds * 0.6))
