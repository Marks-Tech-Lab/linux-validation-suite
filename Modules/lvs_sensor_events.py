#!/usr/bin/env python3
"""Stage sensor threshold event builders."""

from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, Optional

from Modules.lvs_stability_events import create_stability_event


def _threshold_event(
    *,
    category: str,
    severity: str,
    stage_name: str,
    key: str,
    peak: float,
    threshold: float,
    threshold_source: str,
    verb: str,
) -> Dict[str, Any]:
    return create_stability_event(
        category,
        severity,
        stage_name,
        key,
        f"{key} {verb} ({peak} >= {threshold})",
        {
            "metric": key,
            "max": round(peak, 2),
            "threshold": threshold,
            "threshold_source": threshold_source,
        },
    )


def _values_for_key(samples: Iterable[Any], key: str) -> list[Any]:
    return [
        sample.values.get(key)
        for sample in samples
        if getattr(sample, "values", {}).get(key) is not None
    ]


def stage_sensor_events(
    *,
    samples: list[Any],
    stage_name: str,
    metric_thresholds: Callable[[str], Optional[Dict[str, Any]]],
    abort_on_fail_threshold: bool,
    gpu_thermal_throttle_hint_c: float,
    gpu_hotspot_warn_c: float,
    gpu_hotspot_fail_c: float,
    gpu_memory_temp_warn_c: float,
    gpu_memory_temp_fail_c: float,
) -> list[Dict[str, Any]]:
    if not samples:
        return []
    events: list[Dict[str, Any]] = []
    fail_threshold_severity = "error" if abort_on_fail_threshold else "warning"
    thresholds: list[tuple[str, str]] = [("cpu_temp_c", "cpu_temperature")]
    gpu_core_keys = sorted(
        {
            key
            for sample in samples
            for key in getattr(sample, "values", {})
            if key.startswith("gpu_") and key.endswith("_temp_core_c")
        }
    )
    thresholds.extend((key, "gpu_temperature") for key in gpu_core_keys)
    for key, category in thresholds:
        values = _values_for_key(samples, key)
        if not values:
            continue
        threshold_info = metric_thresholds(key)
        warn_value = threshold_info.get("warn_c") if threshold_info else None
        fail_value = threshold_info.get("fail_c") if threshold_info else None
        threshold_source = threshold_info.get("source") if threshold_info else "suite_default"
        peak = max(values)
        if fail_value is not None and peak >= fail_value:
            events.append(
                _threshold_event(
                    category=category,
                    severity=fail_threshold_severity,
                    stage_name=stage_name,
                    key=key,
                    peak=peak,
                    threshold=fail_value,
                    threshold_source=threshold_source,
                    verb="reached fail threshold",
                )
            )
        elif warn_value is not None and peak >= warn_value:
            events.append(
                _threshold_event(
                    category=category,
                    severity="warning",
                    stage_name=stage_name,
                    key=key,
                    peak=peak,
                    threshold=warn_value,
                    threshold_source=threshold_source,
                    verb="exceeded warning threshold",
                )
            )
        elif category == "gpu_temperature" and peak >= gpu_thermal_throttle_hint_c:
            events.append(
                create_stability_event(
                    "gpu_thermal_throttle_zone",
                    "warning",
                    stage_name,
                    key,
                    f"{key} reached possible thermal throttle zone ({peak} >= {gpu_thermal_throttle_hint_c})",
                    {
                        "metric": key,
                        "max": round(peak, 2),
                        "threshold": gpu_thermal_throttle_hint_c,
                        "threshold_source": "suite_throttle_hint",
                    },
                )
            )

    gpu_keys = [
        key
        for sample in samples
        for key in getattr(sample, "values", {})
        if key.startswith("gpu_") and key.endswith("_temp_hotspot_c")
    ]
    for key in sorted(set(gpu_keys)):
        values = _values_for_key(samples, key)
        if not values:
            continue
        threshold_info = metric_thresholds(key)
        warn_value = threshold_info.get("warn_c") if threshold_info else gpu_hotspot_warn_c
        fail_value = threshold_info.get("fail_c") if threshold_info else gpu_hotspot_fail_c
        threshold_source = threshold_info.get("source") if threshold_info else "suite_default"
        peak = max(values)
        if fail_value is not None and peak >= fail_value:
            events.append(
                _threshold_event(
                    category="gpu_hotspot",
                    severity=fail_threshold_severity,
                    stage_name=stage_name,
                    key=key,
                    peak=peak,
                    threshold=fail_value,
                    threshold_source=threshold_source,
                    verb="reached fail threshold",
                )
            )
        elif warn_value is not None and peak >= warn_value:
            events.append(
                _threshold_event(
                    category="gpu_hotspot",
                    severity="warning",
                    stage_name=stage_name,
                    key=key,
                    peak=peak,
                    threshold=warn_value,
                    threshold_source=threshold_source,
                    verb="exceeded warning threshold",
                )
            )

    mem_keys = [
        key
        for sample in samples
        for key in getattr(sample, "values", {})
        if key.startswith("gpu_") and key.endswith("_temp_memory_c")
    ]
    for key in sorted(set(mem_keys)):
        values = _values_for_key(samples, key)
        if not values:
            continue
        threshold_info = metric_thresholds(key)
        warn_value = threshold_info.get("warn_c") if threshold_info else gpu_memory_temp_warn_c
        fail_value = threshold_info.get("fail_c") if threshold_info else gpu_memory_temp_fail_c
        threshold_source = threshold_info.get("source") if threshold_info else "suite_default"
        peak = max(values)
        if fail_value is not None and peak >= fail_value:
            events.append(
                _threshold_event(
                    category="gpu_memory_temperature",
                    severity=fail_threshold_severity,
                    stage_name=stage_name,
                    key=key,
                    peak=peak,
                    threshold=fail_value,
                    threshold_source=threshold_source,
                    verb="reached fail threshold",
                )
            )
        elif warn_value is not None and peak >= warn_value:
            events.append(
                _threshold_event(
                    category="gpu_memory_temperature",
                    severity="warning",
                    stage_name=stage_name,
                    key=key,
                    peak=peak,
                    threshold=warn_value,
                    threshold_source=threshold_source,
                    verb="exceeded warning threshold",
                )
            )
    return events
