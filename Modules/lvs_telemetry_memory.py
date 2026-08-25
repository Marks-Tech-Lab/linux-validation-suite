#!/usr/bin/env python3
"""Pure memory telemetry classification and source discovery helpers."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from Modules.lvs_platform_hwmon import (
    canonical_temperature_identity,
    normalize_platform_temperature_c,
    stable_temperature_device_locator,
    valid_platform_temperature,
)


ReadText = Callable[[Path], Optional[str]]
ReadTemperature = Callable[[Path], Optional[float]]


def memory_usage_gib_from_meminfo(text: str) -> tuple[Optional[float], Optional[float]]:
    values: Dict[str, int] = {}
    for line in str(text or "").splitlines():
        if ":" not in line:
            continue
        key, raw = line.split(":", 1)
        try:
            values[key.strip()] = int(raw.strip().split()[0])
        except (IndexError, ValueError):
            continue
    total_kib = values.get("MemTotal")
    available_kib = values.get("MemAvailable")
    if not total_kib or available_kib is None:
        return None, None
    total_gib = round(total_kib / (1024 * 1024), 2)
    used_gib = round((total_kib - available_kib) / (1024 * 1024), 2)
    return used_gib, total_gib


def read_text_memory_sysfs(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="ignore").strip()
    except Exception:
        return None


def ipmi_memory_sensor_sort_key(label: str) -> Tuple[object, ...]:
    text = str(label or "").upper()
    match = re.search(r"DDR\d*[_ -]?([A-Z]+)(\d*)", text)
    if match:
        letters = match.group(1)
        number = int(match.group(2) or 0)
        return (0, letters, number, text)
    match = re.search(r"DIMM[_ -]?([A-Z]+)(\d*)", text)
    if match:
        letters = match.group(1)
        number = int(match.group(2) or 0)
        return (1, letters, number, text)
    return (9, text)


def spd5118_memory_temp_sources(
    hwmon_root: Path = Path("/sys/class/hwmon"),
    read_text: ReadText | None = None,
    sensor_index: int = 0,
) -> List[Dict[str, Any]]:
    return direct_memory_temp_sources(
        hwmon_root=hwmon_root,
        read_text=read_text,
        sensor_index=sensor_index,
        providers=("spd5118",),
    )


def direct_memory_temp_sources(
    hwmon_root: Path = Path("/sys/class/hwmon"),
    read_text: ReadText | None = None,
    sensor_index: int = 0,
    providers: Tuple[str, ...] = ("spd5118", "jc42"),
) -> List[Dict[str, Any]]:
    """Discover valid direct DIMM sensors before platform/IPMI fallbacks."""
    if read_text is None:
        read_text = read_text_memory_sysfs
    candidates: List[Dict[str, Any]] = []
    seen_identities: set[str] = set()
    for hwmon_dir in sorted(hwmon_root.glob("hwmon*")):
        provider = (read_text(hwmon_dir / "name") or "").lower()
        if provider not in providers:
            continue
        for path in sorted(hwmon_dir.glob("temp*_input")):
            canonical_identity = canonical_temperature_identity(path)
            if canonical_identity in seen_identities:
                continue
            seen_identities.add(canonical_identity)
            value = normalize_platform_temperature_c(read_text(path))
            if not valid_platform_temperature(provider, "", value):
                continue
            stem = path.name.removesuffix("_input")
            candidates.append(
                {
                    "kind": "memory_temp",
                    "path": str(path),
                    "provider": provider,
                    "canonical_identity": canonical_identity,
                    "stable_device_locator": stable_temperature_device_locator(path),
                    "kernel_channel": stem,
                }
            )
    candidates.sort(
        key=lambda source: (
            0 if source["provider"] == "spd5118" else 1,
            str(source["stable_device_locator"]),
            str(source["kernel_channel"]),
        )
    )
    sources: List[Dict[str, Any]] = []
    for offset, source in enumerate(candidates):
        module_index = sensor_index + offset
        provider_label = "SPD Hub" if source["provider"] == "spd5118" else "JC42"
        source.update(
            {
                "label": f"DIMM {module_index} {provider_label}",
                "key": f"memory_module_{module_index}_temp_c",
                "module_index": module_index,
            }
        )
        sources.append(source)
    return sources


def platform_memory_temp_sources(
    thermal_root: Path = Path("/sys/class/thermal"),
    read_text: ReadText | None = None,
) -> List[Dict[str, Any]]:
    """Discover a labeled platform memory thermal zone without relying on its index."""
    if read_text is None:
        read_text = read_text_memory_sysfs
    sources: List[Dict[str, Any]] = []
    for zone_dir in sorted(thermal_root.glob("thermal_zone*")):
        zone_type = str(read_text(zone_dir / "type") or "").strip()
        normalized = zone_type.lower().replace("_", "-")
        if normalized not in {"mem-thermal", "memory-thermal"}:
            continue
        path = zone_dir / "temp"
        if read_text(path) is None:
            continue
        sources.append(
            {
                "kind": "thermal_zone_memory",
                "path": str(path),
                "label": zone_type or "mem-thermal",
                "key": "memory_temp_c",
            }
        )
    return sources[:1]


def read_memory_temps(
    memory_temp_sources: List[Dict[str, Any]],
    read_temperature: ReadTemperature,
) -> Dict[str, Optional[float]]:
    values: Dict[str, Optional[float]] = {}
    for source in memory_temp_sources:
        if source.get("kind") == "ipmi_memory_temp":
            continue
        value = read_temperature(Path(str(source.get("path") or "")))
        if value is not None:
            values[str(source["key"])] = value
    return values


def discover_memory_temp_sources(
    hwmon_root: Path = Path("/sys/class/hwmon"),
    thermal_root: Path = Path("/sys/class/thermal"),
    read_text: ReadText | None = None,
) -> List[Dict[str, Any]]:
    sources = direct_memory_temp_sources(hwmon_root, read_text)
    if sources:
        return sources
    sources = platform_memory_temp_sources(thermal_root, read_text)
    if sources:
        return sources
    return []
