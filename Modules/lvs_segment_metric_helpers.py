from __future__ import annotations

import re
import statistics
from typing import Any, Dict, List, Optional


Stats = Dict[str, Optional[float]]


class SegmentMetricHelper:
    """Generic sample filtering and metric-stat helpers for segment parsers."""

    def samples_for_window(self, samples: List[Any], window: Any) -> List[Any]:
        return [sample for sample in samples if window.analysis_start <= sample.timestamp <= window.analysis_end]

    def metric_max(self, samples: List[Any], key: str) -> Optional[float]:
        vals = self.metric_values_for_stats(samples, key)
        return round(max(vals), 2) if vals else None

    def metric_avg(self, samples: List[Any], key: str) -> Optional[float]:
        vals = self.metric_values_for_stats(samples, key)
        return round(statistics.mean(vals), 2) if vals else None

    def metric_min(self, samples: List[Any], key: str) -> Optional[float]:
        vals = self.metric_values_for_stats(samples, key)
        return round(min(vals), 2) if vals else None

    def metric_stats(self, samples: List[Any], key: str) -> Stats:
        return {
            "Min": self.metric_min(samples, key),
            "Avg": self.metric_avg(samples, key),
            "Max": self.metric_max(samples, key),
        }

    def metric_values_for_stats(self, samples: List[Any], key: str) -> List[float]:
        vals = [float(sample.values[key]) for sample in samples if sample.values.get(key) is not None]
        if not re.match(r"^gpu_\d+_clock_mhz$", key) or len(vals) < 8:
            return vals
        positive = [value for value in vals if value > 0]
        if len(positive) < 8:
            return vals
        median = statistics.median(positive)
        if median < 500.0:
            return vals
        low_threshold = max(100.0, median * 0.25)
        low_count = sum(1 for value in positive if value < low_threshold)
        if low_count == 0:
            return vals
        if low_count <= max(1, int(len(positive) * 0.03)):
            filtered = [value for value in vals if value <= 0 or value >= low_threshold]
            if filtered:
                return filtered
        return vals

    def empty_metric_stats(self) -> Stats:
        return {"Min": None, "Avg": None, "Max": None}

    def empty_stats(self) -> Stats:
        return {"Min": None, "Avg": None, "Max": None}

    def should_blank_gpu_power_stats(
        self,
        gpu_index: int,
        gpu_device_classes: Dict[int, str],
        power_stats: Stats,
    ) -> bool:
        device_class = str(gpu_device_classes.get(gpu_index) or "").strip().lower()
        if device_class not in {"integrated", "apu"}:
            return False
        max_power = power_stats.get("Max")
        if max_power is None:
            return False
        try:
            return float(max_power) < 1.0
        except Exception:
            return False

    def metric_sustain_summary(
        self,
        samples: List[Any],
        key: str,
        thresholds: Optional[List[float]] = None,
    ) -> Dict[str, Any]:
        thresholds = thresholds or [50.0, 75.0, 90.0, 95.0]
        points = [
            (sample.timestamp, sample.values.get(key))
            for sample in samples
            if sample.values.get(key) is not None
        ]
        values = [float(value) for _, value in points if value is not None]
        if not values:
            return {
                "SampleCount": 0,
                "StdDev": None,
                "Range": None,
                "Thresholds": [],
            }
        sample_span_seconds = 0.0
        if len(points) > 1:
            sample_span_seconds = max(0.0, float(points[-1][0]) - float(points[0][0]))
        threshold_entries: List[Dict[str, Any]] = []
        for threshold in thresholds:
            count = sum(1 for value in values if value >= threshold)
            percent = (count / len(values)) * 100.0
            threshold_entries.append(
                {
                    "Threshold": round(threshold, 2),
                    "SamplesAtOrAbove": count,
                    "PercentAtOrAbove": round(percent, 2),
                    "EstimatedSecondsAtOrAbove": round(sample_span_seconds * (percent / 100.0), 2),
                }
            )
        return {
            "SampleCount": len(values),
            "StdDev": round(statistics.pstdev(values), 2) if len(values) > 1 else 0.0,
            "Range": round(max(values) - min(values), 2),
            "Thresholds": threshold_entries,
        }
