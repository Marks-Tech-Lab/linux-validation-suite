#!/usr/bin/env python3
"""Shared support helpers for validation run orchestration."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from Modules.lvs_faults import summarize_fault_events


def build_gpu_recovery_report(
    *,
    read_safety_marker: Callable[[], Optional[Dict[str, Any]]],
    collect_previous_boot_faults: Callable[[], List[Dict[str, Any]]],
) -> Dict[str, Any]:
    safety_marker = read_safety_marker()
    previous_boot_faults: List[Dict[str, Any]] = []
    if safety_marker:
        previous_boot_faults = collect_previous_boot_faults()
    return {
        "unclean_marker_present": bool(safety_marker),
        "marker": safety_marker,
        "previous_boot_faults": previous_boot_faults,
        "previous_boot_fault_summary": summarize_fault_events(previous_boot_faults),
    }


def make_validation_run_dir(
    *,
    results_dir: str | Path,
    profile_name: str,
    timestamp: Optional[str] = None,
) -> Path:
    run_timestamp = timestamp or datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    run_dir = Path(results_dir) / f"{run_timestamp}_{profile_name}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir

