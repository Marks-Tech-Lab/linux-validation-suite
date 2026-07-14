#!/usr/bin/env python3
"""Intel GPU telemetry sampling helpers."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from .lvs_intel_gpu_sidecar import intel_gpu_top_json_sample_attempt
from .lvs_telemetry_sampling import json_objects_from_text, parse_intel_gpu_top_snapshot


CommandExists = Callable[[str], bool]
CommandEnv = Callable[[], Dict[str, str]]


def intel_gpu_top_json_sample_text(
    command_exists: CommandExists,
    command_env: CommandEnv,
) -> str:
    return str(
        intel_gpu_top_json_sample_attempt(
            command_exists=command_exists,
            command_env=command_env,
        ).get("stdout", "")
        or ""
    )


def intel_gpu_top_json_sample_metrics(
    command_exists: CommandExists,
    command_env: CommandEnv,
) -> Dict[str, Optional[float]]:
    attempt = intel_gpu_top_json_sample_attempt(
        command_exists=command_exists,
        command_env=command_env,
    )
    return intel_gpu_top_metrics_from_text(str(attempt.get("stdout") or ""))


def intel_gpu_top_metrics_from_text(text: str) -> Dict[str, Optional[float]]:
    snapshots = [
        item
        for item in json_objects_from_text(text)
        if isinstance(item, dict)
    ]
    for snapshot in reversed(snapshots):
        metrics = parse_intel_gpu_top_snapshot(snapshot)
        if metrics:
            return metrics
    return {}


def read_intel_gpu_top_metrics(
    gpu_sources: List[Dict[str, Any]],
    command_exists: CommandExists,
    command_env: CommandEnv,
) -> Dict[int, Dict[str, Optional[float]]]:
    if not any(source.get("kind") == "intel_gpu_top" for source in gpu_sources):
        return {}

    values = intel_gpu_top_json_sample_metrics(command_exists, command_env)
    if not values:
        return {}

    snapshot: Dict[int, Dict[str, Optional[float]]] = {}
    for source in gpu_sources:
        if source.get("kind") == "intel_gpu_top":
            snapshot[int(source.get("gpu_index", 0))] = values
    return snapshot
