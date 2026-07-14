from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional


Stats = Dict[str, Optional[float]]
MetricStatsFn = Callable[[List[Any], str], Stats]
AggregateClockStatsFn = Callable[[List[Dict[str, Any]]], Stats]


class CpuMetricSectionBuilder:
    """Build the shared CPU parsed-output contract.

    Cpu.Combined is a summary/compatibility section that mirrors the legacy
    aggregate fields. Existing legacy/v3 consumers should keep reading
    Temperatures.Cpu, Power.Cpu, and Clocks.AllCoreAverage.

    Cpu.Packages is additive and appears only when multi-package topology and
    telemetry support it. Package metric targets are stable strings such as
    package_0 and package_1. Combined CPU power is the package sum when
    package power telemetry exists; combined CPU temperature is the safety
    aggregate / hottest-package proxy; combined all-core clock averages across
    observed logical CPUs and can mask per-socket throttling. Package clock is
    emitted only when core clock source metadata includes package/core identity.
    raw_telemetry.csv remains fallback/debug evidence, not the normal
    downstream interface for package temp/power.
    """

    def __init__(
        self,
        *,
        metric_stats: MetricStatsFn,
        aggregate_core_clock_stats: AggregateClockStatsFn,
    ) -> None:
        self._metric_stats = metric_stats
        self._aggregate_core_clock_stats = aggregate_core_clock_stats

    def metric_section(
        self,
        samples: List[Any],
        core_entries: List[Dict[str, Any]],
        package_metadata: Dict[str, Any],
        *,
        temp_stats: Stats,
        power_stats: Stats,
        all_core_clock_stats: Stats,
    ) -> Dict[str, Any]:
        section: Dict[str, Any] = {
            "Combined": {
                "Temp": temp_stats,
                "Power": power_stats,
                "AllCoreAverageClock": all_core_clock_stats,
            }
        }
        packages = self._package_metric_entries(samples, core_entries, package_metadata)
        if packages:
            section["Packages"] = packages
        return section

    def package_metadata(self, cpu_info: Dict[str, Any]) -> Dict[str, Any]:
        if isinstance(cpu_info.get("Hardware"), dict):
            hardware_cpu = cpu_info.get("Hardware", {}).get("Cpu", {})
            if isinstance(hardware_cpu, dict):
                cpu_info = hardware_cpu
        topology = cpu_info.get("Topology", {}) if isinstance(cpu_info.get("Topology"), dict) else {}
        package_count = self._safe_int_value(topology.get("PackageCount") or cpu_info.get("PackageCount")) or 0
        packages: Dict[int, Dict[str, Any]] = {}
        for collection_name in ("PackageDevices",):
            collection = cpu_info.get(collection_name)
            if isinstance(collection, list):
                self._merge_package_records(packages, collection)
        topology_packages = topology.get("Packages")
        if isinstance(topology_packages, list):
            self._merge_package_records(packages, topology_packages)
        if not package_count and packages:
            package_count = len(packages)
        return {"package_count": package_count, "packages": packages}

    def _package_metric_entries(
        self,
        samples: List[Any],
        core_entries: List[Dict[str, Any]],
        package_metadata: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        telemetry_package_ids = self._package_ids_from_samples(samples)
        metadata_packages = package_metadata.get("packages") if isinstance(package_metadata.get("packages"), dict) else {}
        metadata_package_ids = set(metadata_packages.keys())
        package_count = int(package_metadata.get("package_count") or 0)
        if package_count <= 1 and len(telemetry_package_ids) <= 1:
            return []
        package_ids = sorted(metadata_package_ids | telemetry_package_ids)
        entries: List[Dict[str, Any]] = []
        for package_id in package_ids:
            meta = metadata_packages.get(package_id, {})
            temp_stats = self._metric_stats(samples, f"cpu_package_{package_id}_temp_c")
            power_stats = self._metric_stats(samples, f"cpu_package_{package_id}_power_w")
            clock_stats = self._package_clock_stats(core_entries, package_id)
            if not (
                self._stats_have_values(temp_stats)
                or self._stats_have_values(power_stats)
                or self._stats_have_values(clock_stats)
            ):
                continue
            entries.append(
                {
                    "PackageId": package_id,
                    "MetricTarget": f"package_{package_id}",
                    "Name": str(meta.get("Name") or f"CPU Package {package_id}"),
                    "Temp": temp_stats,
                    "Power": power_stats,
                    "Clock": clock_stats,
                }
            )
        return entries

    def _merge_package_records(self, packages: Dict[int, Dict[str, Any]], records: List[Dict[str, Any]]) -> None:
        for record in records:
            if not isinstance(record, dict):
                continue
            package_id = self._safe_int_value(record.get("PackageId"))
            if package_id is None:
                device_id = str(record.get("DeviceId") or "")
                match = re.search(r"cpu_package_(\d+)", device_id)
                if match:
                    package_id = int(match.group(1))
            if package_id is None:
                continue
            target = packages.setdefault(package_id, {"PackageId": package_id})
            for key in ("Name", "DisplayName", "LogicalCpuCount", "LogicalCpuRange", "PhysicalCoreCount"):
                if record.get(key) not in (None, "") and target.get(key) in (None, ""):
                    target[key] = record.get(key)

    def _package_ids_from_samples(self, samples: List[Any]) -> set[int]:
        package_ids: set[int] = set()
        for sample in samples:
            for key in sample.values:
                match = re.match(r"^cpu_package_(\d+)_(?:temp_c|power_w)$", str(key))
                if match:
                    package_ids.add(int(match.group(1)))
        return package_ids

    def _package_clock_stats(self, core_entries: List[Dict[str, Any]], package_id: int) -> Stats:
        filtered = [
            entry
            for entry in core_entries
            if self._package_id_from_physical_core_key(entry.get("PhysicalCoreKey")) == package_id
        ]
        return self._aggregate_core_clock_stats(filtered) if filtered else self._empty_stats()

    def _package_id_from_physical_core_key(self, value: Any) -> Optional[int]:
        match = re.search(r"\bpackage(\d+)\b", str(value or ""))
        return int(match.group(1)) if match else None

    def _empty_stats(self) -> Stats:
        return {"Min": None, "Avg": None, "Max": None}

    def _safe_int_value(self, value: Any) -> Optional[int]:
        try:
            return int(value)
        except Exception:
            return None

    def _stats_have_values(self, stats: Stats) -> bool:
        return any(stats.get(key) is not None for key in ("Min", "Avg", "Max"))
