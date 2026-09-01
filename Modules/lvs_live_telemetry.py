"""Immutable, UI-neutral snapshots derived from an existing telemetry sample."""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Any, Iterable, Mapping, Optional, Sequence


@dataclass(frozen=True)
class LiveTelemetryValue:
    key: str
    label: str
    value: float
    unit: str
    provider: str = ""
    semantic: str = ""


@dataclass(frozen=True)
class LiveCpuCore:
    index: int
    label: str
    core_class: str
    utilization_percent: Optional[float] = None
    clock_mhz: Optional[float] = None


@dataclass(frozen=True)
class LiveGpuTelemetry:
    index: int
    utilization_percent: Optional[float] = None
    temperature_c: Optional[float] = None
    hotspot_c: Optional[float] = None
    power_w: Optional[float] = None
    clock_mhz: Optional[float] = None
    vram_used_gib: Optional[float] = None
    vram_total_gib: Optional[float] = None
    vram_used_percent: Optional[float] = None
    vram_busy_percent: Optional[float] = None
    vram_clock_mhz: Optional[float] = None
    vram_temperature_c: Optional[float] = None
    fan_duty_percent: Optional[float] = None
    fan_rpm: tuple[LiveTelemetryValue, ...] = ()
    vddgfx_v: Optional[float] = None
    vddnb_v: Optional[float] = None


@dataclass(frozen=True)
class LiveTelemetrySnapshot:
    state: str
    sequence: int
    sampled_monotonic: float
    interval_seconds: float
    cpu_utilization_percent: Optional[float] = None
    cpu_temperature_c: Optional[float] = None
    cpu_power_w: Optional[float] = None
    cpu_clock_mhz: Optional[float] = None
    cpu_vcore_v: Optional[float] = None
    cpu_packages: tuple[LiveTelemetryValue, ...] = ()
    cpu_cores: tuple[LiveCpuCore, ...] = ()
    gpus: tuple[LiveGpuTelemetry, ...] = ()
    memory_used_gib: Optional[float] = None
    memory_total_gib: Optional[float] = None
    dimm_temperatures: tuple[LiveTelemetryValue, ...] = ()
    storage_temperatures: tuple[LiveTelemetryValue, ...] = ()
    cooling: tuple[LiveTelemetryValue, ...] = ()
    voltages: tuple[LiveTelemetryValue, ...] = ()
    platform: tuple[LiveTelemetryValue, ...] = ()
    bmc: tuple[LiveTelemetryValue, ...] = ()
    bmc_state: str = "unavailable"


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _first(values: Mapping[str, Any], keys: Iterable[str]) -> Optional[float]:
    for key in keys:
        value = _number(values.get(key))
        if value is not None:
            return value
    return None


def _source_value(values: Mapping[str, Any], source: Mapping[str, Any]) -> Optional[float]:
    return _number(values.get(str(source.get("key") or "")))


def _friendly_label(source: Mapping[str, Any], fallback: str) -> str:
    return str(
        source.get("normalized_label")
        or source.get("label")
        or source.get("raw_label")
        or fallback
    ).strip()


def _live_value(
    values: Mapping[str, Any], source: Mapping[str, Any], fallback: str, default_unit: str = ""
) -> Optional[LiveTelemetryValue]:
    value = _source_value(values, source)
    if value is None:
        return None
    return LiveTelemetryValue(
        key=str(source.get("key") or ""),
        label=_friendly_label(source, fallback),
        value=value,
        unit=str(source.get("unit") or default_unit),
        provider=str(source.get("provider") or source.get("hwmon_name") or ""),
        semantic=str(source.get("semantic_classification") or source.get("metric") or ""),
    )


def _values_from_sources(
    values: Mapping[str, Any], sources: Sequence[Mapping[str, Any]], fallback: str,
    default_unit: str = "",
) -> tuple[LiveTelemetryValue, ...]:
    rows = [_live_value(values, source, fallback, default_unit) for source in sources]
    return tuple(row for row in rows if row is not None)


def _core_class(topology: Mapping[str, Any]) -> str:
    if str(topology.get("classification_source") or "") == "homogeneous_fallback":
        return "unknown"
    core_type = str(topology.get("core_type") or "").upper()
    if core_type == "P":
        return "performance"
    if core_type == "E":
        return "efficiency"
    return "unknown"


def _core_label(index: int, topology: Mapping[str, Any]) -> str:
    classification = _core_class(topology)
    if classification == "performance" and str(topology.get("classification_source")) != "homogeneous_fallback":
        return f"P-Core {index}"
    if classification == "efficiency":
        return f"E-Core {index}"
    return f"Core {index}"


def _gpu_rows(collector: Any, values: Mapping[str, Any]) -> tuple[LiveGpuTelemetry, ...]:
    by_gpu: dict[int, dict[str, Any]] = {}
    fan_rows: dict[int, list[LiveTelemetryValue]] = {}
    for source in getattr(collector, "_gpu_sources", ()):
        index = int(source.get("gpu_index", 0))
        metric = str(source.get("metric") or "")
        value = _source_value(values, source)
        if value is None:
            continue
        if metric == "fan_rpm":
            row = _live_value(values, source, f"GPU {index + 1} fan")
            if row is not None:
                fan_rows.setdefault(index, []).append(row)
            continue
        field = {
            "busy_percent": "utilization_percent",
            "temp_core_c": "temperature_c",
            "temp_hotspot_c": "hotspot_c",
            "power_w": "power_w",
            "clock_mhz": "clock_mhz",
            "vram_used_gb": "vram_used_gib",
            "memory_busy_percent": "vram_busy_percent",
            "memory_clock_mhz": "vram_clock_mhz",
            "temp_memory_c": "vram_temperature_c",
            "fan_percent": "fan_duty_percent",
            "vddgfx_v": "vddgfx_v",
            "vddnb_v": "vddnb_v",
        }.get(metric)
        if field is not None:
            by_gpu.setdefault(index, {}).setdefault(field, value)
    indexes = sorted(set(by_gpu) | set(fan_rows))
    rows = []
    for index in indexes:
        data = dict(by_gpu.get(index, {}))
        data["vram_total_gib"] = _first(values, (
            f"gpu_{index}_vram_total_gib", f"gpu_{index}_memory_total_gib",
        ))
        data["vram_used_percent"] = _first(values, (
            f"gpu_{index}_vram_used_percent", f"gpu_{index}_memory_used_percent",
        ))
        if data["vram_used_percent"] is None and data.get("vram_used_gib") is not None and data["vram_total_gib"]:
            data["vram_used_percent"] = float(data["vram_used_gib"]) / float(data["vram_total_gib"]) * 100.0
        rows.append(LiveGpuTelemetry(index=index, fan_rpm=tuple(fan_rows.get(index, ())), **data))
    return tuple(rows)


def build_live_telemetry_snapshot(collector: Any, sample: Any, *, state: str = "active") -> LiveTelemetrySnapshot:
    """Build a snapshot without performing any hardware or provider reads."""
    values = dict(getattr(sample, "values", {}) or {})
    topology = getattr(collector, "_cpu_core_topology", {}) or {}
    clocks = {int(source.get("cpu_index", -1)): str(source.get("key") or "") for source in getattr(collector, "_cpu_core_clock_sources", ())}
    utilizations = {int(source.get("cpu_index", -1)): str(source.get("key") or "") for source in getattr(collector, "_cpu_core_utilization_sources", ())}
    cores = []
    for index in sorted(set(topology) | set(clocks) | set(utilizations)):
        info = topology.get(index, {})
        clock = _number(values.get(clocks.get(index, "")))
        utilization = _number(values.get(utilizations.get(index, "")))
        if clock is None and utilization is None:
            continue
        cores.append(LiveCpuCore(index, _core_label(index, info), _core_class(info), utilization, clock))

    package_rows = []
    package_metrics = {
        "temp_c": ("temperature", "celsius"),
        "power_w": ("power", "watts"),
        "clock_mhz": ("clock", "mhz"),
    }
    for key in sorted(values):
        match = re.fullmatch(r"cpu_package_(\d+)_(temp_c|power_w|clock_mhz)", key)
        value = _number(values.get(key))
        if match is None or value is None:
            continue
        package_index, suffix = int(match.group(1)), match.group(2)
        metric_label, unit = package_metrics[suffix]
        package_rows.append(LiveTelemetryValue(
            key=key,
            label=f"CPU package {package_index + 1} {metric_label}",
            value=value,
            unit=unit,
            provider="common_telemetry",
            semantic=suffix,
        ))

    direct_sources = list(getattr(collector, "_direct_hwmon_sources", ()) or ())
    direct_values = _values_from_sources(values, direct_sources, "Platform sensor")
    cooling = tuple(row for row in direct_values if row.unit.lower() == "rpm")
    voltages = tuple(row for row in direct_values if row.unit.lower() in {"v", "volt", "volts"})
    cpu_vcore = next((row.value for row in direct_values if row.semantic == "cpu_vcore"), None)
    device_values = _values_from_sources(
        values, getattr(collector, "_device_temp_sources", ()), "Platform temperature", "celsius"
    )
    platform = tuple(
        row for row in direct_values
        if row.unit.lower() not in {"rpm", "v", "volt", "volts"}
    ) + device_values

    bmc_sources = []
    provider = getattr(collector, "_bmc_provider", None)
    if provider is not None:
        try:
            bmc_sources = list(provider.source_catalog())
        except Exception:
            bmc_sources = []
    bmc = _values_from_sources(values, bmc_sources, "BMC sensor")
    bmc_state = "unavailable"
    if provider is not None and bool(getattr(provider, "available", False)):
        bmc_state = "waiting"
        if bmc_sources:
            try:
                bmc_state = "ok" if provider.latest_snapshot(float(getattr(sample, "timestamp", 0.0))) else "stale"
            except Exception:
                bmc_state = "stale"

    dimms = _values_from_sources(
        values, getattr(collector, "_memory_temp_sources", ()), "DIMM temperature", "celsius"
    )
    storage = _values_from_sources(
        values, getattr(collector, "_storage_temp_sources", ()), "Storage temperature", "celsius"
    )
    memory_used = _first(values, ("memory_used_gib", "memory_used_gb"))
    memory_total = _number(getattr(collector, "memory_total_gib", None))
    return LiveTelemetrySnapshot(
        state=state,
        sequence=len(getattr(collector, "samples", ())),
        sampled_monotonic=float(getattr(sample, "timestamp", 0.0)),
        interval_seconds=float(getattr(collector, "interval_seconds", 2.0)),
        cpu_utilization_percent=_number(values.get("cpu_utilization_percent")),
        cpu_temperature_c=_number(values.get("cpu_temp_c")),
        cpu_power_w=_number(values.get("cpu_power_w")),
        cpu_clock_mhz=_number(values.get("cpu_clock_mhz")),
        cpu_vcore_v=cpu_vcore,
        cpu_packages=tuple(package_rows),
        cpu_cores=tuple(cores),
        gpus=_gpu_rows(collector, values),
        memory_used_gib=memory_used,
        memory_total_gib=memory_total,
        dimm_temperatures=dimms,
        storage_temperatures=storage,
        cooling=cooling,
        voltages=voltages,
        platform=platform,
        bmc=bmc,
        bmc_state=bmc_state,
    )
