from __future__ import annotations

"""Telemetry sample row and CSV persistence helpers.

These helpers define the raw telemetry row contract independently from live
hardware discovery so future QA/import tooling can reuse the same shape without
constructing a ``TelemetryCollector``.
"""

import csv
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional


@dataclass
class Sample:
    timestamp: float
    values: Dict[str, Optional[float]]


_DYNAMIC_GPU_VRAM_GB_FIELD = re.compile(r"^gpu_\d+_vram_used_gb$")


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
