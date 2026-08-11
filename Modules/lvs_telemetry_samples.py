from __future__ import annotations

"""Telemetry sample row and CSV persistence helpers.

These helpers define the raw telemetry row contract independently from live
hardware discovery so future QA/import tooling can reuse the same shape without
constructing a ``TelemetryCollector``.
"""

import csv
import re
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional


@dataclass
class Sample:
    timestamp: float
    values: Dict[str, Optional[float]]


_DYNAMIC_GPU_VRAM_GB_FIELD = re.compile(r"^gpu_\d+_vram_used_gb$")
_CPU_CORE_UTILIZATION_FIELD = re.compile(r"^cpu_core_(\d+)_utilization_percent$")
_EXTENDED_FIXED_TELEMETRY_FIELDS = (
    "memory_temp_c",
    "llcc_correctable_error_count",
    "llcc_uncorrectable_error_count",
)


def telemetry_unit_alias_name(field_name: str) -> Optional[str]:
    """Return the additive GiB alias for a legacy binary-GiB field."""
    if field_name == "memory_used_gb":
        return "memory_used_gib"
    if field_name == "gpu_vram_used_gb":
        return "gpu_vram_used_gib"
    if _DYNAMIC_GPU_VRAM_GB_FIELD.fullmatch(field_name):
        return f"{field_name[:-3]}_gib"
    return None


def telemetry_values_with_unit_aliases(
    values: Dict[str, Optional[float]],
) -> Dict[str, Optional[float]]:
    """Copy telemetry values and add unit-correct aliases from legacy fields."""
    aliased = dict(values)
    for field_name, value in values.items():
        alias_name = telemetry_unit_alias_name(field_name)
        if alias_name:
            aliased[alias_name] = value
    return aliased


def telemetry_csv_fieldnames(samples: Iterable[Sample]) -> List[str]:
    dynamic_fields = sorted(
        {
            key
            for sample in samples
            for key in telemetry_values_with_unit_aliases(sample.values).keys()
        }
    )
    return ["timestamp", *dynamic_fields]


def telemetry_sample_row(sample: Sample) -> Dict[str, Optional[float]]:
    row: Dict[str, Optional[float]] = {"timestamp": sample.timestamp}
    row.update(telemetry_values_with_unit_aliases(sample.values))
    return row


def write_telemetry_csv(samples: Iterable[Sample], path: Path) -> None:
    rows = list(samples)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=telemetry_csv_fieldnames(rows))
        writer.writeheader()
        for sample in rows:
            writer.writerow(telemetry_sample_row(sample))


def telemetry_metric_summaries(
    samples: Iterable[Sample],
    field_names: Iterable[str],
) -> Dict[str, Dict[str, Optional[float] | int]]:
    """Build additive snake_case summaries for selected extended metrics."""
    rows = list(samples)
    summaries: Dict[str, Dict[str, Optional[float] | int]] = {}
    for field_name in field_names:
        values = [
            float(sample.values[field_name])
            for sample in rows
            if sample.values.get(field_name) is not None
        ]
        summaries[str(field_name)] = {
            "sample_count": len(values),
            "minimum": round(min(values), 2) if values else None,
            "average": round(statistics.mean(values), 2) if values else None,
            "maximum": round(max(values), 2) if values else None,
        }
    return summaries


def cpu_utilization_metric_field_names(samples: Iterable[Sample]) -> List[str]:
    """Return aggregate plus observed canonical per-core utilization fields."""
    rows = list(samples)
    per_core = {
        key
        for sample in rows
        for key in sample.values
        if _CPU_CORE_UTILIZATION_FIELD.fullmatch(str(key))
    }
    return [
        "cpu_utilization_percent",
        *sorted(per_core, key=lambda key: int(_CPU_CORE_UTILIZATION_FIELD.fullmatch(key).group(1))),
    ]


def extended_telemetry_metric_field_names(samples: Iterable[Sample]) -> List[str]:
    """Return additive metrics owned by the extended result contract."""
    rows = list(samples)
    observed = {str(key) for sample in rows for key in sample.values}
    return [
        *cpu_utilization_metric_field_names(rows),
        *(field for field in _EXTENDED_FIXED_TELEMETRY_FIELDS if field in observed),
    ]
