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

NVIDIA_METRIC_FIELDS = {
    "temp_core_c": ("temperature.gpu", 150.0, "number"),
    "power_w": ("power.draw", 2000.0, "number"),
    "clock_mhz": ("clocks.current.graphics", 10000.0, "number"),
    "memory_clock_mhz": ("clocks.current.memory", 20000.0, "number"),
    "busy_percent": ("utilization.gpu", 100.0, "number"),
    "memory_busy_percent": ("utilization.memory", 100.0, "number"),
    "vram_used_gb": ("memory.used", 10_000_000.0, "mib_to_gib"),
    "fan_percent": ("fan.speed", 100.0, "number"),
}

_NVIDIA_UNAVAILABLE = {"n/a", "[n/a]", "[not available]", "not available"}
_NVIDIA_UNSUPPORTED = {"[not supported]", "not supported", "unsupported"}


def nvidia_field_observation(
    raw: Any = None,
    *,
    query_field: str = "",
    queried: bool = True,
    query_error: str = "",
    upper_bound: float = 10_000_000.0,
    conversion: str = "number",
) -> Dict[str, Any]:
    """Classify one provider field without conflating zero, N/A, and failure."""
    base: Dict[str, Any] = {
        "provider": "nvidia_smi",
        "query_field": query_field,
        "capability_status": "unknown",
        "measurement_status": "unknown",
        "value": None,
        "reason": "insufficient_evidence",
    }
    if query_error:
        base.update(measurement_status="query_error", reason=query_error)
        return base
    if not queried:
        base.update(measurement_status="not_collected", reason="field_not_queried")
        return base
    text = str(raw if raw is not None else "").strip()
    normalized = text.lower()
    if normalized in _NVIDIA_UNSUPPORTED:
        base.update(capability_status="unsupported", measurement_status="unavailable", reason="provider_reported_unsupported")
        return base
    if not text or normalized in _NVIDIA_UNAVAILABLE:
        base.update(measurement_status="unavailable", reason="provider_reported_na" if text else "provider_returned_empty")
        return base
    value = parse_optional_float(text, upper_bound=upper_bound)
    if value is None:
        base.update(measurement_status="query_error", reason="malformed_numeric_value", raw_value=text)
        return base
    if conversion == "mib_to_gib":
        value = round(value / 1024.0, 2)
    base.update(
        capability_status="supported",
        measurement_status="measured",
        value=value,
        reason="",
        raw_value=text,
    )
    return base


def _query_error_reason(completed: Optional[subprocess.CompletedProcess[str]]) -> str:
    if completed is None:
        return "query_exception_or_timeout"
    detail = str(completed.stderr or "").strip()
    return f"query_exit_{completed.returncode}" + (f": {detail}" if detail else "")


def _query_rows(
    fields: List[str],
    command_env: CommandEnv,
) -> tuple[Dict[str, Dict[str, str]], str]:
    completed = run_nvidia_smi_query(fields, command_env)
    if completed is None or completed.returncode != 0:
        return {}, _query_error_reason(completed)
    rows: Dict[str, Dict[str, str]] = {}
    for line in (completed.stdout or "").splitlines():
        parts = [item.strip() for item in line.split(",")]
        if len(parts) < len(fields):
            continue
        row = {field: parts[index] for index, field in enumerate(fields)}
        slot = normalize_pci_slot(row.get("pci.bus_id", "")).lower()
        if slot:
            rows[slot] = row
    if not rows:
        return {}, "malformed_or_empty_response"
    return rows, ""


def _probe_rows_with_field_isolation(
    fields: List[str],
    command_env: CommandEnv,
) -> tuple[Dict[str, Dict[str, str]], Dict[str, str], str]:
    """Probe a batch, isolating provider-field failures only when necessary."""
    rows, error = _query_rows(fields, command_env)
    if not error:
        return rows, {}, ""
    identity_rows, identity_error = _query_rows(["pci.bus_id"], command_env)
    if identity_error:
        return {}, {}, identity_error
    merged = {slot: dict(row) for slot, row in identity_rows.items()}
    field_errors: Dict[str, str] = {}
    for field in fields:
        if field == "pci.bus_id":
            continue
        field_rows, field_error = _query_rows(["pci.bus_id", field], command_env)
        if field_error:
            field_errors[field] = field_error
            continue
        for slot, row in field_rows.items():
            merged.setdefault(slot, {"pci.bus_id": row.get("pci.bus_id", slot)})[field] = row.get(field, "")
    return merged, field_errors, ""


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
        for index, (metric, query_field, label) in enumerate(NVIDIA_CLOCK_EVENT_REASON_FIELDS, start=1)
        if parse_nvidia_active_flag(parts[index]) is not None
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
        memory_observation = nvidia_field_observation(
            parts[5], query_field="memory.total", upper_bound=10_000_000.0
        )
        memory_mb = memory_observation.get("value")
        gpus.append(
            {
                "index": parts[0],
                "slot": normalize_pci_slot(parts[1]),
                "uuid": parts[2],
                "name": parts[3],
                "driver": parts[4],
                "memory_mb": memory_mb,
                "memory_total_observation": memory_observation,
                "clock_event_reason_fields": event_reason_fields,
            }
        )
    metric_observations = probe_nvidia_smi_gpu_observations(command_env)
    provider_observation = (metric_observations.get("__provider__") or {}).get("query")
    for gpu in gpus:
        observations = metric_observations.get(str(gpu.get("slot") or "").lower(), {})
        if not observations and provider_observation:
            observations = {
                metric: {
                    **provider_observation,
                    "query_field": query_field,
                }
                for metric, (query_field, _upper_bound, _conversion) in NVIDIA_METRIC_FIELDS.items()
            }
            observations["temp_memory_c"] = {
                **provider_observation,
                "query_field": "temperature.memory",
            }
        gpu["metric_observations"] = observations
    return gpus


def read_nvidia_smi_gpu_metrics(
    gpu_sources: List[Dict[str, Any]],
    command_env: CommandEnv,
) -> Dict[str, Dict[str, Any]]:
    if not any(source["kind"] == "nvidia_smi" for source in gpu_sources):
        return {}
    blocked_statuses = {"query_error", "not_collected"}
    nvidia_sources = [source for source in gpu_sources if source.get("kind") == "nvidia_smi"]
    allowed_metrics = set(NVIDIA_METRIC_FIELDS)
    for metric in tuple(allowed_metrics):
        metric_sources = [source for source in nvidia_sources if source.get("metric") == metric]
        if metric_sources and all(
            str(source.get("measurement_status") or "") in blocked_statuses
            or str(source.get("capability_status") or "") == "unsupported"
            for source in metric_sources
        ):
            allowed_metrics.discard(metric)
    query_fields = ["pci.bus_id"] + [
        query_field
        for metric, (query_field, _upper_bound, _conversion) in NVIDIA_METRIC_FIELDS.items()
        if metric in allowed_metrics
    ]
    include_memory_temperature = any(
        source.get("metric") == "temp_memory_c"
        and str(source.get("measurement_status") or "") not in blocked_statuses
        and str(source.get("capability_status") or "") != "unsupported"
        for source in nvidia_sources
    )
    if include_memory_temperature:
        query_fields.append("temperature.memory")
    rows, query_error = _query_rows(query_fields, command_env)
    has_fan_speed = "fan.speed" in query_fields
    if query_error:
        # fan.speed is not accepted by every driver. Retrying without that one
        # optional field preserves every unrelated base measurement.
        query_fields = [field for field in query_fields if field != "fan.speed"]
        rows, query_error = _query_rows(query_fields, command_env)
        has_fan_speed = False
    if query_error:
        return {}
    snapshot: Dict[str, Dict[str, Any]] = {}
    for slot, row in rows.items():
        power_instant = parse_optional_float(row.get("power.draw", ""), upper_bound=2000.0)
        snapshot[slot] = {
            "temp_core_c": parse_optional_float(row.get("temperature.gpu", ""), upper_bound=150.0),
            "temp_memory_c": (
                parse_optional_float(row.get("temperature.memory", ""), upper_bound=150.0)
                if include_memory_temperature
                else None
            ),
            "power_w": power_instant,
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
            "_query_fields": {"power_w": "power.draw"},
        }
    # Average power is queried only when instantaneous power yielded no value;
    # it can therefore never make a supported fan field disappear.
    missing_power_slots = [slot for slot, values in snapshot.items() if values.get("power_w") is None]
    if missing_power_slots:
        average_rows, _average_error = _query_rows(["pci.bus_id", "power.draw.average"], command_env)
        for slot in missing_power_slots:
            row = average_rows.get(slot, {})
            average = parse_optional_float(row.get("power.draw.average", ""), upper_bound=2000.0)
            if average is not None:
                snapshot[slot]["power_w"] = average
                snapshot[slot]["_query_fields"]["power_w"] = "power.draw.average"
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


def probe_nvidia_smi_gpu_observations(
    command_env: CommandEnv,
) -> Dict[str, Dict[str, Dict[str, Any]]]:
    """Probe per-field availability once for diagnostics and source metadata."""
    fields = ["pci.bus_id"] + [spec[0] for spec in NVIDIA_METRIC_FIELDS.values()]
    rows, field_errors, query_error = _probe_rows_with_field_isolation(fields, command_env)
    if query_error:
        return {"__provider__": {"query": nvidia_field_observation(query_field="", query_error=query_error)}}
    observations: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for slot, row in rows.items():
        observations[slot] = {}
        for metric, (query_field, upper_bound, conversion) in NVIDIA_METRIC_FIELDS.items():
            observations[slot][metric] = nvidia_field_observation(
                row.get(query_field),
                query_field=query_field,
                queried=query_field in fields,
                query_error=field_errors.get(query_field, ""),
                upper_bound=upper_bound,
                conversion=conversion,
            )
    memory_rows, memory_error = _query_rows(["pci.bus_id", "temperature.memory"], command_env)
    for slot in observations:
        observations[slot]["temp_memory_c"] = nvidia_field_observation(
            memory_rows.get(slot, {}).get("temperature.memory"),
            query_field="temperature.memory",
            query_error=memory_error,
            upper_bound=150.0,
        )
    return observations
