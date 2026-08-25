#!/usr/bin/env python3
"""Optional device telemetry source discovery helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from Modules.lvs_telemetry_cpu import read_temperature_path
from Modules.lvs_platform_hwmon import (
    TRUSTED_PLATFORM_TELEMETRY_CLASSES,
    canonical_temperature_identity,
    normalize_platform_temperature_c,
    platform_hwmon_classification,
    stable_temperature_device_locator,
    valid_platform_temperature,
)


ReadText = Callable[[Path], Optional[str]]
ReadTemperature = Callable[[Path], Optional[float]]


def read_text_device_sysfs(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="ignore").strip()
    except Exception:
        return None


def discover_nic_temp_sources(
    hwmon_root: Path = Path("/sys/class/hwmon"),
    read_text: ReadText = read_text_device_sysfs,
) -> List[Dict[str, Any]]:
    sources: List[Dict[str, Any]] = []
    seen_identities: set[str] = set()
    for hwmon_dir in sorted(hwmon_root.glob("hwmon*")):
        name = (read_text(hwmon_dir / "name") or "").strip()
        name_lower = name.lower()
        try:
            resolved = str(hwmon_dir.resolve()).lower()
        except Exception:
            resolved = str(hwmon_dir).lower()
        if not (name_lower.startswith("r8169") or "/r8169-" in resolved or "realtek" in resolved):
            continue
        path = hwmon_dir / "temp1_input"
        if read_text(path) is None:
            continue
        canonical_identity = canonical_temperature_identity(path)
        if canonical_identity in seen_identities:
            continue
        seen_identities.add(canonical_identity)
        nic_index = len(sources)
        label = name or f"NIC {nic_index}"
        sources.append(
            {
                "kind": "nic_temp",
                "path": str(path),
                "label": label,
                "key": f"nic_{nic_index}_temp_c",
                "nic_index": nic_index,
                "device_name": label,
                "evidence_only": True,
            }
        )
    return sources


def discover_board_temp_sources(
    hwmon_root: Path = Path("/sys/class/hwmon"),
    read_text: ReadText = read_text_device_sysfs,
) -> List[Dict[str, Any]]:
    sources: List[Dict[str, Any]] = []
    seen_identities: set[str] = set()
    for hwmon_dir in sorted(hwmon_root.glob("hwmon*")):
        name = (read_text(hwmon_dir / "name") or "").strip()
        name_lower = name.lower()
        if name_lower != "gigabyte_wmi":
            continue
        sensor_index = 0
        for path in sorted(hwmon_dir.glob("temp*_input")):
            raw_value = read_text(path)
            if raw_value is None:
                continue
            canonical_identity = canonical_temperature_identity(path)
            if canonical_identity in seen_identities:
                continue
            seen_identities.add(canonical_identity)
            source_label = f"{name} {path.name.removesuffix('_input')}"
            sources.append(
                {
                    "kind": "board_temp",
                    "path": str(path),
                    "label": source_label,
                    "key": f"board_{sensor_index}_temp_c",
                    "board_sensor_index": sensor_index,
                    "device_name": name,
                    "evidence_only": True,
                }
            )
            sensor_index += 1
    return sources


def discover_wifi_temp_sources(
    hwmon_root: Path = Path("/sys/class/hwmon"),
    read_text: ReadText = read_text_device_sysfs,
) -> List[Dict[str, Any]]:
    sources: List[Dict[str, Any]] = []
    seen_identities: set[str] = set()
    for hwmon_dir in sorted(hwmon_root.glob("hwmon*")):
        name = (read_text(hwmon_dir / "name") or "").strip()
        name_lower = name.lower()
        if not (name_lower.startswith("iwlwifi") or name_lower.startswith("ath11k")):
            continue
        path = hwmon_dir / "temp1_input"
        if read_text(path) is None:
            continue
        canonical_identity = canonical_temperature_identity(path)
        if canonical_identity in seen_identities:
            continue
        seen_identities.add(canonical_identity)
        wifi_index = len(sources)
        label = name or f"Wi-Fi {wifi_index}"
        sources.append(
            {
                "kind": "wifi_temp",
                "path": str(path),
                "label": label,
                "key": f"wifi_{wifi_index}_temp_c",
                "wifi_index": wifi_index,
                "device_name": label,
                "evidence_only": True,
            }
        )
    return sources


def discover_platform_temp_sources(
    hwmon_root: Path = Path("/sys/class/hwmon"),
    read_text: ReadText = read_text_device_sysfs,
    claimed_sources: List[Dict[str, Any]] | None = None,
) -> List[Dict[str, Any]]:
    """Promote only unclaimed, explicitly labeled platform temperatures."""
    claimed_identities = {
        canonical_temperature_identity(Path(str(source.get("path") or "")))
        for source in (claimed_sources or [])
        if source.get("path")
    }
    seen_identities = set(claimed_identities)
    candidates: List[Dict[str, Any]] = []
    for hwmon_dir in sorted(hwmon_root.glob("hwmon*")):
        provider = (read_text(hwmon_dir / "name") or "").strip()
        for path in sorted(hwmon_dir.glob("temp*_input")):
            canonical_identity = canonical_temperature_identity(path)
            if canonical_identity in seen_identities:
                continue
            seen_identities.add(canonical_identity)
            stem = path.name.removesuffix("_input")
            raw_label = (read_text(hwmon_dir / f"{stem}_label") or "").strip()
            classified = platform_hwmon_classification(provider, raw_label)
            if (
                classified["classification"] not in TRUSTED_PLATFORM_TELEMETRY_CLASSES
                or classified["confidence"] != "high"
                or classified["owner"] != "platform"
            ):
                continue
            value = normalize_platform_temperature_c(read_text(path))
            if not valid_platform_temperature(provider, raw_label, value):
                continue
            candidates.append(
                {
                    "kind": "platform_temp",
                    "path": str(path),
                    "label": raw_label,
                    "raw_label": raw_label,
                    "normalized_label": classified["normalized_label"],
                    "provider": provider,
                    "component_classification": classified["classification"],
                    "confidence": classified["confidence"],
                    "canonical_identity": canonical_identity,
                    "stable_device_locator": stable_temperature_device_locator(path),
                    "kernel_channel": stem,
                }
            )

    candidates.sort(
        key=lambda source: (
            str(source["component_classification"]),
            str(source["provider"]).lower(),
            str(source["stable_device_locator"]),
            str(source["kernel_channel"]),
            str(source["normalized_label"]),
        )
    )
    class_counts: Dict[str, int] = {}
    for source in candidates:
        classification = str(source["component_classification"])
        sensor_index = class_counts.get(classification, 0)
        source["sensor_index"] = sensor_index
        source["key"] = f"{classification}_{sensor_index}_temp_c"
        class_counts[classification] = sensor_index + 1
    return candidates


def discover_device_temp_sources(
    hwmon_root: Path = Path("/sys/class/hwmon"),
    read_text: ReadText = read_text_device_sysfs,
) -> List[Dict[str, Any]]:
    specialized = (
        discover_nic_temp_sources(hwmon_root, read_text)
        + discover_wifi_temp_sources(hwmon_root, read_text)
        + discover_board_temp_sources(hwmon_root, read_text)
    )
    return specialized + discover_platform_temp_sources(hwmon_root, read_text, specialized)


def read_device_temps(
    sources: List[Dict[str, Any]],
    read_temperature: ReadTemperature = read_temperature_path,
    read_text: ReadText = read_text_device_sysfs,
) -> Dict[str, Optional[float]]:
    values: Dict[str, Optional[float]] = {}
    for source in sources:
        path = Path(str(source.get("path") or ""))
        if source.get("kind") == "platform_temp":
            value = normalize_platform_temperature_c(read_text(path))
            if not valid_platform_temperature(
                str(source.get("provider") or ""),
                str(source.get("raw_label") or source.get("label") or ""),
                value,
            ):
                value = None
        else:
            value = read_temperature(path)
        if value is not None:
            values[str(source["key"])] = value
    return values
