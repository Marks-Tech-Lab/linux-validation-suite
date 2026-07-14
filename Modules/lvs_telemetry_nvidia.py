#!/usr/bin/env python3
"""NVIDIA nvidia-smi telemetry discovery and sampling helpers."""

from __future__ import annotations

import subprocess
from typing import Any, Callable, Dict, List, Optional

from .lvs_gpu_identity import normalize_pci_slot
from .lvs_telemetry_sampling import parse_mb_to_gb, parse_optional_float


CommandExists = Callable[[str], bool]
CommandEnv = Callable[[], Dict[str, str]]


NVIDIA_CLOCK_EVENT_REASON_FIELDS = [
    ("throttle_idle", "clocks_event_reasons.gpu_idle", "idle"),
    ("throttle_applications_clocks", "clocks_event_reasons.applications_clocks_setting", "applications clocks setting"),
    ("throttle_sw_power_cap", "clocks_event_reasons.sw_power_cap", "software power cap"),
    ("throttle_hw_slowdown", "clocks_event_reasons.hw_slowdown", "hardware slowdown"),
    ("throttle_hw_thermal", "clocks_event_reasons.hw_thermal_slowdown", "hardware thermal slowdown"),
    ("throttle_hw_power_brake", "clocks_event_reasons.hw_power_brake_slowdown", "hardware power brake slowdown"),
    ("throttle_sync_boost", "clocks_event_reasons.sync_boost", "sync boost"),
    ("throttle_sw_thermal", "clocks_event_reasons.sw_thermal_slowdown", "software thermal slowdown"),
]


def run_nvidia_smi_query(fields: List[str], command_env: CommandEnv) -> Optional[subprocess.CompletedProcess[str]]:
    cmd = [
        "nvidia-smi",
        f"--query-gpu={','.join(fields)}",
        "--format=csv,noheader,nounits",
    ]
    try:
        return subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
            env=command_env(),
        )
    except Exception:
        return None


def parse_nvidia_active_flag(raw: str) -> Optional[float]:
    normalized = str(raw or "").strip().lower()
    if not normalized or normalized in {"n/a", "[not supported]", "not supported", "unsupported"}:
        return None
    if normalized == "active":
        return 1.0
    if normalized == "not active":
        return 0.0
    return None


def supported_nvidia_clock_event_reason_fields(command_env: CommandEnv) -> List[Dict[str, str]]:
    fields = ["pci.bus_id"] + [field for _metric, field, _label in NVIDIA_CLOCK_EVENT_REASON_FIELDS]
    completed = run_nvidia_smi_query(fields, command_env)
    if completed is None or completed.returncode != 0:
        return []
    first_line = next((line for line in (completed.stdout or "").splitlines() if line.strip()), "")
    parts = [item.strip() for item in first_line.split(",")]
    if len(parts) < len(fields):
        return []
    return [
        {"metric": metric, "query_field": query_field, "label": label}
        for metric, query_field, label in NVIDIA_CLOCK_EVENT_REASON_FIELDS
    ]


def discover_nvidia_smi_gpus(
    command_exists: CommandExists,
    command_env: CommandEnv,
) -> List[Dict[str, Any]]:
    if not command_exists("nvidia-smi"):
        return []
    completed = run_nvidia_smi_query(
        ["index", "pci.bus_id", "uuid", "name", "driver_version", "memory.total"],
        command_env,
    )
    if completed is None or completed.returncode != 0:
        return []
    event_reason_fields = supported_nvidia_clock_event_reason_fields(command_env)
    gpus: List[Dict[str, Any]] = []
    for line in (completed.stdout or "").splitlines():
        parts = [item.strip() for item in line.split(",")]
        if len(parts) < 6:
            continue
        try:
            memory_mb = float(parts[5])
        except Exception:
            memory_mb = 0.0
        gpus.append(
            {
                "index": parts[0],
                "slot": normalize_pci_slot(parts[1]),
                "uuid": parts[2],
                "name": parts[3],
                "driver": parts[4],
                "memory_mb": memory_mb,
                "clock_event_reason_fields": event_reason_fields,
            }
        )
    return gpus


def read_nvidia_smi_gpu_metrics(
    gpu_sources: List[Dict[str, Any]],
    command_env: CommandEnv,
) -> Dict[str, Dict[str, Optional[float]]]:
    if not any(source["kind"] == "nvidia_smi" for source in gpu_sources):
        return {}
    query_fields = [
        "pci.bus_id",
        "temperature.gpu",
        "power.draw",
        "clocks.current.graphics",
        "clocks.current.memory",
        "utilization.gpu",
        "utilization.memory",
        "memory.used",
        "fan.speed",
        "power.draw.average",
    ]
    include_memory_temperature = any(
        source.get("metric") == "temp_memory_c"
        for source in gpu_sources
        if source.get("kind") == "nvidia_smi"
    )
    if include_memory_temperature:
        query_fields.append("temperature.memory")
    completed = run_nvidia_smi_query(query_fields, command_env)
    has_average_power = True
    has_memory_temperature = include_memory_temperature
    has_fan_speed = True
    if (completed is None or completed.returncode != 0) and has_memory_temperature:
        query_fields = [field for field in query_fields if field != "temperature.memory"]
        completed = run_nvidia_smi_query(query_fields, command_env)
        has_memory_temperature = False
    if completed is None or completed.returncode != 0:
        query_fields = [field for field in query_fields if field != "fan.speed"]
        completed = run_nvidia_smi_query(query_fields, command_env)
        has_fan_speed = False
    if completed is None or completed.returncode != 0:
        query_fields = [field for field in query_fields if field != "power.draw.average"]
        completed = run_nvidia_smi_query(query_fields, command_env)
        has_average_power = False
    if completed is None or completed.returncode != 0:
        return {}
    snapshot: Dict[str, Dict[str, Optional[float]]] = {}
    for line in (completed.stdout or "").splitlines():
        parts = [item.strip() for item in line.split(",")]
        if len(parts) < 8:
            continue
        row = {field: parts[index] for index, field in enumerate(query_fields) if index < len(parts)}
        slot = normalize_pci_slot(row.get("pci.bus_id", "")).lower()
        power_instant = parse_optional_float(row.get("power.draw", ""), upper_bound=2000.0)
        power_average = (
            parse_optional_float(row.get("power.draw.average", ""), upper_bound=2000.0)
            if has_average_power
            else None
        )
        snapshot[slot] = {
            "temp_core_c": parse_optional_float(row.get("temperature.gpu", ""), upper_bound=150.0),
            "temp_memory_c": (
                parse_optional_float(row.get("temperature.memory", ""), upper_bound=150.0)
                if has_memory_temperature
                else None
            ),
            "power_w": power_instant if power_instant is not None else power_average,
            "clock_mhz": parse_optional_float(row.get("clocks.current.graphics", ""), upper_bound=10000.0),
            "memory_clock_mhz": parse_optional_float(row.get("clocks.current.memory", ""), upper_bound=20000.0),
            "busy_percent": parse_optional_float(row.get("utilization.gpu", ""), upper_bound=100.0),
            "memory_busy_percent": parse_optional_float(row.get("utilization.memory", ""), upper_bound=100.0),
            "vram_used_gb": parse_mb_to_gb(row.get("memory.used", "")),
            "fan_percent": (
                parse_optional_float(row.get("fan.speed", ""), upper_bound=100.0)
                if has_fan_speed
                else None
            ),
        }
    requested_event_metrics = {
        str(source.get("metric") or "")
        for source in gpu_sources
        if source.get("kind") == "nvidia_smi" and str(source.get("metric") or "").startswith("throttle_")
    }
    if requested_event_metrics:
        event_fields = [
            (metric, query_field)
            for metric, query_field, _label in NVIDIA_CLOCK_EVENT_REASON_FIELDS
            if metric in requested_event_metrics
        ]
        completed_events = run_nvidia_smi_query(["pci.bus_id"] + [field for _metric, field in event_fields], command_env)
        if completed_events is not None and completed_events.returncode == 0:
            for line in (completed_events.stdout or "").splitlines():
                parts = [item.strip() for item in line.split(",")]
                if len(parts) < len(event_fields) + 1:
                    continue
                slot = normalize_pci_slot(parts[0]).lower()
                values = snapshot.setdefault(slot, {})
                for index, (metric, _query_field) in enumerate(event_fields, start=1):
                    flag = parse_nvidia_active_flag(parts[index])
                    if flag is not None:
                        values[metric] = flag
    return snapshot
