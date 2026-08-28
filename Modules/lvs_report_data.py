#!/usr/bin/env python3
"""Compile portable, report-oriented data from completed LVS artifacts."""

from __future__ import annotations

import csv
import math
import re
import statistics
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .lvs_core import APP_NAME, APP_VERSION
from .lvs_output_contract_identity import (
    REPORT_DATA_CONTRACT_ID,
    REPORT_DATA_KIND,
    stamp_contract_identity,
)


SOURCE_ARTIFACTS = (
    "system_info.json",
    "run_metadata.json",
    "profile_used.json",
    "run_manifest.json",
    "raw_telemetry.csv",
    "telemetry_source_map.json",
    "parsed_results_extended.json",
    "parsed_results_custom.json",
)

_ABORT_OUTCOMES = {"aborted", "manually_aborted"}
_FAIL_OUTCOMES = {"fail", "failed", "failure", "error", "unstable"}
_WARNING_OUTCOMES = {"warning", "warn"}
_PASS_OUTCOMES = {"pass", "passed", "success", "successful", "finished", "stable"}
_TEMPERATURE_LIMIT_MIN_C = -100.0
_TEMPERATURE_LIMIT_MAX_C = 300.0


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        import json

        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _finite_number(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _duration_seconds(value: Any) -> Optional[float]:
    number = _finite_number(value)
    if number is not None:
        return number
    parts = str(value or "").strip().split(":")
    if len(parts) not in {2, 3}:
        return None
    try:
        numbers = [float(part) for part in parts]
    except ValueError:
        return None
    if len(numbers) == 2:
        return numbers[0] * 60 + numbers[1]
    return numbers[0] * 3600 + numbers[1] * 60 + numbers[2]


def _temperature_limit(value: Any) -> Optional[float]:
    number = _finite_number(value)
    if number is None or not (_TEMPERATURE_LIMIT_MIN_C < number <= _TEMPERATURE_LIMIT_MAX_C):
        return None
    return round(number, 2)


def _slug(value: Any, fallback: str = "component") -> str:
    text = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")
    return text or fallback


def _outcome(value: Any) -> str:
    return str(value or "").strip().lower()


def _portable_metadata(metadata: Dict[str, Any]) -> Dict[str, Any]:
    excluded_tokens = ("sku", "database", "reference_rule", "action_queue", "workbook")
    return {
        str(key): value
        for key, value in sorted(metadata.items(), key=lambda item: str(item[0]))
        if not any(token in str(key).lower() for token in excluded_tokens)
    }


def _event_message(event: Dict[str, Any]) -> str:
    return str(event.get("message") or event.get("category") or "").strip()


def _unique_findings(items: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: set[Tuple[str, str, str]] = set()
    result: List[Dict[str, Any]] = []
    for item in items:
        key = (
            str(item.get("stage_id") or ""),
            str(item.get("category") or ""),
            str(item.get("message") or ""),
        )
        if not key[2] or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return sorted(result, key=lambda item: (
        int(item.get("stage_index", -1) or -1),
        str(item.get("category") or ""),
        str(item.get("message") or ""),
    ))


def _finding(event: Dict[str, Any], *, stage: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    finding = {
        "category": str(event.get("category") or "unspecified"),
        "message": _event_message(event),
        "source": str(event.get("source") or ""),
    }
    if event.get("timestamp"):
        finding["timestamp"] = event.get("timestamp")
    if isinstance(event.get("details"), dict) and event["details"]:
        finding["details"] = dict(event["details"])
    if stage is not None:
        finding["stage_index"] = stage["index"]
        finding["stage_id"] = stage["stage_id"]
    return finding


def _metric_semantics(field: str, source: Dict[str, Any]) -> Tuple[str, str]:
    metric = str(source.get("metric") or source.get("metric_class") or field).lower()
    normalized_units = str(source.get("normalized_units") or "").lower()
    combined = f"{field} {metric} {normalized_units}"
    if "temp" in combined or "temperature" in combined or normalized_units == "c":
        return "temperature", "c"
    if "clock" in combined or "frequency" in combined:
        return "clock", "mhz" if "mhz" in combined else normalized_units or "hz"
    if "power" in combined or normalized_units == "w":
        return "power", "w"
    if "voltage" in combined or re.search(r"(?:^|_)v(?:$|_)", metric) or normalized_units == "v":
        return "voltage", "v"
    if "current" in combined or normalized_units == "a":
        return "current", "a"
    if "rpm" in combined or "rotational" in combined:
        return "rotational", "rpm"
    if "percent" in combined or "utilization" in combined or "busy" in combined:
        return "percentage", "percent"
    if "gib" in combined:
        return "memory_usage", "gib"
    if re.search(r"(?:^|_)gb(?:$|_)", combined):
        return "memory_usage", "gb"
    if "count" in combined or "error" in combined:
        return "counter", "count"
    return "other_numeric", normalized_units or ""


def _source_index(field: str, source: Dict[str, Any], key: str, pattern: str) -> int:
    number = source.get(key)
    if isinstance(number, int):
        return number
    match = re.search(pattern, field)
    return int(match.group(1)) if match else 0


def _component_id(field: str, source: Dict[str, Any]) -> Tuple[str, str]:
    category = str(source.get("category") or "").lower()
    classification = str(source.get("component_classification") or "").lower()
    if category == "cpu_package" or re.match(r"cpu_package_\d+_", field):
        index = _source_index(field, source, "package_id", r"cpu_package_(\d+)_")
        return f"cpu:package:{index}", "cpu_package"
    if category == "cpu_core" or re.match(r"cpu_core_\d+_", field):
        index = _source_index(field, source, "cpu_index", r"cpu_core_(\d+)_")
        return f"cpu:core:{index}", "cpu_core"
    if category == "cpu" or field.startswith("cpu_"):
        return "cpu:aggregate", "cpu"
    if category == "gpu" or re.match(r"gpu_\d+_", field):
        index = _source_index(field, source, "gpu_index", r"gpu_(\d+)_")
        return f"gpu:{index}", "gpu"
    if category == "memory_module" or re.match(r"memory_module_\d+_", field):
        index = _source_index(field, source, "module_index", r"memory_module_(\d+)_")
        return f"memory_module:{index}", "memory_module"
    if category == "memory" or field.startswith("memory_"):
        return "memory:system", "memory"
    if category == "storage" or re.match(r"storage_drive_\d+_", field):
        index = _source_index(field, source, "drive_index", r"storage_drive_(\d+)_")
        return f"storage:{index}", "storage"
    if category == "bmc":
        component = classification or "other_platform"
        locator = source.get("component_locator") or source.get("normalized_label") or source.get("label")
        return f"bmc:{_slug(component)}:{_slug(locator)}", component
    if classification:
        index = _source_index(field, source, "sensor_index", rf"{re.escape(classification)}_(\d+)_")
        return f"platform:{_slug(classification)}:{index}", classification
    if category == "device":
        kind = str(source.get("kind") or "device").removesuffix("_temp")
        index = _source_index(field, source, "sensor_index", r"_(\d+)_temp")
        return f"device:{_slug(kind)}:{index}", kind
    return f"telemetry:{_slug(field)}", category or "telemetry"


def _component_label(component_id: str, component_class: str, source: Dict[str, Any], maps: Dict[str, Any]) -> str:
    if component_id == "cpu:aggregate":
        return "CPU"
    if component_id.startswith("cpu:package:"):
        return f"CPU package {component_id.rsplit(':', 1)[1]}"
    if component_id.startswith("cpu:core:"):
        return f"CPU core {component_id.rsplit(':', 1)[1]}"
    if component_id.startswith("gpu:"):
        index = int(component_id.split(":", 1)[1])
        info = maps.get("gpu", {}).get(index, {})
        return str(info.get("device_name") or info.get("label") or f"GPU {index}")
    if component_id.startswith("memory_module:"):
        return f"DIMM {component_id.rsplit(':', 1)[1]}"
    if component_id.startswith("storage:"):
        index = int(component_id.rsplit(":", 1)[1])
        info = maps.get("storage", {}).get(index, {})
        return str(info.get("device_name") or f"Storage {index}")
    if component_id == "memory:system":
        return "System memory"
    return str(source.get("label") or source.get("raw_label") or component_class.replace("_", " ").title())


def _identity(source: Dict[str, Any]) -> Dict[str, Any]:
    allowed = (
        "provider", "kind", "label", "raw_label", "normalized_label", "card", "slot",
        "vendor", "driver", "device_name", "block_name", "component_locator",
        "sensor_number", "entity_id", "entity_instance", "sensor_type", "confidence",
    )
    return {key: source[key] for key in allowed if source.get(key) not in (None, "", [], {})}


def _hardware_maps(source_map: Dict[str, Any], system_info: Dict[str, Any]) -> Dict[str, Any]:
    hardware = system_info.get("Hardware", {}) if isinstance(system_info.get("Hardware"), dict) else {}
    gpu_inventory = hardware.get("Gpu", []) if isinstance(hardware.get("Gpu"), list) else []
    gpu: Dict[int, Dict[str, Any]] = {}
    for item in source_map.get("gpu_index_map", []) if isinstance(source_map.get("gpu_index_map"), list) else []:
        if not isinstance(item, dict):
            continue
        index = int(item.get("gpu_index", 0) or 0)
        inventory = next((entry for entry in gpu_inventory if entry.get("Card") == item.get("card")), {})
        gpu[index] = {**item, "device_name": inventory.get("Name") or inventory.get("DeviceName") or ""}
    storage = {
        int(item.get("drive_index", 0) or 0): item
        for item in source_map.get("storage_link_map", []) if isinstance(item, dict)
    }
    return {"gpu": gpu, "storage": storage}


def _build_components(source_map: Dict[str, Any], csv_fields: Iterable[str], system_info: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    field_records = source_map.get("fields", {}) if isinstance(source_map.get("fields"), dict) else {}
    maps = _hardware_maps(source_map, system_info)
    components: Dict[str, Dict[str, Any]] = {}
    field_context: Dict[str, Dict[str, Any]] = {}
    for field in sorted(set(csv_fields)):
        if field == "timestamp":
            continue
        source = field_records.get(field, {}) if isinstance(field_records.get(field), dict) else {}
        metric_class, unit = _metric_semantics(field, source)
        component_id, component_class = _component_id(field, source)
        context = {
            "field": field,
            "component_id": component_id,
            "component_class": component_class,
            "metric_class": metric_class,
            "unit": unit,
            "provider": str(source.get("provider") or source.get("kind") or ""),
            "source_label": str(source.get("label") or source.get("raw_label") or field),
            "source": source,
        }
        field_context[field] = context
        component = components.setdefault(component_id, {
            "component_id": component_id,
            "component_class": component_class,
            "label": _component_label(component_id, component_class, source, maps),
            "identity": _identity(source),
            "telemetry_fields": [],
        })
        component["telemetry_fields"].append(field)
    for component in components.values():
        component["telemetry_fields"] = sorted(set(component["telemetry_fields"]))
    return sorted(components.values(), key=lambda item: item["component_id"]), field_context


def _read_telemetry(path: Path) -> Tuple[List[str], List[Tuple[float, Dict[str, float]]]]:
    if not path.is_file():
        return [], []
    rows: List[Tuple[float, Dict[str, float]]] = []
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            fields = list(reader.fieldnames or [])
            for raw in reader:
                timestamp = _finite_number(raw.get("timestamp"))
                if timestamp is None:
                    continue
                values: Dict[str, float] = {}
                for field in fields:
                    if field == "timestamp":
                        continue
                    value = _finite_number(raw.get(field))
                    if value is not None:
                        values[field] = value
                rows.append((timestamp, values))
        return fields, rows
    except Exception:
        return [], []


def _summary(values: List[float]) -> Dict[str, Any]:
    return {
        "sample_count": len(values),
        "minimum": round(min(values), 2),
        "average": round(statistics.mean(values), 2),
        "maximum": round(max(values), 2),
    }


def _window_number(window: Dict[str, Any], key: str, default: float = 0.0) -> float:
    value = _finite_number(window.get(key))
    return value if value is not None else default


def _window_with_recorded_normalization(
    index: int, window: Dict[str, Any], profile: Dict[str, Any],
) -> Dict[str, Any]:
    """Resolve missing window trims only from immutable run artifacts."""
    defaults = profile.get("defaults", {}) if isinstance(profile.get("defaults"), dict) else {}
    profile_stages = [
        item for item in (profile.get("stages", []) if isinstance(profile.get("stages"), list) else [])
        if isinstance(item, dict) and item.get("enabled") is not False
    ]
    stage_id = str(window.get("stage_id") or "")
    profile_stage = next(
        (
            item for item in profile_stages
            if stage_id and stage_id in {str(item.get("id") or ""), str(item.get("stage_id") or "")}
        ),
        profile_stages[index] if index < len(profile_stages) else {},
    )
    normalization = (
        profile_stage.get("normalization", {})
        if isinstance(profile_stage.get("normalization"), dict) else {}
    )
    resolved = dict(window)
    sources: Dict[str, str] = {}
    for key in ("trim_start_seconds", "trim_end_seconds"):
        if _finite_number(window.get(key)) is not None:
            resolved[key] = window[key]
            sources[key] = "recorded_stage_window"
        elif _finite_number(normalization.get(key)) is not None:
            resolved[key] = normalization[key]
            sources[key] = "recorded_profile_stage_normalization"
        elif _finite_number(defaults.get(key)) is not None:
            resolved[key] = defaults[key]
            sources[key] = "recorded_profile_defaults"
        else:
            resolved[key] = 0.0
            sources[key] = "zero_default"
    resolved["normalization_sources"] = sources
    return resolved


def _stage_shell(index: int, window: Dict[str, Any]) -> Dict[str, Any]:
    start = _window_number(window, "started_monotonic")
    end = _window_number(window, "ended_monotonic", start)
    trim_start = _window_number(window, "trim_start_seconds")
    trim_end = _window_number(window, "trim_end_seconds")
    analysis_start = start + trim_start
    uncollapsed_analysis_end = end - trim_end
    analysis_window_valid = bool(
        end >= start
        and trim_start >= 0
        and trim_end >= 0
        and analysis_start <= uncollapsed_analysis_end
    )
    analysis_end = max(analysis_start, uncollapsed_analysis_end)
    display_name = str(window.get("display_name") or window.get("name") or f"Stage {index + 1}")
    return {
        "index": index,
        "stage_id": str(window.get("stage_id") or f"stage_{index + 1}"),
        "stage_type": str(window.get("stage_type") or ""),
        "display_name": display_name,
        "display_label": str(window.get("display_label") or display_name),
        "legacy_bucket_category": window.get("legacy_bucket_category"),
        "started_at": str(window.get("started_iso") or window.get("started_at") or ""),
        "ended_at": str(window.get("ended_iso") or window.get("ended_at") or ""),
        "started_monotonic": start,
        "ended_monotonic": end,
        "duration_seconds": _window_number(window, "duration_seconds", max(0.0, end - start)),
        "trim_start_seconds": trim_start,
        "trim_end_seconds": trim_end,
        "analysis_started_monotonic": analysis_start,
        "analysis_ended_monotonic": analysis_end,
        "analysis_duration_seconds": max(0.0, analysis_end - analysis_start),
        "analysis_window_valid": analysis_window_valid,
        "normalization_sources": dict(window.get("normalization_sources") or {}),
        "native_outcome": _outcome(window.get("verdict")) or "unknown",
        "failures": [],
        "warnings": [],
        "metrics": [],
    }


def _raw_stage_metrics(stage: Dict[str, Any], telemetry_rows: List[Tuple[float, Dict[str, float]]], field_context: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not stage.get("analysis_window_valid"):
        return []
    start = stage["analysis_started_monotonic"]
    end = stage["analysis_ended_monotonic"]
    metrics: List[Dict[str, Any]] = []
    for field, context in sorted(field_context.items()):
        values = [values[field] for timestamp, values in telemetry_rows if start <= timestamp <= end and field in values]
        if not values:
            continue
        metric = {
            "field": field,
            "component_id": context["component_id"],
            "metric_class": context["metric_class"],
            "unit": context["unit"],
            **_summary(values),
            "summary_source": "raw_telemetry",
        }
        if context["provider"]:
            metric["provider"] = context["provider"]
        if context["source_label"]:
            metric["source_label"] = context["source_label"]
        metrics.append(metric)
    return metrics


def _fallback_metric(field: str, component_id: str, metric_class: str, unit: str, block: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(block, dict):
        return None
    values = {name.lower(): _finite_number(block.get(name)) for name in ("Min", "Avg", "Max")}
    if all(value is None for value in values.values()):
        return None
    return {
        "field": field,
        "component_id": component_id,
        "metric_class": metric_class,
        "unit": unit,
        "sample_count": int(block.get("SampleCount") or 0),
        "minimum": values["min"],
        "average": values["avg"],
        "maximum": values["max"],
        "summary_source": "parsed_segment_fallback",
    }


def _fallback_metrics(segment: Dict[str, Any]) -> List[Dict[str, Any]]:
    metrics: List[Dict[str, Any]] = []
    specs = (
        ("cpu_temp_c", "cpu:aggregate", "temperature", "c", (("Temperatures", "Cpu"),)),
        ("cpu_clock_mhz", "cpu:aggregate", "clock", "mhz", (("Clocks", "AllCoreAverage"),)),
        ("cpu_power_w", "cpu:aggregate", "power", "w", (("Power", "Cpu"),)),
    )
    for field, component, metric_class, unit, paths in specs:
        value: Any = segment
        for path in paths[0]:
            value = value.get(path, {}) if isinstance(value, dict) else {}
        row = _fallback_metric(field, component, metric_class, unit, value)
        if row:
            metrics.append(row)
    for gpu in segment.get("GpuMetrics", []) if isinstance(segment.get("GpuMetrics"), list) else []:
        if not isinstance(gpu, dict):
            continue
        index = int(gpu.get("GpuIndex", 0) or 0)
        for suffix, metric_class, unit, key in (
            ("clock_mhz", "clock", "mhz", "Clock"),
            ("power_w", "power", "w", "Power"),
            ("memory_clock_mhz", "clock", "mhz", "MemoryClock"),
            ("utilization_percent", "percentage", "percent", "Usage"),
        ):
            row = _fallback_metric(f"gpu_{index}_{suffix}", f"gpu:{index}", metric_class, unit, gpu.get(key))
            if row:
                metrics.append(row)
    temperatures = segment.get("Temperatures", {}) if isinstance(segment.get("Temperatures"), dict) else {}
    gpu_temps = temperatures.get("Gpu", {}) if isinstance(temperatures.get("Gpu"), dict) else {}
    for domain, suffix in (("Core", "core"), ("Hotspot", "hotspot"), ("Memory", "memory")):
        group = gpu_temps.get(domain, {}) if isinstance(gpu_temps.get(domain), dict) else {}
        for entry in group.get("Gpus", []) if isinstance(group.get("Gpus"), list) else []:
            index = int(entry.get("GpuIndex", 0) or 0)
            row = _fallback_metric(f"gpu_{index}_temp_{suffix}_c", f"gpu:{index}", "temperature", "c", entry.get("Temperatures"))
            if row:
                metrics.append(row)
    memory = temperatures.get("Memory", {}) if isinstance(temperatures.get("Memory"), dict) else {}
    for index, entry in enumerate(memory.get("Modules", []) if isinstance(memory.get("Modules"), list) else []):
        row = _fallback_metric(f"memory_module_{index}_temp_c", f"memory_module:{index}", "temperature", "c", entry.get("Temperatures"))
        if row:
            metrics.append(row)
    storage = temperatures.get("Storage", {}) if isinstance(temperatures.get("Storage"), dict) else {}
    for index, entry in enumerate(storage.get("Drives", []) if isinstance(storage.get("Drives"), list) else []):
        row = _fallback_metric(f"storage_drive_{index}_temp_c", f"storage:{index}", "temperature", "c", entry.get("Temperatures"))
        if row:
            metrics.append(row)
    return sorted(metrics, key=lambda item: (item["component_id"], item["metric_class"], item["field"]))


def _ensure_metric_components(components: List[Dict[str, Any]], stages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_id = {str(item["component_id"]): item for item in components}
    for stage in stages:
        for metric in stage.get("metrics", []):
            component_id = str(metric.get("component_id") or "telemetry:unknown")
            component_class = component_id.split(":", 1)[0]
            item = by_id.setdefault(component_id, {
                "component_id": component_id,
                "component_class": component_class,
                "label": {
                    "cpu:aggregate": "CPU",
                    "memory:system": "System memory",
                }.get(component_id, component_id.replace(":", " ").replace("_", " ").title()),
                "identity": {},
                "telemetry_fields": [],
            })
            item["telemetry_fields"].append(str(metric.get("field") or ""))
    for item in by_id.values():
        item["telemetry_fields"] = sorted(set(filter(None, item["telemetry_fields"])))
    return sorted(by_id.values(), key=lambda item: item["component_id"])


def _reference_record(*, field: str, component_id: str, provider: str, source: str, confidence: str, warning: Any = None, critical: Any = None, warning_semantics: str = "", critical_semantics: str = "") -> Optional[Dict[str, Any]]:
    warn_c = _temperature_limit(warning)
    critical_c = _temperature_limit(critical)
    if warn_c is None and critical_c is None:
        return None
    if warn_c is not None and critical_c is not None and warn_c > critical_c:
        warn_c = None
    record: Dict[str, Any] = {
        "field": field,
        "component_id": component_id,
        "provider": provider,
        "source": source,
        "confidence": confidence or "unknown",
    }
    if warn_c is not None:
        record["warning_limit_c"] = warn_c
        record["warning_semantics"] = warning_semantics or "explicit_provider_warning"
    if critical_c is not None:
        record["critical_limit_c"] = critical_c
        record["critical_semantics"] = critical_semantics or "explicit_provider_critical"
    return record


def _temperature_references(source_map: Dict[str, Any], evidence: Dict[str, Any], field_context: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    references: List[Dict[str, Any]] = []
    fields = source_map.get("fields", {}) if isinstance(source_map.get("fields"), dict) else {}
    for field, source in sorted(fields.items()):
        if field not in field_context or field_context[field]["metric_class"] != "temperature" or not isinstance(source, dict):
            continue
        thresholds = source.get("thresholds") if isinstance(source.get("thresholds"), dict) else {}
        threshold_source = str(thresholds.get("source") or source.get("threshold_source") or "")
        if not threshold_source or threshold_source == "suite_default":
            continue
        record = _reference_record(
            field=field,
            component_id=field_context[field]["component_id"],
            provider=str(source.get("provider") or source.get("kind") or ""),
            source=threshold_source,
            confidence=str(source.get("confidence") or "high"),
            warning=thresholds.get("warn_c"),
            critical=thresholds.get("fail_c"),
            warning_semantics="canonical_telemetry_warning_threshold",
            critical_semantics="canonical_telemetry_failure_threshold",
        )
        if record:
            # Runtime policy may derive its canonical warning from a critical
            # limit.  Keep it as context, not proof of a provider warning.
            record["warning_is_context_only"] = True
            references.append(record)

    cpu_thermal = evidence.get("cpu", {}).get("thermal", {}) if isinstance(evidence.get("cpu"), dict) else {}
    tjmax = cpu_thermal.get("cpu_tjmax_c") if isinstance(cpu_thermal, dict) else None
    record = _reference_record(
        field="cpu_temp_c", component_id="cpu:aggregate", provider="coretemp",
        source="normalized_hardware_evidence.cpu.thermal.cpu_tjmax_c", confidence="high",
        critical=tjmax, critical_semantics=str(cpu_thermal.get("cpu_tjmax_semantics") or "tjmax"),
    )
    if record:
        references.append(record)

    source_path_fields = {
        str(context["source"].get("path") or ""): field
        for field, context in field_context.items()
        if context["source"].get("path")
    }
    for gpu in evidence.get("gpus", []) if isinstance(evidence.get("gpus"), list) else []:
        if not isinstance(gpu, dict):
            continue
        gpu_index = int(gpu.get("gpu_index", 0) or 0)
        component_id = f"gpu:{gpu_index}"
        for domain in gpu.get("thermal_domains", []) if isinstance(gpu.get("thermal_domains"), list) else []:
            if not isinstance(domain, dict):
                continue
            path = str(domain.get("source_path") or "")
            field = source_path_fields.get(path)
            if not field or field_context[field]["component_id"] != component_id:
                continue
            record = _reference_record(
                field=field, component_id=component_id,
                provider=str(domain.get("provider") or gpu.get("provider") or ""), source=path,
                confidence=str(domain.get("confidence") or "high"),
                critical=domain.get("temperature_crit_c", domain.get("temperature_emergency_c")),
                critical_semantics="gpu_hwmon_critical_or_emergency_context",
            )
            if record:
                if domain.get("temperature_emergency_c") is not None:
                    record["emergency_limit_c"] = _temperature_limit(domain.get("temperature_emergency_c"))
                references.append(record)
        nvidia_limits = {
            key: _temperature_limit(gpu.get(key))
            for key in (
                "temperature_target_c", "temperature_slowdown_c",
                "temperature_max_operating_c", "temperature_shutdown_c",
            )
            if _temperature_limit(gpu.get(key)) is not None
        }
        if nvidia_limits:
            candidate_fields = [
                field for field, context in field_context.items()
                if context["component_id"] == component_id and context["metric_class"] == "temperature"
            ]
            if len(candidate_fields) == 1:
                field = candidate_fields[0]
                record = _reference_record(
                    field=field, component_id=component_id,
                    provider="nvidia_smi", source="nvidia-smi -q -d TEMPERATURE",
                    confidence="high", critical=nvidia_limits.get("temperature_shutdown_c"),
                    critical_semantics="nvidia_shutdown_temperature_context",
                ) or {
                    "field": field, "component_id": component_id, "provider": "nvidia_smi",
                    "source": "nvidia-smi -q -d TEMPERATURE", "confidence": "high",
                }
                record["provider_limits_c"] = nvidia_limits
                references.append(record)

    for zone in evidence.get("platform_thermal_zones", []) if isinstance(evidence.get("platform_thermal_zones"), list) else []:
        if not isinstance(zone, dict):
            continue
        field = source_path_fields.get(str(Path(str(zone.get("source_path") or "")) / "temp"))
        if not field:
            continue
        for trip in zone.get("trip_points", []) if isinstance(zone.get("trip_points"), list) else []:
            if not isinstance(trip, dict) or trip.get("confidence") == "do_not_normalize":
                continue
            trip_type = str(trip.get("trip_type") or "unknown").lower()
            value = trip.get("temperature_c")
            record = _reference_record(
                field=field, component_id=field_context[field]["component_id"],
                provider="linux_thermal_zone", source=str(trip.get("source") or zone.get("source_path") or ""),
                confidence=str(trip.get("confidence") or "medium"),
                warning=value if trip_type in {"passive", "hot"} else None,
                critical=value if trip_type in {"critical", "emergency"} else None,
                warning_semantics=f"thermal_zone_{trip_type}_trip_context",
                critical_semantics=f"thermal_zone_{trip_type}_trip_context",
            )
            if record:
                record["warning_is_context_only"] = True
                references.append(record)

    for group_name in ("board_sensors", "other_component_sensors", "memory_modules", "storage_devices"):
        rows = evidence.get(group_name, []) if isinstance(evidence.get(group_name), list) else []
        for index, item in enumerate(rows):
            if not isinstance(item, dict):
                continue
            path = str(item.get("source_path") or "")
            field = source_path_fields.get(path)
            if not field:
                if group_name == "memory_modules":
                    field = f"memory_module_{index}_temp_c"
                elif group_name == "storage_devices":
                    field = f"storage_drive_{index}_temp_c"
            if field not in field_context:
                continue
            confidence = str(item.get("confidence") or "high")
            if confidence in {"low", "ambiguous", "do_not_normalize"} or item.get("threshold_normalization") == "do_not_normalize":
                continue
            record = _reference_record(
                field=field, component_id=field_context[field]["component_id"],
                provider=str(item.get("provider") or ""), source=path or group_name,
                confidence=confidence,
                warning=item.get("storage_warning_temperature_c", item.get("temperature_max_c")),
                critical=item.get("storage_critical_temperature_c", item.get("temperature_crit_c")),
                warning_semantics="provider_warning_or_maximum_context",
                critical_semantics="provider_critical_context",
            )
            if record:
                # Provider maximums are context unless explicitly called warning.
                if "storage_warning_temperature_c" not in item and item.get("temperature_max_c") is not None:
                    record["warning_is_context_only"] = True
                references.append(record)
    unique: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    for item in references:
        key = (item["field"], item.get("provider", ""), item.get("source", ""))
        unique[key] = item
    return sorted(unique.values(), key=lambda item: (item["component_id"], item["field"], item.get("provider", ""), item.get("source", "")))


def evaluate_temperature_context(metric: Dict[str, Any], reference: Dict[str, Any]) -> Dict[str, Any]:
    """Return attributable observed/limit context without inventing thresholds."""
    attributable = bool(
        metric.get("field") == reference.get("field")
        and metric.get("component_id") == reference.get("component_id")
    )
    result = {
        "field": metric.get("field"),
        "component_id": metric.get("component_id"),
        "provider": reference.get("provider", ""),
        "source": reference.get("source", ""),
        "confidence": reference.get("confidence", "unknown"),
        "attributable": attributable,
        "observed": {
            "sample_count": metric.get("sample_count", 0),
            "minimum": metric.get("minimum"),
            "average": metric.get("average"),
            "maximum": metric.get("maximum"),
        },
    }
    maximum = _finite_number(metric.get("maximum"))
    for kind in ("warning", "critical"):
        limit = _temperature_limit(reference.get(f"{kind}_limit_c"))
        if limit is None:
            continue
        result[f"{kind}_limit_c"] = limit
        result[f"{kind}_semantics"] = reference.get(f"{kind}_semantics", "")
        result[f"{kind}_crossed"] = maximum is not None and maximum >= limit
        result[f"{kind}_headroom_c"] = round(limit - maximum, 2) if maximum is not None else None
    dynamic_warning = bool(
        attributable
        and result.get("warning_crossed")
        and not reference.get("warning_is_context_only")
        and str(reference.get("confidence") or "").lower() in {"high", "trusted"}
    )
    result["dynamic_warning"] = dynamic_warning
    return result


def _clock_capabilities(evidence: Dict[str, Any]) -> List[Dict[str, Any]]:
    capabilities: List[Dict[str, Any]] = []
    cpu_frequency = evidence.get("cpu", {}).get("frequency", {}) if isinstance(evidence.get("cpu"), dict) else {}
    for group in cpu_frequency.get("policy_groups", []) if isinstance(cpu_frequency, dict) else []:
        if not isinstance(group, dict):
            continue
        record = {
            "component_id": "cpu:aggregate",
            "provider": str(group.get("frequency_provider") or "linux_cpufreq"),
            "capability_semantics": "cpu_frequency_policy_group",
            "policy_ids": list(group.get("policy_ids") or []),
            "affected_logical_cpus": list(group.get("affected_logical_cpus") or []),
        }
        for key in (
            "core_class", "base_frequency_mhz", "hardware_min_frequency_mhz",
            "hardware_max_frequency_mhz", "policy_min_frequency_mhz", "policy_max_frequency_mhz",
        ):
            if group.get(key) is not None:
                record[key] = group[key]
        if len(record) > 5:
            capabilities.append(record)
    if isinstance(cpu_frequency, dict) and isinstance(cpu_frequency.get("boost_enabled"), bool):
        capabilities.append({
            "component_id": "cpu:aggregate",
            "provider": str((cpu_frequency.get("boost_evidence") or {}).get("provider") or "linux_cpufreq"),
            "capability_semantics": "boost_enabled_state",
            "boost_enabled": cpu_frequency["boost_enabled"],
        })
    for gpu in evidence.get("gpus", []) if isinstance(evidence.get("gpus"), list) else []:
        if not isinstance(gpu, dict):
            continue
        index = int(gpu.get("gpu_index", 0) or 0)
        component_id = f"gpu:{index}"
        common = {
            "component_id": component_id,
            "provider": str(gpu.get("provider") or gpu.get("clock_provider") or ""),
        }
        direct = {key: gpu[key] for key in (
            "core_maximum_frequency_mhz", "sm_maximum_frequency_mhz", "memory_maximum_frequency_mhz",
            "maximum_frequency_mhz", "maximum_frequency_semantics",
        ) if gpu.get(key) is not None}
        if direct:
            capabilities.append({**common, "capability_semantics": "gpu_reported_capability", **direct})
        domains = gpu.get("clock_domains", {}) if isinstance(gpu.get("clock_domains"), dict) else {}
        for domain_name, domain in sorted(domains.items()):
            if not isinstance(domain, dict):
                continue
            values = {key: domain[key] for key in (
                "available_frequency_levels_mhz", "maximum_frequency_mhz", "maximum_frequency_semantics",
                "configured_min_frequency_mhz", "configured_max_frequency_mhz", "rp0_frequency_mhz",
                "boost_frequency_mhz",
            ) if domain.get(key) is not None}
            if values:
                capabilities.append({**common, "domain": str(domain_name), "capability_semantics": "gpu_clock_domain", **values})
    return sorted(capabilities, key=lambda item: (item["component_id"], str(item.get("domain") or ""), str(item.get("provider") or ""), str(item.get("capability_semantics") or "")))


def evaluate_clock_context(metric: Dict[str, Any], capability: Dict[str, Any]) -> Dict[str, Any]:
    """Pair observed clock statistics with capability context; never judge it."""
    return {
        "field": metric.get("field"),
        "component_id": metric.get("component_id"),
        "observed": {
            "sample_count": metric.get("sample_count", 0),
            "minimum": metric.get("minimum"),
            "average": metric.get("average"),
            "maximum": metric.get("maximum"),
        },
        "capability": dict(capability),
        "evaluation": "informational_only",
        "warning": False,
    }


def _hardware(system_info: Dict[str, Any]) -> Dict[str, Any]:
    raw = system_info.get("Hardware", {}) if isinstance(system_info.get("Hardware"), dict) else {}
    return {
        "cpu": raw.get("Cpu", {}),
        "gpus": raw.get("Gpu", []) if isinstance(raw.get("Gpu"), list) else [],
        "memory": raw.get("Memory", {}),
        "motherboard": raw.get("Motherboard", {}),
        "bios": raw.get("Bios", {}),
        "storage": raw.get("Storage", []) if isinstance(raw.get("Storage"), list) else [],
        "os": system_info.get("OperatingSystem", {}),
    }


def _segments(extended: Dict[str, Any]) -> List[Dict[str, Any]]:
    compatibility = extended.get("compatibility_export", {}) if isinstance(extended.get("compatibility_export"), dict) else {}
    segments = compatibility.get("Segments", [])
    return segments if isinstance(segments, list) else []


def _windows_from_segments(segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Build identity-only windows for older parsed-only result directories."""
    windows: List[Dict[str, Any]] = []
    for index, segment in enumerate(segments):
        if not isinstance(segment, dict):
            continue
        name = str(segment.get("DisplayName") or segment.get("Label") or segment.get("Name") or f"Stage {index + 1}")
        windows.append({
            "stage_id": str(segment.get("StageId") or f"stage_{index + 1}"),
            "stage_type": str(segment.get("TestType") or ""),
            "display_name": name,
            "display_label": str(segment.get("Label") or name),
            "legacy_bucket_category": segment.get("LegacyBucketCategory"),
            "started_at": str(segment.get("Started") or ""),
            "ended_at": str(segment.get("Ended") or ""),
            "duration_seconds": _duration_seconds(segment.get("Duration")) or 0.0,
            "verdict": str(segment.get("Verdict") or "unknown"),
            "failure_reasons": list(segment.get("FailureReasons") or []),
            "error_events": list(segment.get("ErrorEvents") or []),
            "system_faults": list(segment.get("SystemFaults") or []),
        })
    return windows


def _strict_warnings(segments: List[Dict[str, Any]], stages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    for index, segment in enumerate(segments):
        stability = segment.get("StabilityInterpretation", {}) if isinstance(segment, dict) else {}
        recommendations = stability.get("ThresholdRecommendations", {}) if isinstance(stability, dict) else {}
        if not isinstance(recommendations, dict) or not recommendations.get("StrictModeApplied"):
            continue
        stage = stages[index] if index < len(stages) else None
        for check in recommendations.get("Checks", []) if isinstance(recommendations.get("Checks"), list) else []:
            if isinstance(check, dict) and check.get("Result") == "would_warn":
                findings.append({
                    "category": "strict_threshold_recommendation",
                    "message": f"Strict recommendation was not met: {check.get('Name') or check.get('Metric') or 'threshold check'}",
                    "source": "parsed_results_extended.json",
                    **({"stage_index": stage["index"], "stage_id": stage["stage_id"]} if stage else {}),
                })
    return findings


def compile_report_data(run_dir: Path | str, *, generated_at: Optional[str] = None) -> Dict[str, Any]:
    """Compile one completed result directory without hardware or network access."""
    root = Path(run_dir)
    if not root.is_dir():
        raise ValueError(f"run directory does not exist: {root}")
    manifest = _read_json(root / "run_manifest.json")
    extended = _read_json(root / "parsed_results_extended.json")
    custom = _read_json(root / "parsed_results_custom.json")
    if not extended and custom:
        extended = {"compatibility_export": custom}
    system_info = _read_json(root / "system_info.json") or (
        extended.get("system_info", {}) if isinstance(extended.get("system_info"), dict) else {}
    )
    if not system_info and isinstance(custom.get("SystemInfo"), dict):
        system_info = custom["SystemInfo"]
    metadata = _read_json(root / "run_metadata.json") or (
        extended.get("run_metadata", {}) if isinstance(extended.get("run_metadata"), dict) else {}
    )
    profile = _read_json(root / "profile_used.json") or (
        extended.get("profile", {}) if isinstance(extended.get("profile"), dict) else {}
    )
    source_map = _read_json(root / "telemetry_source_map.json")
    evidence = extended.get("normalized_hardware_evidence", {}) if isinstance(extended.get("normalized_hardware_evidence"), dict) else {}
    telemetry_fields, telemetry_rows = _read_telemetry(root / "raw_telemetry.csv")
    source_fields = source_map.get("fields", {}).keys() if isinstance(source_map.get("fields"), dict) else []
    components, field_context = _build_components(source_map, telemetry_fields or source_fields, system_info)

    segments = _segments(extended)
    windows = manifest.get("stage_windows", []) if isinstance(manifest.get("stage_windows"), list) else []
    if not windows:
        windows = extended.get("stage_windows", []) if isinstance(extended.get("stage_windows"), list) else []
    if not windows and segments:
        windows = _windows_from_segments(segments)
    resolved_windows = [
        _window_with_recorded_normalization(index, window, profile)
        for index, window in enumerate(windows) if isinstance(window, dict)
    ]
    stages = [_stage_shell(index, window) for index, window in enumerate(resolved_windows)]

    failures: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    information: List[Dict[str, Any]] = []
    for stage, window in zip(stages, windows):
        events = [
            event for event in [*(window.get("error_events") or []), *(window.get("system_faults") or [])]
            if isinstance(event, dict)
        ]
        for event in events:
            severity = str(event.get("severity") or "").lower()
            item = _finding(event, stage=stage)
            if severity == "error":
                failures.append(item)
                stage["failures"].append(item)
            elif severity == "warning":
                warnings.append(item)
                stage["warnings"].append(item)
            else:
                information.append(item)
        native = stage["native_outcome"]
        reasons = [str(reason).strip() for reason in window.get("failure_reasons", []) if str(reason).strip()]
        if native in _FAIL_OUTCOMES:
            if not reasons and not stage["failures"]:
                reasons = [f"Stage reported native outcome: {native}"]
            for reason in reasons:
                item = {"category": "stage_failure", "message": reason, "source": "run_manifest.json", "stage_index": stage["index"], "stage_id": stage["stage_id"]}
                failures.append(item)
                stage["failures"].append(item)
        elif native in _ABORT_OUTCOMES:
            information.append({"category": "stage_aborted", "message": f"Stage outcome: {native}", "source": "run_manifest.json", "stage_index": stage["index"], "stage_id": stage["stage_id"]})
        elif native in _WARNING_OUTCOMES and not stage["warnings"]:
            item = {"category": "stage_warning", "message": "Stage reported a warning outcome.", "source": "run_manifest.json", "stage_index": stage["index"], "stage_id": stage["stage_id"]}
            warnings.append(item)
            stage["warnings"].append(item)

        stage["metrics"] = (
            _raw_stage_metrics(stage, telemetry_rows, field_context)
            if telemetry_rows
            else (_fallback_metrics(segments[stage["index"]]) if stage["index"] < len(segments) else [])
        )
        stage["metric_summary_source"] = "raw_telemetry" if telemetry_rows else "parsed_segment_fallback"
        stage["metric_window_semantics"] = (
            "normalized_analysis_window"
            if telemetry_rows else "existing_parsed_normalized_summary"
        )

    for event in manifest.get("error_events", []) if isinstance(manifest.get("error_events"), list) else []:
        if isinstance(event, dict):
            failures.append(_finding(event))
    for event in manifest.get("warning_events", []) if isinstance(manifest.get("warning_events"), list) else []:
        if isinstance(event, dict):
            warnings.append(_finding(event))

    warnings.extend(_strict_warnings(segments, stages))
    temperature_limits = _temperature_references(source_map, evidence, field_context)
    references_by_field: Dict[str, List[Dict[str, Any]]] = {}
    for reference in temperature_limits:
        references_by_field.setdefault(reference["field"], []).append(reference)
    for stage in stages:
        contexts: List[Dict[str, Any]] = []
        for metric in stage["metrics"]:
            if metric.get("metric_class") != "temperature":
                continue
            for reference in references_by_field.get(str(metric.get("field")), []):
                if reference.get("component_id") != metric.get("component_id"):
                    continue
                context = evaluate_temperature_context(metric, reference)
                contexts.append(context)
                if context.get("dynamic_warning"):
                    item = {
                        "category": "provider_temperature_warning",
                        "message": (
                            f"{metric['field']} reached {metric.get('maximum')} °C, crossing the explicit "
                            f"provider warning limit of {context.get('warning_limit_c')} °C."
                        ),
                        "source": str(reference.get("source") or reference.get("provider") or "provider_limit"),
                        "stage_index": stage["index"],
                        "stage_id": stage["stage_id"],
                        "details": context,
                    }
                    warnings.append(item)
                    stage["warnings"].append(item)
        if contexts:
            stage["temperature_context"] = sorted(contexts, key=lambda item: (str(item.get("component_id")), str(item.get("field")), str(item.get("source"))))

    native_outcome = _outcome(manifest.get("verdict"))
    if not native_outcome:
        compatibility = extended.get("compatibility_export", {}) if isinstance(extended.get("compatibility_export"), dict) else {}
        native_outcome = _outcome(compatibility.get("Result") or compatibility.get("result")) or "unknown"
    stage_outcomes = {str(stage.get("native_outcome") or "") for stage in stages}
    stage_abort = (
        "manually_aborted" if "manually_aborted" in stage_outcomes
        else "aborted" if "aborted" in stage_outcomes
        else ""
    )
    if native_outcome in _ABORT_OUTCOMES:
        report_outcome = native_outcome.upper()
    elif stage_abort:
        report_outcome = stage_abort.upper()
    elif native_outcome in _FAIL_OUTCOMES or failures:
        report_outcome = "FAIL"
    elif native_outcome in _WARNING_OUTCOMES or warnings:
        report_outcome = "WARNING"
    elif native_outcome in _PASS_OUTCOMES:
        report_outcome = "PASS"
    else:
        report_outcome = native_outcome.upper() if native_outcome else "UNKNOWN"

    if native_outcome in _WARNING_OUTCOMES and not warnings:
        warnings.append({"category": "run_warning", "message": "Run reported a warning outcome.", "source": "run_manifest.json"})
    if native_outcome in _FAIL_OUTCOMES and not failures:
        failures.append({"category": "run_failure", "message": f"Run reported native outcome: {native_outcome}", "source": "run_manifest.json"})
    if native_outcome in _ABORT_OUTCOMES:
        information.append({"category": "run_aborted", "message": f"Run ended with native outcome: {native_outcome}", "source": "run_manifest.json"})
    if not telemetry_rows:
        information.append({
            "category": "telemetry_summary_source",
            "message": "Raw telemetry was unavailable or empty; available parsed per-stage summaries were used.",
            "source": "parsed_results_extended.json",
        })

    failures = _unique_findings(failures)
    warnings = _unique_findings(warnings)
    information = _unique_findings(information)
    for stage in stages:
        stage["failures"] = _unique_findings(stage["failures"])
        stage["warnings"] = _unique_findings(stage["warnings"])
        stage["metrics"] = sorted(stage["metrics"], key=lambda item: (item["component_id"], item["metric_class"], item["field"]))
    components = _ensure_metric_components(components, stages)

    clock_capabilities = _clock_capabilities(evidence)
    for stage in stages:
        clock_context = [
            evaluate_clock_context(metric, capability)
            for metric in stage["metrics"] if metric.get("metric_class") == "clock"
            for capability in clock_capabilities if capability.get("component_id") == metric.get("component_id")
        ]
        if clock_context:
            stage["clock_context"] = clock_context

    description = str(metadata.get("description") or profile.get("menu_description") or manifest.get("menu_description") or custom.get("Description") or custom.get("description") or "")
    started = str(manifest.get("started") or "")
    ended = str(manifest.get("ended") or "")
    duration = _finite_number(manifest.get("elapsed_seconds"))
    if duration is None:
        duration = sum(float(stage["duration_seconds"]) for stage in stages)
    provenance_artifacts = []
    for name in SOURCE_ARTIFACTS:
        path = root / name
        if not path.is_file():
            continue
        entry: Dict[str, Any] = {"name": name}
        payload = {
            "run_manifest.json": manifest,
            "telemetry_source_map.json": source_map,
        }.get(name, {})
        if payload.get("contract_id"):
            entry["contract_id"] = payload["contract_id"]
            entry["contract_version"] = payload.get("contract_version")
        provenance_artifacts.append(entry)

    chart_series = [
        {
            "field": field,
            "component_id": context["component_id"],
            "metric_class": context["metric_class"],
            "unit": context["unit"],
            "source_label": context["source_label"],
            "provider": context["provider"],
            "source": str(context["source"].get("source") or context["source"].get("path") or ""),
        }
        for field, context in sorted(field_context.items())
    ]
    payload: Dict[str, Any] = {
        "generated_at": generated_at,
        "generator": {"name": APP_NAME, "version": APP_VERSION, "module": "Modules.lvs_report"},
        "run": {
            "profile_name": str(manifest.get("profile_name") or profile.get("profile_name") or custom.get("ProfileName") or ""),
            "profile_file": str(manifest.get("profile_file") or ""),
            "description": description,
            "started_at": started,
            "ended_at": ended,
            "duration_seconds": round(float(duration or 0.0), 2),
            "native_outcome": native_outcome,
            "report_outcome": report_outcome,
            "metadata": _portable_metadata(metadata),
            "lvs_version": str(manifest.get("app_version") or extended.get("app_version") or ""),
        },
        "review": {"failures": failures, "warnings": warnings, "information": information},
        "hardware": _hardware(system_info),
        "hardware_references": {
            "temperature_limits": temperature_limits,
            "clock_capabilities": clock_capabilities,
        },
        "components": components,
        "stages": stages,
        "chart_catalog": {
            "samples_embedded": False,
            "time_coordinate": "absolute_monotonic_seconds",
            "raw_artifact": "raw_telemetry.csv" if (root / "raw_telemetry.csv").is_file() else None,
            "source_map_artifact": "telemetry_source_map.json" if source_map else None,
            "series": chart_series,
            "stage_windows": [
                {
                    "stage_id": stage["stage_id"],
                    "started_monotonic": stage["started_monotonic"],
                    "ended_monotonic": stage["ended_monotonic"],
                    "trim_start_seconds": stage["trim_start_seconds"],
                    "trim_end_seconds": stage["trim_end_seconds"],
                    "analysis_started_monotonic": stage["analysis_started_monotonic"],
                    "analysis_ended_monotonic": stage["analysis_ended_monotonic"],
                    "analysis_duration_seconds": stage["analysis_duration_seconds"],
                    "analysis_window_valid": stage["analysis_window_valid"],
                    "normalization_sources": stage["normalization_sources"],
                    "metric_summary_source": stage["metric_summary_source"],
                    "metric_window_semantics": stage["metric_window_semantics"],
                }
                for stage in stages
            ],
        },
        "provenance": {
            "source_artifacts": provenance_artifacts,
            "metric_summary_source": "raw_telemetry" if telemetry_rows else "parsed_segment_fallback",
            "metric_window_semantics": (
                "normalized_analysis_window"
                if telemetry_rows else "existing_parsed_normalized_summary"
            ),
            "raw_sample_count": len(telemetry_rows),
        },
    }
    return stamp_contract_identity(payload, contract_id=REPORT_DATA_CONTRACT_ID, kind=REPORT_DATA_KIND)
