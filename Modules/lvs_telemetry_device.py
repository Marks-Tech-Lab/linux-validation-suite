#!/usr/bin/env python3
"""Optional device telemetry source discovery helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from Modules.lvs_telemetry_cpu import read_temperature_path


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
    for hwmon_dir in sorted(hwmon_root.glob("hwmon*")):
        name = (read_text(hwmon_dir / "name") or "").strip()
        name_lower = name.lower()
        if not (name_lower.startswith("iwlwifi") or name_lower.startswith("ath11k")):
            continue
        path = hwmon_dir / "temp1_input"
        if read_text(path) is None:
            continue
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


def discover_device_temp_sources(
    hwmon_root: Path = Path("/sys/class/hwmon"),
    read_text: ReadText = read_text_device_sysfs,
) -> List[Dict[str, Any]]:
    return (
        discover_nic_temp_sources(hwmon_root, read_text)
        + discover_wifi_temp_sources(hwmon_root, read_text)
        + discover_board_temp_sources(hwmon_root, read_text)
    )


def read_device_temps(
    sources: List[Dict[str, Any]],
    read_temperature: ReadTemperature = read_temperature_path,
) -> Dict[str, Optional[float]]:
    values: Dict[str, Optional[float]] = {}
    for source in sources:
        value = read_temperature(Path(str(source.get("path") or "")))
        if value is not None:
            values[str(source["key"])] = value
    return values
