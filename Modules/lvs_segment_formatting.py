from __future__ import annotations

from typing import Any


def format_segment_duration(seconds: float) -> str:
    total = int(round(seconds))
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def format_analysis_window(window: Any) -> str:
    start = round(window.analysis_start - window.started_monotonic, 1)
    end = round(window.analysis_end - window.started_monotonic, 1)
    return f"{start}s - {end}s"
