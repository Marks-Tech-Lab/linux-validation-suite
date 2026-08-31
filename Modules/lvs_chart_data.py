#!/usr/bin/env python3
"""Compile deterministic, non-authoritative chart samples for standalone reports."""

from __future__ import annotations

import csv
import json
import math
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .lvs_output_contract_identity import (
    CHART_DATA_CONTRACT_ID,
    CHART_DATA_KIND,
    stamp_contract_identity,
)


# Measurements on 301/1,801/7,201/21,601-point synthetic series showed that the
# one-hour class remains modest, while longer full payloads grow needlessly.
FULL_SAMPLE_LIMIT = 1_900
PLOTTED_POINT_BUDGET = 1_800
FAMILY_ORDER = (
    "Temperature", "Clock", "Power", "Utilization", "Memory / VRAM",
    "Voltage", "Current", "Fan speed", "Fan duty", "Percentage",
)

Point = Tuple[float, float]


def canonical_chart_json(chart_data: Mapping[str, Any]) -> str:
    """Return the stable serialization used by the artifact and HTML payload."""
    return json.dumps(chart_data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _finite(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _compact_number(value: float) -> float | int:
    rounded = round(value, 6)
    return int(rounded) if rounded.is_integer() else rounded


def _read_telemetry(path: Path) -> Tuple[List[str], List[Tuple[float, Dict[str, float]]]]:
    if not path.is_file():
        return [], []
    rows: List[Tuple[float, Dict[str, float]]] = []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fields = [field for field in (reader.fieldnames or []) if field != "timestamp"]
        for raw in reader:
            timestamp = _finite(raw.get("timestamp"))
            if timestamp is None:
                continue
            values: Dict[str, float] = {}
            for field in fields:
                value = _finite(raw.get(field))
                if value is not None:
                    values[field] = value
            rows.append((timestamp, values))
    rows.sort(key=lambda item: item[0])
    return fields, rows


def _deduplicate(points: Iterable[Point]) -> List[Point]:
    result: List[Point] = []
    seen = set()
    for point in sorted(points, key=lambda item: (item[0], item[1])):
        if point not in seen:
            result.append(point)
            seen.add(point)
    return result


def extrema_reduce(points: Sequence[Point], point_budget: int = PLOTTED_POINT_BUDGET) -> List[Point]:
    """Preserve actual first/minimum/maximum/last points in elapsed-time buckets."""
    if len(points) <= point_budget:
        return list(points)
    bucket_count = max(1, point_budget // 4)
    start, end = points[0][0], points[-1][0]
    span = max(end - start, 1e-12)
    buckets: List[List[Point]] = [[] for _ in range(bucket_count)]
    for point in points:
        bucket = min(bucket_count - 1, int((point[0] - start) * bucket_count / span))
        buckets[bucket].append(point)
    reduced: List[Point] = []
    for bucket in buckets:
        if not bucket:
            continue
        candidates = (
            bucket[0], min(bucket, key=lambda item: item[1]),
            max(bucket, key=lambda item: item[1]), bucket[-1],
        )
        reduced.extend(_deduplicate(candidates))
    return _deduplicate(reduced)


def _runs(points: Sequence[Point]) -> List[List[float | int]]:
    runs: List[List[float | int]] = []
    if not points:
        return runs
    run_start, run_end, value = points[0][0], points[0][0], points[0][1]
    for timestamp, candidate in points[1:]:
        if candidate == value:
            run_end = timestamp
            continue
        runs.append([_compact_number(run_start), _compact_number(run_end), _compact_number(value)])
        run_start = run_end = timestamp
        value = candidate
    runs.append([_compact_number(run_start), _compact_number(run_end), _compact_number(value)])
    return runs


def encode_series(
    points: Sequence[Point], *, full_sample_limit: int = FULL_SAMPLE_LIMIT,
    point_budget: int = PLOTTED_POINT_BUDGET,
) -> Dict[str, Any]:
    """Choose lossless full/run encoding or extrema-preserving reduction."""
    original_count = len(points)
    if original_count <= full_sample_limit:
        encoded = list(points)
        return {
            "encoding": "points", "original_sample_count": original_count,
            "plotted_point_count": original_count,
            "reduction": {"method": "none", "full_sample_limit": full_sample_limit},
            "data": {
                "t": [_compact_number(point[0]) for point in encoded],
                "v": [_compact_number(point[1]) for point in encoded],
            },
        }
    runs = _runs(points)
    # A run interval is lossless and worth using when it beats both the full
    # representation and the graph point budget by a meaningful margin.
    if len(runs) * 2 <= min(original_count, point_budget):
        return {
            "encoding": "plateau_runs", "original_sample_count": original_count,
            "plotted_point_count": len(runs) * 2,
            "reduction": {
                "method": "exact_constant_runs", "run_count": len(runs),
                "full_sample_limit": full_sample_limit,
            },
            "data": {"runs": runs},
        }
    reduced = extrema_reduce(points, point_budget)
    return {
        "encoding": "extrema_buckets", "original_sample_count": original_count,
        "plotted_point_count": len(reduced),
        "reduction": {
            "method": "elapsed_time_first_min_max_last", "point_budget": point_budget,
            "bucket_count": max(1, point_budget // 4), "full_sample_limit": full_sample_limit,
        },
        "data": {
            "t": [_compact_number(point[0]) for point in reduced],
            "v": [_compact_number(point[1]) for point in reduced],
        },
    }


def decode_series_points(encoded: Mapping[str, Any]) -> List[Point]:
    """Decode stored measurements for tests/tooling; runs retain step boundaries."""
    data = encoded.get("data", {}) if isinstance(encoded.get("data"), Mapping) else {}
    if encoded.get("encoding") == "plateau_runs":
        points: List[Point] = []
        for start, end, value in data.get("runs", []):
            points.append((float(start), float(value)))
            if end != start:
                points.append((float(end), float(value)))
        return points
    return [(float(t), float(v)) for t, v in zip(data.get("t", []), data.get("v", []))]


def _family(series: Mapping[str, Any]) -> Optional[str]:
    metric_class = str(series.get("metric_class") or "")
    field = str(series.get("field") or "").lower()
    source_text = " ".join(
        str(series.get(key) or "").lower() for key in ("source_label", "source", "provider")
    )
    component = str(series.get("component_id") or "")
    if metric_class == "temperature":
        return "Temperature"
    if metric_class == "clock":
        return "Clock"
    if metric_class == "power":
        return "Power"
    if metric_class == "memory_usage":
        return "Memory / VRAM"
    if metric_class == "voltage":
        return "Voltage"
    if metric_class == "current":
        return "Current"
    if metric_class == "fan_duty":
        return "Fan duty"
    if metric_class in {"fan_speed", "rotational_speed", "rpm"}:
        if str(series.get("unit") or "").lower() in {"percent", "%"}:
            return "Fan duty"
        return "Fan speed"
    if metric_class == "percentage":
        if any(token in f"{field} {source_text}" for token in ("utilization", "busy", "usage")):
            return "Utilization"
        return "Percentage"
    return None


def _display_unit(family: str, source_unit: str) -> Optional[Tuple[str, float]]:
    source = source_unit.lower()
    if family == "Clock":
        factors = {"hz": 1e-9, "khz": 1e-6, "mhz": 1e-3, "ghz": 1.0}
        return ("GHz", factors[source]) if source in factors else None
    expected = {
        "Temperature": ({"c", "°c", "celsius"}, "°C"),
        "Power": ({"w", "watt", "watts"}, "W"),
        "Utilization": ({"percent", "%"}, "%"),
        "Percentage": ({"percent", "%"}, "%"),
        "Memory / VRAM": ({"gib", "gb"}, "GiB" if source == "gib" else "GB"),
        "Voltage": ({"v", "volt", "volts"}, "V"),
        "Current": ({"a", "amp", "amps"}, "A"),
    }
    if family == "Fan speed":
        if source == "rpm":
            return ("RPM", 1.0)
        return None
    if family == "Fan duty":
        return ("%", 1.0) if source in {"percent", "%"} else None
    units, display = expected.get(family, (set(), ""))
    return (display, 1.0) if source in units else None


def _component_label(component_id: str, components: Mapping[str, Mapping[str, Any]]) -> str:
    item = components.get(component_id, {})
    display_label = str(item.get("display_label") or "").strip()
    if display_label:
        return display_label
    if component_id.startswith("cpu:core:"):
        return f"CPU core {component_id.rsplit(':', 1)[-1]}"
    if component_id.startswith("cpu:"):
        return "CPU"
    if component_id.startswith("gpu:"):
        return f"GPU {int(component_id.rsplit(':', 1)[-1]) + 1}"
    if component_id.startswith("memory_module:"):
        return f"DIMM {int(component_id.rsplit(':', 1)[-1]) + 1}"
    if component_id == "memory:system":
        return "System memory"
    if component_id.startswith("storage:"):
        return f"Storage {int(component_id.rsplit(':', 1)[-1]) + 1}"
    if component_id.startswith("device:board:"):
        return f"Board sensor {int(component_id.rsplit(':', 1)[-1]) + 1}"
    if component_id.startswith("device:nic:"):
        return "NIC"
    if component_id.startswith("device:wifi:"):
        return "Wi-Fi"
    return str(item.get("label") or component_id.replace(":", " ").title())


def _metric_label(series: Mapping[str, Any], family: str) -> str:
    field = str(series.get("field") or "").lower()
    provider = str(series.get("provider") or "").lower()
    if family == "Temperature":
        if "hotspot" in field or "junction" in field:
            return "Hotspot temperature"
        if field.startswith("gpu_") and any(token in field for token in ("memory", "vram")):
            return "VRAM temperature"
        if field.startswith("storage_"):
            source_label = str(series.get("source_label") or "").strip().lower()
            if re.search(r"(?:^|[\s:_-])controller(?:\s+temperature)?$", source_label):
                return "Controller temperature"
            if re.search(r"(?:^|[\s:_-])nand(?:\s+temperature)?$", source_label):
                return "NAND temperature"
            sensor = re.search(r"sensor_(\d+)", field)
            if sensor:
                return f"Sensor {sensor.group(1)} temperature"
            if provider == "storage_temp":
                return "Composite temperature"
        return "Temperature"
    if family == "Clock" and field.startswith("gpu_") and any(token in field for token in ("memory", "vram", "mclk")):
        return "VRAM clock"
    if family == "Clock":
        return "Clock"
    if family == "Utilization" and field.startswith("gpu_") and any(token in field for token in ("memory", "vram")):
        return "VRAM utilization"
    if family == "Utilization":
        return "Utilization"
    if family == "Memory / VRAM":
        return "VRAM used" if field.startswith("gpu_") else "Used memory"
    if family == "Fan speed":
        return "Fan speed"
    if family == "Fan duty":
        return "Fan duty"
    if family == "Voltage":
        if any(token in field for token in ("memory", "vram")):
            return "Memory voltage"
        if "vddnb" in field:
            return "VDDNB voltage"
        if "soc" in field:
            return "SOC voltage"
        return "Voltage"
    return family


def _selector_label(series: Mapping[str, Any], family_items: Sequence[Mapping[str, Any]]) -> str:
    """Return the concise, unique UI label within a selected stage/family."""
    if series.get("advanced_group") == "cpu_cores":
        return str(series.get("display_label") or series.get("component_label") or f"Core {series.get('core_index')}")
    component = str(series.get("component_label") or "")
    metric = str(series.get("metric_label") or "")
    component_items = [item for item in family_items if item.get("component_id") == series.get("component_id")]
    if len(component_items) == 1:
        return component
    if metric == "Temperature":
        return f"{component} core"
    if metric == "Clock":
        return f"{component} core"
    if metric == "Utilization":
        return f"{component} core"
    if metric == "Fan speed":
        return f"{component} fan"
    if metric == "Fan duty":
        return f"{component} fan"
    if metric == "Power":
        return f"{component} power"
    if metric == "Voltage":
        return f"{component} core"
    if metric == "VDDNB voltage":
        return f"{component} VDDNB"
    if metric == "SOC voltage":
        return f"{component} SOC"
    if metric in {"VRAM temperature", "VRAM clock", "VRAM utilization", "VRAM used"}:
        return f"{component} VRAM"
    if metric == "Hotspot temperature":
        return f"{component} hotspot"
    if metric == "Composite temperature":
        return f"{component} composite"
    sensor = re.match(r"^Sensor (\d+)", metric)
    if sensor:
        return f"{component} sensor {sensor.group(1)}"
    return f"{component} {metric.lower()}".strip()


def _apply_selector_labels(series: List[Dict[str, Any]]) -> None:
    """Attach deterministic visible labels and fail-safe disambiguators."""
    for family in FAMILY_ORDER:
        family_items = [item for item in series if item.get("metric_family") == family]
        used: Dict[str, int] = {}
        for item in family_items:
            label = _selector_label(item, family_items)
            count = used.get(label, 0)
            used[label] = count + 1
            if count:
                label = f"{label} {count + 1}"
            item["selector_label"] = label


def _is_primary_voltage(series: Mapping[str, Any]) -> bool:
    """Recognize canonical component voltage without promoting diagnostic rails."""
    field = str(series.get("field") or "").lower()
    component = str(series.get("component_id") or "")
    secondary_tokens = ("memory", "vram", "soc", "aux", "rail", "sensor", "input")
    if any(token in field for token in secondary_tokens):
        return False
    if component == "cpu:aggregate":
        return bool(re.fullmatch(r"cpu_(?:package_|core_)?voltage_v", field))
    if component.startswith("gpu:"):
        return bool(re.fullmatch(r"gpu_\d+_(?:voltage|core_voltage|vddgfx)_v", field))
    # BMC/PSU voltages stay diagnostic unless retained metadata explicitly marks
    # one canonical measurement. This avoids guessing which physical rail is primary.
    if component.startswith("bmc:") and "psu" in component:
        return series.get("chart_role") in {"primary", "canonical"}
    return False


def _is_primary(series: Mapping[str, Any], metric_label: str) -> bool:
    field = str(series.get("field") or "").lower()
    component = str(series.get("component_id") or "")
    provider = str(series.get("provider") or "").lower()
    if component.startswith("cpu:core:"):
        return False
    if metric_label in {"Voltage", "Memory voltage", "VDDNB voltage", "SOC voltage"}:
        return _is_primary_voltage(series)
    if component.startswith("device:") or component.startswith("bmc:") or provider.startswith(("bmc", "ipmi")):
        return False
    if metric_label == "Hotspot temperature":
        return component.startswith("gpu:")
    if "sensor_" in field:
        return False
    if component.startswith("storage:"):
        return provider == "storage_temp" and "sensor_" not in field
    if metric_label in {"Fan speed", "Fan duty"}:
        return component.startswith(("gpu:", "bmc:"))
    if metric_label in {"Current", "Percentage"}:
        return False
    return component.startswith(("cpu:", "gpu:", "memory_module:", "memory:system"))


def _series_order(series: Mapping[str, Any]) -> Tuple[Any, ...]:
    component = str(series.get("component_id") or "")
    if component.startswith("cpu:"):
        group = 0
    elif component.startswith("gpu:"):
        group = 1
    elif component == "memory:system":
        group = 2
    elif component.startswith("memory_module:"):
        group = 3
    elif component.startswith("storage:"):
        group = 4
    elif component.startswith("bmc:"):
        group = 5
    else:
        group = 6
    numbers = tuple(int(value) for value in re.findall(r"\d+", component))
    return (not bool(series.get("primary")), group, numbers, str(series.get("label")), str(series.get("field")))


def _same_points(left: Sequence[Point], right: Sequence[Point]) -> bool:
    return len(left) == len(right) and all(a == b for a, b in zip(left, right))


def _canonicalize_aliases(series_points: Dict[str, List[Point]], catalog: Sequence[Mapping[str, Any]]) -> set[str]:
    suppressed: set[str] = set()
    for field, points in series_points.items():
        if field.endswith("_gb"):
            canonical = field[:-3] + "_gib"
            if canonical in series_points and _same_points(points, series_points[canonical]):
                suppressed.add(field)
    by_field = {str(item.get("field")): item for item in catalog}
    if "cpu_temp_c" in series_points and "cpu_package_0_temp_c" in series_points:
        left, right = by_field.get("cpu_temp_c", {}), by_field.get("cpu_package_0_temp_c", {})
        if left.get("source") == right.get("source") and _same_points(series_points["cpu_temp_c"], series_points["cpu_package_0_temp_c"]):
            suppressed.add("cpu_temp_c")
    return suppressed


def compile_chart_data(
    run_dir: Path | str, report_data: Mapping[str, Any], *,
    full_sample_limit: int = FULL_SAMPLE_LIMIT,
    point_budget: int = PLOTTED_POINT_BUDGET,
) -> Dict[str, Any]:
    """Compile visualization-only samples from raw telemetry and report windows."""
    root = Path(run_dir)
    raw_path = root / "raw_telemetry.csv"
    raw_fields, telemetry = _read_telemetry(raw_path)
    catalog_root = report_data.get("chart_catalog", {}) if isinstance(report_data.get("chart_catalog"), Mapping) else {}
    catalog = [item for item in catalog_root.get("series", []) if isinstance(item, Mapping)]
    windows = [item for item in catalog_root.get("stage_windows", []) if isinstance(item, Mapping)]
    report_stages = {
        str(item.get("stage_id")): item for item in report_data.get("stages", [])
        if isinstance(item, Mapping)
    }
    components = {
        str(item.get("component_id")): item for item in report_data.get("components", [])
        if isinstance(item, Mapping)
    }
    stages: List[Dict[str, Any]] = []
    if telemetry:
        for stage_index, window in enumerate(windows):
            stage_id = str(window.get("stage_id") or f"stage_{stage_index + 1}")
            start = _finite(window.get("analysis_started_monotonic"))
            end = _finite(window.get("analysis_ended_monotonic"))
            valid = bool(window.get("analysis_window_valid")) and start is not None and end is not None and start <= end
            field_points: Dict[str, List[Point]] = {}
            if valid:
                for item in catalog:
                    field = str(item.get("field") or "")
                    if field not in raw_fields:
                        continue
                    points = [
                        (_compact_number(timestamp - start), values[field])
                        for timestamp, values in telemetry
                        if start <= timestamp <= end and field in values
                    ]
                    if points:
                        field_points[field] = [(float(t), value) for t, value in points]
            suppressed = _canonicalize_aliases(field_points, catalog)
            chart_series: List[Dict[str, Any]] = []
            for item in catalog:
                field = str(item.get("field") or "")
                if field in suppressed or field not in field_points:
                    continue
                family = _family(item)
                units = _display_unit(family, str(item.get("unit") or "")) if family else None
                if not family or units is None:
                    continue
                display_unit, factor = units
                component_id = str(item.get("component_id") or "unclassified")
                metric_label = _metric_label(item, family)
                component_label = _component_label(component_id, components)
                converted = [(timestamp, value * factor) for timestamp, value in field_points[field]]
                encoded = encode_series(converted, full_sample_limit=full_sample_limit, point_budget=point_budget)
                primary = _is_primary(item, metric_label)
                core_match = re.fullmatch(r"cpu:core:(\d+)", component_id)
                component_meta = components.get(component_id, {})
                chart_series.append({
                    "series_id": field, "component_id": component_id,
                    "component_label": component_label, "field": field,
                    "label": f"{component_label} — {metric_label}", "display_label": component_label,
                    "metric_label": metric_label,
                    "metric_family": family, "source_unit": str(item.get("unit") or ""),
                    "display_unit": display_unit, "primary": primary,
                    "advanced_group": "cpu_cores" if core_match else None,
                    "core_index": int(core_match.group(1)) if core_match else None,
                    "core_class": component_meta.get("core_class") if core_match else None,
                    "core_class_label": component_meta.get("core_class_label") if core_match else None,
                    "core_type_source": component_meta.get("core_type_source") if core_match else None,
                    "provider": str(item.get("provider") or ""),
                    "source_label": str(item.get("source_label") or ""),
                    "source": str(item.get("source") or ""),
                    **encoded,
                })
            _apply_selector_labels(chart_series)
            chart_series.sort(key=_series_order)
            families = [family for family in FAMILY_ORDER if any(item["metric_family"] == family for item in chart_series)]
            stage = report_stages.get(stage_id, {})
            display_name = str(stage.get("display_name") or stage_id)
            short_name, separator, description = display_name.partition(" — ")
            stage_type = str(stage.get("stage_type") or "").strip().lower()
            workload_component_class = next(
                (candidate for candidate in ("cpu", "gpu", "memory", "storage") if stage_type.startswith(candidate)),
                None,
            )
            stages.append({
                "stage_id": stage_id, "index": int(stage.get("index", stage_index)),
                "label": f"Stage {int(stage.get('index', stage_index)) + 1} — {short_name}",
                "description": description if separator else "",
                "workload_component_class": workload_component_class,
                "started_monotonic": window.get("started_monotonic"),
                "ended_monotonic": window.get("ended_monotonic"),
                "trim_start_seconds": window.get("trim_start_seconds", 0.0),
                "trim_end_seconds": window.get("trim_end_seconds", 0.0),
                "analysis_started_monotonic": window.get("analysis_started_monotonic"),
                "analysis_ended_monotonic": window.get("analysis_ended_monotonic"),
                "analysis_duration_seconds": window.get("analysis_duration_seconds"),
                "analysis_window_valid": bool(window.get("analysis_window_valid")),
                "normalization_sources": dict(window.get("normalization_sources") or {}),
                "metric_window_semantics": window.get("metric_window_semantics"),
                "families": families, "series": chart_series,
            })
    payload: Dict[str, Any] = {
        "available": bool(telemetry),
        "unavailable_reason": None if telemetry else "raw_telemetry_absent",
        "authority": "derived_visualization_only",
        "source": {
            "raw_artifact": "raw_telemetry.csv" if raw_path.is_file() else None,
            "report_contract_id": report_data.get("contract_id"),
            "report_contract_version": report_data.get("contract_version"),
        },
        "time_coordinate": "analysis_elapsed_seconds",
        "window_inclusion": "analysis_start <= timestamp <= analysis_end",
        "full_sample_limit": full_sample_limit,
        "plotted_point_budget": point_budget,
        "stages": stages,
    }
    return stamp_contract_identity(payload, contract_id=CHART_DATA_CONTRACT_ID, kind=CHART_DATA_KIND)
