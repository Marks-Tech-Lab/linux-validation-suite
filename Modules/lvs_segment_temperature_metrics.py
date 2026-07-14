from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional


Stats = Dict[str, Optional[float]]
MetricStatsFn = Callable[[List[Any], str], Stats]
GpuSortKeyFn = Callable[[int, Dict[int, int]], tuple[int, int]]
GpuNameFn = Callable[[int, Dict[int, str]], str]
GpuDisplayNameFn = Callable[[str, int, Optional[Dict[int, int]]], str]
GpuIndexFn = Callable[[str], int]


class TemperatureMetricSectionBuilder:
    """Build parsed temperature sections for memory, storage, and GPU sensors."""

    def __init__(
        self,
        *,
        metric_stats: MetricStatsFn,
        gpu_export_sort_key: GpuSortKeyFn,
        gpu_index_from_key: GpuIndexFn,
        gpu_display_name: GpuNameFn,
        duplicate_safe_gpu_name: GpuDisplayNameFn,
    ) -> None:
        self._metric_stats = metric_stats
        self._gpu_export_sort_key = gpu_export_sort_key
        self._gpu_index_from_key = gpu_index_from_key
        self._gpu_display_name = gpu_display_name
        self._duplicate_safe_gpu_name = duplicate_safe_gpu_name

    def memory_temp_entries(self, samples: List[Any], telemetry: Optional[Any] = None) -> List[Dict[str, Any]]:
        source_by_key = {
            str(source.get("key", "")): source
            for source in getattr(telemetry, "_memory_temp_sources", [])
            if source.get("key")
        }
        module_keys = sorted(
            {
                key
                for sample in samples
                for key in sample.values.keys()
                if key.startswith("memory_module_") and key.endswith("_temp_c")
            },
            key=self.memory_module_index_from_key,
        )
        entries: List[Dict[str, Any]] = []
        for key in module_keys:
            module_index = self.memory_module_index_from_key(key)
            source = source_by_key.get(key, {})
            sensor_name = str(source.get("label") or f"DIMM {module_index} SPD Hub")
            entries.append(
                {
                    "Name": f"DIMM {module_index}",
                    "SensorName": sensor_name,
                    "Source": str(source.get("kind") or "memory_temp"),
                    "Temperatures": self._metric_stats(samples, key),
                }
            )
        return entries

    def aggregate_memory_temp_stats(self, modules: List[Dict[str, Any]]) -> Stats:
        mins = [module["Temperatures"]["Min"] for module in modules if module["Temperatures"]["Min"] is not None]
        avgs = [module["Temperatures"]["Avg"] for module in modules if module["Temperatures"]["Avg"] is not None]
        maxs = [module["Temperatures"]["Max"] for module in modules if module["Temperatures"]["Max"] is not None]
        return {
            "Min": round(min(mins), 2) if mins else None,
            "Avg": round(max(avgs), 2) if avgs else None,
            "Max": round(max(maxs), 2) if maxs else None,
        }

    def storage_temp_entries(self, samples: List[Any], telemetry: Optional[Any]) -> List[Dict[str, Any]]:
        source_by_key = {
            str(source.get("key", "")): source
            for source in getattr(telemetry, "_storage_temp_sources", [])
            if source.get("key")
        }
        drive_keys = sorted(
            {
                key
                for sample in samples
                for key in sample.values.keys()
                if re.fullmatch(r"storage_drive_\d+_temp_c", key)
            },
            key=self.storage_drive_index_from_key,
        )
        entries: List[Dict[str, Any]] = []
        for key in drive_keys:
            source = source_by_key.get(key, {})
            drive_index = self.storage_drive_index_from_key(key)
            device_name = str(source.get("device_name") or source.get("block_name") or f"Storage {drive_index + 1}")
            sensor_name = str(source.get("label") or device_name)
            sensor_entries = self.storage_secondary_sensor_entries(samples, source_by_key, drive_index)
            entries.append(
                {
                    "DeviceName": device_name,
                    "Model": device_name,
                    "SensorName": sensor_name,
                    "BlockDevice": source.get("block_name", ""),
                    "Temperatures": self._metric_stats(samples, key),
                    "Sensors": sensor_entries,
                }
            )
        return entries

    def storage_secondary_sensor_entries(
        self,
        samples: List[Any],
        source_by_key: Dict[str, Dict[str, Any]],
        drive_index: int,
    ) -> List[Dict[str, Any]]:
        prefix = f"storage_drive_{drive_index}_sensor_"
        sensor_keys = sorted(
            {
                key
                for sample in samples
                for key in sample.values.keys()
                if key.startswith(prefix) and key.endswith("_temp_c")
            },
            key=self.storage_secondary_sensor_index_from_key,
        )
        entries: List[Dict[str, Any]] = []
        for key in sensor_keys:
            source = source_by_key.get(key, {})
            sensor_index = int(source.get("sensor_index") or self.storage_secondary_sensor_index_from_key(key))
            entries.append(
                {
                    "SensorIndex": sensor_index,
                    "SensorName": str(source.get("label") or f"Sensor {sensor_index}"),
                    "Source": str(source.get("kind") or "storage_temp_secondary"),
                    "Temperatures": self._metric_stats(samples, key),
                }
            )
        return entries

    def aggregate_storage_temp_stats(self, drives: List[Dict[str, Any]]) -> Dict[str, Optional[float]]:
        mins = [drive["Temperatures"]["Min"] for drive in drives if drive["Temperatures"]["Min"] is not None]
        avgs = [drive["Temperatures"]["Avg"] for drive in drives if drive["Temperatures"]["Avg"] is not None]
        maxs = [drive["Temperatures"]["Max"] for drive in drives if drive["Temperatures"]["Max"] is not None]
        return {
            "Min": round(min(mins), 2) if mins else None,
            "Avg": round(max(avgs), 2) if avgs else None,
            "Max": round(max(maxs), 2) if maxs else None,
            "DriveCount": len(drives),
        }

    def gpu_temperature_groups(
        self,
        samples: List[Any],
        gpu_names: Dict[int, str],
        gpu_order: Dict[int, int],
    ) -> Dict[str, Any]:
        return {
            "Core": self.gpu_temp_group(samples, "temp_core_c", "edge", gpu_names, gpu_order),
            "Hotspot": self.gpu_temp_group(samples, "temp_hotspot_c", "junction", gpu_names, gpu_order),
            "Memory": self.gpu_temp_group(samples, "temp_memory_c", "mem", gpu_names, gpu_order),
        }

    def gpu_temp_group(
        self,
        samples: List[Any],
        suffix: str,
        sensor_label: str,
        gpu_names: Dict[int, str],
        gpu_order: Dict[int, int],
    ) -> Dict[str, Any]:
        gpu_keys = sorted(
            {
                key
                for sample in samples
                for key in sample.values.keys()
                if key.startswith("gpu_") and key.endswith(suffix)
            },
            key=lambda key: self._gpu_export_sort_key(self._gpu_index_from_key(key), gpu_order),
        )
        gpus = []
        max_values = []
        for key in gpu_keys:
            gpu_index = self._gpu_index_from_key(key)
            stats = self._metric_stats(samples, key)
            if stats["Max"] is not None:
                max_values.append(stats["Max"])
            display_name = self._gpu_display_name(gpu_index, gpu_names)
            duplicate_safe_name = self._duplicate_safe_gpu_name(display_name, gpu_index, gpu_order)
            gpus.append(
                {
                    "GpuIndex": gpu_index,
                    "Name": duplicate_safe_name,
                    "BaseName": display_name,
                    "DisplayName": duplicate_safe_name,
                    "SensorName": sensor_label,
                    "Temperatures": stats,
                }
            )
        return {
            "Max": round(max(max_values), 2) if max_values else None,
            "Gpus": gpus,
        }

    def storage_drive_index_from_key(self, key: str) -> int:
        try:
            return int(key.removeprefix("storage_drive_").removesuffix("_temp_c"))
        except Exception:
            return 0

    def storage_secondary_sensor_index_from_key(self, key: str) -> int:
        match = re.search(r"_sensor_(\d+)_temp_c$", key)
        if not match:
            return 0
        try:
            return int(match.group(1))
        except Exception:
            return 0

    def memory_module_index_from_key(self, key: str) -> int:
        try:
            return int(key.removeprefix("memory_module_").removesuffix("_temp_c"))
        except Exception:
            return 0
