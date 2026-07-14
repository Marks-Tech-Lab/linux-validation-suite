from __future__ import annotations

import statistics
from typing import Any, Callable, Dict, List, Optional


Stats = Dict[str, Optional[float]]
MetricStatsFn = Callable[[List[Any], str], Stats]
MetricSustainFn = Callable[..., Dict[str, Any]]
GpuNameFn = Callable[[int, Dict[int, str]], str]
GpuDisplayNameFn = Callable[[str, int, Optional[Dict[int, int]]], str]
GpuPowerBlankFn = Callable[[int, Dict[int, str], Stats], bool]


class GpuMetricSectionBuilder:
    """Build parsed GPU metric rows and aggregate summaries.

    Target discovery remains in SegmentParser because it combines stage worker
    payloads with inventory identity. This class owns the reusable parsed metric
    contract produced after targeting is known.
    """

    def __init__(
        self,
        *,
        metric_stats: MetricStatsFn,
        metric_sustain_summary: MetricSustainFn,
        gpu_display_name: GpuNameFn,
        duplicate_safe_gpu_name: GpuDisplayNameFn,
        should_blank_gpu_power_stats: GpuPowerBlankFn,
    ) -> None:
        self._metric_stats = metric_stats
        self._metric_sustain_summary = metric_sustain_summary
        self._gpu_display_name = gpu_display_name
        self._duplicate_safe_gpu_name = duplicate_safe_gpu_name
        self._should_blank_gpu_power_stats = should_blank_gpu_power_stats

    def metric_entries(
        self,
        samples: List[Any],
        gpu_names: Dict[int, str],
        gpu_order: Dict[int, int],
        gpu_targeting: List[Dict[str, Any]],
        gpu_device_classes: Dict[int, str],
    ) -> List[Dict[str, Any]]:
        targeting_map = {
            int(entry.get("GpuIndex", 0)): entry
            for entry in gpu_targeting
        }
        observed_indices = {
            self._gpu_index_from_key(key)
            for sample in samples
            for key in sample.values.keys()
            if key.startswith("gpu_")
        }
        gpu_indices = sorted(
            observed_indices | set(targeting_map.keys()),
            key=lambda gpu_index: (
                int((targeting_map.get(gpu_index) or {}).get("InventoryOrder", gpu_order.get(gpu_index, gpu_index))),
                gpu_index,
            ),
        )
        entries: List[Dict[str, Any]] = []
        for gpu_index in gpu_indices:
            clock_stats = self._metric_stats(samples, f"gpu_{gpu_index}_clock_mhz")
            memory_clock_stats = self._metric_stats(samples, f"gpu_{gpu_index}_memory_clock_mhz")
            power_stats = self._metric_stats(samples, f"gpu_{gpu_index}_power_w")
            if self._should_blank_gpu_power_stats(gpu_index, gpu_device_classes, power_stats):
                power_stats = self._empty_metric_stats()
            usage_stats = self._metric_stats(samples, f"gpu_{gpu_index}_busy_percent")
            memory_usage_stats = self._metric_stats(samples, f"gpu_{gpu_index}_memory_busy_percent")
            vram_used_stats = self._metric_stats(samples, f"gpu_{gpu_index}_vram_used_gb")
            usage_sustain = self._metric_sustain_summary(samples, f"gpu_{gpu_index}_busy_percent")
            memory_usage_sustain = self._metric_sustain_summary(
                samples,
                f"gpu_{gpu_index}_memory_busy_percent",
                thresholds=[10.0, 25.0, 50.0, 75.0, 90.0, 95.0],
            )
            has_metric_values = any(
                value is not None
                for value in (
                    *clock_stats.values(),
                    *memory_clock_stats.values(),
                    *power_stats.values(),
                    *usage_stats.values(),
                    *memory_usage_stats.values(),
                    *vram_used_stats.values(),
                )
            )
            targeting = targeting_map.get(gpu_index, {})
            if not has_metric_values and not targeting.get("Targeted"):
                continue
            worker_evidence = dict(targeting.get("WorkerEvidence") or {})
            load_quality = self._gpu_load_quality(usage_stats, usage_sustain)
            if not has_metric_values and targeting.get("Targeted"):
                worker_count = int(worker_evidence.get("WorkerResultCount") or 0)
                worker_errors = int(worker_evidence.get("WorkerErrorCount") or 0)
                successful_workers = int(worker_evidence.get("SuccessfulWorkerResultCount") or 0)
                verification_passes = int(worker_evidence.get("VerificationPasses") or 0)
                if worker_errors > 0:
                    load_quality = "worker_error_no_telemetry"
                elif worker_count > 0 and successful_workers == worker_count and verification_passes > 0:
                    load_quality = "verified_no_telemetry"
            display_name = str(targeting.get("Name") or self._gpu_display_name(gpu_index, gpu_names))
            entries.append(
                {
                    "GpuIndex": gpu_index,
                    "Name": display_name,
                    "DisplayName": str(targeting.get("DisplayName") or self._duplicate_safe_gpu_name(display_name, gpu_index, gpu_order)),
                    "InventoryOrder": targeting.get("InventoryOrder", gpu_order.get(gpu_index, gpu_index)),
                    "Targeted": bool(targeting.get("Targeted", False)),
                    "ObservationRole": str(targeting.get("ObservationRole", "observed_only")),
                    "ObservedInTelemetry": bool(targeting.get("ObservedInTelemetry", False)) or gpu_index in observed_indices,
                    "TelemetryMissing": not has_metric_values,
                    "TargetIds": list(targeting.get("TargetIds", [])),
                    "Cards": list(targeting.get("Cards", [])),
                    "Slots": list(targeting.get("Slots", [])),
                    "Workloads": list(targeting.get("Workloads", [])),
                    "Backends": list(targeting.get("Backends", [])),
                    "ResolvedDeviceNames": list(targeting.get("ResolvedDeviceNames", [])),
                    "WorkerEvidence": worker_evidence,
                    "Clock": clock_stats,
                    "MemoryClock": memory_clock_stats,
                    "Power": power_stats,
                    "Usage": usage_stats,
                    "UsageSustain": usage_sustain,
                    "LoadQuality": load_quality,
                    "MemoryUsage": memory_usage_stats,
                    "MemoryUsageSustain": memory_usage_sustain,
                    "VramUsedGB": vram_used_stats,
                    "PowerSensorName": "power",
                    "PowerCategory": "board",
                }
            )
        return entries

    def aggregate_metric_stats(self, gpu_metrics: List[Dict[str, Any]], field: str) -> Stats:
        mins = [metric[field]["Min"] for metric in gpu_metrics if metric[field]["Min"] is not None]
        avgs = [metric[field]["Avg"] for metric in gpu_metrics if metric[field]["Avg"] is not None]
        maxs = [metric[field]["Max"] for metric in gpu_metrics if metric[field]["Max"] is not None]
        return {
            "Min": round(min(mins), 2) if mins else None,
            "Avg": round(max(avgs), 2) if avgs else None,
            "Max": round(max(maxs), 2) if maxs else None,
        }

    def aggregate_sustain_summary(
        self,
        gpu_metrics: List[Dict[str, Any]],
        field: str,
    ) -> Dict[str, Any]:
        threshold_groups: Dict[float, List[float]] = {}
        sample_counts: List[int] = []
        ranges: List[float] = []
        stddevs: List[float] = []
        for metric in gpu_metrics:
            sustain = metric.get(field)
            if not isinstance(sustain, dict):
                continue
            sample_count = sustain.get("SampleCount")
            if not isinstance(sample_count, (int, float)) or int(sample_count) <= 0:
                continue
            sample_counts.append(int(sample_count))
            range_value = sustain.get("Range")
            if isinstance(range_value, (int, float)):
                ranges.append(float(range_value))
            stddev = sustain.get("StdDev")
            if isinstance(stddev, (int, float)):
                stddevs.append(float(stddev))
            for threshold_entry in sustain.get("Thresholds", []):
                if not isinstance(threshold_entry, dict):
                    continue
                threshold = threshold_entry.get("Threshold")
                percent = threshold_entry.get("PercentAtOrAbove")
                if not isinstance(threshold, (int, float)) or not isinstance(percent, (int, float)):
                    continue
                threshold_groups.setdefault(float(threshold), []).append(float(percent))
        thresholds = []
        for threshold in sorted(threshold_groups):
            values = threshold_groups[threshold]
            thresholds.append(
                {
                    "Threshold": round(threshold, 2),
                    "MinPercentAtOrAbove": round(min(values), 2),
                    "AvgPercentAtOrAbove": round(statistics.mean(values), 2),
                    "MaxPercentAtOrAbove": round(max(values), 2),
                }
            )
        return {
            "GpuCount": len(gpu_metrics),
            "MinSampleCount": min(sample_counts) if sample_counts else 0,
            "MaxRange": round(max(ranges), 2) if ranges else None,
            "MaxStdDev": round(max(stddevs), 2) if stddevs else None,
            "Thresholds": thresholds,
        }

    def load_quality_counts(self, gpu_metrics: List[Dict[str, Any]]) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for metric in gpu_metrics:
            quality = str(metric.get("LoadQuality") or "unknown")
            counts[quality] = counts.get(quality, 0) + 1
        return dict(sorted(counts.items()))

    def observation_summary(
        self,
        gpu_targeting: List[Dict[str, Any]],
        gpu_metrics: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        targeted = [entry for entry in gpu_targeting if entry.get("Targeted")]
        observed_only = [entry for entry in gpu_targeting if not entry.get("Targeted")]
        targeted_metrics = [entry for entry in gpu_metrics if entry.get("Targeted")]
        observed_only_metrics = [entry for entry in gpu_metrics if not entry.get("Targeted")]
        return {
            "TargetedGpuCount": len(targeted),
            "ObservedOnlyGpuCount": len(observed_only),
            "TargetedGpuIndices": [int(entry.get("GpuIndex", 0)) for entry in targeted],
            "ObservedOnlyGpuIndices": [int(entry.get("GpuIndex", 0)) for entry in observed_only],
            "TargetedUsageMax": self.aggregate_metric_stats(targeted_metrics, "Usage")["Max"],
            "TargetedUsageSustain": self.aggregate_sustain_summary(targeted_metrics, "UsageSustain"),
            "TargetedLoadQualityCounts": self.load_quality_counts(targeted_metrics),
            "ObservedOnlyUsageMax": self.aggregate_metric_stats(observed_only_metrics, "Usage")["Max"],
            "ObservedOnlyUsageSustain": self.aggregate_sustain_summary(observed_only_metrics, "UsageSustain"),
            "ObservedOnlyLoadQualityCounts": self.load_quality_counts(observed_only_metrics),
            "TargetedPowerAvg": self.aggregate_metric_stats(targeted_metrics, "Power")["Avg"],
            "TargetedPowerMax": self.aggregate_metric_stats(targeted_metrics, "Power")["Max"],
            "ObservedOnlyPowerAvg": self.aggregate_metric_stats(observed_only_metrics, "Power")["Avg"],
            "ObservedOnlyPowerMax": self.aggregate_metric_stats(observed_only_metrics, "Power")["Max"],
            "TargetedMemoryUsageMax": self.aggregate_metric_stats(targeted_metrics, "MemoryUsage")["Max"],
            "TargetedMemoryUsageSustain": self.aggregate_sustain_summary(targeted_metrics, "MemoryUsageSustain"),
            "ObservedOnlyMemoryUsageMax": self.aggregate_metric_stats(observed_only_metrics, "MemoryUsage")["Max"],
            "ObservedOnlyMemoryUsageSustain": self.aggregate_sustain_summary(observed_only_metrics, "MemoryUsageSustain"),
            "TargetedVramUsedMaxGB": self.aggregate_metric_stats(targeted_metrics, "VramUsedGB")["Max"],
            "ObservedOnlyVramUsedMaxGB": self.aggregate_metric_stats(observed_only_metrics, "VramUsedGB")["Max"],
        }

    def _gpu_load_quality(self, usage_stats: Stats, usage_sustain: Dict[str, Any]) -> str:
        if not usage_stats.get("Max") and not usage_sustain.get("SampleCount"):
            return "unobserved"
        avg = usage_stats.get("Avg")
        pct_75 = self._threshold_percent(usage_sustain, 75.0)
        pct_90 = self._threshold_percent(usage_sustain, 90.0)
        pct_95 = self._threshold_percent(usage_sustain, 95.0)
        if avg is not None and avg >= 95.0 and pct_95 is not None and pct_95 >= 95.0:
            return "sustained_extreme"
        if avg is not None and avg >= 90.0 and pct_90 is not None and pct_90 >= 85.0:
            return "sustained_high"
        if pct_75 is not None and pct_75 >= 95.0 and avg is not None and avg >= 85.0:
            return "variable_high"
        if avg is not None and avg >= 60.0:
            return "moderate_or_variable"
        return "low_or_idle"

    def _threshold_percent(self, sustain: Dict[str, Any], threshold: float) -> Optional[float]:
        for entry in sustain.get("Thresholds", []):
            if not isinstance(entry, dict):
                continue
            entry_threshold = entry.get("Threshold")
            if not isinstance(entry_threshold, (int, float)):
                continue
            if abs(float(entry_threshold) - float(threshold)) > 0.001:
                continue
            percent = entry.get("PercentAtOrAbove")
            return float(percent) if isinstance(percent, (int, float)) else None
        return None

    def _empty_metric_stats(self) -> Stats:
        return {"Min": None, "Avg": None, "Max": None}

    def _gpu_index_from_key(self, key: str) -> int:
        try:
            return int(key.removeprefix("gpu_").split("_", 1)[0])
        except Exception:
            return 0
