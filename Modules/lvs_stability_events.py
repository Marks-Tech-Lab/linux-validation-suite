#!/usr/bin/env python3
"""Stability event construction and summary helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, Optional

from Modules.lvs_core import now_local_iso


@dataclass
class StabilityEvent:
    timestamp: str
    category: str
    severity: str
    stage: str
    source: str
    message: str
    details: Dict[str, Any] = field(default_factory=dict)


def create_stability_event(
    category: str,
    severity: str,
    stage: str,
    source: str,
    message: str,
    details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return asdict(
        StabilityEvent(
            timestamp=now_local_iso(),
            category=category,
            severity=severity,
            stage=stage,
            source=source,
            message=message,
            details=details or {},
        )
    )


def event_signature(event: Dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(event.get("category") or ""),
        str(event.get("source") or ""),
        str(event.get("message") or ""),
    )


def dedupe_events(events: Iterable[Dict[str, Any]]) -> list[Dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    unique: list[Dict[str, Any]] = []
    for event in events:
        signature = event_signature(event)
        if signature in seen:
            continue
        seen.add(signature)
        unique.append(event)
    return unique


def new_unique_events(
    candidates: Iterable[Dict[str, Any]],
    existing: Iterable[Dict[str, Any]],
) -> list[Dict[str, Any]]:
    existing_signatures = {event_signature(event) for event in existing}
    return [event for event in candidates if event_signature(event) not in existing_signatures]


def threshold_run_seconds(
    samples: Iterable[Any],
    key: str,
    threshold: float,
    interval_seconds: float,
) -> float:
    longest = 0.0
    current = 0.0
    step = max(0.1, float(interval_seconds or 0.0))
    for sample in samples:
        values = getattr(sample, "values", {})
        value = values.get(key) if isinstance(values, dict) else None
        if value is not None and float(value) >= float(threshold):
            current += step
            longest = max(longest, current)
        else:
            current = 0.0
    return round(longest, 2)
