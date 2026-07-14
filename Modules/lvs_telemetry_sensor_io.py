#!/usr/bin/env python3
"""Shared sensor file I/O and threshold helpers."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Callable, Optional

from .lvs_telemetry_sampling import parse_temperature_text


ReadText = Callable[[Path], Optional[str]]


def safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="ignore").strip()
    except Exception:
        return None


def safe_read_text_sudo(path: Path, read_text: ReadText = safe_read_text) -> Optional[str]:
    if os.geteuid() == 0:
        return read_text(path)
    if shutil.which("sudo") is None:
        return None
    try:
        completed = subprocess.run(
            ["sudo", "-n", "cat", str(path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except Exception:
        return None
    if completed.returncode != 0:
        return None
    return (completed.stdout or "").strip()


def sensor_label(data_path: Path, read_text: ReadText = safe_read_text) -> str:
    label_path = data_path.with_name(data_path.name.replace("_input", "_label").replace("_average", "_label"))
    return read_text(label_path) or ""


def read_temp_limit_c(path: Path, read_text: ReadText = safe_read_text) -> Optional[float]:
    raw = read_text(path)
    if raw is None:
        return None
    return parse_temperature_text(raw, upper_bound=200.0)


def read_hwmon_temp_limit(
    input_path: Path,
    suffix: str,
    read_text: ReadText = safe_read_text,
) -> Optional[float]:
    candidate_dirs: list[Path] = [input_path.parent]
    try:
        resolved_parent = input_path.resolve().parent
    except Exception:
        resolved_parent = input_path.parent
    if resolved_parent not in candidate_dirs:
        candidate_dirs.append(resolved_parent)
    stem = input_path.name.removesuffix("_input")
    for directory in candidate_dirs:
        value = read_temp_limit_c(directory / f"{stem}_{suffix}", read_text)
        if value is not None:
            return value
    return None


def hwmon_temp_thresholds(
    input_path: Path,
    read_text: ReadText = safe_read_text,
) -> tuple[Optional[float], Optional[float], str]:
    max_c = read_hwmon_temp_limit(input_path, "max", read_text)
    crit_c = read_hwmon_temp_limit(input_path, "crit", read_text)
    crit_hyst_c = read_hwmon_temp_limit(input_path, "crit_hyst", read_text)
    emergency_c = read_hwmon_temp_limit(input_path, "emergency", read_text)
    fail_c = crit_c or emergency_c or max_c
    warn_c = max_c or crit_hyst_c
    if warn_c is None and fail_c is not None:
        warn_c = max(0.0, round(fail_c - 5.0, 2))
    if warn_c is None and fail_c is None:
        return None, None, "suite_default"
    return warn_c, fail_c, "hwmon_limit"


def thermal_zone_thresholds(
    zone_dir: Path,
    read_text: ReadText = safe_read_text,
) -> tuple[Optional[float], Optional[float], str]:
    warn_c: Optional[float] = None
    fail_c: Optional[float] = None
    for type_path in sorted(zone_dir.glob("trip_point_*_type")):
        suffix = type_path.name.removeprefix("trip_point_").removesuffix("_type")
        temp_path = zone_dir / f"trip_point_{suffix}_temp"
        trip_type = (read_text(type_path) or "").strip().lower()
        trip_temp = read_temp_limit_c(temp_path, read_text)
        if trip_temp is None:
            continue
        if trip_type == "critical":
            fail_c = trip_temp if fail_c is None else min(fail_c, trip_temp)
        elif trip_type in {"hot", "passive"}:
            warn_c = trip_temp if warn_c is None else min(warn_c, trip_temp)
    if warn_c is None and fail_c is not None:
        warn_c = max(0.0, round(fail_c - 5.0, 2))
    if warn_c is None and fail_c is None:
        return None, None, "suite_default"
    return warn_c, fail_c, "thermal_zone_trip"
