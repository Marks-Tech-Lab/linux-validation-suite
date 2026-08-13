#!/usr/bin/env python3
"""Executable provenance and structured evidence for external stage processes."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence


STRESS_NG_METRIC_FIELDS = (
    "stressor",
    "bogo_ops",
    "real_time_seconds",
    "user_time_seconds",
    "system_time_seconds",
    "bogo_ops_per_second_real",
    "bogo_ops_per_second_cpu",
)


def resolve_executable_path(
    executable: str,
    *,
    command_env: Optional[Mapping[str, str]] = None,
) -> str:
    """Resolve an executable with the PATH rules used by subprocess execution."""
    requested = str(executable or "").strip()
    if not requested:
        return ""
    if os.path.dirname(requested):
        candidate = Path(requested)
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate.resolve())
        return ""
    search_path = command_env.get("PATH", os.defpath) if command_env is not None else None
    resolved = shutil.which(requested, path=search_path)
    return str(Path(resolved).resolve()) if resolved else ""


def executable_version(
    resolved_path: str,
    *,
    command_env: Optional[Dict[str, str]] = None,
    run_command: Callable[..., Any] = subprocess.run,
    timeout_seconds: float = 5.0,
) -> str:
    """Return harmless ``--version`` output, or blank when it is unavailable."""
    if not resolved_path:
        return ""
    try:
        completed = run_command(
            [resolved_path, "--version"],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=command_env,
            check=False,
        )
    except Exception:
        return ""
    if int(getattr(completed, "returncode", 1) or 0) != 0:
        return ""
    text = str(getattr(completed, "stdout", "") or getattr(completed, "stderr", "") or "").strip()
    return text.splitlines()[0].strip() if text else ""


def stress_ng_requested_stressor_count(command: Sequence[str], stressor: str = "cpu") -> int:
    args = [str(value) for value in command]
    try:
        index = args.index(f"--{str(stressor or 'cpu').strip().lower()}")
        return max(0, int(args[index + 1]))
    except (ValueError, IndexError, TypeError):
        return 0


def _last_integer_match(text: str, pattern: str) -> Optional[int]:
    matches = re.findall(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
    return int(matches[-1]) if matches else None


def parse_stress_ng_metrics_brief(output: str) -> Dict[str, Any]:
    """Parse stable stress-ng metrics/count records without depending on prose."""
    text = str(output or "")
    parsed: Dict[str, Any] = {
        "dispatched_stressor_count": _last_integer_match(
            text,
            r"dispatching\s+hogs:\s*(\d+)\s+(?:cpu|vm)\b",
        ),
        "passed_stressor_count": _last_integer_match(text, r"^.*?passed:\s*(\d+)\b"),
        "failed_stressor_count": _last_integer_match(text, r"^.*?failed:\s*(\d+)\b"),
        "skipped_stressor_count": _last_integer_match(text, r"^.*?skipped:\s*(\d+)\b"),
        "metrics_untrustworthy_count": _last_integer_match(
            text,
            r"^.*?metrics\s+untrustworthy:\s*(\d+)\b",
        ),
        "stressor_metrics": [],
    }
    metric_pattern = re.compile(
        r"^.*?\b(cpu|vm)\s+(\d+)\s+"
        r"([0-9]+(?:\.[0-9]+)?)\s+([0-9]+(?:\.[0-9]+)?)\s+"
        r"([0-9]+(?:\.[0-9]+)?)\s+([0-9]+(?:\.[0-9]+)?)\s+"
        r"([0-9]+(?:\.[0-9]+)?)\s*$",
        flags=re.IGNORECASE | re.MULTILINE,
    )
    for match in metric_pattern.finditer(text):
        values: List[Any] = [match.group(1).lower(), int(match.group(2))]
        values.extend(float(match.group(index)) for index in range(3, 8))
        parsed["stressor_metrics"].append(dict(zip(STRESS_NG_METRIC_FIELDS, values)))
    return parsed


def build_stress_ng_cpu_evidence(
    command: Sequence[str],
    output: str,
) -> Dict[str, Any]:
    """Build worker-health evidence and strict explicit-count validation."""
    requested = stress_ng_requested_stressor_count(command)
    metrics = parse_stress_ng_metrics_brief(output)
    passed = metrics.get("passed_stressor_count")
    failed = metrics.get("failed_stressor_count")
    skipped = metrics.get("skipped_stressor_count")
    dispatched = metrics.get("dispatched_stressor_count")
    metric_rows = list(metrics.get("stressor_metrics") or [])
    errors: List[str] = []
    if requested <= 0:
        errors.append("stress-ng CPU command did not contain a positive --cpu worker count")
    if "--verify" not in [str(value) for value in command]:
        errors.append("stress-ng CPU command did not enable verification")
    if dispatched is None or (requested > 0 and dispatched < requested):
        errors.append("stress-ng did not report dispatching every requested CPU stressor")
    if passed is None or failed is None or skipped is None:
        errors.append("stress-ng did not report complete passed/failed/skipped stressor counts")
    else:
        if failed > 0:
            errors.append(f"stress-ng reported {failed} failed CPU stressor(s)")
        if skipped > 0:
            errors.append(f"stress-ng reported {skipped} skipped CPU stressor(s)")
        if requested > 0 and passed != requested:
            errors.append(f"stress-ng passed {passed} of {requested} requested CPU stressor(s)")
    if not metric_rows or sum(int(row.get("bogo_ops") or 0) for row in metric_rows) <= 0:
        errors.append("stress-ng did not report positive CPU bogo operations")
    return {
        "kind": "cpu",
        "backend": "stress_ng",
        "status": "error" if errors else "ok",
        "error_count": len(errors),
        "last_error": errors[0] if errors else "",
        "errors": errors,
        "requested_stressor_count": requested,
        "verification_enabled": "--verify" in [str(value) for value in command],
        **metrics,
    }


def build_stress_ng_memory_evidence(command: Sequence[str], output: str) -> Dict[str, Any]:
    requested = stress_ng_requested_stressor_count(command, "vm")
    metrics = parse_stress_ng_metrics_brief(output)
    metric_rows = [row for row in list(metrics.get("stressor_metrics") or []) if row.get("stressor") == "vm"]
    passed = metrics.get("passed_stressor_count")
    failed = metrics.get("failed_stressor_count")
    skipped = metrics.get("skipped_stressor_count")
    dispatched = metrics.get("dispatched_stressor_count")
    errors: List[str] = []
    if requested <= 0:
        errors.append("stress-ng memory command did not contain a positive --vm worker count")
    if "--verify" not in [str(value) for value in command]:
        errors.append("stress-ng memory command did not enable verification")
    if dispatched is None or dispatched < requested:
        errors.append("stress-ng did not report dispatching every requested VM stressor")
    if passed is None or failed is None or skipped is None:
        errors.append("stress-ng did not report complete passed/failed/skipped stressor counts")
    else:
        if failed > 0:
            errors.append(f"stress-ng reported {failed} failed memory stressor(s)")
        if skipped > 0:
            errors.append(f"stress-ng reported {skipped} skipped memory stressor(s)")
        if passed != requested:
            errors.append(f"stress-ng passed {passed} of {requested} requested memory stressor(s)")
    if not metric_rows or sum(int(row.get("bogo_ops") or 0) for row in metric_rows) <= 0:
        errors.append("stress-ng did not report positive VM bogo operations")
    return {
        "kind": "memory",
        "backend": "stress_ng",
        "status": "error" if errors else "ok",
        "error_count": len(errors),
        "last_error": errors[0] if errors else "",
        "errors": errors,
        "requested_stressor_count": requested,
        "verification_enabled": "--verify" in [str(value) for value in command],
        **metrics,
        "stressor_metrics": metric_rows,
    }
