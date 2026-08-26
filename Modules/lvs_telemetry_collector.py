#!/usr/bin/env python3
"""Telemetry sampling and source discovery for Linux Validation Suite."""

from __future__ import annotations

import json
import os
import subprocess
import time
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from .lvs_gpu_identity import gpu_vendor_name, normalize_pci_slot
from .lvs_hardware_evidence import HardwareEvidenceCollector, format_hardware_evidence_summary
from .lvs_settings import DEFAULT_SAMPLE_INTERVAL_SECONDS
from .lvs_telemetry_gpu import (
    discover_gpu_cards,
    discover_gpu_sources,
    gpu_hwmon_dirs,
    gpu_temp_metric,
    intel_gpu_clock_path,
    pci_slot_from_device_dir,
    read_gpu_clock,
    read_gpu_values,
)
from .lvs_telemetry_intel import (
    intel_gpu_top_json_sample_metrics,
    intel_gpu_top_json_sample_text,
    read_intel_gpu_top_metrics,
)
from .lvs_telemetry_cpu import (
    add_privileged_cpu_power_sources,
    aggregate_cpu_package_power_source,
    assign_cpu_package_temp_sources,
    classify_physical_cpu_cores,
    cpu_core_utilization_sources,
    cpu_core_classification_summary_from_topology,
    cpu_index_from_name,
    discover_cpu_core_clock_sources,
    discover_cpu_core_topology,
    discover_cpu_clock_source,
    discover_cpu_utilization_source,
    discover_cpu_power_source,
    discover_cpu_temp_sources,
    parse_cpu_list,
    parse_explicit_core_type,
    performance_tiers,
    read_cpu_clock_mhz,
    read_cpu_core_clocks,
    read_cpu_package_temps,
    read_cpu_power,
    read_cpu_power_component,
    read_cpu_temp,
    read_cpu_sysfs_int,
    parse_proc_stat_cpu_snapshot,
    cpu_utilization_percent,
    read_energy_power_source,
    read_hwmon_power_source,
    read_temperature_path,
    score_cpu_power_source,
    score_cpu_temp_source,
    score_energy_source,
    score_rapl_source,
    score_thermal_zone,
)
from .lvs_telemetry_device import discover_device_temp_sources, read_device_temps
from .lvs_telemetry_edac import discover_llcc_edac_sources, read_llcc_edac_counters
from .lvs_telemetry_memory import (
    discover_memory_temp_sources,
    ipmi_memory_sensor_sort_key,
    memory_usage_gib_from_meminfo,
    read_memory_temps,
)
from .lvs_telemetry_bmc import (
    BmcSnapshotProvider,
    bmc_snapshot_evidence,
    bmc_thermal_compatibility,
)
from .lvs_telemetry_nvidia import (
    discover_nvidia_smi_gpus,
    read_nvidia_smi_gpu_metrics,
    run_nvidia_smi_query,
)
from .lvs_telemetry_sampling import (
    json_objects_from_text,
    metric_number,
    parse_intel_gpu_top_snapshot,
    parse_optional_float,
    walk_json_numbers,
)
from .lvs_telemetry_samples import Sample, telemetry_values_with_unit_aliases, write_telemetry_csv
from .lvs_telemetry_sensor_io import (
    hwmon_temp_thresholds,
    read_hwmon_temp_limit,
    read_temp_limit_c,
    safe_read_text,
    safe_read_text_sudo,
    sensor_label,
    thermal_zone_thresholds,
)
from .lvs_telemetry_storage_sources import discover_storage_temp_sources, read_storage_temps
from .lvs_telemetry_sources import (
    build_gpu_telemetry_matrix,
    build_telemetry_capability_summary,
    build_telemetry_source_map,
    preferred_metric_source,
    source_thresholds,
    sources_for_metric,
    telemetry_source_description,
    unreadable_source_description,
)


CPU_TEMP_WARN_C = 95.0
CPU_TEMP_FAIL_C = 100.0
GPU_TEMP_WARN_C = 90.0
GPU_TEMP_FAIL_C = 95.0
GPU_THERMAL_THROTTLE_HINT_C = 85.0
GPU_HOTSPOT_WARN_C = 100.0
GPU_HOTSPOT_FAIL_C = 110.0
GPU_MEMORY_TEMP_WARN_C = 96.0
GPU_MEMORY_TEMP_FAIL_C = 104.0

class TelemetryCollector:
    def __init__(
        self,
        interval_seconds: float = DEFAULT_SAMPLE_INTERVAL_SECONDS,
        runtime_environment: Optional[Dict[str, str]] = None,
        privileged_helper_enabled: bool = False,
        cpu_core_type_probe: Optional[Dict[str, Any]] = None,
        bmc_provider: Optional[BmcSnapshotProvider] = None,
        enable_bmc_provider: bool = True,
    ) -> None:
        self.interval_seconds = interval_seconds
        self.samples: List[Sample] = []
        self._env_overrides = {str(key): str(value) for key, value in (runtime_environment or {}).items()}
        self._privileged_helper_enabled = bool(privileged_helper_enabled)
        self._cpu_core_type_probe = dict(cpu_core_type_probe or {})
        self._cpu_temp_sources = self._discover_cpu_temp_sources()
        self._cpu_power_unreadable_sources: List[Dict[str, Any]] = []
        self._cpu_power_source = self._discover_cpu_power_source()
        self._cpu_clock_source = self._discover_cpu_clock_source()
        self._cpu_utilization_source = self._discover_cpu_utilization_source()
        self._previous_cpu_stat_counters = None
        self._previous_cpu_core_stat_counters: Dict[int, tuple[int, ...]] = {}
        self._last_cpu_core_utilization_values: Dict[str, Optional[float]] = {}
        self._cpu_core_topology = self._discover_cpu_core_topology()
        self._cpu_core_utilization_sources = cpu_core_utilization_sources(
            self._cpu_core_topology.keys(),
            self._cpu_utilization_source,
        )
        self._cpu_package_temp_sources = self._assign_cpu_package_temp_sources()
        self._cpu_core_clock_sources = self._discover_cpu_core_clock_sources()
        self._memory_temp_sources = self._discover_memory_temp_sources()
        self._direct_memory_temp_sources_present = bool(self._memory_temp_sources)
        self._bmc_memory_aliases_initialized = False
        self._bmc_memory_aliases: Dict[str, str] = {}
        self._llcc_edac_sources = self._discover_llcc_edac_sources()
        self._storage_temp_sources = self._discover_storage_temp_sources()
        self._device_temp_sources = self._discover_device_temp_sources()
        self._gpu_sources = self._discover_gpu_sources()
        self._energy_source_state: Dict[str, Dict[str, float]] = {}
        self._last_cpu_package_power_values: Dict[str, float] = {}
        self.memory_total_gib: Optional[float] = None
        self._intel_gpu_top_snapshot_cache: Optional[Dict[int, Dict[str, Optional[float]]]] = None
        self._normalized_hardware_evidence_cache: Optional[Dict[str, Any]] = None
        # Start the optional worker only after synchronous source discovery has
        # completed, so constructor failures cannot orphan it.
        self._bmc_provider = bmc_provider or BmcSnapshotProvider(
            command_exists=self._command_exists,
            command_env=self._command_env,
            privileged_helper_enabled=self._privileged_helper_enabled,
            enabled=enable_bmc_provider,
        )

    def _command_env(self) -> Dict[str, str]:
        env = os.environ.copy()
        env.update(self._env_overrides)
        return env

    def metric_thresholds(self, key: str) -> Optional[Dict[str, Any]]:
        if key == "cpu_temp_c":
            if not self._cpu_temp_sources:
                return None
            return self._source_thresholds(self._cpu_temp_sources[0], CPU_TEMP_WARN_C, CPU_TEMP_FAIL_C)
        for source in self._gpu_sources:
            if source.get("key") == key and str(source.get("metric", "")).startswith("temp_"):
                if source["metric"] == "temp_core_c":
                    return self._source_thresholds(source, GPU_TEMP_WARN_C, GPU_TEMP_FAIL_C)
                if source["metric"] == "temp_hotspot_c":
                    return self._source_thresholds(source, GPU_HOTSPOT_WARN_C, GPU_HOTSPOT_FAIL_C)
                if source["metric"] == "temp_memory_c":
                    return self._source_thresholds(source, GPU_MEMORY_TEMP_WARN_C, GPU_MEMORY_TEMP_FAIL_C)
        return None

    def _source_thresholds(self, source: Dict[str, Any], default_warn: float, default_fail: float) -> Dict[str, Any]:
        return source_thresholds(source, default_warn, default_fail)

    def _gpu_sources_for_metric(self, metric: str) -> List[Dict[str, Any]]:
        return sources_for_metric(self._gpu_sources, metric)

    def _preferred_gpu_source(self, metric: str, prefer_hardware_thresholds: bool = False) -> Optional[Dict[str, Any]]:
        return preferred_metric_source(
            self._gpu_sources,
            metric,
            prefer_hardware_thresholds=prefer_hardware_thresholds,
        )

    def _gpu_metric_threshold_summary(self, metric: str) -> List[Dict[str, Any]]:
        details: List[Dict[str, Any]] = []
        for source in self._gpu_sources_for_metric(metric):
            details.append(
                {
                    "gpu_index": int(source.get("gpu_index", 0)),
                    "source": self._describe_source(source),
                    "thresholds": self.metric_thresholds(source.get("key", "")),
                }
            )
        return details

    def _command_exists(self, name: str) -> bool:
        from shutil import which
        return which(name) is not None

    def collect_once(self) -> None:
        sample_time = time.monotonic()
        self._intel_gpu_top_snapshot_cache = None
        cpu_power_w = self._read_cpu_power(sample_time)
        cpu_package_temps = self._read_cpu_package_temps()
        values = {
            "cpu_temp_c": self._read_cpu_temp(cpu_package_temps),
            "cpu_power_w": cpu_power_w,
            "cpu_clock_mhz": self._read_cpu_clock_mhz(),
            "cpu_utilization_percent": self._read_cpu_utilization_percent(),
            "memory_used_gb": self._read_memory_used_gb(),
        }
        values.update(getattr(self, "_last_cpu_core_utilization_values", {}))
        values.update(cpu_package_temps)
        values.update(self._last_cpu_package_power_values)
        values.update(self._read_cpu_core_clocks())
        values.update(self._read_memory_temps())
        values.update(self._read_bmc_values(sample_time))
        values.update(self._read_llcc_edac_counters())
        values.update(self._read_storage_temps())
        values.update(self._read_device_temps())
        values.update(self._read_gpu_values(sample_time))
        self.samples.append(
            Sample(timestamp=sample_time, values=telemetry_values_with_unit_aliases(values))
        )

    def _read_cpu_temp(self, package_temps: Optional[Dict[str, Optional[float]]] = None) -> Optional[float]:
        return read_cpu_temp(self._cpu_temp_sources, self._safe_read_text, package_temps)

    def _read_cpu_package_temps(self) -> Dict[str, Optional[float]]:
        return read_cpu_package_temps(self._cpu_package_temp_sources, self._safe_read_text)

    def _read_cpu_power(self, sample_time: float) -> Optional[float]:
        value, package_values = read_cpu_power(
            self._cpu_power_source,
            sample_time,
            self._energy_source_state,
            self._safe_read_text,
            self._safe_read_text_sudo,
        )
        self._last_cpu_package_power_values = package_values
        return value

    def _read_cpu_power_component(self, source: Dict[str, Any], sample_time: float) -> Optional[float]:
        return read_cpu_power_component(
            source,
            sample_time,
            self._energy_source_state,
            self._safe_read_text,
            self._safe_read_text_sudo,
            max_watts=1500.0,
        )

    def _read_hwmon_power_source(self, source: Dict[str, Any], *, max_watts: float) -> Optional[float]:
        return read_hwmon_power_source(source, self._safe_read_text, max_watts=max_watts)

    def _read_energy_power_source(
        self,
        source: Dict[str, Any],
        sample_time: float,
        max_watts: float,
    ) -> Optional[float]:
        return read_energy_power_source(
            source,
            sample_time,
            self._energy_source_state,
            self._safe_read_text,
            self._safe_read_text_sudo,
            max_watts=max_watts,
        )

    def _read_memory_used_gb(self) -> Optional[float]:
        try:
            meminfo = Path("/proc/meminfo").read_text(encoding="utf-8", errors="ignore")
            used_gib, total_gib = memory_usage_gib_from_meminfo(meminfo)
            if total_gib is not None:
                self.memory_total_gib = total_gib
            return used_gib
        except Exception:
            pass
        return None

    def write_csv(self, path: Path) -> None:
        self.finalize_sources()
        write_telemetry_csv(self.samples, path)

    def finalize_sources(self) -> None:
        """Nonblockingly incorporate provider catalogs before artifacts are written."""
        provider = getattr(self, "_bmc_provider", None)
        if provider is None:
            return
        completed_values = getattr(provider, "completed_values", None)
        values = completed_values() if callable(completed_values) else provider.sample_values()
        catalog = provider.source_catalog()
        self._initialize_bmc_memory_aliases(catalog, values)
        field_names = {
            self._bmc_memory_aliases.get(str(source.get("key") or ""), str(source.get("key") or ""))
            for source in catalog
            if source.get("key")
        }
        for sample in self.samples:
            for field_name in field_names:
                sample.values.setdefault(field_name, None)

    def detect_capabilities(self) -> Dict[str, Dict[str, Any]]:
        return build_telemetry_capability_summary(
            cpu_temp_source=self._cpu_temp_sources[0] if self._cpu_temp_sources else None,
            cpu_power_source=self._cpu_power_source,
            cpu_power_unreadable_sources=self._cpu_power_unreadable_sources,
            cpu_clock_source=self._cpu_clock_source,
            cpu_core_clock_sources=self._cpu_core_clock_sources,
            cpu_core_utilization_sources=self._cpu_core_utilization_sources,
            cpu_core_classification=self.cpu_core_classification_summary(),
            memory_temp_sources=self._memory_temp_sources,
            llcc_edac_sources=self._llcc_edac_sources,
            storage_temp_sources=self._storage_temp_sources,
            device_temp_sources=self._device_temp_sources,
            gpu_sources=self._gpu_sources,
            gpu_temp_source=self._preferred_gpu_source("temp_core_c", prefer_hardware_thresholds=True),
            describe_source=self._describe_source,
            describe_unreadable_sources=self._describe_unreadable_sources,
            metric_thresholds=self.metric_thresholds,
            gpu_metric_threshold_summary=self._gpu_metric_threshold_summary,
            gpu_telemetry_matrix=self._gpu_telemetry_matrix,
            memory_used_available=Path("/proc/meminfo").exists(),
            privileged_helper_enabled=self._privileged_helper_enabled,
            process_is_root=self._process_is_root(),
            sudo_available=self._sudo_available(),
            cpu_utilization_source=self._cpu_utilization_source,
        )

    def _gpu_telemetry_matrix(self) -> List[Dict[str, Any]]:
        return build_gpu_telemetry_matrix(self._discover_gpu_cards(), self._gpu_sources)

    def source_map(self) -> Dict[str, Any]:
        self.finalize_sources()
        provider = getattr(self, "_bmc_provider", None)
        bmc_catalog = provider.source_catalog() if provider is not None else []
        bmc_catalog = [
            source
            for source in bmc_catalog
            if str(source.get("key") or "") not in self._bmc_memory_aliases
        ]
        payload = build_telemetry_source_map(
            cpu_temp_source=self._cpu_temp_sources[0] if self._cpu_temp_sources else None,
            cpu_package_temp_sources=self._cpu_package_temp_sources,
            cpu_power_source=self._cpu_power_source,
            cpu_clock_source=self._cpu_clock_source,
            cpu_core_clock_sources=self._cpu_core_clock_sources,
            cpu_core_utilization_sources=self._cpu_core_utilization_sources,
            memory_temp_sources=self._memory_temp_sources,
            bmc_sources=bmc_catalog,
            llcc_edac_sources=self._llcc_edac_sources,
            storage_temp_sources=self._storage_temp_sources,
            device_temp_sources=self._device_temp_sources,
            gpu_sources=self._gpu_sources,
            gpu_cards=self._discover_gpu_cards(),
            privileged_helper_enabled=self._privileged_helper_enabled,
            process_is_root=self._process_is_root(),
            sudo_available=self._sudo_available(),
            cpu_power_unreadable_sources=self._cpu_power_unreadable_sources,
            cpu_utilization_source=self._cpu_utilization_source,
        )
        # Additive schema-v1 evidence. The established telemetry source fields
        # retain their original meanings and casing.
        payload["normalized_hardware_evidence"] = self.normalized_hardware_evidence()
        return payload

    def normalized_hardware_evidence(self) -> Dict[str, Any]:
        provider = getattr(self, "_bmc_provider", None)
        if self._normalized_hardware_evidence_cache is None:
            collector = HardwareEvidenceCollector(
                cpu_core_topology=self._cpu_core_topology,
                gpu_cards=self._discover_gpu_cards(),
                read_text=self._safe_read_text,
                command_env=self._command_env,
                bmc_snapshot=provider.snapshot_for_evidence() if provider is not None else None,
            )
            evidence = collector.collect()
            evidence["operator_summary"] = format_hardware_evidence_summary(evidence)
            self._normalized_hardware_evidence_cache = evidence
        if provider is not None:
            snapshot = provider.snapshot_for_evidence()
            self._normalized_hardware_evidence_cache["bmc_sensors"] = bmc_snapshot_evidence(snapshot)
            self._normalized_hardware_evidence_cache["bmc_thermal_sensors"] = bmc_thermal_compatibility(snapshot)
            status_evidence_method = getattr(provider, "status_evidence", None)
            status_evidence = status_evidence_method() if callable(status_evidence_method) else {}
            if status_evidence:
                self._normalized_hardware_evidence_cache["bmc_status"] = status_evidence
            else:
                self._normalized_hardware_evidence_cache.pop("bmc_status", None)
        return self._normalized_hardware_evidence_cache

    def _process_is_root(self) -> bool:
        return bool(hasattr(os, "geteuid") and os.geteuid() == 0)

    def _sudo_available(self) -> bool:
        return shutil.which("sudo") is not None

    def _discover_cpu_temp_sources(self) -> List[Dict[str, Any]]:
        return discover_cpu_temp_sources(
            read_text=self._safe_read_text,
            sensor_label=self._sensor_label,
            hwmon_temp_thresholds=self._hwmon_temp_thresholds,
            thermal_zone_thresholds=self._thermal_zone_thresholds,
        )

    def _cpu_package_ids(self) -> List[int]:
        from .lvs_telemetry_cpu import cpu_package_ids_from_topology
        return cpu_package_ids_from_topology(self._cpu_core_topology)

    def _cpu_package_id_from_temp_source(self, source: Dict[str, Any]) -> Optional[int]:
        from .lvs_telemetry_cpu import cpu_package_id_from_temp_source
        return cpu_package_id_from_temp_source(source)

    def _assign_cpu_package_temp_sources(self) -> List[Dict[str, Any]]:
        return assign_cpu_package_temp_sources(self._cpu_temp_sources, self._cpu_core_topology)

    def _discover_cpu_power_source(self) -> Optional[Dict[str, Any]]:
        source, unreadable_sources = discover_cpu_power_source(
            read_text=self._safe_read_text,
            sensor_label=self._sensor_label,
            read_text_sudo=self._safe_read_text_sudo,
            privileged_helper_enabled=self._privileged_helper_enabled,
        )
        self._cpu_power_unreadable_sources.extend(unreadable_sources)
        return source

    def _add_privileged_cpu_power_sources(self, sources: List[Dict[str, Any]]) -> None:
        add_privileged_cpu_power_sources(
            sources,
            self._cpu_power_unreadable_sources,
            self._safe_read_text_sudo,
            privileged_helper_enabled=self._privileged_helper_enabled,
        )

    def _aggregate_cpu_package_power_source(self, sources: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        return aggregate_cpu_package_power_source(sources)

    def _cpu_package_id_from_power_source(self, source: Dict[str, Any]) -> Optional[str]:
        from .lvs_telemetry_cpu import cpu_package_id_from_power_source
        return cpu_package_id_from_power_source(source)

    def _read_temperature_path(self, path: Path) -> Optional[float]:
        return read_temperature_path(path, self._safe_read_text)

    def _read_cpu_clock_mhz(self) -> Optional[float]:
        return read_cpu_clock_mhz(self._cpu_clock_source, self._safe_read_text)

    def _read_cpu_utilization_percent(self) -> Optional[float]:
        if not getattr(self, "_cpu_utilization_source", None):
            return None
        path = Path(str(self._cpu_utilization_source.get("path") or "/proc/stat"))
        current, current_per_cpu = parse_proc_stat_cpu_snapshot(self._safe_read_text(path))
        if current is None:
            return None
        previous = getattr(self, "_previous_cpu_stat_counters", None)
        self._previous_cpu_stat_counters = current
        previous_per_cpu = getattr(self, "_previous_cpu_core_stat_counters", {})
        self._previous_cpu_core_stat_counters = current_per_cpu
        utilization_sources = getattr(self, "_cpu_core_utilization_sources", [])
        self._cpu_core_utilization_sources = utilization_sources
        known_indexes = {
            int(source.get("cpu_index"))
            for source in utilization_sources
            if source.get("cpu_index") is not None
        }
        new_indexes = sorted(set(current_per_cpu) - known_indexes)
        if new_indexes:
            utilization_sources.extend(
                cpu_core_utilization_sources(new_indexes, self._cpu_utilization_source)
            )
        self._last_cpu_core_utilization_values = {
            f"cpu_core_{cpu_index}_utilization_percent": cpu_utilization_percent(
                previous_per_cpu.get(cpu_index),
                counters,
            )
            for cpu_index, counters in sorted(current_per_cpu.items())
        }
        return cpu_utilization_percent(previous, current)

    def _read_cpu_core_clocks(self) -> Dict[str, Optional[float]]:
        return read_cpu_core_clocks(self._cpu_core_clock_sources, self._safe_read_text)

    def _read_memory_temps(self) -> Dict[str, Optional[float]]:
        return read_memory_temps(
            self._memory_temp_sources,
            self._read_temperature_path,
        )

    def _initialize_bmc_memory_aliases(
        self,
        catalog: List[Dict[str, Any]],
        values: Optional[Dict[str, Optional[float]]] = None,
    ) -> None:
        if getattr(self, "_bmc_memory_aliases_initialized", False) or getattr(
            self, "_direct_memory_temp_sources_present", bool(getattr(self, "_memory_temp_sources", []))
        ):
            return
        if not hasattr(self, "_bmc_memory_aliases"):
            self._bmc_memory_aliases = {}
        candidates = [
            source
            for source in catalog
            if source.get("metric_class") == "temperature"
            and source.get("component_classification") == "memory_module"
            and (values is None or values.get(str(source.get("key") or "")) is not None)
        ]
        if not candidates:
            return
        candidates.sort(key=lambda source: ipmi_memory_sensor_sort_key(str(source.get("label") or "")))
        for module_index, source in enumerate(candidates):
            bmc_key = str(source.get("key") or "")
            alias_key = f"memory_module_{module_index}_temp_c"
            self._bmc_memory_aliases[bmc_key] = alias_key
            self._memory_temp_sources.append(
                {
                    **source,
                    "kind": "ipmi_memory_temp",
                    "path": str(source.get("command") or "ipmitool sdr elist"),
                    "key": alias_key,
                    "module_index": module_index,
                    "sensor_id": list(source.get("canonical_identity") or ()),
                    "bmc_source_key": bmc_key,
                }
            )
        self._bmc_memory_aliases_initialized = True

    def _read_bmc_values(self, sample_time: float) -> Dict[str, Optional[float]]:
        provider = getattr(self, "_bmc_provider", None)
        if provider is None:
            return {}
        values = provider.sample_values(sample_time)
        catalog = provider.source_catalog()
        self._initialize_bmc_memory_aliases(catalog, values)
        for bmc_key, alias_key in self._bmc_memory_aliases.items():
            values[alias_key] = values.pop(bmc_key, None)
        return values

    def _read_storage_temps(self) -> Dict[str, Optional[float]]:
        return read_storage_temps(self._storage_temp_sources, self._read_temperature_path)

    def _read_device_temps(self) -> Dict[str, Optional[float]]:
        return read_device_temps(
            self._device_temp_sources,
            self._read_temperature_path,
            self._safe_read_text,
        )

    def _read_gpu_values(self, sample_time: Optional[float] = None) -> Dict[str, Optional[float]]:
        if sample_time is None:
            sample_time = time.monotonic()
        return read_gpu_values(
            self._gpu_sources,
            self._safe_read_text,
            self._safe_read_text_sudo,
            self._energy_source_state,
            self._read_nvidia_smi_gpu_metrics(),
            self._read_intel_gpu_top_metrics(),
            sample_time,
        )

    def _safe_read_text(self, path: Path) -> Optional[str]:
        return safe_read_text(path)

    def _safe_read_text_sudo(self, path: Path) -> Optional[str]:
        return safe_read_text_sudo(path, self._safe_read_text)

    def _sensor_label(self, data_path: Path) -> str:
        return sensor_label(data_path, self._safe_read_text)

    def _read_temp_limit_c(self, path: Path) -> Optional[float]:
        return read_temp_limit_c(path, self._safe_read_text)

    def _read_hwmon_temp_limit(self, input_path: Path, suffix: str) -> Optional[float]:
        return read_hwmon_temp_limit(input_path, suffix, self._safe_read_text)

    def _hwmon_temp_thresholds(self, input_path: Path) -> tuple[Optional[float], Optional[float], str]:
        return hwmon_temp_thresholds(input_path, self._safe_read_text)

    def _thermal_zone_thresholds(self, zone_dir: Path) -> tuple[Optional[float], Optional[float], str]:
        return thermal_zone_thresholds(zone_dir, self._safe_read_text)

    def _discover_cpu_clock_source(self) -> Optional[Dict[str, Any]]:
        return discover_cpu_clock_source(read_text=self._safe_read_text)

    def _discover_cpu_utilization_source(self) -> Optional[Dict[str, Any]]:
        return discover_cpu_utilization_source(read_text=self._safe_read_text)

    def _discover_cpu_core_topology(self) -> Dict[int, Dict[str, Any]]:
        return discover_cpu_core_topology(
            read_text=self._safe_read_text,
            core_type_probe=self._cpu_core_type_probe,
        )

    def _classify_physical_cpu_cores(
        self,
        physical: Dict[str, Dict[str, Any]],
    ) -> tuple[Dict[str, str], Dict[str, str], Dict[str, Optional[int]]]:
        return classify_physical_cpu_cores(physical)

    def _performance_tiers(self, values: Dict[str, int]) -> List[tuple[float, List[str]]]:
        return performance_tiers(values)

    def _parse_explicit_core_type(self, value: str) -> str:
        return parse_explicit_core_type(value)

    def _safe_read_int(self, path: Path) -> Optional[int]:
        return read_cpu_sysfs_int(path, self._safe_read_text)

    def _parse_cpu_list(self, value: str) -> List[int]:
        return parse_cpu_list(value)

    def _cpu_index_from_name(self, name: str) -> int:
        return cpu_index_from_name(name)

    def cpu_core_classification_summary(self) -> Dict[str, Any]:
        return cpu_core_classification_summary_from_topology(self._cpu_core_topology)

    def _discover_cpu_core_clock_sources(self) -> List[Dict[str, Any]]:
        return discover_cpu_core_clock_sources(self._cpu_core_topology, read_text=self._safe_read_text)

    def _discover_memory_temp_sources(self) -> List[Dict[str, Any]]:
        return discover_memory_temp_sources(read_text=self._safe_read_text)

    def _discover_llcc_edac_sources(self) -> List[Dict[str, Any]]:
        return discover_llcc_edac_sources(read_text=self._safe_read_text)

    def _read_llcc_edac_counters(self) -> Dict[str, Optional[float]]:
        return read_llcc_edac_counters(
            getattr(self, "_llcc_edac_sources", []),
            self._safe_read_text,
        )

    def close(self) -> None:
        provider = getattr(self, "_bmc_provider", None)
        if provider is not None:
            provider.close()

    def _discover_storage_temp_sources(self) -> List[Dict[str, Any]]:
        return discover_storage_temp_sources(read_text=self._safe_read_text)

    def _discover_device_temp_sources(self) -> List[Dict[str, Any]]:
        return discover_device_temp_sources(read_text=self._safe_read_text)

    def _discover_gpu_sources(self) -> List[Dict[str, Any]]:
        return discover_gpu_sources(
            self._safe_read_text,
            self._sensor_label,
            self._hwmon_temp_thresholds,
            self._command_exists,
            self._discover_nvidia_smi_gpus,
            self._intel_gpu_top_json_sample_metrics,
            thermal_zone_thresholds=self._thermal_zone_thresholds,
        )

    def _gpu_hwmon_dirs(self, card: Path) -> List[Path]:
        return gpu_hwmon_dirs(card, self._safe_read_text)

    def _pci_slot_from_device_dir(self, device_dir: Path) -> str:
        return pci_slot_from_device_dir(device_dir)

    def _intel_gpu_clock_path(self, device_dir: Path) -> Optional[Path]:
        return intel_gpu_clock_path(device_dir, self._safe_read_text)

    def _discover_gpu_cards(self) -> List[Dict[str, Any]]:
        return discover_gpu_cards()

    def _read_nvidia_smi_gpu_metrics(self) -> Dict[str, Dict[str, Optional[float]]]:
        return read_nvidia_smi_gpu_metrics(self._gpu_sources, self._command_env)

    def _run_nvidia_smi_query(self, fields: List[str]) -> Optional[subprocess.CompletedProcess[str]]:
        return run_nvidia_smi_query(fields, self._command_env)

    def _read_intel_gpu_top_metrics(self) -> Dict[int, Dict[str, Optional[float]]]:
        if self._intel_gpu_top_snapshot_cache is not None:
            return self._intel_gpu_top_snapshot_cache
        self._intel_gpu_top_snapshot_cache = read_intel_gpu_top_metrics(
            self._gpu_sources,
            self._command_exists,
            self._command_env,
        )
        return self._intel_gpu_top_snapshot_cache

    def _run_intel_gpu_top_json_sample(self) -> str:
        return intel_gpu_top_json_sample_text(self._command_exists, self._command_env)

    def _intel_gpu_top_json_sample_attempt(self) -> Dict[str, Any]:
        from .lvs_intel_gpu_sidecar import intel_gpu_top_json_sample_attempt
        return intel_gpu_top_json_sample_attempt(command_exists=self._command_exists, command_env=self._command_env)

    def _intel_gpu_top_json_sample_metrics(self) -> Dict[str, Optional[float]]:
        return intel_gpu_top_json_sample_metrics(self._command_exists, self._command_env)

    def _json_objects_from_text(self, text: str) -> List[Any]:
        return json_objects_from_text(text)

    def _parse_intel_gpu_top_snapshot(self, snapshot: Dict[str, Any]) -> Dict[str, Optional[float]]:
        return parse_intel_gpu_top_snapshot(snapshot)

    def _metric_number(self, value: Any) -> Optional[float]:
        return metric_number(value)

    def _walk_json_numbers(self, value: Any, prefix: str = "") -> List[tuple[str, float]]:
        return walk_json_numbers(value, prefix)

    def _parse_optional_float(self, raw: str, upper_bound: float) -> Optional[float]:
        return parse_optional_float(raw, upper_bound)

    def _normalize_pci_slot(self, slot: str) -> str:
        return normalize_pci_slot(slot)

    def _gpu_vendor_name(self, vendor_id: str) -> str:
        return gpu_vendor_name(vendor_id)

    def _discover_nvidia_smi_gpus(self) -> List[Dict[str, Any]]:
        return discover_nvidia_smi_gpus(self._command_exists, self._command_env)

    def _gpu_temp_metric(self, label: str, hwmon_name: str = "", path: Optional[Path] = None) -> Optional[str]:
        return gpu_temp_metric(label, hwmon_name, path)

    def _read_gpu_clock(self, path: Path) -> Optional[float]:
        return read_gpu_clock(path, self._safe_read_text)

    def _score_cpu_temp_source(self, hwmon_name: str, label: str) -> int:
        return score_cpu_temp_source(hwmon_name, label)

    def _score_thermal_zone(self, zone_type: str) -> int:
        return score_thermal_zone(zone_type)

    def _score_cpu_power_source(self, hwmon_name: str, label: str) -> int:
        return score_cpu_power_source(hwmon_name, label)

    def _score_rapl_source(self, name: str) -> int:
        return score_rapl_source(name)

    def _score_energy_source(self, hwmon_name: str, label: str) -> int:
        return score_energy_source(hwmon_name, label)

    def _describe_source(self, source: Optional[Dict[str, Any]]) -> str:
        return telemetry_source_description(source)

    def _describe_unreadable_sources(self, sources: List[Dict[str, Any]]) -> str:
        return unreadable_source_description(sources)
