#!/usr/bin/env python3
"""Pure memory telemetry classification and source discovery helpers."""

from __future__ import annotations

import re
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from Modules.lvs_telemetry_sampling import parse_optional_float


ReadText = Callable[[Path], Optional[str]]
CommandExists = Callable[[str], bool]
CommandEnv = Callable[[], Dict[str, str]]
ReadTemperature = Callable[[Path], Optional[float]]
ReadIpmiTemperatures = Callable[[], Dict[str, Optional[float]]]


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


def looks_like_ipmi_memory_temperature(label: str) -> bool:
    text = str(label or "").lower()
    if not text:
        return False
    if not (
        any(token in text for token in ("dimm", "ddr", "dram", "memory"))
        or re.search(r"(^|[^a-z0-9])mem([_ -]?[a-z0-9]|$)", text)
    ):
        return False
    exclude_tokens = (
        "gpu",
        "cpu",
        "vrm",
        "vram",
        "nvme",
        "m.2",
        "ssd",
        "hdd",
        "psu",
        "pch",
        "chipset",
        "lan",
        "nic",
        "bmc",
        "system",
        "ambient",
        "inlet",
        "outlet",
        "fan",
    )
    return not any(token in text for token in exclude_tokens)


def spd5118_memory_temp_sources(
    hwmon_root: Path = Path("/sys/class/hwmon"),
    read_text: ReadText | None = None,
    sensor_index: int = 0,
) -> List[Dict[str, Any]]:
    if read_text is None:
        read_text = read_text_memory_sysfs
    sources: List[Dict[str, Any]] = []
    for hwmon_dir in sorted(hwmon_root.glob("hwmon*")):
        name = read_text(hwmon_dir / "name")
        if (name or "").lower() != "spd5118":
            continue
        for path in sorted(hwmon_dir.glob("temp*_input")):
            if read_text(path) is None:
                continue
            sources.append(
                {
                    "kind": "memory_temp",
                    "path": str(path),
                    "label": f"DIMM {sensor_index} SPD Hub",
                    "key": f"memory_module_{sensor_index}_temp_c",
                    "module_index": sensor_index,
                }
            )
            sensor_index += 1
    return sources


def ipmi_memory_temp_sources(
    temperatures: Dict[str, Optional[float]],
    sensor_index: int = 0,
) -> List[Dict[str, Any]]:
    sources: List[Dict[str, Any]] = []
    for label in sorted(temperatures.keys(), key=ipmi_memory_sensor_sort_key):
        value = temperatures.get(label)
        if value is None:
            continue
        if not looks_like_ipmi_memory_temperature(label):
            continue
        sources.append(
            {
                "kind": "ipmi_memory_temp",
                "path": "ipmitool sensor",
                "label": label,
                "sensor_id": label,
                "key": f"memory_module_{sensor_index}_temp_c",
                "module_index": sensor_index,
            }
        )
        sensor_index += 1
    return sources


def parse_ipmi_sensor_temperatures(text: str) -> Dict[str, Optional[float]]:
    if not text:
        return {}
    values: Dict[str, Optional[float]] = {}
    for line in text.splitlines():
        if "|" not in line:
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) < 3:
            continue
        label = parts[0]
        unit = parts[2].lower()
        if "degree" not in unit and unit not in {"c", "deg c"}:
            continue
        value = parse_optional_float(parts[1], 150.0)
        if value is None:
            continue
        values[label] = round(value, 2)
    return values


def run_ipmitool_sensor_text(
    command_exists: CommandExists,
    command_env: CommandEnv,
    *,
    privileged_helper_enabled: bool = False,
) -> str:
    if not command_exists("ipmitool"):
        return ""
    commands = [["ipmitool", "sensor"]]
    if privileged_helper_enabled and os.geteuid() != 0 and shutil.which("sudo") is not None:
        commands.append(["sudo", "-n", "ipmitool", "sensor"])
    for command in commands:
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=8,
                env=command_env(),
            )
        except Exception:
            continue
        if completed.returncode == 0 and (completed.stdout or "").strip():
            return completed.stdout
    return ""


def read_ipmi_sensor_temperatures(
    command_exists: CommandExists,
    command_env: CommandEnv,
    *,
    privileged_helper_enabled: bool = False,
) -> Dict[str, Optional[float]]:
    return parse_ipmi_sensor_temperatures(
        run_ipmitool_sensor_text(
            command_exists,
            command_env,
            privileged_helper_enabled=privileged_helper_enabled,
        )
    )


def cached_ipmi_sensor_temperatures(
    cache: Optional[Tuple[float, Dict[str, Optional[float]]]],
    now: float,
    read_temperatures: ReadIpmiTemperatures,
    *,
    force: bool = False,
    ttl_seconds: float = 5.0,
) -> tuple[Dict[str, Optional[float]], Tuple[float, Dict[str, Optional[float]]]]:
    if not force and cache is not None:
        timestamp, values = cache
        if now - timestamp < ttl_seconds:
            return dict(values), cache
    values = read_temperatures()
    new_cache = (now, dict(values))
    return values, new_cache


def read_memory_temps(
    memory_temp_sources: List[Dict[str, Any]],
    read_temperature: ReadTemperature,
    read_ipmi_temperatures_cached: ReadIpmiTemperatures,
) -> Dict[str, Optional[float]]:
    values: Dict[str, Optional[float]] = {}
    ipmi_snapshot: Optional[Dict[str, Optional[float]]] = None
    for source in memory_temp_sources:
        if source.get("kind") == "ipmi_memory_temp":
            if ipmi_snapshot is None:
                ipmi_snapshot = read_ipmi_temperatures_cached()
            value = ipmi_snapshot.get(str(source.get("sensor_id") or ""))
        else:
            value = read_temperature(Path(str(source.get("path") or "")))
        if value is not None:
            values[str(source["key"])] = value
    return values


def discover_memory_temp_sources_with_ipmi(
    read_text: ReadText,
    command_exists: CommandExists,
    local_ipmi_available: Callable[[], bool],
    read_ipmi_temperatures_cached: ReadIpmiTemperatures,
) -> List[Dict[str, Any]]:
    sources = discover_memory_temp_sources(read_text=read_text)
    if sources:
        return sources
    if command_exists("ipmitool") and local_ipmi_available():
        return discover_memory_temp_sources(
            read_text=read_text,
            ipmi_temperatures=read_ipmi_temperatures_cached(),
        )
    return []


def local_ipmi_device_available(
    dev_root: Path = Path("/dev"),
    ipmi_sys_root: Path = Path("/sys/class/ipmi"),
) -> bool:
    if list(dev_root.glob("ipmi*")):
        return True
    return bool(list(ipmi_sys_root.glob("ipmi*")))


def discover_memory_temp_sources(
    hwmon_root: Path = Path("/sys/class/hwmon"),
    read_text: ReadText | None = None,
    ipmi_temperatures: Dict[str, Optional[float]] | None = None,
) -> List[Dict[str, Any]]:
    sources = spd5118_memory_temp_sources(hwmon_root, read_text)
    if sources:
        return sources
    return ipmi_memory_temp_sources(ipmi_temperatures or {}, sensor_index=len(sources))
