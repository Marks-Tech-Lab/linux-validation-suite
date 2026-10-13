#!/usr/bin/env python3
"""Optional device telemetry source discovery helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from Modules.lvs_telemetry_cpu import read_temperature_path
from Modules.lvs_telemetry_sampling import parse_temperature_text
from Modules.lvs_temperature_provenance import classify_thermal_zone_type
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
ThermalZoneThresholds = Callable[[Path], tuple[Optional[float], Optional[float], str]]


def _zone_index(path: Path) -> int:
    try:
        return int(path.name.removeprefix("thermal_zone"))
    except ValueError:
        return 0


def _thermal_zone_aliases(zone_dir: Path, hwmon_root: Path) -> List[str]:
    """Return only aliases proven to resolve to the exact same sensor file."""
    zone_temp = zone_dir / "temp"
    aliases: List[str] = []
    for hwmon in sorted(hwmon_root.glob("hwmon*")):
        for path in sorted(hwmon.glob("temp*_input")):
            try:
                if path.samefile(zone_temp):
                    aliases.append(str(path))
            except Exception:
                continue
    return aliases


def discover_platform_thermal_zone_sources(
    thermal_root: Path = Path("/sys/class/thermal"),
    hwmon_root: Path = Path("/sys/class/hwmon"),
    read_text: ReadText | None = None,
    thermal_zone_thresholds: ThermalZoneThresholds | None = None,
    claimed_sources: List[Dict[str, Any]] | None = None,
) -> List[Dict[str, Any]]:
    """Discover non-CPU thermal zones as distinct, continuously sampled sources."""
    if read_text is None:
        read_text = read_text_device_sysfs
    if thermal_zone_thresholds is None:
        thermal_zone_thresholds = lambda _zone: (None, None, "suite_default")
    claimed_paths: List[Path] = []
    for source in claimed_sources or []:
        candidates = [source, *(source.get("sources") or [])]
        for candidate in candidates:
            if isinstance(candidate, dict) and candidate.get("path"):
                claimed_paths.append(Path(str(candidate["path"])))
    sources: List[Dict[str, Any]] = []
    for zone_dir in sorted(thermal_root.glob("thermal_zone*"), key=_zone_index):
        path = zone_dir / "temp"
        if any(
            str(candidate) == str(path)
            or (candidate.exists() and path.exists() and candidate.samefile(path))
            for candidate in claimed_paths
        ):
            continue
        if parse_temperature_text(read_text(path)) is None:
            continue
        zone_type = str(read_text(zone_dir / "type") or zone_dir.name).strip()
        provenance = classify_thermal_zone_type(zone_type)
        if str(provenance.get("component_scope") or "").startswith("cpu_"):
            continue
        zone_index = _zone_index(zone_dir)
        warn_c, fail_c, threshold_source = thermal_zone_thresholds(zone_dir)
        trip_points: List[Dict[str, Any]] = []
        for type_path in sorted(zone_dir.glob("trip_point_*_type")):
            suffix = type_path.name.removeprefix("trip_point_").removesuffix("_type")
            temp_path = zone_dir / f"trip_point_{suffix}_temp"
            temperature_c = parse_temperature_text(read_text(temp_path), upper_bound=200.0)
            if temperature_c is None:
                continue
            trip_points.append({
                "trip_index": int(suffix),
                "trip_type": str(read_text(type_path) or "unknown").strip().lower(),
                "temperature_c": temperature_c,
                "source": str(temp_path),
            })
        trip_types = {str(item.get("trip_type") or "") for item in trip_points}
        warn_semantics = (
            "firmware_warning_trip"
            if trip_types & {"hot", "passive"}
            else "derived_5c_below_firmware_critical" if warn_c is not None and "critical" in trip_types
            else ""
        )
        fail_semantics = "firmware_critical_trip" if "critical" in trip_types and fail_c is not None else ""
        sources.append({
            "kind": "platform_thermal_zone",
            "provider": "linux_thermal_zone",
            "path": str(path),
            "label": f"{zone_type} {zone_dir.name}",
            "raw_label": zone_type,
            "zone_type": zone_type,
            "zone_id": zone_dir.name,
            "zone_index": zone_index,
            "sensor_index": zone_index,
            "key": f"platform_thermal_zone_{zone_index}_temp_c",
            "metric": "temperature_c",
            "unit": "celsius",
            "warn_threshold_c": warn_c,
            "fail_threshold_c": fail_c,
            "threshold_source": threshold_source,
            "warn_threshold_semantics": warn_semantics,
            "fail_threshold_semantics": fail_semantics,
            "thresholds": {
                "warn_c": warn_c,
                "fail_c": fail_c,
                "source": threshold_source,
                "derived_from_hardware": threshold_source != "suite_default",
            },
            "trip_points": trip_points,
            "alias_paths": _thermal_zone_aliases(zone_dir, hwmon_root),
            "source_scope": "platform_thermal_zone",
            "component_classification": "platform_thermal_zone",
            "measurement_semantics": "measured_temperature",
            **provenance,
        })
    return sources


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
