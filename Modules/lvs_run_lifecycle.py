#!/usr/bin/env python3
"""Run lifecycle event formatting helpers.

These helpers own the stable text shape used by CLI output and by service/TUI
synthetic events. Keep the formatter intentionally small so visible phase lines
do not drift while orchestration continues moving into modules.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any


def future_local_iso(seconds_from_now: float) -> str:
    """Return a local ISO timestamp offset from the current time."""

    return (datetime.now().astimezone() + timedelta(seconds=seconds_from_now)).isoformat()


def phase_line(timestamp: str, event_type: str, **fields: Any) -> str:
    """Build the stable `[phase] ... | event | key=value` line format."""

    parts = [f"[phase] {timestamp}", str(event_type)]
    for key, value in fields.items():
        if value is None:
            continue
        parts.append(f"{key}={value}")
    return " | ".join(parts)
