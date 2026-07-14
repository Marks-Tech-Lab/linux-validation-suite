#!/usr/bin/env python3
"""Pure CPU telemetry and topology helper rules."""

from __future__ import annotations

import re
import statistics
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

from .lvs_telemetry_sampling import parse_power_text_w, parse_temperature_text


ReadText = Callable[[Path], Optional[str]]
SensorLabel = Callable[[Path], str]
HwmonTempThresholds = Callable[[Path], tuple[Optional[float], Optional[float], str]]
ThermalZoneThresholds = Callable[[Path], tuple[Optional[float], Optional[float], str]]


def read_text_cpu_sysfs(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="ignore").strip()
    except Exception:
        return None


def read_cpu_sysfs_int(path: Path, read_text: ReadText = read_text_cpu_sysfs) -> Optional[int]:
    raw = read_text(path)
    if raw is None:
        return None
    try:
        return int(str(raw).strip(), 0)
    except Exception:
        return None


def cpu_sensor_label(data_path: Path, read_text: ReadText = read_text_cpu_sysfs) -> str:
    label_path = data_path.with_name(data_path.name.replace("_input", "_label").replace("_average", "_label"))
    return read_text(label_path) or ""


def read_temperature_path(path: Path, read_text: ReadText = read_text_cpu_sysfs) -> Optional[float]:
    raw = read_text(path)
    if raw is None:
        return None
    return parse_temperature_text(raw)


def read_cpu_temp(
    cpu_temp_sources: Iterable[Dict[str, Any]],
    read_text: ReadText = read_text_cpu_sysfs,
    package_temps: Optional[Dict[str, Optional[float]]] = None,
) -> Optional[float]:
    if package_temps:
        values = [value for value in package_temps.values() if value is not None]
        if values:
            return max(values)
    for source in cpu_temp_sources:
        value = read_temperature_path(Path(str(source.get("path") or "")), read_text)
        if value is not None:
            return value
    return None


def read_cpu_package_temps(
    cpu_package_temp_sources: Iterable[Dict[str, Any]],
    read_text: ReadText = read_text_cpu_sysfs,
) -> Dict[str, Optional[float]]:
    values: Dict[str, Optional[float]] = {}
    for source in cpu_package_temp_sources:
        key = str(source.get("key") or "")
        if not key:
            continue
        values[key] = read_temperature_path(Path(str(source.get("path") or "")), read_text)
    return values


def read_hwmon_power_source(
    source: Dict[str, Any],
    read_text: ReadText = read_text_cpu_sysfs,
    *,
    max_watts: float,
) -> Optional[float]:
    path = Path(str(source.get("path") or ""))
    raw_text = read_text(path)
    if raw_text is None:
        return None
    return parse_power_text_w(raw_text, max_watts=max_watts)


def read_energy_power_source(
    source: Dict[str, Any],
    sample_time: float,
    energy_source_state: Dict[str, Dict[str, float]],
    read_text: ReadText = read_text_cpu_sysfs,
    read_text_sudo: ReadText = read_text_cpu_sysfs,
    *,
    max_watts: float,
) -> Optional[float]:
    path = Path(str(source.get("path") or ""))
    raw_text = read_text_sudo(path) if source.get("kind") == "sudo_rapl" else read_text(path)
    if raw_text is None:
        return None
    try:
        energy_uj = int(raw_text)
    except Exception:
        return None

    state_key = str(path)
    state = energy_source_state.get(state_key)
    if state is None:
        energy_source_state[state_key] = {
            "energy_uj": float(energy_uj),
            "timestamp": sample_time,
        }
        return None

    delta_energy_uj = energy_uj - int(state["energy_uj"])
    max_range_uj = source.get("max_energy_range_uj")
    if delta_energy_uj < 0 and isinstance(max_range_uj, int) and max_range_uj > 0:
        delta_energy_uj += max_range_uj

    delta_time = sample_time - float(state["timestamp"])
    energy_source_state[state_key] = {
        "energy_uj": float(energy_uj),
        "timestamp": sample_time,
    }

    if delta_time <= 0 or delta_energy_uj <= 0:
        return None

    watts = delta_energy_uj / (delta_time * 1_000_000.0)
    return round(watts, 2) if 0 < watts < max_watts else None


def read_cpu_power_component(
    source: Dict[str, Any],
    sample_time: float,
    energy_source_state: Dict[str, Dict[str, float]],
    read_text: ReadText = read_text_cpu_sysfs,
    read_text_sudo: ReadText = read_text_cpu_sysfs,
    *,
    max_watts: float,
) -> Optional[float]:
    kind = source.get("kind")
    if kind == "hwmon":
        return read_hwmon_power_source(source, read_text, max_watts=max_watts)
    if kind in {"rapl", "sudo_rapl", "energy_hwmon"}:
        return read_energy_power_source(
            source,
            sample_time,
            energy_source_state,
            read_text,
            read_text_sudo,
            max_watts=max_watts,
        )
    return None


def read_cpu_power(
    cpu_power_source: Optional[Dict[str, Any]],
    sample_time: float,
    energy_source_state: Dict[str, Dict[str, float]],
    read_text: ReadText = read_text_cpu_sysfs,
    read_text_sudo: ReadText = read_text_cpu_sysfs,
) -> tuple[Optional[float], Dict[str, float]]:
    if not cpu_power_source:
        return None, {}

    kind = cpu_power_source.get("kind")
    if kind in {"aggregate_energy", "aggregate_power"}:
        package_values: Dict[str, float] = {}
        values: List[float] = []
        for source in cpu_power_source.get("sources", []):
            if not isinstance(source, dict):
                continue
            value = read_cpu_power_component(
                source,
                sample_time,
                energy_source_state,
                read_text,
                read_text_sudo,
                max_watts=1500.0,
            )
            if value is None:
                continue
            values.append(value)
            package_id = source.get("package_id")
            if package_id not in (None, ""):
                package_values[f"cpu_package_{package_id}_power_w"] = value
        return (round(sum(values), 2) if values else None), package_values

    if kind == "hwmon":
        return read_hwmon_power_source(cpu_power_source, read_text, max_watts=1000.0), {}

    if kind in {"rapl", "sudo_rapl", "energy_hwmon"}:
        return (
            read_energy_power_source(
                cpu_power_source,
                sample_time,
                energy_source_state,
                read_text,
                read_text_sudo,
                max_watts=1000.0,
            ),
            {},
        )

    return None, {}


def _clock_mhz_from_raw(raw: str) -> Optional[float]:
    try:
        value = float(raw)
    except Exception:
        return None
    if value > 10000:
        value /= 1000.0
    return round(value, 2) if value > 0 else None


def read_cpu_clock_mhz(
    cpu_clock_source: Optional[Dict[str, Any]],
    read_text: ReadText = read_text_cpu_sysfs,
) -> Optional[float]:
    if not cpu_clock_source:
        return None

    kind = cpu_clock_source.get("kind")
    if kind == "cpufreq":
        values: List[float] = []
        for path_text in cpu_clock_source.get("paths", []):
            raw = read_text(Path(str(path_text)))
            if raw is None:
                continue
            value = _clock_mhz_from_raw(raw)
            if value is not None:
                values.append(value)
        return round(statistics.mean(values), 2) if values else None

    if kind == "proc_cpuinfo":
        cpuinfo = read_text(Path(str(cpu_clock_source.get("path") or "/proc/cpuinfo")))
        if cpuinfo is None:
            return None
        values = []
        for line in cpuinfo.splitlines():
            if line.lower().startswith("cpu mhz"):
                try:
                    values.append(float(line.split(":", 1)[1].strip()))
                except Exception:
                    continue
        return round(statistics.mean(values), 2) if values else None

    return None


def read_cpu_core_clocks(
    cpu_core_clock_sources: Iterable[Dict[str, Any]],
    read_text: ReadText = read_text_cpu_sysfs,
) -> Dict[str, Optional[float]]:
    values: Dict[str, Optional[float]] = {}
    for source in cpu_core_clock_sources:
        raw = read_text(Path(str(source.get("path") or "")))
        if raw is None:
            continue
        value = _clock_mhz_from_raw(raw)
        if value is not None:
            values[str(source.get("key") or "")] = value
    return {key: value for key, value in values.items() if key}


def score_cpu_temp_source(hwmon_name: str, label: str) -> int:
    text = f"{hwmon_name} {label}".lower()
    score = 0
    if "package id 0" in text:
        score += 120
    if "cpu package" in text:
        score += 110
    if "tdie" in text or "tctl" in text:
        score += 100
    if "package" in text:
        score += 80
    if "cpu" in text:
        score += 40
    if "coretemp" in text or "k10temp" in text or "zenpower" in text:
        score += 30
    return score


def score_thermal_zone(zone_type: str) -> int:
    text = str(zone_type or "").lower()
    score = 0
    if "x86_pkg_temp" in text:
        score += 90
    if "cpu" in text:
        score += 70
    if "pkg" in text or "package" in text:
        score += 60
    if "acpitz" in text:
        score += 10
    return score


def score_cpu_power_source(hwmon_name: str, label: str) -> int:
    text = f"{hwmon_name} {label}".lower()
    score = 0
    if "amd_hsmp_hwmon" in text:
        score += 260
    if "package" in text or "pkg" in text:
        score += 120
    if "cpu" in text:
        score += 80
    if ("ppt" in text or "power" in text) and ("zenpower" in text or "fam15h_power" in text):
        score += 60
    if ("ppt" in text or "power" in text) and ("k10temp" in text) and ("cpu" in text or "package" in text or "pkg" in text):
        score += 50
    if "rapl" in text or "zenpower" in text or "fam15h_power" in text:
        score += 40
    return score


def score_rapl_source(name: str) -> int:
    text = str(name or "").lower()
    score = 0
    if "package" in text:
        score += 120
    if "core" in text and "uncore" not in text:
        score -= 20
    if "psys" in text:
        score += 80
    if "core" in text:
        score += 30
    if "cpu" in text or "amd" in text:
        score += 20
    return score


def score_energy_source(hwmon_name: str, label: str) -> int:
    text = f"{hwmon_name} {label}".lower()
    score = 0
    if "energy" in text:
        score += 40
    if "package" in text or "pkg" in text:
        score += 120
    if "zenergy" in text:
        score += 30
        if "esocket" in text or "socket" in text:
            score += 150
        elif re.search(r"\becore\d*", text):
            score += 35
    if "cpu" in text:
        score += 80
    if "amd_energy" in text or "zenpower" in text or "fam15h_power" in text:
        score += 70
    return score


def discover_cpu_temp_sources(
    hwmon_root: Path = Path("/sys/class/hwmon"),
    thermal_root: Path = Path("/sys/class/thermal"),
    read_text: ReadText = read_text_cpu_sysfs,
    sensor_label: SensorLabel | None = None,
    hwmon_temp_thresholds: HwmonTempThresholds | None = None,
    thermal_zone_thresholds: ThermalZoneThresholds | None = None,
) -> List[Dict[str, Any]]:
    if sensor_label is None:
        sensor_label = lambda path: cpu_sensor_label(path, read_text)
    if hwmon_temp_thresholds is None:
        hwmon_temp_thresholds = lambda _path: (None, None, "suite_default")
    if thermal_zone_thresholds is None:
        thermal_zone_thresholds = lambda _path: (None, None, "suite_default")

    sources: List[Dict[str, Any]] = []
    for hwmon_dir in sorted(hwmon_root.glob("hwmon*")):
        hwmon_name = read_text(hwmon_dir / "name") or ""
        for path in sorted(hwmon_dir.glob("temp*_input")):
            if read_text(path) is None:
                continue
            label = sensor_label(path)
            warn_threshold_c, fail_threshold_c, threshold_source = hwmon_temp_thresholds(path)
            sources.append(
                {
                    "kind": "hwmon",
                    "path": str(path),
                    "label": label or hwmon_name or path.name,
                    "hwmon_name": hwmon_name,
                    "score": score_cpu_temp_source(hwmon_name, label),
                    "warn_threshold_c": warn_threshold_c,
                    "fail_threshold_c": fail_threshold_c,
                    "threshold_source": threshold_source,
                }
            )

    for zone_dir in sorted(thermal_root.glob("thermal_zone*")):
        path = zone_dir / "temp"
        if not path.exists():
            continue
        if read_text(path) is None:
            continue
        zone_type = read_text(zone_dir / "type") or ""
        warn_threshold_c, fail_threshold_c, threshold_source = thermal_zone_thresholds(zone_dir)
        sources.append(
            {
                "kind": "thermal_zone",
                "path": str(path),
                "label": zone_type or zone_dir.name,
                "score": score_thermal_zone(zone_type),
                "warn_threshold_c": warn_threshold_c,
                "fail_threshold_c": fail_threshold_c,
                "threshold_source": threshold_source,
            }
        )

    sources.sort(key=lambda item: item["score"], reverse=True)
    return sources


def discover_cpu_power_candidates(
    hwmon_root: Path = Path("/sys/class/hwmon"),
    powercap_roots: Iterable[Path] = (Path("/sys/class/powercap"), Path("/sys/devices/virtual/powercap")),
    read_text: ReadText = read_text_cpu_sysfs,
    sensor_label: SensorLabel | None = None,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    if sensor_label is None:
        sensor_label = lambda path: cpu_sensor_label(path, read_text)
    sources: List[Dict[str, Any]] = []
    unreadable_sources: List[Dict[str, Any]] = []

    for hwmon_dir in sorted(hwmon_root.glob("hwmon*")):
        try:
            resolved_hwmon = hwmon_dir.resolve()
        except Exception:
            resolved_hwmon = hwmon_dir
        resolved_text = str(resolved_hwmon)
        if "/drm/card" in resolved_text:
            continue
        hwmon_name = read_text(hwmon_dir / "name") or ""
        for pattern in ("power*_average", "power*_input"):
            for path in sorted(hwmon_dir.glob(pattern)):
                if read_text(path) is None:
                    continue
                label = sensor_label(path)
                score = score_cpu_power_source(hwmon_name, label)
                if score <= 0:
                    continue
                sources.append(
                    {
                        "kind": "hwmon",
                        "path": str(path),
                        "label": label or hwmon_name or path.name,
                        "score": score + 100,
                    }
                )
        for path in sorted(hwmon_dir.glob("energy*_input")):
            raw = read_text(path)
            if raw is None:
                continue
            label = sensor_label(path)
            score = score_cpu_power_source(hwmon_name, label)
            if score <= 0:
                score = score_energy_source(hwmon_name, label)
            if score <= 0:
                continue
            max_range_text = read_text(path.with_name(path.name.replace("_input", "_max")))
            max_range_uj = int(max_range_text) if max_range_text and max_range_text.isdigit() else None
            sources.append(
                {
                    "kind": "energy_hwmon",
                    "path": str(path),
                    "label": label or hwmon_name or path.name,
                    "score": score + 90,
                    "max_energy_range_uj": max_range_uj,
                }
            )

    seen_paths: Dict[str, bool] = {}
    for root in powercap_roots:
        if not root.exists():
            continue
        for path in sorted(root.glob("**/energy_uj")):
            resolved = str(path.resolve())
            if resolved in seen_paths:
                continue
            seen_paths[resolved] = True
            name = read_text(path.parent / "name") or path.parent.name
            max_range_text = read_text(path.parent / "max_energy_range_uj")
            max_range_uj = int(max_range_text) if max_range_text and max_range_text.isdigit() else None
            source = {
                "kind": "rapl",
                "path": str(path),
                "label": name,
                "score": score_rapl_source(name),
                "max_energy_range_uj": max_range_uj,
            }
            if read_text(path) is None:
                unreadable_sources.append(source)
            else:
                sources.append(source)

    return sources, unreadable_sources


def add_privileged_cpu_power_sources(
    sources: List[Dict[str, Any]],
    unreadable_sources: Iterable[Dict[str, Any]],
    read_text_sudo: ReadText,
    *,
    privileged_helper_enabled: bool,
) -> None:
    if not privileged_helper_enabled:
        return
    seen_source_paths = {
        str(Path(str(source.get("path") or "")).resolve())
        for source in sources
        if source.get("path")
    }
    for source in unreadable_sources:
        path_text = str(source.get("path") or "")
        if not path_text:
            continue
        path = Path(path_text)
        resolved = str(path.resolve())
        if resolved in seen_source_paths:
            continue
        sudo_source = dict(source)
        sudo_source["kind"] = "sudo_rapl"
        sudo_source["label"] = f"{source.get('label') or 'rapl'} via sudo"
        raw = read_text_sudo(path)
        if raw is None:
            continue
        sources.append(sudo_source)
        seen_source_paths.add(resolved)


def select_cpu_power_source(sources: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not sources:
        return None
    sources.sort(key=lambda item: item["score"], reverse=True)
    aggregate_source = aggregate_cpu_package_power_source(sources)
    return aggregate_source or sources[0]


def discover_cpu_power_source(
    hwmon_root: Path = Path("/sys/class/hwmon"),
    powercap_roots: Iterable[Path] = (Path("/sys/class/powercap"), Path("/sys/devices/virtual/powercap")),
    read_text: ReadText = read_text_cpu_sysfs,
    sensor_label: SensorLabel | None = None,
    read_text_sudo: ReadText = read_text_cpu_sysfs,
    *,
    privileged_helper_enabled: bool = False,
) -> tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    sources, unreadable_sources = discover_cpu_power_candidates(
        hwmon_root=hwmon_root,
        powercap_roots=powercap_roots,
        read_text=read_text,
        sensor_label=sensor_label,
    )
    add_privileged_cpu_power_sources(
        sources,
        unreadable_sources,
        read_text_sudo,
        privileged_helper_enabled=privileged_helper_enabled,
    )
    return select_cpu_power_source(sources), unreadable_sources


def discover_cpu_clock_source(
    cpu_root: Path = Path("/sys/devices/system/cpu"),
    proc_cpuinfo_path: Path = Path("/proc/cpuinfo"),
    read_text: ReadText = read_text_cpu_sysfs,
) -> Optional[Dict[str, Any]]:
    cpufreq_paths = [
        str(path)
        for path in sorted(cpu_root.glob("cpu[0-9]*/cpufreq/scaling_cur_freq"))
        if read_text(path) is not None
    ]
    if cpufreq_paths:
        return {"kind": "cpufreq", "paths": cpufreq_paths, "path": cpufreq_paths[0], "label": "scaling_cur_freq"}

    if proc_cpuinfo_path.exists():
        cpuinfo = read_text(proc_cpuinfo_path)
        if cpuinfo is not None and "cpu MHz" in cpuinfo:
            return {"kind": "proc_cpuinfo", "path": str(proc_cpuinfo_path), "label": "cpu MHz"}

    return None


def performance_tiers(values: Dict[str, int]) -> List[tuple[float, List[str]]]:
    tiers: List[tuple[float, List[str]]] = []
    for key, value in sorted(values.items(), key=lambda item: item[1], reverse=True):
        placed = False
        for index, (tier_value, keys) in enumerate(tiers):
            if tier_value > 0 and abs(float(value) - tier_value) / tier_value <= 0.03:
                keys.append(key)
                new_value = statistics.mean([values[k] for k in keys])
                tiers[index] = (float(new_value), keys)
                placed = True
                break
        if not placed:
            tiers.append((float(value), [key]))
    return tiers


def parse_explicit_core_type(value: str) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    if text in {"p", "pcore", "p-core", "performance", "big", "core"}:
        return "P"
    if text in {"e", "ecore", "e-core", "efficient", "efficiency", "little", "atom", "compact", "c-core", "ccore"}:
        return "E"
    if text.isdigit():
        # Kernel/platform-specific numeric encodings are not standardized enough
        # to trust without labels. Leave them for capacity/perf fallback.
        return ""
    if any(token in text for token in ("efficient", "efficiency", "little", "atom", "compact")):
        return "E"
    if any(token in text for token in ("performance", "big")):
        return "P"
    return ""


def parse_cpu_list(value: str) -> List[int]:
    cpus: List[int] = []
    for part in str(value or "").split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start_text, end_text = part.split("-", 1)
            try:
                start = int(start_text)
                end = int(end_text)
            except Exception:
                continue
            cpus.extend(range(min(start, end), max(start, end) + 1))
            continue
        try:
            cpus.append(int(part))
        except Exception:
            continue
    return sorted(set(cpus))


def cpu_index_from_name(name: str) -> int:
    try:
        return int(str(name).removeprefix("cpu"))
    except Exception:
        return -1


def cpu_package_ids_from_topology(cpu_core_topology: Dict[int, Dict[str, Any]]) -> List[int]:
    package_ids = {
        int(info["package_id"])
        for info in cpu_core_topology.values()
        if info.get("package_id") is not None
    }
    return sorted(package_ids)


def cpu_package_id_from_temp_source(source: Dict[str, Any]) -> Optional[int]:
    text = f"{source.get('label', '')} {source.get('path', '')}".lower()
    patterns = (
        r"package\s*id\s*(\d+)",
        r"\bpackage[-_\s]*(\d+)\b",
        r"\bpkg[-_\s]*(\d+)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            try:
                return int(match.group(1))
            except Exception:
                return None
    return None


def assign_cpu_package_temp_sources(
    cpu_temp_sources: Iterable[Dict[str, Any]],
    cpu_core_topology: Dict[int, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    package_ids = cpu_package_ids_from_topology(cpu_core_topology)
    if not package_ids:
        return []

    source_list = list(cpu_temp_sources)
    selected: Dict[int, Dict[str, Any]] = {}
    for source in source_list:
        package_id = cpu_package_id_from_temp_source(source)
        if package_id is None or package_id not in package_ids or package_id in selected:
            continue
        selected[package_id] = dict(source)

    if len(selected) < len(package_ids):
        assigned_paths = {str(source.get("path") or "") for source in selected.values()}
        implicit_candidates = [
            source
            for source in source_list
            if str(source.get("path") or "") not in assigned_paths
            and str(source.get("kind") or "") == "hwmon"
            and score_cpu_temp_source(str(source.get("hwmon_name") or ""), str(source.get("label") or "")) >= 100
        ]
        implicit_candidates.sort(key=lambda source: str(source.get("path") or ""))
        missing_package_ids = [package_id for package_id in package_ids if package_id not in selected]
        if len(implicit_candidates) >= len(missing_package_ids):
            for package_id, source in zip(missing_package_ids, implicit_candidates):
                selected[package_id] = dict(source)

    package_sources: List[Dict[str, Any]] = []
    for package_id in package_ids:
        source = selected.get(package_id)
        if not source:
            continue
        source["package_id"] = package_id
        source["key"] = f"cpu_package_{package_id}_temp_c"
        source["label"] = source.get("label") or f"package-{package_id}"
        package_sources.append(source)
    return package_sources


def cpu_package_id_from_power_source(source: Dict[str, Any]) -> Optional[str]:
    text = f"{source.get('label') or ''} {source.get('path') or ''}".lower()
    match = re.search(r"(?:package|pkg)[-_ ]?(\d+)", text)
    if match:
        return match.group(1)
    match = re.search(r"amdi0097:(\d+)", text)
    return str(int(match.group(1))) if match else None


def aggregate_cpu_package_power_source(sources: Iterable[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    package_sources: List[Dict[str, Any]] = []
    seen_package_ids: set[str] = set()
    for source in sources:
        if source.get("kind") not in {"hwmon", "rapl", "sudo_rapl"}:
            continue
        package_id = cpu_package_id_from_power_source(source)
        if package_id is None or package_id in seen_package_ids:
            continue
        seen_package_ids.add(package_id)
        source_with_package = dict(source)
        source_with_package["package_id"] = package_id
        source_with_package["key"] = f"cpu_package_{package_id}_power_w"
        package_sources.append(source_with_package)
    if len(package_sources) <= 1:
        return None
    package_sources.sort(key=lambda item: str(item.get("label") or item.get("path") or ""))
    labels = [
        str(source.get("label") or Path(str(source.get("path") or "")).parent.name)
        for source in package_sources
    ]
    return {
        "kind": "aggregate_power" if any(source.get("kind") == "hwmon" for source in package_sources) else "aggregate_energy",
        "path": ", ".join(str(source.get("path") or "") for source in package_sources),
        "label": f"sum({', '.join(labels)})",
        "score": max(int(source.get("score") or 0) for source in package_sources) + 10,
        "sources": package_sources,
        "package_count": len(package_sources),
    }


def classify_physical_cpu_cores(
    physical: Dict[str, Dict[str, Any]],
) -> tuple[Dict[str, str], Dict[str, str], Dict[str, Optional[int]]]:
    explicit: Dict[str, str] = {}
    for key, physical_entry in physical.items():
        entry = physical_entry.get("entry", {})
        parsed = parse_explicit_core_type(str(entry.get("explicit_core_type", "") or ""))
        if parsed:
            explicit[key] = parsed
    if explicit and len(explicit) == len(physical):
        return (
            explicit,
            {key: "explicit_core_type" for key in physical},
            {key: None for key in physical},
        )

    for field, source in (
        ("cpu_capacity", "cpu_capacity"),
        ("cppc_highest_perf", "acpi_cppc_highest_perf"),
        ("cpuinfo_max_freq_khz", "cpuinfo_max_freq"),
        ("base_frequency_khz", "base_frequency"),
    ):
        values: Dict[str, int] = {}
        for key, physical_entry in physical.items():
            value = physical_entry.get("entry", {}).get(field)
            if isinstance(value, int) and value > 0:
                values[key] = value
        if len(values) < 2:
            continue
        max_value = max(values.values())
        min_value = min(values.values())
        if max_value <= 0 or min_value / max_value >= 0.85:
            continue
        tiers = performance_tiers(values)
        if len(tiers) < 2 or len(tiers) > 3:
            continue
        if tiers[1][0] / tiers[0][0] >= 0.85:
            continue
        top_tier_keys = set(tiers[0][1])
        classes = {key: ("P" if key in top_tier_keys else "E") for key in values}
        for key in physical:
            classes.setdefault(key, "P")
        return (
            classes,
            {key: source if key in values else "homogeneous_fallback" for key in physical},
            {key: values.get(key) for key in physical},
        )

    return (
        {key: "P" for key in physical},
        {key: "homogeneous_fallback" for key in physical},
        {key: None for key in physical},
    )


def discover_cpu_core_topology(
    cpu_root: Path = Path("/sys/devices/system/cpu"),
    read_text: ReadText = read_text_cpu_sysfs,
) -> Dict[int, Dict[str, Any]]:
    cpu_dirs = sorted(
        [path for path in cpu_root.glob("cpu[0-9]*") if path.is_dir()],
        key=lambda path: cpu_index_from_name(path.name),
    )
    logical: Dict[int, Dict[str, Any]] = {}
    physical: Dict[str, Dict[str, Any]] = {}
    for cpu_dir in cpu_dirs:
        cpu_index = cpu_index_from_name(cpu_dir.name)
        if cpu_index < 0:
            continue
        topology_dir = cpu_dir / "topology"
        package_id = read_cpu_sysfs_int(topology_dir / "physical_package_id", read_text)
        core_id = read_cpu_sysfs_int(topology_dir / "core_id", read_text)
        siblings_text = read_text(topology_dir / "thread_siblings_list") or ""
        siblings = parse_cpu_list(siblings_text)
        physical_key = (
            f"package{package_id}:core{core_id}"
            if package_id is not None and core_id is not None
            else f"cpu{min(siblings) if siblings else cpu_index}"
        )
        entry = {
            "cpu_index": cpu_index,
            "package_id": package_id,
            "core_id": core_id,
            "physical_core_key": physical_key,
            "physical_core_index": 0,
            "thread_siblings": siblings,
            "thread_siblings_list": siblings_text,
            "cpu_capacity": read_cpu_sysfs_int(cpu_dir / "cpu_capacity", read_text),
            "cppc_highest_perf": read_cpu_sysfs_int(cpu_dir / "acpi_cppc" / "highest_perf", read_text),
            "cppc_nominal_perf": read_cpu_sysfs_int(cpu_dir / "acpi_cppc" / "nominal_perf", read_text),
            "cpuinfo_max_freq_khz": read_cpu_sysfs_int(cpu_dir / "cpufreq" / "cpuinfo_max_freq", read_text),
            "base_frequency_khz": read_cpu_sysfs_int(cpu_dir / "cpufreq" / "base_frequency", read_text),
            "explicit_core_type": (
                read_text(cpu_dir / "core_type")
                or read_text(topology_dir / "core_type")
                or ""
            ),
            "core_type": "P",
            "core_class": "P-Core",
            "classification_source": "homogeneous_fallback",
            "classification_value": None,
        }
        logical[cpu_index] = entry
        current = physical.get(physical_key)
        if current is None or cpu_index < int(current.get("representative_cpu", cpu_index)):
            physical[physical_key] = {"representative_cpu": cpu_index, "entry": entry}

    if not logical:
        return {}

    ordered_physical_keys = sorted(
        physical.keys(),
        key=lambda key: int(physical[key].get("representative_cpu", 0)),
    )
    physical_index_by_key = {key: index for index, key in enumerate(ordered_physical_keys)}
    for entry in logical.values():
        entry["physical_core_index"] = physical_index_by_key.get(str(entry.get("physical_core_key", "")), 0)

    class_by_physical, source_by_physical, value_by_physical = classify_physical_cpu_cores(physical)
    for entry in logical.values():
        key = str(entry.get("physical_core_key", ""))
        core_type = class_by_physical.get(key, "P")
        entry["core_type"] = core_type
        entry["core_class"] = "E-Core" if core_type == "E" else "P-Core"
        entry["classification_source"] = source_by_physical.get(key, "homogeneous_fallback")
        entry["classification_value"] = value_by_physical.get(key)
    return logical


def cpu_core_classification_summary_from_topology(cpu_core_topology: Dict[int, Dict[str, Any]]) -> Dict[str, Any]:
    entries = list(cpu_core_topology.values())
    physical_keys = {
        str(entry.get("physical_core_key", ""))
        for entry in entries
        if str(entry.get("physical_core_key", ""))
    }
    physical_type: Dict[str, str] = {}
    source_counts: Dict[str, int] = {}
    for entry in entries:
        key = str(entry.get("physical_core_key", ""))
        if key:
            physical_type.setdefault(key, str(entry.get("core_type", "P") or "P"))
        source = str(entry.get("classification_source", "homogeneous_fallback") or "homogeneous_fallback")
        source_counts[source] = source_counts.get(source, 0) + 1
    p_physical = sum(1 for value in physical_type.values() if value == "P")
    e_physical = sum(1 for value in physical_type.values() if value == "E")
    return {
        "logical_count": len(entries),
        "physical_count": len(physical_keys),
        "p_core_count": p_physical,
        "e_core_count": e_physical,
        "has_p_cores": p_physical > 0,
        "has_e_cores": e_physical > 0,
        "sources": source_counts,
    }


def discover_cpu_core_clock_sources(
    cpu_core_topology: Dict[int, Dict[str, Any]],
    cpu_root: Path = Path("/sys/devices/system/cpu"),
    read_text: ReadText = read_text_cpu_sysfs,
) -> List[Dict[str, Any]]:
    sources: List[Dict[str, Any]] = []
    for path in sorted(cpu_root.glob("cpu[0-9]*/cpufreq/scaling_cur_freq")):
        raw = read_text(path)
        if raw is None:
            continue
        cpu_name = path.parts[-3]
        cpu_index = cpu_index_from_name(cpu_name)
        if cpu_index < 0:
            continue
        topology = cpu_core_topology.get(cpu_index, {})
        sources.append(
            {
                "kind": "cpufreq_core",
                "path": str(path),
                "label": f"{topology.get('core_class', 'P-Core')} {cpu_index} Clock",
                "key": f"cpu_core_{cpu_index}_clock_mhz",
                "cpu_index": cpu_index,
                "core_type": topology.get("core_type", "P"),
                "core_class": topology.get("core_class", "P-Core"),
                "physical_core_index": topology.get("physical_core_index"),
                "physical_core_key": topology.get("physical_core_key", ""),
                "thread_siblings": topology.get("thread_siblings", []),
                "classification_source": topology.get("classification_source", "homogeneous_fallback"),
                "classification_value": topology.get("classification_value"),
            }
        )
    return sources
