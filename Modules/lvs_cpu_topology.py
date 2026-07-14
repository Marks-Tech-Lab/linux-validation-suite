#!/usr/bin/env python3
"""CPU topology summary helpers for system inventory/export."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional


ReadText = Callable[[Path], Optional[str]]


def parse_proc_cpuinfo_models(cpuinfo_text: str) -> Dict[int, str]:
    """Return processor index -> model name from /proc/cpuinfo text."""
    models: Dict[int, str] = {}
    current_index: Optional[int] = None
    current_model = ""
    for raw_line in str(cpuinfo_text or "").splitlines():
        line = raw_line.strip()
        if not line:
            if current_index is not None and current_model:
                models[current_index] = current_model
            current_index = None
            current_model = ""
            continue
        if ":" not in line:
            continue
        key, value = [part.strip() for part in line.split(":", 1)]
        lowered = key.lower()
        if lowered == "processor":
            try:
                current_index = int(value)
            except Exception:
                current_index = None
        elif lowered == "model name":
            current_model = value
    if current_index is not None and current_model:
        models[current_index] = current_model
    return models


def _cpu_index_from_path(path: Path) -> int:
    try:
        return int(path.name.replace("cpu", ""))
    except Exception:
        return -1


def _safe_int(text: Optional[str]) -> Optional[int]:
    try:
        return int(str(text or "").strip(), 0)
    except Exception:
        return None


def _compact_cpu_list(values: Iterable[int]) -> str:
    ordered = sorted({int(value) for value in values})
    if not ordered:
        return ""
    ranges: List[str] = []
    start = prev = ordered[0]
    for value in ordered[1:]:
        if value == prev + 1:
            prev = value
            continue
        ranges.append(f"{start}-{prev}" if start != prev else str(start))
        start = prev = value
    ranges.append(f"{start}-{prev}" if start != prev else str(start))
    return ",".join(ranges)


def _summary_name(package_records: List[Dict[str, Any]], fallback_name: str) -> str:
    names = [str(record.get("Name") or "").strip() for record in package_records]
    names = [name for name in names if name]
    if not names:
        return fallback_name
    unique_names = []
    for name in names:
        if name not in unique_names:
            unique_names.append(name)
    if len(names) > 1 and len(unique_names) == 1:
        return f"{len(names)}x {unique_names[0]}"
    if len(names) > 1:
        return " | ".join(
            f"CPU{index}: {name or fallback_name or 'Unknown CPU'}"
            for index, name in enumerate(names)
        )
    return names[0]


def _cpu_package_device(record: Dict[str, Any]) -> Dict[str, Any]:
    package_id = record.get("PackageId")
    name = str(record.get("Name") or "Unknown CPU")
    return {
        "DeviceId": f"cpu_package_{package_id}",
        "PackageId": package_id,
        "Name": name,
        "DisplayName": f"CPU {package_id}: {name}",
        "LogicalCpuCount": record.get("LogicalCpuCount", 0),
        "LogicalCpuRange": record.get("LogicalCpuRange", ""),
        "PhysicalCoreCount": record.get("PhysicalCoreCount", 0),
    }


def cpu_package_devices_from_topology(topology: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return additive per-package CPU device records from a topology block."""
    packages = topology.get("Packages") if isinstance(topology, dict) else []
    if not isinstance(packages, list):
        return []
    return [_cpu_package_device(record) for record in packages if isinstance(record, dict)]


def collect_cpu_topology_info(
    *,
    cpu_root: Path = Path("/sys/devices/system/cpu"),
    cpuinfo_text: str = "",
    read_text: Optional[ReadText] = None,
    fallback_name: str = "",
) -> Dict[str, Any]:
    """Build a socket/package-aware topology summary from Linux sysfs."""
    reader = read_text or (lambda path: path.read_text(encoding="utf-8", errors="ignore").strip())
    cpu_models = parse_proc_cpuinfo_models(cpuinfo_text)
    cpu_dirs = sorted(
        [path for path in cpu_root.glob("cpu[0-9]*") if path.is_dir()],
        key=_cpu_index_from_path,
    )
    packages: Dict[int, Dict[str, Any]] = {}
    all_physical_keys: set[str] = set()
    logical_count = 0

    for cpu_dir in cpu_dirs:
        cpu_index = _cpu_index_from_path(cpu_dir)
        if cpu_index < 0:
            continue
        topology_dir = cpu_dir / "topology"
        package_id = _safe_int(reader(topology_dir / "physical_package_id"))
        core_id = _safe_int(reader(topology_dir / "core_id"))
        if package_id is None:
            package_id = 0
        logical_count += 1
        model_name = cpu_models.get(cpu_index) or fallback_name or "Unknown CPU"
        record = packages.setdefault(
            package_id,
            {
                "PackageId": package_id,
                "Name": model_name,
                "LogicalCpuIndexes": [],
                "PhysicalCoreKeys": set(),
            },
        )
        if not record.get("Name") or record.get("Name") == "Unknown CPU":
            record["Name"] = model_name
        record["LogicalCpuIndexes"].append(cpu_index)
        physical_key = f"package{package_id}:core{core_id}" if core_id is not None else f"package{package_id}:cpu{cpu_index}"
        record["PhysicalCoreKeys"].add(physical_key)
        all_physical_keys.add(physical_key)

    package_records: List[Dict[str, Any]] = []
    for package_id in sorted(packages):
        record = packages[package_id]
        logical_indexes = sorted(record.get("LogicalCpuIndexes", []))
        physical_keys = sorted(record.get("PhysicalCoreKeys", []))
        package_records.append(
            {
                "PackageId": package_id,
                "Name": record.get("Name") or fallback_name or "Unknown CPU",
                "LogicalCpuCount": len(logical_indexes),
                "LogicalCpuRange": _compact_cpu_list(logical_indexes),
                "PhysicalCoreCount": len(physical_keys),
            }
        )

    name_summary = _summary_name(package_records, fallback_name or "Unknown CPU")
    package_devices = [_cpu_package_device(record) for record in package_records]
    package_names = [str(record.get("Name") or "Unknown CPU") for record in package_records]
    package_count = len(package_records) if package_records else (1 if fallback_name else 0)
    aggregate = {
        "Name": name_summary,
        "BaseName": fallback_name or name_summary or "Unknown CPU",
        "PackageCount": package_count,
        "LogicalCpuCount": logical_count,
        "PhysicalCoreCount": len(all_physical_keys),
    }
    return {
        "NameSummary": name_summary,
        "Aggregate": aggregate,
        "PackageCount": package_count,
        "LogicalCpuCount": logical_count,
        "PhysicalCoreCount": len(all_physical_keys),
        "Packages": package_records,
        "PackageNames": package_names,
        "PackageDevices": package_devices,
    }
