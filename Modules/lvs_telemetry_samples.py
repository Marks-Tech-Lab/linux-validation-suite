from __future__ import annotations

"""Telemetry sample row and CSV persistence helpers.

These helpers define the raw telemetry row contract independently from live
hardware discovery so future QA/import tooling can reuse the same shape without
constructing a ``TelemetryCollector``.
"""

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional


@dataclass
class Sample:
    timestamp: float
    values: Dict[str, Optional[float]]


def telemetry_csv_fieldnames(samples: Iterable[Sample]) -> List[str]:
    dynamic_fields = sorted(
        {
            key
            for sample in samples
            for key in sample.values.keys()
        }
    )
    return ["timestamp", *dynamic_fields]


def telemetry_sample_row(sample: Sample) -> Dict[str, Optional[float]]:
    row: Dict[str, Optional[float]] = {"timestamp": sample.timestamp}
    row.update(sample.values)
    return row


def write_telemetry_csv(samples: Iterable[Sample], path: Path) -> None:
    rows = list(samples)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=telemetry_csv_fieldnames(rows))
        writer.writeheader()
        for sample in rows:
            writer.writerow(telemetry_sample_row(sample))
