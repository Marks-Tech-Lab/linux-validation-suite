#!/usr/bin/env python3
"""CPU power-limit parsing helpers."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional


ReadSysfs = Callable[[Path], Optional[str]]


def read_microunit_watts(path: Path, read_sysfs: ReadSysfs) -> Optional[float]:
    text = read_sysfs(path)
    if not text:
        return None
    try:
        value = float(text)
    except Exception:
        return None
    if value <= 0:
        return None
    return round(value / 1_000_000.0, 2)


def read_microseconds(path: Path, read_sysfs: ReadSysfs) -> Optional[float]:
    text = read_sysfs(path)
    if not text:
        return None
    try:
        value = float(text)
    except Exception:
        return None
    if value <= 0:
        return None
    return round(value / 1_000_000.0, 3)


def format_watts(watts: Any) -> str:
    try:
        value = float(watts)
    except Exception:
        return ""
    return f"{int(value) if value.is_integer() else round(value, 2):g}W"


def format_seconds(seconds: Any) -> str:
    try:
        value = float(seconds)
    except Exception:
        return ""
    return f"{int(value) if value.is_integer() else round(value, 3):g}s"


def select_rapl_package_dir(candidates: Iterable[Path]) -> Optional[Path]:
    return next((path for path in candidates if path.exists()), None)


def collect_rapl_constraints(package_dir: Path, read_sysfs: ReadSysfs) -> List[Dict[str, Any]]:
    constraints: List[Dict[str, Any]] = []
    for name_path in sorted(package_dir.glob("constraint_*_name")):
        match = re.match(r"constraint_(\d+)_name$", name_path.name)
        if not match:
            continue
        index = match.group(1)
        label = read_sysfs(name_path) or f"constraint_{index}"
        limit_w = read_microunit_watts(package_dir / f"constraint_{index}_power_limit_uw", read_sysfs)
        max_w = read_microunit_watts(package_dir / f"constraint_{index}_max_power_uw", read_sysfs)
        time_seconds = read_microseconds(package_dir / f"constraint_{index}_time_window_us", read_sysfs)
        constraints.append(
            {
                "Index": int(index),
                "Name": label,
                "PowerLimitW": limit_w,
                "MaxPowerW": max_w,
                "TimeWindowSeconds": time_seconds,
            }
        )
    return constraints


def build_cpu_power_limit_info(package_dir: Optional[Path], read_sysfs: ReadSysfs) -> Dict[str, Any]:
    if package_dir is None:
        return {"Source": "not found", "PowerLimitData": "", "AmdPpt": ""}

    constraints = collect_rapl_constraints(package_dir, read_sysfs)
    pl1 = next(
        (item for item in constraints if str(item.get("Name", "")).lower() in {"long_term", "long term", "long"}),
        None,
    )
    pl2 = next(
        (item for item in constraints if str(item.get("Name", "")).lower() in {"short_term", "short term", "short"}),
        None,
    )
    if pl1 is None and constraints:
        pl1 = constraints[0]
    if pl2 is None and len(constraints) > 1:
        pl2 = constraints[1]

    parts: List[str] = []
    if pl1 and pl1.get("PowerLimitW") is not None:
        parts.append(f"PL1:{format_watts(pl1['PowerLimitW'])}")
    if pl2 and pl2.get("PowerLimitW") is not None:
        parts.append(f"PL2:{format_watts(pl2['PowerLimitW'])}")
    turbo_seconds = pl1.get("TimeWindowSeconds") if pl1 else None
    if turbo_seconds is not None:
        parts.append(f"Turbo:{format_seconds(turbo_seconds)}")

    return {
        "Source": str(package_dir),
        "PowerLimitData": "|".join(parts),
        "AmdPpt": "",
        "Constraints": constraints,
    }
