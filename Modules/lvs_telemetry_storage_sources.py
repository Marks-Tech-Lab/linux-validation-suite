from __future__ import annotations

"""Storage temperature telemetry source discovery helpers."""

import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from Modules.lvs_storage_inventory import clean_storage_value, read_text_sysfs
from Modules.lvs_pcie_link import pcie_link_info_for_path
from Modules.lvs_telemetry_cpu import read_temperature_path


ReadText = Callable[[Path], Optional[str]]
ReadTemperature = Callable[[Path], Optional[float]]


def sensor_label(data_path: Path, read_text: ReadText = read_text_sysfs) -> str:
    label_path = data_path.with_name(data_path.name.replace("_input", "_label").replace("_average", "_label"))
    return read_text(label_path) or ""


def storage_block_devices(
    block_root: Path = Path("/sys/block"),
    read_text: ReadText = read_text_sysfs,
) -> Dict[str, Dict[str, str]]:
    devices: Dict[str, Dict[str, str]] = {}
    for block_dir in sorted(block_root.glob("*")):
        name = block_dir.name
        if name.startswith(("loop", "ram", "zram", "dm-", "md")):
            continue
        size_text = read_text(block_dir / "size") or "0"
        try:
            if int(size_text) <= 0:
                continue
        except Exception:
            continue
        model = clean_storage_value(read_text(block_dir / "device" / "model"))
        vendor = clean_storage_value(read_text(block_dir / "device" / "vendor"))
        display = " ".join(part for part in (vendor, model) if part).strip() or model or name
        try:
            resolved = str(block_dir.resolve())
        except Exception:
            resolved = str(block_dir)
        devices[name] = {
            "name": name,
            "model": display,
            "resolved": resolved.lower(),
            "pcie_link": pcie_link_info_for_path(block_dir / "device", read_text),
        }
    return devices


def looks_like_storage_hwmon(hwmon_name: str, hwmon_dir: Path) -> bool:
    name = hwmon_name.lower()
    if name in {"nvme", "drivetemp", "scttemp"}:
        return True
    try:
        resolved = str(hwmon_dir.resolve()).lower()
    except Exception:
        resolved = str(hwmon_dir).lower()
    return "/nvme/" in resolved or "/ata" in resolved or "/host" in resolved


def storage_block_for_hwmon(hwmon_dir: Path, block_devices: Dict[str, Dict[str, str]]) -> str:
    try:
        resolved = str(hwmon_dir.resolve()).lower()
    except Exception:
        resolved = str(hwmon_dir).lower()
    for block_name, info in block_devices.items():
        block_resolved = str(info.get("resolved", ""))
        if block_name in resolved or (block_resolved and block_resolved in resolved):
            return block_name
        if block_name.startswith("nvme"):
            controller = re.match(r"(nvme\d+)", block_name)
            if controller and f"/{controller.group(1)}/" in resolved:
                return block_name
    return ""


def score_storage_temp_source(hwmon_name: str, label: str, path: Path) -> int:
    text = f"{hwmon_name} {label} {path.name}".lower()
    score = 0
    if "composite" in text:
        score += 100
    if "drive" in text:
        score += 90
    if "temp1" in path.name:
        score += 80
    if "sensor" in text:
        score += 20
    return score


def storage_secondary_sensor_index(label: str, path: Path, fallback_index: int) -> int:
    match = re.search(r"sensor\s*(\d+)", str(label or ""), re.IGNORECASE)
    if match:
        try:
            return int(match.group(1))
        except Exception:
            pass
    match = re.match(r"temp(\d+)_input", path.name)
    if match:
        try:
            return max(1, int(match.group(1)) - 1)
        except Exception:
            pass
    return fallback_index


def discover_storage_temp_sources(
    hwmon_root: Path = Path("/sys/class/hwmon"),
    block_root: Path = Path("/sys/block"),
    read_text: ReadText = read_text_sysfs,
) -> List[Dict[str, Any]]:
    block_devices = storage_block_devices(block_root, read_text)
    candidates_by_block: Dict[str, List[Dict[str, Any]]] = {}
    unmapped_candidates: List[Dict[str, Any]] = []

    for hwmon_dir in sorted(hwmon_root.glob("hwmon*")):
        hwmon_name = (read_text(hwmon_dir / "name") or "").strip()
        if not looks_like_storage_hwmon(hwmon_name, hwmon_dir):
            continue
        block_name = storage_block_for_hwmon(hwmon_dir, block_devices)
        for path in sorted(hwmon_dir.glob("temp*_input")):
            if read_text(path) is None:
                continue
            label = sensor_label(path, read_text) or path.name
            source = {
                "kind": "storage_temp",
                "path": str(path),
                "label": label,
                "hwmon_name": hwmon_name,
                "block_name": block_name or "",
                "device_name": block_devices.get(block_name or "", {}).get("model", "") if block_name else "",
                "pcie_link": block_devices.get(block_name or "", {}).get("pcie_link", {}) if block_name else {},
                "score": score_storage_temp_source(hwmon_name, label, path),
            }
            if block_name:
                candidates_by_block.setdefault(block_name, []).append(source)
            else:
                unmapped_candidates.append(source)

    sources: List[Dict[str, Any]] = []
    for index, block_name in enumerate(sorted(candidates_by_block)):
        candidates = sorted(
            candidates_by_block[block_name],
            key=lambda item: (int(item.get("score", 0) or 0), str(item.get("path") or "")),
            reverse=True,
        )
        best = candidates[0]
        device_name = best.get("device_name") or block_devices.get(block_name, {}).get("model") or block_name
        best["label"] = f"{device_name} {best.get('label') or 'temperature'}".strip()
        best["key"] = f"storage_drive_{index}_temp_c"
        best["drive_index"] = index
        sources.append(best)
        secondary_index = 1
        for source in sorted(candidates[1:], key=lambda item: str(item.get("path") or "")):
            source_label = str(source.get("label") or "Sensor")
            sensor_index = storage_secondary_sensor_index(source_label, Path(str(source.get("path") or "")), secondary_index)
            source["kind"] = "storage_temp_secondary"
            source["label"] = f"{device_name} {source_label}".strip()
            source["key"] = f"storage_drive_{index}_sensor_{sensor_index}_temp_c"
            source["drive_index"] = index
            source["sensor_index"] = sensor_index
            source["primary_key"] = f"storage_drive_{index}_temp_c"
            sources.append(source)
            secondary_index += 1

    offset = len(candidates_by_block)
    for index, source in enumerate(sorted(unmapped_candidates, key=lambda item: str(item.get("path", "")))):
        source["key"] = f"storage_drive_{offset + index}_temp_c"
        source["drive_index"] = offset + index
        source["label"] = f"{source.get('hwmon_name') or 'storage'} {source.get('label') or 'temperature'}".strip()
        sources.append(source)

    return sources


def read_storage_temps(
    storage_temp_sources: List[Dict[str, Any]],
    read_temperature: ReadTemperature = read_temperature_path,
) -> Dict[str, Optional[float]]:
    values: Dict[str, Optional[float]] = {}
    for source in storage_temp_sources:
        value = read_temperature(Path(str(source.get("path") or "")))
        if value is not None:
            values[str(source["key"])] = value
    return values
