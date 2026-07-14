#!/usr/bin/env python3
"""Pure telemetry-source formatting and selection helpers."""

from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, List, Optional

from .lvs_pcie_link import trusted_pcie_link_for_slot


TelemetrySource = Dict[str, Any]


def source_thresholds(source: TelemetrySource, default_warn: float, default_fail: float) -> Dict[str, Any]:
    warn = source.get("warn_threshold_c")
    fail = source.get("fail_threshold_c")
    threshold_source = source.get("threshold_source") or "suite_default"
    if warn is None and fail is None:
        warn = default_warn
        fail = default_fail
    elif warn is None and fail is not None:
        warn = max(0.0, round(float(fail) - 5.0, 2))
    elif fail is None and warn is not None:
        fail = max(float(warn), default_fail)
    return {
        "warn_c": round(float(warn), 2) if warn is not None else None,
        "fail_c": round(float(fail), 2) if fail is not None else None,
        "source": threshold_source,
        "derived_from_hardware": threshold_source != "suite_default",
    }


def sources_for_metric(sources: Iterable[TelemetrySource], metric: str) -> List[TelemetrySource]:
    return [source for source in sources if source.get("metric") == metric]


def preferred_metric_source(
    sources: Iterable[TelemetrySource],
    metric: str,
    *,
    prefer_hardware_thresholds: bool = False,
) -> Optional[TelemetrySource]:
    candidates = sources_for_metric(sources, metric)
    if not candidates:
        return None

    def score(source: TelemetrySource) -> tuple[int, int, int]:
        threshold_source = str(source.get("threshold_source") or "")
        derived = 1 if threshold_source and threshold_source != "suite_default" else 0
        has_fail = 1 if source.get("fail_threshold_c") is not None else 0
        has_warn = 1 if source.get("warn_threshold_c") is not None else 0
        base = derived * 100 + has_fail * 10 + has_warn
        if prefer_hardware_thresholds:
            base += derived * 1000
        return (base, -int(source.get("gpu_index", 0) or 0), -len(str(source.get("label", ""))))

    return max(candidates, key=score)


def telemetry_source_description(source: Optional[TelemetrySource]) -> str:
    if not source:
        return "not found"
    label = source.get("label", "")
    kind = source.get("kind", "")
    path = source.get("path", "")
    if label:
        return f"{kind}:{label} ({path})"
    return f"{kind}:{path}"


def telemetry_source_access_mode(source: Optional[TelemetrySource]) -> str:
    if not source:
        return "unavailable"
    kind = str(source.get("kind") or "")
    if kind.startswith("sudo_"):
        return "sudo"
    return "direct"


def _source_and_components(source: Optional[TelemetrySource]) -> List[TelemetrySource]:
    if not source:
        return []
    sources = [source]
    components = source.get("sources")
    if isinstance(components, list):
        sources.extend(item for item in components if isinstance(item, dict))
    return sources


def build_telemetry_privilege_summary(
    *,
    privileged_helper_enabled: bool,
    process_is_root: bool,
    sudo_available: bool,
    telemetry_sources: Iterable[TelemetrySource],
    unreadable_sources: Iterable[TelemetrySource] = (),
) -> Dict[str, Any]:
    source_list = list(telemetry_sources)
    unreadable_source_list = list(unreadable_sources)
    sudo_sources = [
        source
        for source in source_list
        if telemetry_source_access_mode(source) == "sudo"
    ]
    sudo_source_kinds = sorted({str(source.get("kind") or "") for source in sudo_sources if source.get("kind")})
    if sudo_sources:
        source_mode = "sudo_telemetry"
    elif process_is_root:
        source_mode = "root_process"
    elif privileged_helper_enabled and sudo_available:
        source_mode = "privileged_helper_available"
    else:
        source_mode = "unprivileged"
    return {
        "source_mode": source_mode,
        "privileged_helper_enabled": bool(privileged_helper_enabled),
        "process_is_root": bool(process_is_root),
        "sudo_available": bool(sudo_available),
        "sudo_sources_used": bool(sudo_sources),
        "sudo_source_kinds": sudo_source_kinds,
        "sudo_source_count": len(sudo_sources),
        "unreadable_privileged_candidate_count": len(unreadable_source_list),
    }


def telemetry_source_record(
    field_name: str,
    source: Optional[TelemetrySource],
    *,
    category: str,
    metric: str = "",
) -> Dict[str, Any]:
    """Return a stable source-map row for one raw telemetry field."""
    record: Dict[str, Any] = {
        "field": field_name,
        "category": category,
        "metric": metric or field_name,
        "source": telemetry_source_description(source),
    }
    if not source:
        record["available"] = False
        return record

    record.update(
        {
            "available": True,
            "kind": source.get("kind", ""),
            "label": source.get("label", ""),
            "path": source.get("path", ""),
            "access_mode": telemetry_source_access_mode(source),
        }
    )
    for key in (
        "gpu_index",
        "card",
        "slot",
        "vendor",
        "driver",
        "query_field",
        "module_index",
        "drive_index",
        "sensor_index",
        "block_name",
        "device_name",
        "sensor_id",
        "package_count",
        "package_id",
        "evidence_only",
        "nic_index",
        "wifi_index",
        "board_sensor_index",
        "pcie_link",
    ):
        if source.get(key) not in (None, ""):
            record[key] = source.get(key)
    if source.get("sources"):
        record["component_sources"] = [
            telemetry_source_description(item)
            for item in source.get("sources", [])
            if isinstance(item, dict)
        ]
    return record


def build_telemetry_source_map(
    *,
    cpu_temp_source: Optional[TelemetrySource],
    cpu_package_temp_sources: Iterable[TelemetrySource],
    cpu_power_source: Optional[TelemetrySource],
    cpu_clock_source: Optional[TelemetrySource],
    cpu_core_clock_sources: Iterable[TelemetrySource],
    memory_temp_sources: Iterable[TelemetrySource],
    storage_temp_sources: Iterable[TelemetrySource],
    gpu_sources: Iterable[TelemetrySource],
    gpu_cards: Iterable[Dict[str, Any]],
    device_temp_sources: Iterable[TelemetrySource] = (),
    privileged_helper_enabled: bool = False,
    process_is_root: bool = False,
    sudo_available: bool = False,
    cpu_power_unreadable_sources: Iterable[TelemetrySource] = (),
) -> Dict[str, Any]:
    """Build a machine-readable map for raw telemetry CSV fields.

    The raw CSV uses compact field names such as ``gpu_2_power_w``. During
    multi-GPU failures, those compact names need an explicit slot/card/source
    mapping so logs can be interpreted without guessing which device vanished.
    """
    cpu_package_temp_source_list = list(cpu_package_temp_sources)
    cpu_core_clock_source_list = list(cpu_core_clock_sources)
    memory_temp_source_list = list(memory_temp_sources)
    storage_temp_source_list = list(storage_temp_sources)
    device_temp_source_list = list(device_temp_sources)
    gpu_source_list = list(gpu_sources)
    cpu_power_unreadable_source_list = list(cpu_power_unreadable_sources)

    fields: Dict[str, Dict[str, Any]] = {
        "timestamp": {
            "field": "timestamp",
            "category": "time",
            "metric": "monotonic_seconds",
            "source": "time.monotonic()",
            "available": True,
        },
        "cpu_temp_c": telemetry_source_record("cpu_temp_c", cpu_temp_source, category="cpu", metric="temperature_c"),
        "cpu_power_w": telemetry_source_record("cpu_power_w", cpu_power_source, category="cpu", metric="power_w"),
        "cpu_clock_mhz": telemetry_source_record("cpu_clock_mhz", cpu_clock_source, category="cpu", metric="clock_mhz"),
        "memory_used_gb": {
            "field": "memory_used_gb",
            "category": "memory",
            "metric": "used_gb",
            "source": "/proc/meminfo",
            "available": True,
            "kind": "procfs",
            "path": "/proc/meminfo",
        },
    }
    for source in cpu_package_temp_source_list:
        field = str(source.get("key") or "")
        if field:
            fields[field] = telemetry_source_record(field, source, category="cpu_package", metric="temperature_c")

    if cpu_power_source and cpu_power_source.get("sources"):
        for source in cpu_power_source.get("sources", []):
            if not isinstance(source, dict):
                continue
            field = str(source.get("key") or "")
            if field:
                fields[field] = telemetry_source_record(field, source, category="cpu_package", metric="power_w")

    for source in cpu_core_clock_source_list:
        field = str(source.get("key") or "")
        if field:
            fields[field] = telemetry_source_record(field, source, category="cpu_core", metric="clock_mhz")

    for source in memory_temp_source_list:
        field = str(source.get("key") or "")
        if field:
            fields[field] = telemetry_source_record(field, source, category="memory_module", metric="temperature_c")

    for source in storage_temp_source_list:
        field = str(source.get("key") or "")
        if field:
            fields[field] = telemetry_source_record(field, source, category="storage", metric="temperature_c")

    for source in device_temp_source_list:
        field = str(source.get("key") or "")
        if field:
            fields[field] = telemetry_source_record(field, source, category="device", metric="temperature_c")

    for source in gpu_source_list:
        field = str(source.get("key") or "")
        if field:
            fields[field] = telemetry_source_record(
                field,
                source,
                category="gpu",
                metric=str(source.get("metric") or field),
            )

    gpu_index_map: List[Dict[str, Any]] = []
    for card in gpu_cards:
        entry = {
            "gpu_index": int(card.get("gpu_index", 0) or 0),
            "card": card.get("card", ""),
            "slot": card.get("slot", ""),
            "vendor": card.get("vendor", ""),
            "driver": card.get("driver", ""),
        }
        pcie_link = trusted_pcie_link_for_slot(card.get("pcie_link", {}), card.get("slot", ""))
        if pcie_link:
            entry["pcie_link"] = pcie_link
        gpu_index_map.append(entry)

    source_list: List[TelemetrySource] = []
    for source in (
        [cpu_temp_source, cpu_power_source, cpu_clock_source]
        + cpu_package_temp_source_list
        + cpu_core_clock_source_list
        + memory_temp_source_list
        + storage_temp_source_list
        + device_temp_source_list
        + gpu_source_list
    ):
        source_list.extend(_source_and_components(source))

    return {
        "version": 1,
        "purpose": "Maps raw_telemetry.csv field names to hardware telemetry sources.",
        "telemetry_privilege": build_telemetry_privilege_summary(
            privileged_helper_enabled=privileged_helper_enabled,
            process_is_root=process_is_root,
            sudo_available=sudo_available,
            telemetry_sources=source_list,
            unreadable_sources=cpu_power_unreadable_source_list,
        ),
        "fields": {key: fields[key] for key in sorted(fields)},
        "gpu_index_map": sorted(gpu_index_map, key=lambda item: int(item.get("gpu_index", 0) or 0)),
        "storage_link_map": sorted(
            [
                {
                    "drive_index": int(source.get("drive_index", 0) or 0),
                    "block_name": source.get("block_name", ""),
                    "device_name": source.get("device_name", ""),
                    "pcie_link": source.get("pcie_link", {}),
                }
                for source in storage_temp_source_list
                if source.get("kind") == "storage_temp" and source.get("pcie_link")
            ],
            key=lambda item: int(item.get("drive_index", 0) or 0),
        ),
    }


def unreadable_source_description(sources: Iterable[TelemetrySource]) -> str:
    source_list = list(sources)
    if not source_list:
        return "not found"
    ordered = sorted(
        source_list,
        key=lambda source: int(source.get("score", 0) or 0),
        reverse=True,
    )
    return f"present but unreadable: {telemetry_source_description(ordered[0])}"


def metric_gpu_count(sources: Iterable[TelemetrySource], metric: str) -> int:
    return len(
        {
            int(source.get("gpu_index", 0) or 0)
            for source in sources
            if source.get("metric") == metric
        }
    )


def build_gpu_telemetry_matrix(
    cards: Iterable[Dict[str, Any]],
    sources: Iterable[TelemetrySource],
) -> List[Dict[str, Any]]:
    metric_order = [
        ("temp_core_c", "temperature"),
        ("temp_memory_c", "memory_temperature"),
        ("power_w", "power"),
        ("clock_mhz", "clock"),
        ("memory_clock_mhz", "memory_clock"),
        ("busy_percent", "busy"),
        ("memory_busy_percent", "memory_busy"),
        ("vram_used_gb", "vram_used"),
        ("fan_percent", "fan"),
        ("vddgfx_v", "vddgfx_voltage"),
        ("vddnb_v", "vddnb_voltage"),
        ("throttle_idle", "throttle_idle"),
        ("throttle_applications_clocks", "throttle_applications_clocks"),
        ("throttle_sw_power_cap", "throttle_sw_power_cap"),
        ("throttle_hw_slowdown", "throttle_hw_slowdown"),
        ("throttle_hw_thermal", "throttle_hw_thermal"),
        ("throttle_hw_power_brake", "throttle_hw_power_brake"),
        ("throttle_sync_boost", "throttle_sync_boost"),
        ("throttle_sw_thermal", "throttle_sw_thermal"),
    ]

    def empty_metrics() -> Dict[str, Dict[str, Any]]:
        return {
            label: {"available": False, "source": "not found"}
            for _, label in metric_order
        }

    per_gpu: Dict[int, Dict[str, Any]] = {}
    for card in cards:
        try:
            gpu_index = int(card.get("gpu_index", 0) or 0)
        except Exception:
            gpu_index = 0
        per_gpu[gpu_index] = {
            "gpu_index": gpu_index,
            "card": card.get("card", ""),
            "slot": card.get("slot", ""),
            "vendor": card.get("vendor", ""),
            "driver": card.get("driver", ""),
            "metrics": empty_metrics(),
        }

    for source in sources:
        try:
            gpu_index = int(source.get("gpu_index", 0) or 0)
        except Exception:
            gpu_index = 0
        info = per_gpu.setdefault(
            gpu_index,
            {
                "gpu_index": gpu_index,
                "card": "",
                "slot": "",
                "vendor": "",
                "driver": "",
                "metrics": empty_metrics(),
            },
        )
        metric = str(source.get("metric") or "")
        label = next((label for metric_key, label in metric_order if metric_key == metric), "")
        if not label:
            continue
        existing = info["metrics"].get(label, {})
        if existing.get("available"):
            continue
        info["metrics"][label] = {
            "available": True,
            "source": telemetry_source_description(source),
            "kind": source.get("kind", ""),
            "metric": metric,
        }

    return [per_gpu[index] for index in sorted(per_gpu)]


def build_telemetry_capability_summary(
    *,
    cpu_temp_source: Optional[TelemetrySource],
    cpu_power_source: Optional[TelemetrySource],
    cpu_power_unreadable_sources: Iterable[TelemetrySource],
    cpu_clock_source: Optional[TelemetrySource],
    cpu_core_clock_sources: Iterable[TelemetrySource],
    cpu_core_classification: Dict[str, Any],
    memory_temp_sources: Iterable[TelemetrySource],
    storage_temp_sources: Iterable[TelemetrySource],
    gpu_sources: Iterable[TelemetrySource],
    gpu_temp_source: Optional[TelemetrySource],
    describe_source: Callable[[Optional[TelemetrySource]], str],
    describe_unreadable_sources: Callable[[Iterable[TelemetrySource]], str],
    metric_thresholds: Callable[[str], Optional[Dict[str, Any]]],
    gpu_metric_threshold_summary: Callable[[str], List[Dict[str, Any]]],
    gpu_telemetry_matrix: Callable[[], List[Dict[str, Any]]],
    memory_used_available: bool,
    device_temp_sources: Iterable[TelemetrySource] = (),
    privileged_helper_enabled: bool = False,
    process_is_root: bool = False,
    sudo_available: bool = False,
) -> Dict[str, Dict[str, Any]]:
    """Build the diagnostics/export telemetry capability payload.

    Hardware discovery remains in the collector. This helper only assembles the
    discovered source records into the stable shape consumed by diagnostics,
    dependency reports, manifests, and frontends.
    """
    cpu_core_clock_source_list = list(cpu_core_clock_sources)
    memory_temp_source_list = list(memory_temp_sources)
    storage_temp_source_list = list(storage_temp_sources)
    device_temp_source_list = list(device_temp_sources)
    primary_storage_temp_source_list = [
        source for source in storage_temp_source_list
        if source.get("kind") != "storage_temp_secondary"
    ]
    secondary_storage_temp_source_list = [
        source for source in storage_temp_source_list
        if source.get("kind") == "storage_temp_secondary"
    ]
    nic_temp_source_list = [
        source for source in device_temp_source_list
        if source.get("kind") == "nic_temp"
    ]
    board_temp_source_list = [
        source for source in device_temp_source_list
        if source.get("kind") == "board_temp"
    ]
    wifi_temp_source_list = [
        source for source in device_temp_source_list
        if source.get("kind") == "wifi_temp"
    ]
    gpu_source_list = list(gpu_sources)
    cpu_power_unreadable_source_list = list(cpu_power_unreadable_sources)

    def first_source_for_metric(metric: str) -> Optional[TelemetrySource]:
        return next((source for source in gpu_source_list if source.get("metric") == metric), None)

    capabilities: Dict[str, Dict[str, Any]] = {
        "cpu_temp_c": {
            "available": cpu_temp_source is not None,
            "source": describe_source(cpu_temp_source) if cpu_temp_source else "not found",
            "thresholds": metric_thresholds("cpu_temp_c"),
        },
        "cpu_power_w": {
            "available": cpu_power_source is not None,
            "source": (
                describe_source(cpu_power_source)
                if cpu_power_source
                else describe_unreadable_sources(cpu_power_unreadable_source_list)
            ),
            "permission_issue": cpu_power_source is None and bool(cpu_power_unreadable_source_list),
        },
        "cpu_clock_mhz": {
            "available": cpu_clock_source is not None,
            "source": describe_source(cpu_clock_source) if cpu_clock_source else "not found",
        },
        "cpu_core_clock_mhz": {
            "available": bool(cpu_core_clock_source_list),
            "source": describe_source(cpu_core_clock_source_list[0]) if cpu_core_clock_source_list else "not found",
            "count": len(cpu_core_clock_source_list),
            "classification": cpu_core_classification,
        },
        "memory_temp_c": {
            "available": bool(memory_temp_source_list),
            "source": describe_source(memory_temp_source_list[0]) if memory_temp_source_list else "not found",
            "count": len(memory_temp_source_list),
        },
        "storage_temp_c": {
            "available": bool(primary_storage_temp_source_list),
            "source": describe_source(primary_storage_temp_source_list[0]) if primary_storage_temp_source_list else "not found",
            "count": len(primary_storage_temp_source_list),
        },
        "storage_secondary_temp_c": {
            "available": bool(secondary_storage_temp_source_list),
            "source": describe_source(secondary_storage_temp_source_list[0]) if secondary_storage_temp_source_list else "not found",
            "count": len(secondary_storage_temp_source_list),
        },
        "nic_temp_c": {
            "available": bool(nic_temp_source_list),
            "source": describe_source(nic_temp_source_list[0]) if nic_temp_source_list else "not found",
            "count": len(nic_temp_source_list),
            "evidence_only": True,
        },
        "board_temp_c": {
            "available": bool(board_temp_source_list),
            "source": describe_source(board_temp_source_list[0]) if board_temp_source_list else "not found",
            "count": len(board_temp_source_list),
            "evidence_only": True,
        },
        "wifi_temp_c": {
            "available": bool(wifi_temp_source_list),
            "source": describe_source(wifi_temp_source_list[0]) if wifi_temp_source_list else "not found",
            "count": len(wifi_temp_source_list),
            "evidence_only": True,
        },
        "gpu_temp_c": {
            "available": any(source.get("metric") == "temp_core_c" for source in gpu_source_list),
            "source": describe_source(gpu_temp_source) if gpu_temp_source else "not found",
            "count": metric_gpu_count(gpu_source_list, "temp_core_c"),
            "thresholds": metric_thresholds(str(gpu_temp_source.get("key") or "")) if gpu_temp_source else None,
            "thresholds_by_gpu": gpu_metric_threshold_summary("temp_core_c"),
        },
        "gpu_memory_temp_c": {
            "available": any(source.get("metric") == "temp_memory_c" for source in gpu_source_list),
            "source": describe_source(first_source_for_metric("temp_memory_c")),
            "count": metric_gpu_count(gpu_source_list, "temp_memory_c"),
            "thresholds_by_gpu": gpu_metric_threshold_summary("temp_memory_c"),
        },
        "gpu_power_w": {
            "available": any(source.get("metric") == "power_w" for source in gpu_source_list),
            "source": describe_source(first_source_for_metric("power_w")),
            "count": metric_gpu_count(gpu_source_list, "power_w"),
        },
        "gpu_clock_mhz": {
            "available": any(source.get("metric") == "clock_mhz" for source in gpu_source_list),
            "source": describe_source(first_source_for_metric("clock_mhz")),
            "count": metric_gpu_count(gpu_source_list, "clock_mhz"),
        },
        "gpu_memory_clock_mhz": {
            "available": any(source.get("metric") == "memory_clock_mhz" for source in gpu_source_list),
            "source": describe_source(first_source_for_metric("memory_clock_mhz")),
            "count": metric_gpu_count(gpu_source_list, "memory_clock_mhz"),
        },
        "gpu_busy_percent": {
            "available": any(source.get("metric") == "busy_percent" for source in gpu_source_list),
            "source": describe_source(first_source_for_metric("busy_percent")),
            "count": metric_gpu_count(gpu_source_list, "busy_percent"),
        },
        "gpu_memory_busy_percent": {
            "available": any(source.get("metric") == "memory_busy_percent" for source in gpu_source_list),
            "source": describe_source(first_source_for_metric("memory_busy_percent")),
            "count": metric_gpu_count(gpu_source_list, "memory_busy_percent"),
        },
        "gpu_vram_used_gb": {
            "available": any(source.get("metric") == "vram_used_gb" for source in gpu_source_list),
            "source": describe_source(first_source_for_metric("vram_used_gb")),
            "count": metric_gpu_count(gpu_source_list, "vram_used_gb"),
        },
        "gpu_fan_percent": {
            "available": any(source.get("metric") == "fan_percent" for source in gpu_source_list),
            "source": describe_source(first_source_for_metric("fan_percent")),
            "count": metric_gpu_count(gpu_source_list, "fan_percent"),
        },
        "gpu_vddgfx_v": {
            "available": any(source.get("metric") == "vddgfx_v" for source in gpu_source_list),
            "source": describe_source(first_source_for_metric("vddgfx_v")),
            "count": metric_gpu_count(gpu_source_list, "vddgfx_v"),
        },
        "gpu_vddnb_v": {
            "available": any(source.get("metric") == "vddnb_v" for source in gpu_source_list),
            "source": describe_source(first_source_for_metric("vddnb_v")),
            "count": metric_gpu_count(gpu_source_list, "vddnb_v"),
        },
        "gpu_throttle_idle": {
            "available": any(source.get("metric") == "throttle_idle" for source in gpu_source_list),
            "source": describe_source(first_source_for_metric("throttle_idle")),
            "count": metric_gpu_count(gpu_source_list, "throttle_idle"),
            "evidence_only": True,
        },
        "gpu_throttle_applications_clocks": {
            "available": any(source.get("metric") == "throttle_applications_clocks" for source in gpu_source_list),
            "source": describe_source(first_source_for_metric("throttle_applications_clocks")),
            "count": metric_gpu_count(gpu_source_list, "throttle_applications_clocks"),
            "evidence_only": True,
        },
        "gpu_throttle_sw_power_cap": {
            "available": any(source.get("metric") == "throttle_sw_power_cap" for source in gpu_source_list),
            "source": describe_source(first_source_for_metric("throttle_sw_power_cap")),
            "count": metric_gpu_count(gpu_source_list, "throttle_sw_power_cap"),
            "evidence_only": True,
        },
        "gpu_throttle_hw_slowdown": {
            "available": any(source.get("metric") == "throttle_hw_slowdown" for source in gpu_source_list),
            "source": describe_source(first_source_for_metric("throttle_hw_slowdown")),
            "count": metric_gpu_count(gpu_source_list, "throttle_hw_slowdown"),
            "evidence_only": True,
        },
        "gpu_throttle_hw_thermal": {
            "available": any(source.get("metric") == "throttle_hw_thermal" for source in gpu_source_list),
            "source": describe_source(first_source_for_metric("throttle_hw_thermal")),
            "count": metric_gpu_count(gpu_source_list, "throttle_hw_thermal"),
            "evidence_only": True,
        },
        "gpu_throttle_hw_power_brake": {
            "available": any(source.get("metric") == "throttle_hw_power_brake" for source in gpu_source_list),
            "source": describe_source(first_source_for_metric("throttle_hw_power_brake")),
            "count": metric_gpu_count(gpu_source_list, "throttle_hw_power_brake"),
            "evidence_only": True,
        },
        "gpu_throttle_sync_boost": {
            "available": any(source.get("metric") == "throttle_sync_boost" for source in gpu_source_list),
            "source": describe_source(first_source_for_metric("throttle_sync_boost")),
            "count": metric_gpu_count(gpu_source_list, "throttle_sync_boost"),
            "evidence_only": True,
        },
        "gpu_throttle_sw_thermal": {
            "available": any(source.get("metric") == "throttle_sw_thermal" for source in gpu_source_list),
            "source": describe_source(first_source_for_metric("throttle_sw_thermal")),
            "count": metric_gpu_count(gpu_source_list, "throttle_sw_thermal"),
            "evidence_only": True,
        },
        "memory_used_gb": {
            "available": bool(memory_used_available),
            "source": "/proc/meminfo",
        },
    }
    capabilities["gpu_telemetry_by_gpu"] = {
        "available": bool(gpu_source_list),
        "source": "per-gpu telemetry source matrix",
        "gpus": gpu_telemetry_matrix(),
    }
    privilege_sources: List[TelemetrySource] = []
    for source in (
        [cpu_temp_source, cpu_power_source, cpu_clock_source]
        + cpu_core_clock_source_list
        + memory_temp_source_list
        + storage_temp_source_list
        + device_temp_source_list
        + gpu_source_list
    ):
        privilege_sources.extend(_source_and_components(source))
    capabilities["telemetry_privilege"] = build_telemetry_privilege_summary(
        privileged_helper_enabled=privileged_helper_enabled,
        process_is_root=process_is_root,
        sudo_available=sudo_available,
        telemetry_sources=privilege_sources,
        unreadable_sources=cpu_power_unreadable_source_list,
    )
    return capabilities
