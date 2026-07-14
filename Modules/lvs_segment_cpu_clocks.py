from __future__ import annotations

import statistics
from typing import Any, Callable, Dict, List, Optional


Stats = Dict[str, Optional[float]]
MetricStatsFn = Callable[[List[Any], str], Stats]


class CpuClockMetricSectionBuilder:
    """Build parsed CPU core clock rows and aggregate clock summaries."""

    def __init__(self, *, metric_stats: MetricStatsFn) -> None:
        self._metric_stats = metric_stats

    def core_clock_entries(self, samples: List[Any], telemetry: Any) -> List[Dict[str, Any]]:
        source_by_key = {
            str(source.get("key", "")): source
            for source in getattr(telemetry, "_cpu_core_clock_sources", [])
            if source.get("key")
        }
        core_keys = sorted(
            {
                key
                for sample in samples
                for key in sample.values.keys()
                if key.startswith("cpu_core_") and key.endswith("_clock_mhz")
            },
            key=self.core_index_from_key,
        )
        entries: List[Dict[str, Any]] = []
        for key in core_keys:
            core_index = self.core_index_from_key(key)
            source = source_by_key.get(key, {})
            core_type = str(source.get("core_type", "P") or "P")
            core_class = str(source.get("core_class", "E-Core" if core_type == "E" else "P-Core") or "P-Core")
            physical_core_index = source.get("physical_core_index")
            entries.append(
                {
                    "Name": f"Core {core_index} Clock",
                    "Type": "Core",
                    "CoreType": core_type,
                    "CoreClass": core_class,
                    "CoreNumber": core_index,
                    "LogicalCpu": core_index,
                    "PhysicalCore": physical_core_index,
                    "PhysicalCoreKey": source.get("physical_core_key", ""),
                    "ThreadSiblings": source.get("thread_siblings", []),
                    "ClassificationSource": source.get("classification_source", "homogeneous_fallback"),
                    "ClassificationValue": source.get("classification_value"),
                    "Stats": self._metric_stats(samples, key),
                }
            )
        return entries

    def aggregate_core_clock_stats(self, core_entries: List[Dict[str, Any]]) -> Stats:
        mins = [entry["Stats"]["Min"] for entry in core_entries if entry["Stats"]["Min"] is not None]
        avgs = [entry["Stats"]["Avg"] for entry in core_entries if entry["Stats"]["Avg"] is not None]
        maxs = [entry["Stats"]["Max"] for entry in core_entries if entry["Stats"]["Max"] is not None]
        return {
            "Min": round(min(mins), 2) if mins else None,
            "Avg": round(statistics.mean(avgs), 2) if avgs else None,
            "Max": round(max(maxs), 2) if maxs else None,
        }

    def aggregate_core_clock_stats_by_type(
        self,
        core_entries: List[Dict[str, Any]],
        core_type: str,
    ) -> Stats:
        filtered = [
            entry
            for entry in core_entries
            if str(entry.get("CoreType", "") or "").upper() == core_type.upper()
        ]
        return self.aggregate_core_clock_stats(filtered) if filtered else self.empty_stats()

    def core_index_from_key(self, key: str) -> int:
        try:
            return int(key.removeprefix("cpu_core_").removesuffix("_clock_mhz"))
        except Exception:
            return 0

    def empty_stats(self) -> Stats:
        return {"Min": None, "Avg": None, "Max": None}
