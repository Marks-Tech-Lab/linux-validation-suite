#!/usr/bin/env python3
"""Render the portable LVS report contract as one offline HTML document."""

from __future__ import annotations

import html
import re
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional


def _escape(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _number(value: Any, unit: str = "") -> str:
    if value is None or value == "":
        return "—"
    try:
        number = float(value)
        text = f"{number:,.2f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        text = str(value)
    suffix = {
        "c": " °C", "mhz": " MHz", "hz": " Hz", "w": " W", "v": " V",
        "a": " A", "rpm": " RPM", "percent": "%", "gib": " GiB", "gb": " GB",
    }.get(str(unit).lower(), f" {unit}" if unit else "")
    return f"{_escape(text)}{_escape(suffix)}"


def _clock_range(metric: Optional[Dict[str, Any]]) -> str:
    if not metric:
        return "—"
    try:
        low = float(metric.get("minimum"))
        high = float(metric.get("maximum"))
    except (TypeError, ValueError):
        return _number(metric.get("average"), str(metric.get("unit") or ""))
    unit = str(metric.get("unit") or "").lower()
    field = str(metric.get("field") or "").lower()
    if unit == "mhz" and "memory" not in field and max(abs(low), abs(high)) >= 1000:
        low /= 1000
        high /= 1000
        display_unit = "GHz"
    else:
        display_unit = {"mhz": "MHz"}.get(unit, unit)
    low_text = f"{low:,.2f}".rstrip("0").rstrip(".")
    high_text = f"{high:,.2f}".rstrip("0").rstrip(".")
    value = low_text if low_text == high_text else f"{low_text}–{high_text}"
    return f"{_escape(value)} {_escape(display_unit)}".rstrip()


def _metric_number(metric: Dict[str, Any], key: str) -> str:
    """Format a canonical metric value for technician-facing HTML."""
    value = metric.get(key)
    unit = str(metric.get("unit") or "").lower()
    field = str(metric.get("field") or "").lower()
    if unit == "mhz" and "memory" not in field:
        try:
            if abs(float(value)) >= 1000:
                return f"{_escape(f'{float(value) / 1000:.2f}')} GHz"
        except (TypeError, ValueError):
            pass
    return _number(value, unit)


def _duration(value: Any) -> str:
    try:
        seconds = max(0, int(round(float(value))))
    except (TypeError, ValueError):
        return "—"
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:d}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:d}:{seconds:02d}"


def _timestamp(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "—"
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    rendered = parsed.strftime("%Y-%m-%d %H:%M:%S %z")
    return f"{rendered[:-2]}:{rendered[-2:]}" if parsed.tzinfo is not None else rendered.rstrip()


def _normalized_text(value: Any) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(value or "").lower()))


def _status_class(value: Any) -> str:
    status = str(value or "unknown").strip().lower()
    if status in {"pass", "passed", "success", "successful", "finished", "stable"}:
        return "pass"
    if status in {"warning", "warn"}:
        return "warning"
    if status in {"fail", "failed", "failure", "error", "unstable"}:
        return "fail"
    if "abort" in status:
        return "aborted"
    return "unknown"


def _value_from(mapping: Any, keys: Iterable[str]) -> str:
    if not isinstance(mapping, dict):
        return ""
    for key in keys:
        value = mapping.get(key)
        if value not in (None, "", [], {}):
            if isinstance(value, list):
                return ", ".join(str(item) for item in value)
            return str(value)
    return ""


def _identity_rows(rows: Iterable[tuple[str, str]]) -> str:
    content = "".join(
        f'<dt>{_escape(label)}</dt><dd>{_escape(value)}</dd>'
        for label, value in rows if value
    )
    return content or '<p class="muted compact">Not recorded.</p>'


def _memory_total(memory: Dict[str, Any]) -> str:
    text = _value_from(memory, ("Total", "TotalMemory", "Summary", "total"))
    if text:
        return text
    value = memory.get("TotalPhysicalMemoryGB")
    return f"{value} GB" if value not in (None, "") else ""


def _system_identity(hardware: Dict[str, Any], components: Optional[Dict[str, Dict[str, Any]]] = None) -> str:
    cpu = hardware.get("cpu", {}) if isinstance(hardware.get("cpu"), dict) else {}
    board = hardware.get("motherboard", {}) if isinstance(hardware.get("motherboard"), dict) else {}
    bios = hardware.get("bios", {}) if isinstance(hardware.get("bios"), dict) else {}
    operating_system = hardware.get("os", {}) if isinstance(hardware.get("os"), dict) else {}
    memory = hardware.get("memory", {}) if isinstance(hardware.get("memory"), dict) else {}
    gpus = hardware.get("gpus", []) if isinstance(hardware.get("gpus"), list) else []
    storage = hardware.get("storage", []) if isinstance(hardware.get("storage"), list) else []

    board_name = _value_from(board, ("DisplayName", "Product", "ProductName", "BoardName", "Model"))
    if not board_name:
        board_name = " ".join(filter(None, (
            _value_from(board, ("Manufacturer", "Vendor", "manufacturer")),
            _value_from(board, ("Product", "ProductName", "Model", "product")),
        )))
    system_rows = [
        ("CPU", _value_from(cpu, ("Name", "AggregateName", "ModelName", "Model", "name"))),
        ("Motherboard", board_name),
        ("BIOS", _value_from(bios, ("FullName", "Version", "BiosVersion", "Name", "version"))),
        ("Operating system", _value_from(operating_system, ("PrettyName", "Name", "Distribution", "name"))),
    ]

    total_label = "OS-reported memory" if memory.get("TotalPhysicalMemoryGB") not in (None, "") else "Total"
    memory_rows: List[tuple[str, str]] = [(total_label, _memory_total(memory))]
    speed = memory.get("SpeedSummary", {}) if isinstance(memory.get("SpeedSummary"), dict) else {}
    if speed.get("OperatingSpeedMTs") not in (None, ""):
        memory_rows.append(("Operating speed", f'{speed["OperatingSpeedMTs"]} MT/s'))
    modules = memory.get("Modules", []) if isinstance(memory.get("Modules"), list) else []
    for index, module in enumerate(modules):
        if not isinstance(module, dict):
            continue
        memory_rows.append((f"Module {index + 1}", _module_identity(module)))

    gpu_rows: List[tuple[str, str]] = []
    mapped_gpus = sorted(
        (item for item in (components or {}).values() if item.get("component_class") == "gpu"),
        key=lambda item: int(str(item.get("component_id") or "0").rsplit(":", 1)[-1]),
    )
    for index, gpu in enumerate(gpus if not mapped_gpus else mapped_gpus):
        if not isinstance(gpu, dict):
            continue
        name = str(gpu.get("label") or "") if mapped_gpus else _value_from(gpu, ("Name", "MarketingName", "DeviceName", "Model", "name"))
        inventory = next((item for item in gpus if name and name in _value_from(item, ("Name", "MarketingName", "DeviceName", "Model", "name"))), {})
        detail = " · ".join(filter(None, (_value_from(inventory, ("DeviceClass",)), _value_from(inventory, ("Memory",)))))
        gpu_rows.append((f"GPU {index + 1}", " · ".join(filter(None, (name, detail)))))
    storage_rows: List[tuple[str, str]] = []
    for index, drive in enumerate(storage):
        if not isinstance(drive, dict):
            continue
        name = _value_from(drive, ("Model", "model", "Device", "Name"))
        capacity = drive.get("CapacityGB", drive.get("capacity_gb"))
        detail = " · ".join(filter(None, (
            f"{capacity} GB" if capacity not in (None, "") else "",
            _value_from(drive, ("InterfaceType", "Interface", "interface_type", "interface")),
        )))
        storage_rows.append((f"Storage {index + 1}", " · ".join(filter(None, (name, detail)))))

    cards = [("System", system_rows, "identity-card-system"), ("Memory", memory_rows, "identity-card-memory")]
    if len(gpu_rows) + len(storage_rows) > 4:
        cards.extend((("Graphics", gpu_rows, "identity-card-graphics"), ("Storage", storage_rows, "identity-card-storage")))
    else:
        cards.append(("Graphics / storage", [*gpu_rows, *storage_rows], "identity-card-devices"))
    return "".join(
        f'<section class="identity-card {css_class}"><h3>{_escape(title)}</h3>'
        f'<dl class="identity">{_identity_rows(rows)}</dl></section>'
        for title, rows, css_class in cards
    )


def _review_summary(review: Dict[str, Any]) -> str:
    issue_groups = [
        ("Failure", "fail", review.get("failures", [])),
        ("Warning", "warning", review.get("warnings", [])),
    ]
    findings = [
        (label, css_class, item)
        for label, css_class, items in issue_groups
        for item in (items if isinstance(items, list) else [])
        if isinstance(item, dict)
    ]
    if not findings:
        return '<div class="review-clean"><strong>No issues found</strong><span>No failures or warnings were recorded.</span></div>'
    findings.extend(
        ("Information", "info", item)
        for item in (review.get("information", []) if isinstance(review.get("information"), list) else [])
        if isinstance(item, dict)
    )
    primary_label, primary_class, primary = findings[0]
    additional = "".join(
        f'<li><span class="badge {css_class}">{_escape(label)}</span>{_escape(item.get("message"))}</li>'
        for label, css_class, item in findings[1:]
    )
    evidence = "".join(
        f'<tr><td>{index}</td><td>{_escape(label)}</td><td>{_escape(item.get("stage_id") or "Run")}</td>'
        f'<td>{_escape(item.get("category") or "—")}</td><td>{_escape(item.get("source") or "—")}</td></tr>'
        for index, (label, _css_class, item) in enumerate(findings, start=1)
    )
    return f'''<div class="review-card {primary_class}">
      <span class="eyebrow">Primary finding</span>
      <div class="review-primary"><span class="badge {primary_class}">{_escape(primary_label)}</span><strong>{_escape(primary.get("message"))}</strong></div>
      {f'<ul class="additional-findings">{additional}</ul>' if additional else ''}
      <details class="evidence-details secondary-disclosure"><summary>Finding source details</summary><div class="table-wrap"><table><thead><tr><th>#</th><th>Severity</th><th>Stage</th><th>Category</th><th>Source</th></tr></thead><tbody>{evidence}</tbody></table></div></details>
    </div>'''


def _stage_evidence(stages: List[Dict[str, Any]], review: Dict[str, Any], report_outcome: str) -> str:
    if _status_class(report_outcome) == "pass":
        return ""
    review_by_stage: Dict[str, List[tuple[str, str]]] = {}
    for bucket in ("failures", "warnings"):
        for finding in review.get(bucket, []) if isinstance(review.get(bucket), list) else []:
            if not isinstance(finding, dict) or not finding.get("stage_id") or not finding.get("message"):
                continue
            review_by_stage.setdefault(str(finding["stage_id"]), []).append(
                ("fail" if bucket == "failures" else "warning", str(finding["message"]))
            )
    cards = []
    for stage in stages:
        native = str(stage.get("native_outcome") or "unknown")
        messages: List[str] = []
        evidence_levels: List[str] = []
        for key in ("failures", "warnings"):
            values = stage.get(key, []) if isinstance(stage.get(key), list) else []
            messages.extend(str(item.get("message") if isinstance(item, dict) else item) for item in values if item)
            if values:
                evidence_levels.append("fail" if key == "failures" else "warning")
        for level, message in review_by_stage.get(str(stage.get("stage_id") or ""), []):
            evidence_levels.append(level)
            messages.append(message)
        if _status_class(native) in {"fail", "warning", "aborted"} and not messages:
            messages.append(f'Stage reported {native.replace("_", " ").upper()}.')
            evidence_levels.append(_status_class(native))
        unique = list(dict.fromkeys(message for message in messages if message))
        if not unique:
            continue
        title, _description = _stage_title_parts(stage)
        status = "fail" if "fail" in evidence_levels else "warning" if "warning" in evidence_levels else _status_class(native)
        evidence_label = "FAIL" if status == "fail" else "WARNING" if status == "warning" else native.replace("_", " ").upper()
        bullets = "".join(f"<li>{_escape(message)}</li>" for message in unique)
        cards.append(
            f'<article class="stage-evidence-card status-{status}"><h3>Stage {_escape(stage.get("index", 0) + 1)} — {_escape(title)} '
            f'<span class="badge {status}">{_escape(evidence_label)}</span></h3><ul>{bullets}</ul></article>'
        )
    if not cards:
        return ""
    return '<div class="section-heading"><h2>Stage evidence</h2></div><div class="stage-evidence-grid">' + "".join(cards) + "</div>"


def _component_index(components: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {
        str(component.get("component_id")): component
        for component in components if isinstance(component, dict) and component.get("component_id")
    }


def _component_label(component_id: str, components: Dict[str, Dict[str, Any]]) -> str:
    label = str(components.get(component_id, {}).get("label") or "").strip()
    if label:
        return label
    if component_id == "cpu:aggregate" or component_id.startswith("cpu:package:"):
        return "CPU"
    if component_id.startswith("cpu:core:"):
        return f"CPU core {component_id.rsplit(':', 1)[-1]}"
    if component_id.startswith("gpu:"):
        return f"GPU {int(component_id.rsplit(':', 1)[-1]) + 1}"
    if component_id.startswith("memory_module:"):
        return f"DIMM {component_id.rsplit(':', 1)[-1]}"
    if component_id.startswith("storage:"):
        return f"Storage {int(component_id.rsplit(':', 1)[-1]) + 1}"
    return component_id.replace(":", " ").replace("_", " ").title()


def _short_component_label(component_id: str) -> str:
    if component_id in {"cpu:aggregate", "cpu:primary"} or component_id.startswith("cpu:package:"):
        return "CPU"
    if component_id.startswith("cpu:core:"):
        return f"CPU Core {component_id.rsplit(':', 1)[-1]}"
    if component_id.startswith("gpu:"):
        index = component_id.rsplit(":", 1)[-1]
        return f"GPU {int(index) + 1}" if index.isdigit() else "GPU"
    if component_id.startswith("memory_module:"):
        index = component_id.rsplit(":", 1)[-1]
        return f"DIMM {int(index) + 1}" if index.isdigit() else "DIMM"
    if component_id == "memory:system":
        return "System memory"
    if component_id.startswith("storage:"):
        index = component_id.rsplit(":", 1)[-1]
        return f"Storage {int(index) + 1}" if index.isdigit() else "Storage"
    if component_id.startswith("device:board:"):
        index = component_id.rsplit(":", 1)[-1]
        return f"Board sensor {int(index) + 1}" if index.isdigit() else "Board sensor"
    if component_id.startswith("device:nic:"):
        return "NIC sensor"
    if component_id.startswith("device:wifi:"):
        return "Wi-Fi sensor"
    if component_id.startswith("bmc:"):
        return "BMC sensor"
    return component_id.replace(":", " ").replace("_", " ").title()


def _friendly_metric_label(metric: Dict[str, Any], components: Dict[str, Dict[str, Any]]) -> str:
    field = str(metric.get("field") or "")
    component_id = str(metric.get("component_id") or "")
    metric_class = str(metric.get("metric_class") or "metric")
    component = _short_component_label(component_id)
    if component_id.startswith("cpu:"):
        if metric_class == "temperature":
            if component_id.startswith("cpu:core:"):
                return f"{component} temperature"
            if component_id.startswith("cpu:package:"):
                return f"CPU package {component_id.rsplit(':', 1)[-1]} temperature"
            return "CPU aggregate temperature"
        if metric_class == "clock":
            return f"{component} clock" if component_id.startswith("cpu:core:") else "CPU average clock"
        if metric_class == "power":
            return "CPU package power"
    if component_id.startswith("gpu:"):
        if metric_class == "temperature":
            domain = "memory" if "memory" in field else "hotspot" if "hotspot" in field else "GPU"
            return f"{component} {domain} temperature"
        if metric_class == "clock":
            return f'{component} {"memory" if "memory" in field else "core"} clock'
        if metric_class == "power":
            return f"{component} power"
        if metric_class == "percentage":
            return f"{component} memory-busy utilization" if "memory_busy" in field else f"{component} utilization"
        if metric_class in {"memory_usage", "other_numeric"} and "vram_used" in field:
            return f"{component} VRAM used"
    if component_id.startswith("memory_module:") and metric_class == "temperature":
        return f"{component} temperature"
    if component_id.startswith("storage:") and metric_class == "temperature":
        sensor = re.search(r"_sensor_(\d+)_", field)
        return f"{component} sensor {sensor.group(1)} temperature" if sensor else f"{component} composite temperature"
    if component_id == "memory:system" and metric_class in {"memory_usage", "other_numeric"}:
        return "System memory used"
    names = {
        "temperature": "temperature", "clock": "clock", "power": "power", "voltage": "voltage",
        "current": "current", "percentage": "utilization", "rotational": "fan speed",
        "memory_usage": "memory usage", "counter": "counter",
    }
    return f"{component} {names.get(metric_class, metric_class.replace('_', ' '))}"


def _same_summary(left: Dict[str, Any], right: Dict[str, Any]) -> bool:
    return all(left.get(key) == right.get(key) for key in ("sample_count", "minimum", "average", "maximum"))


def _visible_metrics(metrics: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Suppress only proven compatibility aliases from normal HTML detail."""
    by_field = {str(item.get("field") or ""): item for item in metrics}
    hidden = set()
    for field, metric in by_field.items():
        if field.endswith("_gb"):
            canonical = by_field.get(f"{field[:-3]}_gib")
            if canonical and metric.get("component_id") == canonical.get("component_id") and _same_summary(metric, canonical):
                hidden.add(field)
    aggregate = by_field.get("cpu_temp_c")
    packages = [item for field, item in by_field.items() if re.fullmatch(r"cpu_package_\d+_temp_c", field)]
    if aggregate:
        identical = [
            item for item in packages
            if item.get("provider") == aggregate.get("provider")
            and item.get("source_label") == aggregate.get("source_label")
            and _same_summary(item, aggregate)
        ]
        if len(identical) == 1:
            hidden.add("cpu_temp_c")
    return [item for item in metrics if str(item.get("field") or "") not in hidden]


def _metric_name(metric: Dict[str, Any]) -> str:
    field = str(metric.get("field") or "").lower()
    component_id = str(metric.get("component_id") or "")
    metric_class = str(metric.get("metric_class") or "metric")
    if metric_class == "temperature":
        if "hotspot" in field:
            return "Hotspot temperature"
        if "memory" in field and str(metric.get("component_id") or "").startswith("gpu:"):
            return "Memory temperature"
        sensor = re.search(r"_sensor_(\d+)_", field)
        if sensor:
            return f"Sensor {sensor.group(1)} temperature"
        if component_id.startswith("storage:") and (
            "composite" in str(metric.get("source_label") or "").lower()
            or re.fullmatch(r"storage_drive_\d+_temp_c", field)
        ):
            return "Composite temperature"
        return "Temperature"
    if metric_class == "clock":
        return "Memory clock" if "memory" in field else "Clock"
    if metric_class == "percentage":
        return "Memory-busy utilization" if "memory_busy" in field else "Utilization"
    if component_id == "memory:system" and field.startswith("memory_used_"):
        return "Used memory (compatibility GB field)" if field.endswith("_gb") else "Used memory"
    named = {
        "power": "Power", "voltage": "Voltage", "current": "Current",
        "percentage": "Utilization", "rotational": "Fan speed",
        "memory_usage": "Memory usage", "counter": "Counter",
    }.get(metric_class)
    if named:
        if metric_class == "memory_usage" and "vram_used" in field:
            return "VRAM used"
        return named
    if "vram_used_gb" in field:
        return "VRAM used (compatibility GB field)"
    if field == "memory_used_gb":
        return "Used memory (compatibility GB field)"
    prefix = {
        "gpu": rf"gpu_{component_id.rsplit(':', 1)[-1]}_",
        "storage": rf"storage_drive_{component_id.rsplit(':', 1)[-1]}_",
        "memory_module": rf"memory_module_{component_id.rsplit(':', 1)[-1]}_",
    }.get(component_id.split(":", 1)[0], "")
    human_field = re.sub(rf"^{prefix}", "", field) if prefix else field
    human_field = re.sub(r"_(?:percent|mhz|hz|rpm|gib|gb|[cwva])$", "", human_field)
    return human_field.replace("_", " ").strip().capitalize() or "Unclassified metric"


def _pick_metric(metrics: List[Dict[str, Any]], rank) -> Optional[Dict[str, Any]]:
    candidates = [metric for metric in metrics if rank(metric) is not None]
    return min(candidates, key=lambda metric: (rank(metric), str(metric.get("field") or ""))) if candidates else None


def _cpu_metric(metrics: List[Dict[str, Any]], metric_class: str) -> Optional[Dict[str, Any]]:
    def rank(metric: Dict[str, Any]) -> Optional[int]:
        component_id = str(metric.get("component_id") or "")
        field = str(metric.get("field") or "")
        if metric.get("metric_class") != metric_class or not component_id.startswith("cpu:") or component_id.startswith("cpu:core:"):
            return None
        if metric_class == "temperature":
            if component_id.startswith("cpu:package:") and re.fullmatch(r"cpu_package_\d+_temp_c", field):
                return int(component_id.rsplit(":", 1)[-1])
            if component_id == "cpu:aggregate" and field == "cpu_temp_c":
                return 100
            return 200
        if metric_class == "clock":
            if component_id == "cpu:aggregate" and field == "cpu_clock_mhz":
                return 0
            return 10 if component_id.startswith("cpu:package:") else 20
        if metric_class == "power":
            if component_id == "cpu:aggregate" and field == "cpu_power_w":
                return 0
            return 10 if component_id.startswith("cpu:package:") else 20
        return None
    return _pick_metric(metrics, rank)


def _component_metric(metrics: List[Dict[str, Any]], component_id: str, metric_class: str) -> Optional[Dict[str, Any]]:
    def rank(metric: Dict[str, Any]) -> Optional[int]:
        if metric.get("component_id") != component_id or metric.get("metric_class") != metric_class:
            return None
        field = str(metric.get("field") or "")
        if component_id.startswith("gpu:"):
            if metric_class == "temperature":
                if "temp_core" in field or "temp_edge" in field or re.search(r"_temp_c$", field):
                    return 0
                if "hotspot" in field:
                    return 10
                if "memory" in field:
                    return 20
            if metric_class == "clock":
                return 10 if "memory" in field else 0
            if metric_class == "power":
                return 0
        if component_id.startswith("memory_module:") and metric_class == "temperature":
            return 0
        if component_id.startswith("storage:") and metric_class == "temperature":
            return 10 if re.search(r"_sensor_\d+_", field) else 0
        return 0
    return _pick_metric(metrics, rank)


def _stage_component_rows(stage: Dict[str, Any], components: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    metrics = [metric for metric in stage.get("metrics", []) if isinstance(metric, dict)]
    rows: List[Dict[str, Any]] = []
    cpu = {
        "component_id": "cpu:primary", "label": "CPU",
        "temperature": _cpu_metric(metrics, "temperature"),
        "clock": _cpu_metric(metrics, "clock"),
        "power": _cpu_metric(metrics, "power"),
    }
    if any(cpu[key] for key in ("temperature", "clock", "power")):
        rows.append(cpu)
    component_ids = sorted({
        str(metric.get("component_id") or "") for metric in metrics
        if str(metric.get("component_id") or "").startswith(("gpu:", "memory_module:", "storage:"))
    }, key=lambda value: (
        0 if value.startswith("gpu:") else 1 if value.startswith("memory_module:") else 2,
        int(value.rsplit(":", 1)[-1]) if value.rsplit(":", 1)[-1].isdigit() else 0,
    ))
    for component_id in component_ids:
        row = {
            "component_id": component_id,
            "label": _short_component_label(component_id),
            "temperature": _component_metric(metrics, component_id, "temperature"),
            "clock": _component_metric(metrics, component_id, "clock"),
            "power": _component_metric(metrics, component_id, "power"),
        }
        if any(row[key] for key in ("temperature", "clock", "power")):
            rows.append(row)
    return rows


def _stage_title_parts(stage: Dict[str, Any]) -> tuple[str, str]:
    label = str(stage.get("display_label") or stage.get("display_name") or stage.get("stage_id") or "Stage")
    if " — " in label:
        title, description = label.split(" — ", 1)
        if title.strip() and description.strip():
            return title.strip(), description.strip()
    return label, ""


def _stage_card(stage: Dict[str, Any], components: Dict[str, Dict[str, Any]]) -> str:
    native = stage.get("native_outcome") or "unknown"
    status = _status_class(native)
    title, description = _stage_title_parts(stage)
    rows = "".join(
        '<div class="component-metric-row">'
        f'<strong class="component-name">{_escape(row["label"])}</strong>'
        f'<span class="metric-cell">{_metric_number(row["temperature"], "maximum") if row["temperature"] else "—"}</span>'
        f'<span class="metric-cell">{_clock_range(row["clock"])}</span>'
        f'<span class="metric-cell">{_metric_number(row["power"], "maximum") if row["power"] else "—"}</span>'
        '</div>'
        for row in _stage_component_rows(stage, components)
    )
    metrics = (
        '<div class="component-metric-grid"><div class="component-metric-head">'
        '<span>Component</span><span>Temp max</span><span>Clock range</span><span>Power max</span></div>'
        f'{rows}</div>'
        if rows else '<p class="muted compact no-stage-metrics">No stage telemetry summary was recorded.</p>'
    )
    return f'''<article class="stage-card status-{status}" data-stage-card="stage-detail-{_escape(stage.get("index", 0))}">
      <div class="stage-heading"><div><span class="eyebrow">Stage {_escape(stage.get("index", 0) + 1)}</span><h3>{_escape(title)}</h3>{f'<p class="stage-description">{_escape(description)}</p>' if description else ''}</div></div>
      <div class="stage-meta"><span class="badge {status}">{_escape(str(native).replace("_", " ").upper())}</span><span>Duration {_escape(_duration(stage.get("duration_seconds")))}</span></div>
      {metrics}
      <button type="button" class="stage-detail-toggle" data-stage-detail="stage-detail-{_escape(stage.get("index", 0))}" aria-expanded="false">Show full min/avg/max metrics</button>
    </article>'''


def _metric_rows(metrics: List[Dict[str, Any]]) -> str:
    return "".join(
        '<div class="full-metric-row">'
        f'<div class="full-metric-cell component" title="Report ID: {_escape(metric.get("component_id"))}"><strong>{_escape(_short_component_label(str(metric.get("component_id") or "")))}</strong></div>'
        f'<div class="full-metric-cell metric"><strong>{_escape(_metric_name(metric))}</strong>'
        f'<small title="Raw telemetry field">{_escape(metric.get("field"))}</small></div>'
        f'<div class="full-metric-cell num">{_metric_number(metric, "minimum")}</div>'
        f'<div class="full-metric-cell num">{_metric_number(metric, "average")}</div>'
        f'<div class="full-metric-cell num">{_metric_number(metric, "maximum")}</div>'
        f'<div class="full-metric-cell samples">{_escape(metric.get("sample_count"))}</div>'
        '</div>'
        for metric in metrics
    )


def _metric_group(component_id: str) -> str:
    if component_id.startswith("cpu:"):
        return "CPU"
    if component_id.startswith("gpu:"):
        return _short_component_label(component_id)
    if component_id.startswith(("memory:", "memory_module:")):
        return "Memory"
    if component_id.startswith("storage:"):
        return "Storage"
    if component_id.startswith("bmc:"):
        return "BMC / IPMI"
    if component_id.startswith("device:"):
        return "Platform"
    return "Other"


def _metric_grid(metrics: List[Dict[str, Any]], *, include_header: bool = True) -> str:
    rows = _metric_rows(metrics) or '<p class="muted compact">No recorded metrics.</p>'
    header = '<div class="full-metric-head"><span>Component</span><span>Metric</span><span>Min</span><span>Average</span><span>Max</span><span>Samples</span></div>' if include_header else ""
    return f'''<div class="full-metric-grid">{header}{rows}</div>'''


def _metric_table(stage: Dict[str, Any], components: Dict[str, Dict[str, Any]]) -> str:
    metrics = _visible_metrics([item for item in stage.get("metrics", []) if isinstance(item, dict)])
    core_metrics = sorted(
        (item for item in metrics if str(item.get("component_id") or "").startswith("cpu:core:")),
        key=lambda item: (
            int(str(item.get("component_id") or "0").rsplit(":", 1)[-1]),
            str(item.get("field") or ""),
        ),
    )
    regular = [item for item in metrics if item not in core_metrics]
    groups = []
    present_groups = {_metric_group(str(item.get("component_id") or "")) for item in regular}
    gpu_groups = sorted((name for name in present_groups if name.startswith("GPU ")), key=lambda name: int(name.split()[-1]))
    group_order = ["CPU", *gpu_groups, "Memory", "Storage"]
    for group_name in group_order:
        group_metrics = [item for item in regular if _metric_group(str(item.get("component_id") or "")) == group_name]
        if group_metrics:
            groups.append(f'<div class="full-metric-group-label">{_escape(group_name)}</div>{_metric_rows(group_metrics)}')
        if group_name == "CPU" and core_metrics:
            core_count = len({str(item.get("component_id")) for item in core_metrics})
            groups.append(
                f'<details class="metric-subgroup nested-disclosure"><summary>CPU cores ({core_count})</summary>{_metric_grid(core_metrics, include_header=False)}</details>'
            )
    bmc_metrics = [item for item in regular if _metric_group(str(item.get("component_id") or "")) == "BMC / IPMI"]
    if bmc_metrics:
        bmc_count = len({str(item.get("component_id") or "") for item in bmc_metrics})
        if bmc_count > 3:
            groups.append(
                f'<details class="metric-subgroup bmc-metric-subgroup nested-disclosure"><summary>BMC / IPMI ({bmc_count})</summary>{_metric_grid(bmc_metrics, include_header=False)}</details>'
            )
        else:
            groups.append(f'<div class="full-metric-group-label">BMC / IPMI</div>{_metric_rows(bmc_metrics)}')
    platform_metrics = [item for item in regular if _metric_group(str(item.get("component_id") or "")) == "Platform"]
    if platform_metrics:
        platform_count = len({str(item.get("component_id") or "") for item in platform_metrics})
        groups.append(
            f'<details class="metric-subgroup platform-metric-subgroup nested-disclosure"><summary>Platform sensors ({platform_count})</summary>{_metric_grid(platform_metrics, include_header=False)}</details>'
        )
    other_metrics = [item for item in regular if _metric_group(str(item.get("component_id") or "")) == "Other"]
    if other_metrics:
        groups.append(f'<div class="full-metric-group-label">OTHER</div>{_metric_rows(other_metrics)}')
    content = (
        '<div class="full-metric-grid"><div class="full-metric-head"><span>Component</span><span>Metric</span>'
        '<span>Min</span><span>Average</span><span>Max</span><span>Samples</span></div>'
        f'{"".join(groups)}</div>' if groups else '<p class="muted compact">No recorded metrics.</p>'
    )
    title, _description = _stage_title_parts(stage)
    native = str(stage.get("native_outcome") or "unknown")
    status = _status_class(native)
    return f'''<section class="stage-detail-panel status-{status}" id="stage-detail-{_escape(stage.get("index", 0))}" hidden>
      <header class="stage-detail-header"><div><h3>Stage {_escape(stage.get("index", 0) + 1)} — {_escape(title)}</h3><p>Full min/avg/max metrics</p></div><div class="stage-detail-actions"><span class="badge {status}">{_escape(native.replace("_", " ").upper())}</span><button type="button" class="stage-detail-close">Close</button></div></header>
      <div class="stage-metric-groups">{content}</div>
    </section>'''


def _module_locator(module: Dict[str, Any]) -> str:
    return _value_from(module, (
        "Position", "Locator", "DeviceLocator", "Device Locator", "SlotLocator", "slot_locator",
    ))


def _module_identity(module: Dict[str, Any]) -> str:
    manufacturer = _value_from(module, ("Manufacturer", "manufacturer"))
    model = _value_from(module, ("display_part_number", "PartNumber", "part_number", "Model", "model"))
    if manufacturer and model.lower().startswith(manufacturer.lower()):
        name = model
    else:
        name = " ".join(filter(None, (manufacturer, model)))
    capacity = _value_from(module, ("Size", "size", "Capacity", "capacity"))
    speed = _value_from(module, (
        "OperatingSpeed", "operating_speed", "ConfiguredSpeed", "configured_speed", "Speed", "speed",
    ))
    detail = " @ ".join(filter(None, (capacity, speed))) if capacity and speed else capacity or speed
    return " · ".join(filter(None, (name, detail))) or "Memory module"


def _module_locator_display(module: Dict[str, Any]) -> tuple[str, str]:
    locator = _module_locator(module)
    bank = _value_from(module, ("bank_locator", "BankLocator", "Bank Locator"))
    if "/" in locator:
        prefix, physical = locator.split("/", 1)
        return physical, bank or prefix
    return locator, bank if bank and bank != locator else ""


def _proven_memory_links(
    modules: List[Dict[str, Any]], telemetry_components: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """Link telemetry to inventory only through an explicit stable identity."""
    links: Dict[str, Dict[str, Any]] = {}
    for component in telemetry_components:
        identity = component.get("identity", {}) if isinstance(component.get("identity"), dict) else {}
        locator = _value_from(identity, ("slot_locator", "physical_locator", "locator", "position", "bank_locator"))
        serial = _value_from(identity, ("serial_number", "serial"))
        if not locator and not serial:
            continue
        matches = [
            module for module in modules if isinstance(module, dict) and (
                (locator and locator in {_module_locator(module), _value_from(module, ("bank_locator", "BankLocator"))})
                or (serial and serial == _value_from(module, ("serial_number", "SerialNumber", "serial")))
            )
        ]
        if len(matches) == 1:
            links[str(component.get("component_id") or "")] = matches[0]
    return links


def _memory_mapping(modules: List[Dict[str, Any]], telemetry_components: List[Dict[str, Any]]) -> tuple[str, str]:
    inventory_rows = []
    for index, module in enumerate(modules):
        if not isinstance(module, dict):
            continue
        locator, bank = _module_locator_display(module)
        title = locator or f"Physical module {index + 1}"
        slot_note = "" if locator else '<small class="mapping-note">Physical slot not reported</small>'
        identity = " · ".join(filter(None, (bank, _module_identity(module))))
        inventory_rows.append(
            f'<li><strong>{_escape(title)}</strong><span>{_escape(identity)}{slot_note}</span></li>'
        )
    links = _proven_memory_links(modules, telemetry_components)
    telemetry_rows = []
    for component in telemetry_components:
        component_id = str(component.get("component_id") or "")
        module = links.get(component_id)
        if module:
            locator = _module_locator(module)
            detail = f"Temperature · {locator or _module_identity(module)}"
        else:
            detail = "Temperature · Physical module association unavailable"
        telemetry_rows.append(
            f'<li><strong>{_escape(_short_component_label(component_id))}</strong><span>{_escape(detail)}</span></li>'
        )
    return "".join(inventory_rows), "".join(telemetry_rows)


def _friendly_component_groups(components: List[Dict[str, Any]], hardware: Dict[str, Any]) -> str:
    graphics = [item for item in components if item.get("component_class") == "gpu"]
    storage = [item for item in components if item.get("component_class") == "storage"]
    telemetry_memory = [item for item in components if item.get("component_class") == "memory_module"]
    memory = hardware.get("memory", {}) if isinstance(hardware.get("memory"), dict) else {}
    modules = memory.get("Modules", []) if isinstance(memory.get("Modules"), list) else []
    groups: List[tuple[str, str]] = []
    if graphics:
        groups.append(("Graphics", "".join(
            f'<li><strong>{_escape(_short_component_label(str(item.get("component_id") or "")))}</strong>'
            f'<span>{_escape(item.get("label") or "Detected graphics device")}</span></li>' for item in graphics
        )))
    inventory_rows, telemetry_rows = _memory_mapping(modules, telemetry_memory)
    if inventory_rows:
        groups.append(("Installed memory", inventory_rows))
    if telemetry_rows:
        groups.append(("Memory telemetry", telemetry_rows))
    if storage:
        drives = hardware.get("storage", []) if isinstance(hardware.get("storage"), list) else []
        storage_rows = []
        for item in storage:
            label = str(item.get("label") or "Detected storage device")
            drive = next((candidate for candidate in drives if label and label in _value_from(candidate, ("Model", "model", "Device", "Name"))), {})
            capacity = drive.get("CapacityGB", drive.get("capacity_gb")) if isinstance(drive, dict) else None
            extra = " · ".join(filter(None, (
                f"{capacity} GB" if capacity not in (None, "") else "",
                _value_from(drive, ("InterfaceType", "Interface", "interface_type", "interface")),
            )))
            storage_rows.append(
                f'<li><strong>{_escape(_short_component_label(str(item.get("component_id") or "")))}</strong>'
                f'<span>{_escape(" · ".join(filter(None, (label, extra))))}</span></li>'
            )
        groups.append(("Storage", "".join(
            storage_rows
        )))
    return "".join(
        f'<div class="component-key-group"><dt>{_escape(title)}</dt><dd><ul>{rows}</ul></dd></div>'
        for title, rows in groups
    ) or '<p class="muted compact">No physical component mapping was recorded.</p>'


def _telemetry_field_rows(component: Dict[str, Any], series_by_field: Dict[str, Dict[str, Any]]) -> str:
    component_id = str(component.get("component_id") or "")
    identity = component.get("identity", {}) if isinstance(component.get("identity"), dict) else {}
    rows = []
    for field in component.get("telemetry_fields", []):
        series = series_by_field.get(str(field), {"field": field, "component_id": component_id})
        metric_name = _metric_name(series)
        metric_phrase = metric_name if metric_name.startswith("VRAM") else metric_name[:1].lower() + metric_name[1:]
        label = metric_name if component_id == "memory:system" else f'{_short_component_label(component_id)} {metric_phrase}'
        source = str(series.get("source_label") or identity.get("label") or "")
        provider = str(series.get("provider") or _value_from(identity, ("provider", "kind")))
        provider_source = " · ".join(filter(None, (provider, source))) or "—"
        alias_note = ""
        if str(field).endswith("_gb"):
            canonical_field = f'{str(field)[:-3]}_gib'
            canonical = series_by_field.get(canonical_field)
            if canonical and canonical.get("component_id") == component_id and canonical.get("provider") == series.get("provider"):
                alias_note = f'Compatibility alias of {canonical_field}'
        elif str(field).endswith("_gib"):
            compatibility_field = f'{str(field)[:-4]}_gb'
            compatibility = series_by_field.get(compatibility_field)
            if compatibility and compatibility.get("component_id") == component_id and compatibility.get("provider") == series.get("provider"):
                alias_note = f'Canonical field; compatibility alias: {compatibility_field}'
        rows.append(
            f'<tr><td>{_escape(label)}</td><td><code>{_escape(field)}</code>'
            f'{f"<small>{_escape(alias_note)}</small>" if alias_note else ""}</td><td>{_escape(provider_source)}</td></tr>'
        )
    return "".join(rows)


def _telemetry_table(components: List[Dict[str, Any]], series_by_field: Dict[str, Dict[str, Any]]) -> str:
    rows = "".join(_telemetry_field_rows(component, series_by_field) for component in components)
    if not rows:
        return '<p class="muted compact">No telemetry fields recorded.</p>'
    return (
        '<div class="table-wrap"><table class="telemetry-map-table"><thead><tr>'
        '<th>Friendly sensor</th><th>Raw field</th><th>Provider/source</th>'
        f'</tr></thead><tbody>{rows}</tbody></table></div>'
    )


def _advanced_telemetry_mapping(
    components: List[Dict[str, Any]], chart_catalog: Dict[str, Any], stages: List[Dict[str, Any]],
) -> str:
    series = chart_catalog.get("series", []) if isinstance(chart_catalog.get("series"), list) else []
    providers = {
        str(metric.get("field")): str(metric.get("provider") or "")
        for stage in stages for metric in (stage.get("metrics", []) if isinstance(stage.get("metrics"), list) else [])
        if isinstance(metric, dict) and metric.get("field")
    }
    series_by_field = {
        str(item.get("field")): {**item, "provider": providers.get(str(item.get("field")), "")}
        for item in series if isinstance(item, dict) and item.get("field")
    }
    cpu = [item for item in components if item.get("component_class") in {"cpu", "cpu_package"}]
    cores = [item for item in components if item.get("component_class") == "cpu_core"]
    gpus = sorted(
        (item for item in components if item.get("component_class") == "gpu"),
        key=lambda item: int(str(item.get("component_id") or "0").rsplit(":", 1)[-1]),
    )
    memory = [item for item in components if item.get("component_class") in {"memory", "memory_module"}]
    storage = [item for item in components if item.get("component_class") == "storage"]
    bmc = [item for item in components if str(item.get("component_id") or "").startswith("bmc:")]
    platform = [
        item for item in components
        if item.get("component_class") in {"board", "nic", "wifi"}
    ]
    assigned = {id(item) for item in [*cpu, *cores, *gpus, *memory, *storage, *bmc, *platform]}
    other = [item for item in components if id(item) not in assigned]
    groups = []
    if cpu or cores:
        ordered_cores = sorted(
            cores, key=lambda item: int(str(item.get("component_id") or "0").rsplit(":", 1)[-1])
        )
        groups.append(("CPU", _telemetry_table([*cpu, *ordered_cores], series_by_field)))
    groups.extend((_short_component_label(str(item.get("component_id") or "")), _telemetry_table([item], series_by_field)) for item in gpus)
    if memory:
        groups.append(("Memory telemetry", _telemetry_table(memory, series_by_field)))
    if storage:
        groups.append(("Storage", _telemetry_table(storage, series_by_field)))
    if bmc:
        groups.append(("BMC / IPMI", _telemetry_table(bmc, series_by_field)))
    if platform:
        groups.append(("Platform sensors", _telemetry_table(platform, series_by_field)))
    if other:
        groups.append(("Other telemetry", _telemetry_table(other, series_by_field)))
    return "".join(
        f'<details class="telemetry-group nested-disclosure"><summary>{_escape(title)}</summary>'
        f'<div class="telemetry-group-body">{content}</div></details>'
        for title, content in groups
    ) or '<p class="muted compact">No telemetry mapping was recorded.</p>'


def _component_mapping(components: List[Dict[str, Any]], hardware: Dict[str, Any]) -> str:
    return f'''<details class="component-mapping secondary-disclosure"><summary>Component mapping</summary>
      <dl class="component-key-list">{_friendly_component_groups(components, hardware)}</dl>
    </details>'''


def _reference_tables(
    references: Dict[str, Any], components: List[Dict[str, Any]], chart_catalog: Dict[str, Any], stages: List[Dict[str, Any]],
) -> str:
    temperature_rows = "".join(
        "<tr>"
        f'<td><code>{_escape(item.get("field"))}</code><small>{_escape(item.get("component_id"))}</small></td>'
        f'<td>{_escape(item.get("provider"))}</td><td>{_number(item.get("warning_limit_c"), "c")}</td>'
        f'<td>{_number(item.get("critical_limit_c"), "c")}</td><td>{_escape(", ".join(f"{key}={value}" for key, value in sorted((item.get("provider_limits_c") or {}).items())))}</td><td>{_escape(item.get("source"))}</td></tr>'
        for item in references.get("temperature_limits", [])
    )
    temperatures = (
        f'<div class="table-wrap"><table><thead><tr><th>Metric</th><th>Provider</th><th>Warning</th><th>Critical/reference</th><th>Other limits</th><th>Source</th></tr></thead><tbody>{temperature_rows}</tbody></table></div>'
        if temperature_rows else '<p class="muted compact">No attributable temperature limits were recorded.</p>'
    )
    clock_rows = "".join(
        f'<tr><td>{_escape(item.get("component_id"))}</td><td>{_escape(item.get("provider"))}</td><td><code>{_escape(item.get("capability_semantics"))}</code></td><td>{_escape(", ".join(f"{key}={value}" for key, value in sorted(item.items()) if key not in {"component_id", "provider", "capability_semantics"}))}</td></tr>'
        for item in references.get("clock_capabilities", [])
    )
    clocks = (
        f'<div class="table-wrap"><table><thead><tr><th>Component</th><th>Provider</th><th>Semantics</th><th>Values</th></tr></thead><tbody>{clock_rows}</tbody></table></div>'
        if clock_rows else '<p class="muted compact">No provider-backed clock capability data was recorded.</p>'
    )
    return f'''<details class="hardware-references secondary-disclosure"><summary>Hardware references and advanced details</summary>
      <div class="disclosure-body"><h3>Temperature limits</h3>{temperatures}
      <h3>Clock capabilities</h3>{clocks}</div>
      <details class="advanced-telemetry-mapping secondary-disclosure"><summary>Advanced telemetry mapping</summary>
        <div class="advanced-group-list">{_advanced_telemetry_mapping(components, chart_catalog, stages)}</div>
      </details>
    </details>'''


def render_report_html(report: Dict[str, Any]) -> str:
    """Return safe, dependency-free HTML for one report-data payload."""
    run = report.get("run", {}) if isinstance(report.get("run"), dict) else {}
    review = report.get("review", {}) if isinstance(report.get("review"), dict) else {}
    hardware = report.get("hardware", {}) if isinstance(report.get("hardware"), dict) else {}
    components_list = report.get("components", []) if isinstance(report.get("components"), list) else []
    components = _component_index(components_list)
    stages = report.get("stages", []) if isinstance(report.get("stages"), list) else []
    report_outcome = str(run.get("report_outcome") or "UNKNOWN")
    status = _status_class(report_outcome)
    stage_cards = "".join(_stage_card(stage, components) for stage in stages) or '<div class="panel"><p class="muted">No executed stages were recorded.</p></div>'
    stage_details = "".join(_metric_table(stage, components) for stage in stages)
    stage_evidence = _stage_evidence(stages, review, report_outcome)
    title = str(run.get("profile_name") or "Linux Validation Suite result")
    run_description = str(run.get("description") or "").strip()
    description = (
        f'<p class="description">{_escape(run_description)}</p>'
        if run_description and _normalized_text(run_description) != _normalized_text(title) else ""
    )
    css = """
:root{color-scheme:light;--bg-page:#f3f5f8;--bg-surface:#fff;--bg-surface-muted:#f7f8fa;--border:#e3e7ee;--border-strong:#cbd2dd;--text:#1c2430;--text-muted:#6b7280;--primary:#2563eb;--success:#157347;--success-soft:#e7f6ec;--warning:#92610a;--warning-soft:#fdf3dd;--danger:#b42318;--danger-soft:#fbeaea;--info-soft:#eef1f6;--radius-sm:6px;--radius-md:10px}*{box-sizing:border-box}body{margin:0;background:var(--bg-page);color:var(--text);font:14px/1.45 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}.shell{width:min(1580px,calc(100% - 36px));margin:18px auto 48px}.topbar{margin-bottom:10px}h1{font-size:24px;margin:2px 0 3px}h2{font-size:17px;margin:0 0 8px}h3{font-size:14px;margin:0 0 6px}.description{color:var(--text-muted);max-width:900px;margin:0}.eyebrow{text-transform:uppercase;letter-spacing:.07em;font-size:11px;color:var(--text-muted);font-weight:700}.panel,.result-tile,.stage-card,.review-card{background:var(--bg-surface);border:1px solid var(--border);border-radius:var(--radius-md);box-shadow:0 1px 2px rgba(16,24,40,.06),0 1px 1px rgba(16,24,40,.04)}.panel{padding:13px 16px;margin-bottom:10px}.summary-grid{display:grid;grid-template-columns:minmax(280px,.72fr) minmax(0,1.28fr);gap:10px;margin-bottom:10px}.result-tile{padding:13px 16px;border-top:4px solid var(--border-strong)}.result-tile.pass{border-top-color:var(--success)}.result-tile.warning{border-top-color:var(--warning)}.result-tile.fail{border-top-color:var(--danger)}.result-value{display:flex;align-items:center;gap:10px;font-size:24px;font-weight:700;margin:3px 0}.run-meta{display:flex;flex-wrap:wrap;gap:5px 14px;color:var(--text-muted);font-size:.9em}.identity-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:0;margin-bottom:10px;align-items:start;background:var(--bg-surface);border:1px solid var(--border);border-radius:var(--radius-md)}.identity-card{padding:10px 14px;border:0;border-left:1px solid var(--border);border-radius:0;background:transparent;box-shadow:none}.identity-card:first-child{border-left:0}.identity-card h3{text-transform:uppercase;letter-spacing:.06em;font-size:11px;color:var(--text-muted)}.identity{display:grid;grid-template-columns:128px minmax(0,1fr);gap:5px 10px;margin:0}.identity dt{color:var(--text-muted);font-weight:600}.identity dd{margin:0;min-width:0;overflow-wrap:anywhere}.badge{display:inline-flex;align-items:center;border-radius:999px;padding:1px 9px;font-size:.82em;font-weight:600;background:var(--info-soft);color:var(--text-muted);white-space:nowrap}.badge.pass{background:var(--success-soft);color:var(--success)}.badge.warning{background:var(--warning-soft);color:var(--warning)}.badge.fail{background:var(--danger-soft);color:var(--danger)}.badge.info,.badge.aborted,.badge.unknown{background:var(--info-soft);color:var(--text-muted)}.review-clean{display:inline-flex;align-items:baseline;gap:10px;margin:0 0 8px;padding:5px 10px;border:1px solid var(--border);border-left:3px solid var(--success);border-radius:var(--radius-sm);background:var(--bg-surface);font-size:.9em}.review-clean span{color:var(--text-muted)}.review-card{padding:12px 16px;margin:6px 0 10px;border-left:4px solid var(--border-strong)}.review-card.warning{border-left-color:var(--warning)}.review-card.fail{border-left-color:var(--danger)}.review-card.info{border-left-color:var(--primary)}.review-primary{display:flex;gap:8px;align-items:center;margin-top:3px}.additional-findings{list-style:none;padding:0;margin:7px 0 0}.additional-findings li{display:flex;gap:8px;align-items:flex-start;padding:4px 0;border-top:1px solid var(--border)}.evidence-details{margin-top:7px}.section-heading{display:flex;align-items:baseline;justify-content:space-between;gap:12px;margin:14px 0 6px}.section-heading h2{margin:0}.section-note{color:var(--text-muted);font-size:.85em}.stage-evidence-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:10px;margin:6px 0 10px}.stage-evidence-card{border:1px solid var(--border);border-left:3px solid var(--border-strong);border-radius:var(--radius-sm);padding:8px 12px;background:var(--bg-surface)}.stage-evidence-card.status-warning{border-left-color:var(--warning)}.stage-evidence-card.status-fail{border-left-color:var(--danger)}.stage-evidence-card h3{display:flex;align-items:center;gap:7px;flex-wrap:wrap}.stage-evidence-card ul{margin:3px 0 0 17px;padding:0;font-size:.92em}.stage-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(440px,100%),1fr));gap:12px;margin:6px 0 10px;align-items:start}.stage-card{padding:10px 14px;border-left:4px solid var(--border-strong)}.stage-card.status-pass{border-left-color:var(--success)}.stage-card.status-warning{border-left-color:var(--warning)}.stage-card.status-fail{border-left-color:var(--danger)}.stage-heading{margin-bottom:2px}.stage-heading h3{font-size:15px;margin:1px 0;line-height:1.25}.stage-description{margin:1px 0 5px;color:var(--text-muted);font-size:.86em}.stage-meta{display:flex;justify-content:space-between;align-items:center;gap:10px;color:var(--text-muted);font-size:.85em;margin:0 0 7px}.component-metric-grid{font-size:.9em}.component-metric-head,.component-metric-row{display:grid;grid-template-columns:30fr 22fr 26fr 22fr;gap:6px 8px;align-items:stretch}.component-metric-head{color:var(--text-muted);font-size:.82em;font-weight:600;padding:0 4px 2px}.component-metric-row{margin-top:6px}.component-name,.metric-cell{display:flex;align-items:center;min-width:0;min-height:34px;background:var(--bg-surface-muted);border:1px solid var(--border);border-radius:var(--radius-sm);padding:6px 10px}.metric-cell{justify-content:flex-end;text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}.no-stage-metrics{padding-top:6px}.detail-disclosure,.secondary-disclosure,.nested-disclosure{border:1px solid var(--border);border-radius:var(--radius-md);background:var(--bg-surface);margin:10px 0;box-shadow:0 1px 2px rgba(16,24,40,.06),0 1px 1px rgba(16,24,40,.04)}.detail-disclosure>summary,.secondary-disclosure>summary,.nested-disclosure>summary{cursor:pointer;list-style:none;padding:9px 12px;font-size:.9em;font-weight:600}.detail-disclosure>summary::-webkit-details-marker,.secondary-disclosure>summary::-webkit-details-marker,.nested-disclosure>summary::-webkit-details-marker{display:none}.detail-disclosure>summary:before,.secondary-disclosure>summary:before,.nested-disclosure>summary:before{content:"▸";display:inline-block;width:16px;color:var(--text-muted)}.detail-disclosure[open]>summary:before,.secondary-disclosure[open]>summary:before,.nested-disclosure[open]>summary:before{content:"▾"}.detail-disclosure[open]>summary,.secondary-disclosure[open]>summary,.nested-disclosure[open]>summary{border-bottom:1px solid var(--border)}.secondary-disclosure{background:var(--bg-surface-muted);box-shadow:none}.secondary-disclosure>summary{color:var(--text-muted);font-size:.88em}.nested-disclosure{margin:6px 0;border-radius:var(--radius-sm);box-shadow:none}.nested-disclosure>summary{padding:7px 10px;font-size:.86em}.stage-metrics{margin:8px 0 0}.stage-metric-groups{padding:8px 10px}.metric-section{margin:0 0 9px}.metric-section h4{margin:0 0 2px;color:var(--text-muted);font-size:.78em;text-transform:uppercase;letter-spacing:.05em}.full-metric-grid{padding:0;font-size:.9em;overflow:auto}.full-metric-head,.full-metric-row{display:grid;grid-template-columns:28fr 20fr 17.34fr 17.33fr 17.33fr;gap:6px 8px;min-width:620px}.full-metric-head{color:var(--text-muted);font-size:.82em;font-weight:600;padding:0 4px 2px}.full-metric-row{margin-top:6px}.full-metric-cell{display:flex;flex-direction:column;justify-content:center;min-width:0;min-height:34px;padding:6px 10px;background:var(--bg-surface-muted);border:1px solid var(--border);border-radius:var(--radius-sm)}.full-metric-cell.num{align-items:flex-end;font-variant-numeric:tabular-nums;white-space:nowrap}.full-metric-cell small,.mapping-note{display:block;color:var(--text-muted);font-size:.8em;font-weight:400;overflow-wrap:anywhere}.metric-subgroup>.full-metric-grid{padding:8px}.component-key-list{margin:0;padding:8px 14px}.component-key-group{display:grid;grid-template-columns:128px minmax(0,1fr);gap:10px;border-top:1px solid var(--border);padding:6px 0}.component-key-group:first-child{border-top:0}.component-key-group dt{color:var(--text-muted);font-size:.78em;font-weight:700;text-transform:uppercase;letter-spacing:.05em}.component-key-group dd{margin:0}.component-key-group ul{list-style:none;margin:0;padding:0}.component-key-group li{display:grid;grid-template-columns:180px minmax(0,1fr);gap:10px;padding:3px 0}.component-key-group li strong{font-weight:600}.component-key-group li span{min-width:0;overflow-wrap:anywhere}.advanced-telemetry-mapping{margin:0 10px 10px;background:var(--bg-surface)}.advanced-group-list{padding:4px 10px 8px}.telemetry-group{background:var(--bg-surface-muted)}.telemetry-group-body{padding:2px 10px 7px}.telemetry-component{background:var(--bg-surface)}.telemetry-subgroup{background:var(--bg-surface)}.telemetry-field-list{list-style:none;margin:0;padding:6px 10px}.telemetry-field-list li{padding:4px 0;border-top:1px solid var(--border)}.telemetry-field-list li:first-child{border-top:0}.telemetry-field-list small{display:block;color:var(--text-muted);font-size:.82em;overflow-wrap:anywhere}.disclosure-body{padding:10px 14px}.disclosure-body h3{margin-top:10px}.disclosure-body h3:first-child{margin-top:0}.evidence-details .table-wrap{padding:0 10px 10px}.table-wrap{overflow:auto}table{border-collapse:collapse;width:100%;font-size:.86em}th,td{text-align:left;padding:7px 9px;border-bottom:1px solid var(--border);vertical-align:top}th{background:var(--bg-surface-muted);color:var(--text-muted);font-weight:600}td small{display:block;color:var(--text-muted);margin-top:2px}code{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:.9em;color:#475467}.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}.muted{color:var(--text-muted)}.compact{margin:4px 0}.telemetry-placeholder{background:var(--bg-surface-muted);border:1px solid var(--border);border-radius:var(--radius-sm);padding:10px 12px;color:var(--text-muted)}footer{color:var(--text-muted);font-size:.85em;text-align:center;margin-top:18px}@media(max-width:1100px){.identity-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.identity-card:nth-child(3){border-left:0;border-top:1px solid var(--border)}}@media(max-width:760px){.shell{width:min(100% - 20px,1580px);margin-top:12px}.summary-grid{display:block}.result-tile{margin-bottom:10px}.identity-grid{grid-template-columns:1fr}.identity-card,.identity-card:nth-child(3){border-left:0;border-top:1px solid var(--border)}.identity-card:first-child{border-top:0}.identity{grid-template-columns:105px minmax(0,1fr)}.component-metric-head,.component-metric-row{grid-template-columns:28fr 22fr 28fr 22fr;gap:4px}.component-name,.metric-cell{padding:6px}.review-primary{align-items:flex-start}.review-clean{display:flex;flex-direction:column;gap:1px}.section-heading{display:block}.section-note{display:block;margin-top:2px}.component-key-group{grid-template-columns:1fr}.component-key-group li{grid-template-columns:130px minmax(0,1fr)}}
"""
    css += """
html,body{max-width:100%;min-width:0}.shell{width:calc(100% - 48px);max-width:1650px;margin-inline:auto}.shell>*,.summary-grid>*,.identity-grid>*,.stage-grid>*,.stage-detail-panel,.stage-metric-groups,.metric-section,.component-key-group>*,.disclosure-body{min-width:0}.stage-grid{grid-template-columns:repeat(3,minmax(0,1fr))}.stage-card{min-width:0}.stage-card.active{border-color:var(--primary);border-left-color:var(--primary);box-shadow:0 0 0 2px rgba(37,99,235,.12)}.stage-detail-toggle,.stage-detail-close{font:inherit;color:var(--primary);background:transparent;border:0;padding:5px 0;cursor:pointer;font-size:.86em;font-weight:600}.stage-detail-toggle{margin-top:7px}.stage-detail-toggle:hover,.stage-detail-close:hover{text-decoration:underline}.stage-detail-region{display:none}.stage-detail-panel{grid-column:1/-1;width:100%;min-width:0;margin:0 0 2px;background:var(--bg-surface);border:1px solid var(--primary);border-left:4px solid var(--primary);border-radius:var(--radius-md);box-shadow:0 1px 2px rgba(16,24,40,.06),0 1px 1px rgba(16,24,40,.04)}.stage-detail-header{position:sticky;top:0;z-index:2;display:flex;align-items:flex-start;justify-content:space-between;gap:16px;padding:10px 14px;border-bottom:1px solid var(--border);background:#f7faff}.stage-detail-header h3{margin:1px 0}.stage-detail-header p{margin:1px 0;color:var(--text-muted);font-size:.88em}.stage-detail-actions{display:flex;align-items:center;gap:12px}.stage-detail-panel .stage-metric-groups{padding:10px 14px}.component-metric-head,.component-metric-row{grid-template-columns:minmax(0,1.45fr) minmax(0,.78fr) minmax(0,1.25fr) minmax(0,.78fr)}.component-metric-head>*{min-width:0}.component-name,.metric-cell{overflow:hidden}.full-metric-grid{width:100%;min-width:0;overflow:visible}.full-metric-head,.full-metric-row{width:100%;min-width:0;grid-template-columns:minmax(120px,.8fr) minmax(180px,1.5fr) repeat(3,minmax(76px,.52fr)) minmax(52px,.3fr)}.full-metric-group-label{margin:9px 0 2px;padding:4px 8px;border-bottom:1px solid var(--border);color:var(--text-muted);font-size:.78em;font-weight:700;text-transform:uppercase;letter-spacing:.05em}.full-metric-cell{overflow-wrap:anywhere}.full-metric-cell.num{white-space:nowrap;text-align:right}.full-metric-cell.samples{align-items:flex-end;font-variant-numeric:tabular-nums}.component-key-group li{grid-template-columns:minmax(220px,.85fr) minmax(0,1.8fr)}.component-key-group li strong,.component-key-group li span,.stage-description,.description{min-width:0;overflow-wrap:anywhere}.advanced-telemetry-mapping{margin:10px 0 0}.telemetry-map-table th:nth-child(1){width:28%}.telemetry-map-table th:nth-child(2){width:36%}.telemetry-map-table th:nth-child(3){width:36%}.table-wrap{min-width:0;overflow:visible}table{table-layout:fixed}th,td{overflow-wrap:anywhere}.telemetry-map-table code{overflow-wrap:anywhere;word-break:break-word}.identity-card,.panel,.result-tile,.review-card,.stage-card,.secondary-disclosure{max-width:100%}[hidden]{display:none!important}@media(max-width:1599px){.stage-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:1039px){.stage-grid{grid-template-columns:1fr}.identity-grid{grid-template-columns:1fr}.identity-card,.identity-card:nth-child(3){border-left:0;border-top:1px solid var(--border)}.identity-card:first-child{border-top:0}}@media(max-width:680px){.shell{width:calc(100% - 20px)}.summary-grid{display:block}.result-tile{margin-bottom:10px}.stage-detail-header{display:block}.stage-detail-actions{margin-top:6px}.component-metric-grid{font-size:.84em}.component-metric-head,.component-metric-row{gap:3px}.component-name,.metric-cell{padding:5px 4px}.full-metric-head{display:none}.full-metric-row{grid-template-columns:minmax(90px,.7fr) minmax(0,1.3fr);gap:4px;margin-top:8px}.full-metric-cell.num,.full-metric-cell.samples{grid-column:1/-1;display:flex;flex-direction:row;justify-content:space-between;align-items:center;min-height:28px}.full-metric-cell.num:nth-child(3):before{content:"Min";color:var(--text-muted)}.full-metric-cell.num:nth-child(4):before{content:"Average";color:var(--text-muted)}.full-metric-cell.num:nth-child(5):before{content:"Max";color:var(--text-muted)}.full-metric-cell.samples:before{content:"Samples";color:var(--text-muted)}.component-key-group li{grid-template-columns:1fr}.component-key-group li span{padding-left:0}.identity{grid-template-columns:105px minmax(0,1fr)}}
"""
    css += """
.summary-grid{align-items:stretch}.summary-grid>.result-tile,.summary-grid>.run-details{height:100%;margin-bottom:0}.result-tile{border:1px solid var(--border-strong);background:var(--info-soft)}.result-tile.pass{background:var(--success-soft);border-color:#b7dfc5}.result-tile.warning{background:var(--warning-soft);border-color:#ead59c}.result-tile.fail{background:var(--danger-soft);border-color:#efc2c2}.result-tile.aborted,.result-tile.unknown{background:var(--info-soft);border-color:var(--border-strong)}.result-value{display:block;font-size:26px;line-height:1.15;font-weight:750;margin:4px 0;color:var(--text)}.result-tile.pass .result-value{color:var(--success)}.result-tile.warning .result-value{color:var(--warning)}.result-tile.fail .result-value{color:var(--danger)}.run-details{background:var(--bg-surface);border-color:var(--border)}@media(max-width:760px){.summary-grid>.result-tile,.summary-grid>.run-details{height:auto}.summary-grid>.result-tile{margin-bottom:10px}}
"""
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{_escape(title)} — LVS report</title><style>{css}</style></head>
<body><main class="shell">
  <header class="topbar"><span class="eyebrow">Linux Validation Suite result</span><h1>{_escape(title)}</h1>{description}</header>
  <section class="summary-grid">
    <div class="result-tile {status}"><span class="eyebrow">Final result</span><div class="result-value">{_escape(report_outcome.replace("_", " "))}</div><p class="compact">Native outcome: <strong>{_escape(run.get("native_outcome") or "unknown")}</strong></p><div class="run-meta"><span>Duration {_escape(_duration(run.get("duration_seconds")))}</span><span>{_escape(len(stages))} stages</span><span>Run version: {_escape(run.get("lvs_version") or "unknown")}</span></div></div>
    <section class="panel run-details"><h2>Run details</h2><dl class="identity"><dt>Started</dt><dd>{_escape(_timestamp(run.get("started_at")))}</dd><dt>Ended</dt><dd>{_escape(_timestamp(run.get("ended_at")))}</dd><dt>Profile file</dt><dd>{_escape(run.get("profile_file") or "—")}</dd></dl></section>
  </section>
  <div class="section-heading"><h2>System identity</h2></div><section class="identity-grid">{_system_identity(hardware, components)}</section>
  <div class="section-heading"><h2>Review summary</h2></div>{_review_summary(review)}
  {stage_evidence}
  <div class="section-heading"><h2>Stage overview</h2><span class="section-note">Primary per-stage temperatures, clocks, and power</span></div><div class="stage-grid" aria-live="polite">{stage_cards}{stage_details}</div>
  <section class="panel telemetry-explorer"><h2>Telemetry explorer</h2><div class="telemetry-placeholder"><strong>Interactive stage telemetry</strong><br>Available in a later report version.</div></section>
  {_component_mapping(components_list, hardware)}
  {_reference_tables(report.get("hardware_references", {}), components_list, report.get("chart_catalog", {}), stages)}
  <footer>Report generated by {_escape(report.get("generator", {}).get("name") or "Linux Validation Suite")} {_escape(report.get("generator", {}).get("version") or "")} · Report data contract v{_escape(report.get("contract_version"))}</footer>
<script>(function(){{var grid=document.querySelector('.stage-grid');var cards=[].slice.call(document.querySelectorAll('.stage-card'));var buttons=[].slice.call(document.querySelectorAll('.stage-detail-toggle'));var panels=[].slice.call(document.querySelectorAll('.stage-detail-panel'));var selected=null;function place(panel,card){{var top=card.offsetTop;var row=cards.filter(function(item){{return item.offsetTop===top;}});var last=row[row.length-1]||card;last.insertAdjacentElement('afterend',panel);}}function closeAll(){{selected=null;panels.forEach(function(panel){{panel.hidden=true;}});cards.forEach(function(card){{card.classList.remove('active');}});buttons.forEach(function(button){{button.setAttribute('aria-expanded','false');button.textContent='Show full min/avg/max metrics';}});}}function open(button,panel){{var card=button.closest('.stage-card');selected={{button:button,panel:panel,card:card}};place(panel,card);panel.hidden=false;card.classList.add('active');button.setAttribute('aria-expanded','true');button.textContent='Hide full min/avg/max metrics';}}buttons.forEach(function(button){{button.addEventListener('click',function(){{var panel=document.getElementById(button.getAttribute('data-stage-detail'));var wasOpen=panel&&!panel.hidden;closeAll();if(panel&&!wasOpen){{open(button,panel);}}}});}});document.querySelectorAll('.stage-detail-close').forEach(function(button){{button.addEventListener('click',closeAll);}});var resizeFrame;window.addEventListener('resize',function(){{if(!selected)return;cancelAnimationFrame(resizeFrame);resizeFrame=requestAnimationFrame(function(){{place(selected.panel,selected.card);}});}});}})();</script>
</main></body></html>'''
