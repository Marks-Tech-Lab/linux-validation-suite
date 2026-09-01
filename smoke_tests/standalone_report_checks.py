#!/usr/bin/env python3
"""Focused, hardware-free checks for standalone LVS report Wave 1."""

from __future__ import annotations

import base64
import csv
import hashlib
import json
import re
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Modules.lvs_chart_data import (
    FULL_SAMPLE_LIMIT, PLOTTED_POINT_BUDGET, canonical_chart_json,
    compile_chart_data, decode_series_points, encode_series, extrema_reduce,
)
from Modules.lvs_output_contract_identity import (
    CHART_DATA_CONTRACT_ID, CHART_DATA_KIND, CONTRACT_VERSION,
    REPORT_DATA_CONTRACT_ID, REPORT_DATA_KIND,
)
from Modules.lvs_report import generate_report
from Modules.lvs_report_data import compile_report_data, evaluate_clock_context, evaluate_temperature_context
from Modules.lvs_report_html import (
    _advanced_telemetry_mapping, _clock_range, _component_index, _memory_mapping, _metric_table, _stage_component_rows,
    _timestamp, _visible_metrics, render_report_html,
)


def _write_json(root: Path, name: str, payload: Dict[str, Any]) -> None:
    (root / name).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _source_map() -> Dict[str, Any]:
    return {
        "contract_id": "linux_validation_suite.telemetry_source_map",
        "contract_version": 1,
        "kind": "telemetry_source_map",
        "gpu_index_map": [
            {"gpu_index": 0, "card": "card0", "slot": "0000:01:00.0", "driver": "i915"},
            {"gpu_index": 1, "card": "card1", "slot": "0000:02:00.0", "driver": "amdgpu"},
        ],
        "storage_link_map": [{"drive_index": 0, "device_name": "NVMe Test", "block_name": "nvme0n1"}],
        "fields": {
            "cpu_temp_c": {"category": "cpu", "metric": "temperature_c", "kind": "coretemp", "provider": "coretemp", "label": "CPU Package", "path": "/sys/cpu/temp1_input", "thresholds": {"warn_c": 95, "fail_c": 100, "source": "coretemp:temp1_crit"}},
            "cpu_clock_mhz": {"category": "cpu", "metric": "clock_mhz", "kind": "cpufreq", "provider": "cpufreq", "label": "CPU clock"},
            "cpu_power_w": {"category": "cpu", "metric": "power_w", "kind": "rapl", "provider": "rapl", "label": "CPU package power"},
            "cpu_package_0_temp_c": {"category": "cpu_package", "package_id": 0, "metric": "temperature_c", "kind": "coretemp", "provider": "coretemp", "label": "CPU package 0"},
            "cpu_core_0_clock_mhz": {"category": "cpu_core", "cpu_index": 0, "metric": "clock_mhz", "kind": "cpufreq", "provider": "cpufreq", "label": "P-Core 0 Clock"},
            "cpu_core_2_clock_mhz": {"category": "cpu_core", "cpu_index": 2, "metric": "clock_mhz", "kind": "cpufreq", "provider": "cpufreq", "label": "P-Core 2 Clock"},
            "cpu_core_10_clock_mhz": {"category": "cpu_core", "cpu_index": 10, "metric": "clock_mhz", "kind": "cpufreq", "provider": "cpufreq", "label": "E-Core 10 Clock"},
            "cpu_core_0_utilization_percent": {"category": "cpu_core", "cpu_index": 0, "metric": "utilization_percent", "kind": "psutil", "provider": "psutil", "label": "CPU 0 utilization"},
            "cpu_core_2_utilization_percent": {"category": "cpu_core", "cpu_index": 2, "metric": "utilization_percent", "kind": "psutil", "provider": "psutil", "label": "CPU 2 utilization"},
            "cpu_core_10_utilization_percent": {"category": "cpu_core", "cpu_index": 10, "metric": "utilization_percent", "kind": "psutil", "provider": "psutil", "label": "CPU 10 utilization"},
            "gpu_0_temp_c": {"category": "gpu", "metric": "temperature_c", "gpu_index": 0, "provider": "amdgpu", "label": "GPU edge", "path": "/sys/gpu/temp1_input"},
            "gpu_0_temp_hotspot_c": {"category": "gpu", "metric": "temperature_c", "gpu_index": 0, "provider": "amdgpu", "label": "GPU hotspot"},
            "gpu_0_clock_mhz": {"category": "gpu", "metric": "clock_mhz", "gpu_index": 0, "provider": "amdgpu", "label": "GPU core clock"},
            "gpu_0_power_w": {"category": "gpu", "metric": "power_w", "gpu_index": 0, "provider": "amdgpu", "label": "GPU power"},
            "gpu_0_memory_clock_mhz": {"category": "gpu", "metric": "memory_clock_mhz", "gpu_index": 0, "provider": "amdgpu", "label": "GPU memory clock"},
            "gpu_0_voltage_v": {"category": "gpu", "metric": "voltage_v", "gpu_index": 0, "provider": "amdgpu", "label": "GPU voltage"},
            "gpu_0_utilization_percent": {"category": "gpu", "metric": "utilization_percent", "gpu_index": 0, "provider": "amdgpu", "label": "GPU utilization"},
            "gpu_0_vram_used_gb": {"category": "gpu", "metric": "vram_used_gb", "gpu_index": 0, "provider": "amdgpu", "label": "GPU VRAM used"},
            "gpu_0_throttle_applications_clocks": {"category": "gpu", "metric": "throttle_applications_clocks", "gpu_index": 0, "provider": "nvidia_smi", "kind": "nvidia_smi", "label": "GPU applications clocks setting", "query_field": "clocks_event_reasons.applications_clocks_setting", "evidence_only": True},
            "gpu_0_throttle_hw_slowdown": {"category": "gpu", "metric": "throttle_hw_slowdown", "gpu_index": 0, "provider": "nvidia_smi", "kind": "nvidia_smi", "label": "GPU hardware slowdown", "query_field": "clocks_event_reasons.hw_slowdown", "evidence_only": True},
            "gpu_0_throttle_hw_thermal": {"category": "gpu", "metric": "throttle_hw_thermal", "gpu_index": 0, "provider": "nvidia_smi", "kind": "nvidia_smi", "label": "GPU hardware thermal slowdown", "query_field": "clocks_event_reasons.hw_thermal_slowdown", "evidence_only": True},
            "gpu_0_throttle_idle": {"category": "gpu", "metric": "throttle_idle", "gpu_index": 0, "provider": "nvidia_smi", "kind": "nvidia_smi", "label": "GPU idle", "query_field": "clocks_event_reasons.gpu_idle", "evidence_only": True},
            "gpu_0_throttle_sw_thermal": {"category": "gpu", "metric": "throttle_sw_thermal", "gpu_index": 0, "provider": "nvidia_smi", "kind": "nvidia_smi", "label": "GPU software thermal slowdown", "query_field": "clocks_event_reasons.sw_thermal_slowdown", "evidence_only": True},
            "gpu_0_throttle_sync_boost": {"category": "gpu", "metric": "throttle_sync_boost", "gpu_index": 0, "provider": "nvidia_smi", "kind": "nvidia_smi", "label": "GPU sync boost", "query_field": "clocks_event_reasons.sync_boost", "evidence_only": True},
            "gpu_0_throttle_hw_power_brake": {"category": "gpu", "metric": "throttle_hw_power_brake", "gpu_index": 0, "provider": "nvidia_smi", "kind": "nvidia_smi", "label": "GPU hardware power brake slowdown", "query_field": "clocks_event_reasons.hw_power_brake_slowdown", "evidence_only": True},
            "gpu_0_throttle_sw_power_cap": {"category": "gpu", "metric": "throttle_sw_power_cap", "gpu_index": 0, "provider": "nvidia_smi", "kind": "nvidia_smi", "label": "GPU software power cap", "query_field": "clocks_event_reasons.sw_power_cap", "evidence_only": True},
            "gpu_1_temp_c": {"category": "gpu", "metric": "temperature_c", "gpu_index": 1, "provider": "amdgpu", "label": "GPU 2 edge"},
            "storage_drive_0_temp_c": {"category": "storage", "metric": "temperature_c", "drive_index": 0, "provider": "nvme_hwmon", "label": "NVMe composite", "path": "/sys/nvme/temp1_input"},
            "memory_module_0_temp_c": {"category": "memory_module", "metric": "temperature_c", "module_index": 0, "provider": "spd5118", "label": "DIMM 0", "path": "/sys/dimm/temp1_input"},
            "memory_used_gb": {"category": "memory", "metric": "memory_used_gb", "provider": "procfs", "label": "memory_used_gb"},
            "bmc_memory_power_w": {"category": "bmc", "metric": "power_w", "provider": "ipmi_bmc", "component_classification": "memory_rail", "component_locator": "memory", "raw_label": "Memory_Power", "normalized_units": "w"},
            "gpu_0_fan_percent": {"category": "gpu", "metric": "fan_percent", "gpu_index": 0, "provider": "nvidia_smi", "kind": "nvidia_smi", "label": "GPU fan speed", "query_field": "fan.speed"},
            "gpu_0_power_limit_percent": {"category": "gpu", "metric": "power_limit_percent", "gpu_index": 0, "provider": "nvidia_smi", "kind": "nvidia_smi", "label": "GPU power limit", "query_field": "power.limit"},
        },
    }


def _extended() -> Dict[str, Any]:
    return {
        "app_name": "Linux Validation Suite",
        "app_version": "0.2.0",
        "normalized_hardware_evidence": {
            "cpu": {
                "thermal": {"cpu_tjmax_c": 100, "cpu_tjmax_semantics": "coretemp_package_temp_crit_alias"},
                "frequency": {
                    "boost_enabled": True,
                    "boost_evidence": {"provider": "intel_pstate"},
                    "policy_groups": [{
                        "frequency_provider": "intel_pstate", "policy_ids": [0, 1],
                        "affected_logical_cpus": [0, 1], "base_frequency_mhz": 3000,
                        "hardware_min_frequency_mhz": 800, "hardware_max_frequency_mhz": 5200,
                        "policy_min_frequency_mhz": 800, "policy_max_frequency_mhz": 5200,
                    }],
                },
            },
            "gpus": [{
                "gpu_index": 0, "provider": "amdgpu",
                "clock_domains": {"core": {"maximum_frequency_mhz": 2500, "maximum_frequency_semantics": "available_dpm_level_max", "available_frequency_levels_mhz": [500, 1500, 2500]}},
                "thermal_domains": [{"domain": "edge", "provider": "amdgpu", "source_path": "/sys/gpu/temp1_input", "temperature_crit_c": 105, "confidence": "high"}],
            }],
            "storage_devices": [{
                "provider": "nvme", "source_path": "/sys/nvme/temp1_input", "confidence": "high",
                "storage_warning_temperature_c": 70, "storage_critical_temperature_c": 85,
            }],
            "memory_modules": [{
                "provider": "spd5118", "source_path": "/sys/dimm/temp1_input", "confidence": "high",
                "temperature_max_c": 85, "temperature_crit_c": 95,
            }],
        },
        "compatibility_export": {
            "Result": "PASS",
            "Segments": [{
                "Label": "CPU fallback stage", "DisplayName": "CPU fallback stage", "TestType": "CPU", "Verdict": "pass",
                "Started": "2026-01-02T00:00:00+00:00", "Ended": "2026-01-02T00:01:00+00:00", "Duration": 60,
                "Temperatures": {"Cpu": {"Min": 40, "Avg": 50, "Max": 60, "SampleCount": 4}},
                "Clocks": {"AllCoreAverage": {"Min": 3000, "Avg": 4000, "Max": 4900, "SampleCount": 4}},
                "Power": {"Cpu": {"Min": 40, "Avg": 80, "Max": 100, "SampleCount": 4}},
            }],
        },
    }


def _manifest(native: str = "pass") -> Dict[str, Any]:
    return {
        "contract_id": "linux_validation_suite.run_manifest", "contract_version": 1, "kind": "run_manifest",
        "app_version": "0.2.0", "profile_name": "Profile </script><img src=x onerror=alert(1)>",
        "profile_file": "profiles/test.json", "menu_description": "Synthetic report fixture",
        "started": "2026-01-02T00:00:00+00:00", "ended": "2026-01-02T00:04:00+00:00",
        "elapsed_seconds": 240, "verdict": native, "error_events": [], "warning_events": [],
        "stage_windows": [
            {"stage_id": "cpu_stage", "stage_type": "CPU", "display_name": "CPU workload", "display_label": "CPU <load>", "legacy_bucket_category": "CPU", "started_iso": "2026-01-02T00:00:00+00:00", "ended_iso": "2026-01-02T00:01:40+00:00", "started_monotonic": 100, "ended_monotonic": 200, "duration_seconds": 100, "trim_start_seconds": 10, "trim_end_seconds": 10, "verdict": "pass", "failure_reasons": [], "error_events": [], "system_faults": []},
            {"stage_id": "gpu_stage", "stage_type": "GPU", "display_name": "GPU workload", "display_label": "GPU workload", "legacy_bucket_category": "GPU", "started_iso": "2026-01-02T00:01:40+00:00", "ended_iso": "2026-01-02T00:03:20+00:00", "started_monotonic": 200, "ended_monotonic": 300, "duration_seconds": 100, "trim_start_seconds": 0, "trim_end_seconds": 0, "verdict": "pass", "failure_reasons": [], "error_events": [], "system_faults": []},
        ],
    }


def _build_fixture(root: Path, *, native: str = "pass", storage_hot: bool = False, raw: bool = True) -> None:
    _write_json(root, "run_manifest.json", _manifest(native))
    _write_json(root, "parsed_results_extended.json", _extended())
    _write_json(root, "telemetry_source_map.json", _source_map())
    _write_json(root, "profile_used.json", {"profile_name": "Profile <test>", "menu_description": "Synthetic"})
    _write_json(root, "run_metadata.json", {"description": "Operator & fixture", "operator": "<operator>", "case_sku": "database-only"})
    _write_json(root, "system_info.json", {
        "Hardware": {
            "Cpu": {"Name": "CPU <unsafe>"}, "Memory": {"Total": "64 GiB", "Modules": [
                {"Manufacturer": "Kingston", "PartNumber": "KF560C32-48", "Size": "48 GB", "OperatingSpeed": "4800 MT/s", "Position": "A2"},
                {"Manufacturer": "Kingston", "PartNumber": "KF560C32-48", "Size": "48 GB", "OperatingSpeed": "4800 MT/s", "Position": "B2"},
            ]},
            "Motherboard": {"Manufacturer": "Example", "Product": "Board & Co"},
            "Bios": {"Version": "1.0"}, "Gpu": [
                {"Card": "card0", "Name": "Mesa Intel Graphics", "Ignored": True, "Role": "display_only"},
                {"Card": "card1", "Name": "AMD Radeon Test", "Role": "validation"},
            ],
            "Storage": [{"Model": "NVMe One"}],
        },
        "OperatingSystem": {"PrettyName": "Linux Test"},
    })
    if raw:
        fields = ["timestamp", *_source_map()["fields"].keys()]
        rows = [
            [105, 20, 1000, 30, 20, 900, 800, 700, 2, 3, 4, 25, 35, 500, 10, 5000, 0.90, 5, 1.0, 0, 0, 0, 1, 0, 0, 0, 0, 28, 30, 12, 0, 0, 20, 90],
            [115, 50, 4000, 80, 50, 3900, 3800, 3700, 20, 25, 30, 55, 75, 1800, 120, 9500, 0.95, 75, 2.0, 0, 0, 0, 0, 0, 0, 0, 1, 58, 60, 13, 45, 65, 25, 100],
            [150, "", 4200, 90, "", 4100, 4050, 3950, 50, 55, 60, 58, 78, 1900, 130, 9700, 1.00, 80, 3.0, 0, 0, 1, 0, 0, 0, 0, 1, 62, 72 if storage_hot else 65, 14, 46, 66, 30, 100],
            [185, 80, 4500, 110, 80, 4400, 4350, 4250, 75, 80, 85, 62, 82, 2100, 140, 9800, 1.05, 85, 4.0, 0, 1, 0, 0, 0, 0, 0, 0, 65, 68, 15, 48, 67, 40, 95],
            [220, 75, 2000, 70, 75, 1900, 1850, 1750, 10, 15, 20, 90, 100, 2200, 150, 9900, 1.10, 90, 5.0, 0, 0, 0, 0, 1, 1, 0, 0, 80, 55, 16, 47, 68, 50, 90],
            [280, 70, 1800, 60, 70, 1700, 1650, 1550, 8, 9, 10, 85, 95, 2000, 145, 9400, 1.00, 70, 6.0, 0, 0, 0, 1, 0, 0, 1, 0, 78, 54, 17, 46, 67, 45, 90],
        ]
        with (root / "raw_telemetry.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(fields)
            writer.writerows(rows)


def _hashes(root: Path) -> Dict[str, str]:
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.iterdir() if path.is_file() and path.name not in {"lvs_report_data.json", "lvs_chart_data.json", "result_report.html"}
    }


def _synthetic_dense_core_chart(core_count: int, *, heterogeneous: bool) -> Dict[str, Any]:
    series = []
    for index in range(core_count):
        core_class = None
        prefix = "Core"
        if heterogeneous:
            core_class = "performance" if index < max(1, core_count // 3) else "efficiency"
            prefix = "P-Core" if core_class == "performance" else "E-Core"
        label = f"{prefix} {index}"
        series.append({
            "series_id": f"cpu_core_{index}_utilization_percent",
            "field": f"cpu_core_{index}_utilization_percent",
            "component_id": f"cpu:core:{index}", "component_label": label,
            "display_label": label, "selector_label": label,
            "metric_family": "Utilization", "metric_label": "Utilization",
            "display_unit": "%", "source_unit": "percent", "primary": False,
            "advanced_group": "cpu_cores", "core_index": index,
            "core_class": core_class, "core_class_label": core_class,
            "encoding": "points", "data": {"t": [0, 1], "v": [0, 1]},
        })
    return {
        "contract_id": CHART_DATA_CONTRACT_ID, "contract_version": 1,
        "kind": CHART_DATA_KIND, "available": True, "stages": [{
            "stage_id": "cpu_stage", "index": 0, "label": "Stage 1 — CPU workload",
            "description": "", "families": ["Utilization"], "series": series,
            "analysis_duration_seconds": 1, "trim_start_seconds": 0,
            "trim_end_seconds": 0, "workload_component_class": "cpu",
        }],
    }


def _write_boundary_telemetry(root: Path) -> None:
    with (root / "raw_telemetry.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["timestamp", "cpu_clock_mhz"])
        writer.writerows([
            [109.999, 9999],
            [110, 1100],
            [190, 1900],
            [190.001, 9999],
        ])


def _run_chart_data_checks() -> None:
    short = encode_series([(0.0, 0.0), (2.0, 1.0)])
    assert short["encoding"] == "points" and short["data"]["v"][0] == 0
    assert short["original_sample_count"] == short["plotted_point_count"] == 2

    plateau_points = [(float(index * 2), 550.0 if index < 1000 else 800.0) for index in range(FULL_SAMPLE_LIMIT + 101)]
    plateau = encode_series(plateau_points)
    assert plateau["encoding"] == "plateau_runs" and plateau["reduction"]["method"] == "exact_constant_runs"
    assert plateau["data"]["runs"] == [[0, 1998, 550], [2000, 4000, 800]]
    assert decode_series_points(plateau) == [(0.0, 550.0), (1998.0, 550.0), (2000.0, 800.0), (4000.0, 800.0)]

    changing = [(float(index), float((index * 37) % 101)) for index in range(5000)]
    changing[2222] = (2222.0, 999.0)
    changing[3333] = (3333.0, -99.0)
    reduced = extrema_reduce(changing, 400)
    assert changing[0] in reduced and changing[-1] in reduced
    assert changing[2222] in reduced and changing[3333] in reduced
    assert reduced == sorted(reduced) and len(reduced) <= 400
    encoded = encode_series(changing, full_sample_limit=100, point_budget=400)
    assert encoded["encoding"] == "extrema_buckets" and encoded["original_sample_count"] == 5000
    assert encoded["plotted_point_count"] == len(reduced)
    assert encode_series(changing, full_sample_limit=100, point_budget=400) == encoded

    with TemporaryDirectory(prefix="lvs_chart_contract_") as temporary:
        root = Path(temporary)
        fields = [
            "timestamp", "cpu_temp_c", "gpu_0_vram_used_gib", "gpu_0_vram_used_gb",
            "cpu_core_0_clock_mhz", "cpu_core_2_clock_mhz", "cpu_core_10_clock_mhz",
            "cpu_core_0_utilization_percent", "cpu_core_2_utilization_percent", "cpu_core_10_utilization_percent",
            "gpu_0_temp_memory_c", "gpu_0_memory_clock_mhz", "gpu_0_memory_busy_percent",
            "gpu_0_vddgfx_v", "gpu_0_memory_voltage_v", "gpu_0_utilization_percent", "gpu_0_fan_percent", "gpu_0_power_limit_percent",
            "gpu_0_throttle_applications_clocks", "gpu_0_throttle_hw_thermal",
            "gpu_0_throttle_hw_power_brake", "gpu_0_throttle_sw_power_cap", "gpu_0_throttle_voltage_reliability",
            "gpu_0_temp_core_c", "gpu_0_temp_hotspot_c",
            "storage_drive_0_temp_c", "storage_drive_0_sensor_1_temp_c",
            "storage_drive_0_sensor_2_temp_c", "storage_drive_0_sensor_3_temp_c",
            "bmc_temp_c", "bmc_voltage_v", "bmc_current_a",
            "bmc_memory_power_w", "bmc_fan_rpm", "bmc_percentage", "bmc_status",
        ]
        with (root / "raw_telemetry.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for timestamp in (9.999, 10, 15, 20, 20.001, 30, 40):
                value = max(0.0, timestamp - 10)
                writer.writerow({
                    "timestamp": timestamp, "cpu_temp_c": 50 + value,
                    "gpu_0_vram_used_gib": value, "gpu_0_vram_used_gb": value,
                    "cpu_core_0_clock_mhz": 1000 + value,
                    "cpu_core_2_clock_mhz": 1200 + value,
                    "cpu_core_10_clock_mhz": 1400 + value,
                    "cpu_core_0_utilization_percent": value,
                    "cpu_core_2_utilization_percent": value + 1,
                    "cpu_core_10_utilization_percent": value + 2,
                    "gpu_0_temp_memory_c": "nan" if timestamp == 15 else 60 + value,
                    "gpu_0_memory_clock_mhz": 1000 + value,
                    "gpu_0_memory_busy_percent": value,
                    "gpu_0_vddgfx_v": 0.9,
                    "gpu_0_memory_voltage_v": 1.35,
                    "gpu_0_utilization_percent": value,
                    "gpu_0_fan_percent": 45,
                    "gpu_0_power_limit_percent": 90,
                    "gpu_0_throttle_applications_clocks": 0,
                    "gpu_0_throttle_hw_thermal": 0,
                    "gpu_0_throttle_hw_power_brake": 0,
                    "gpu_0_throttle_sw_power_cap": 1 if timestamp == 20 else 0,
                    "gpu_0_throttle_voltage_reliability": 0,
                    "gpu_0_temp_core_c": 60 + value,
                    "gpu_0_temp_hotspot_c": 70 + value,
                    "storage_drive_0_temp_c": 40 + value,
                    "storage_drive_0_sensor_1_temp_c": 41 + value,
                    "storage_drive_0_sensor_2_temp_c": 42 + value,
                    "storage_drive_0_sensor_3_temp_c": 43 + value,
                    "bmc_temp_c": 30 + value, "bmc_voltage_v": 12,
                    "bmc_current_a": 4, "bmc_memory_power_w": 100 + value,
                    "bmc_fan_rpm": 1200, "bmc_percentage": 50, "bmc_status": 1,
                })
        catalog = [
            {"field": "cpu_temp_c", "component_id": "cpu:aggregate", "metric_class": "temperature", "unit": "c", "provider": "hwmon", "source": "cpu"},
            {"field": "cpu_core_0_clock_mhz", "component_id": "cpu:core:0", "metric_class": "clock", "unit": "mhz", "provider": "cpufreq", "source": "cpu0"},
            {"field": "cpu_core_2_clock_mhz", "component_id": "cpu:core:2", "metric_class": "clock", "unit": "mhz", "provider": "cpufreq", "source": "cpu2"},
            {"field": "cpu_core_10_clock_mhz", "component_id": "cpu:core:10", "metric_class": "clock", "unit": "mhz", "provider": "cpufreq", "source": "cpu10"},
            {"field": "cpu_core_0_utilization_percent", "component_id": "cpu:core:0", "metric_class": "percentage", "unit": "percent", "provider": "psutil", "source": "cpu0"},
            {"field": "cpu_core_2_utilization_percent", "component_id": "cpu:core:2", "metric_class": "percentage", "unit": "percent", "provider": "psutil", "source": "cpu2"},
            {"field": "cpu_core_10_utilization_percent", "component_id": "cpu:core:10", "metric_class": "percentage", "unit": "percent", "provider": "psutil", "source": "cpu10"},
            {"field": "gpu_0_vram_used_gib", "component_id": "gpu:0", "metric_class": "memory_usage", "unit": "gib", "provider": "gpu", "source": "vram"},
            {"field": "gpu_0_vram_used_gb", "component_id": "gpu:0", "metric_class": "other_numeric", "unit": "", "provider": "gpu", "source": "vram"},
            {"field": "gpu_0_temp_memory_c", "component_id": "gpu:0", "metric_class": "temperature", "unit": "c", "provider": "gpu", "source": "memory"},
            {"field": "gpu_0_memory_clock_mhz", "component_id": "gpu:0", "metric_class": "clock", "unit": "mhz", "provider": "gpu", "source": "mclk"},
            {"field": "gpu_0_memory_busy_percent", "component_id": "gpu:0", "metric_class": "percentage", "unit": "percent", "provider": "gpu", "source": "busy"},
            {"field": "gpu_0_vddgfx_v", "component_id": "gpu:0", "metric_class": "voltage", "unit": "v", "provider": "gpu", "source": "vddgfx"},
            {"field": "gpu_0_memory_voltage_v", "component_id": "gpu:0", "metric_class": "voltage", "unit": "v", "provider": "gpu", "source": "memory voltage"},
            {"field": "gpu_0_utilization_percent", "component_id": "gpu:0", "metric_class": "percentage", "unit": "percent", "provider": "gpu", "source": "utilization"},
            {"field": "gpu_0_fan_percent", "component_id": "gpu:0", "metric_class": "fan_speed", "unit": "percent", "provider": "gpu", "source": "fan.speed"},
            {"field": "gpu_0_power_limit_percent", "component_id": "gpu:0", "metric_class": "percentage", "unit": "percent", "provider": "gpu", "source": "power.limit"},
            {"field": "gpu_0_throttle_applications_clocks", "component_id": "gpu:0", "metric_class": "status", "unit": "", "provider": "nvidia_smi", "source": "clocks_event_reasons.applications_clocks_setting"},
            {"field": "gpu_0_throttle_hw_thermal", "component_id": "gpu:0", "metric_class": "status", "unit": "", "provider": "nvidia_smi", "source": "clocks_event_reasons.hw_thermal_slowdown"},
            {"field": "gpu_0_throttle_hw_power_brake", "component_id": "gpu:0", "metric_class": "status", "unit": "", "provider": "nvidia_smi", "source": "clocks_event_reasons.hw_power_brake_slowdown"},
            {"field": "gpu_0_throttle_sw_power_cap", "component_id": "gpu:0", "metric_class": "status", "unit": "", "provider": "nvidia_smi", "source": "clocks_event_reasons.sw_power_cap"},
            {"field": "gpu_0_throttle_voltage_reliability", "component_id": "gpu:0", "metric_class": "status", "unit": "", "provider": "nvidia_smi", "source": "clocks_event_reasons.sw_voltage_reliability"},
            {"field": "gpu_0_temp_core_c", "component_id": "gpu:0", "metric_class": "temperature", "unit": "c", "provider": "gpu", "source": "core", "source_label": "GPU edge"},
            {"field": "gpu_0_temp_hotspot_c", "component_id": "gpu:0", "metric_class": "temperature", "unit": "c", "provider": "gpu", "source": "hotspot"},
            {"field": "storage_drive_0_temp_c", "component_id": "storage:0", "metric_class": "temperature", "unit": "c", "provider": "storage_temp", "source": "temp1", "source_label": "NVMe Composite"},
            {"field": "storage_drive_0_sensor_1_temp_c", "component_id": "storage:0", "metric_class": "temperature", "unit": "c", "provider": "storage_temp_secondary", "source": "temp2", "source_label": "NVMe Sensor 1"},
            {"field": "storage_drive_0_sensor_2_temp_c", "component_id": "storage:0", "metric_class": "temperature", "unit": "c", "provider": "storage_temp_secondary", "source": "temp3", "source_label": "NVMe Sensor 2"},
            {"field": "storage_drive_0_sensor_3_temp_c", "component_id": "storage:0", "metric_class": "temperature", "unit": "c", "provider": "storage_temp_secondary", "source": "temp4", "source_label": "NVMe Controller"},
            {"field": "bmc_temp_c", "component_id": "bmc:thermal", "metric_class": "temperature", "unit": "c", "provider": "ipmi", "source": "bmc"},
            {"field": "bmc_voltage_v", "component_id": "bmc:rail", "metric_class": "voltage", "unit": "v", "provider": "ipmi", "source": "bmc"},
            {"field": "bmc_current_a", "component_id": "bmc:rail", "metric_class": "current", "unit": "a", "provider": "ipmi", "source": "bmc"},
            {"field": "bmc_memory_power_w", "component_id": "bmc:memory", "metric_class": "power", "unit": "w", "provider": "ipmi", "source": "bmc"},
            {"field": "bmc_fan_rpm", "component_id": "bmc:fan", "metric_class": "fan_speed", "unit": "rpm", "provider": "ipmi", "source": "bmc"},
            {"field": "bmc_percentage", "component_id": "bmc:misc", "metric_class": "percentage", "unit": "percent", "provider": "ipmi", "source": "bmc"},
            {"field": "bmc_status", "component_id": "bmc:status", "metric_class": "discrete", "unit": "", "provider": "ipmi", "source": "bmc"},
        ]
        windows = [
            {"stage_id": "one", "started_monotonic": 0, "ended_monotonic": 25, "trim_start_seconds": 10, "trim_end_seconds": 5, "analysis_started_monotonic": 10, "analysis_ended_monotonic": 20, "analysis_duration_seconds": 10, "analysis_window_valid": True, "normalization_sources": {"trim_start_seconds": "recorded", "trim_end_seconds": "recorded"}, "metric_window_semantics": "normalized_analysis_window"},
            {"stage_id": "two", "started_monotonic": 30, "ended_monotonic": 40, "trim_start_seconds": 0, "trim_end_seconds": 0, "analysis_started_monotonic": 30, "analysis_ended_monotonic": 40, "analysis_duration_seconds": 10, "analysis_window_valid": True, "normalization_sources": {"trim_start_seconds": "zero_default", "trim_end_seconds": "zero_default"}, "metric_window_semantics": "normalized_analysis_window"},
        ]
        report = {
            "contract_id": REPORT_DATA_CONTRACT_ID, "contract_version": 1,
            "chart_catalog": {"series": catalog, "stage_windows": windows},
            "stages": [
                {"stage_id": "one", "index": 0, "display_name": "One"},
                {"stage_id": "two", "index": 1, "display_name": "Two"},
            ],
            "components": [
                {"component_id": "cpu:aggregate", "label": "CPU"},
                {"component_id": "gpu:0", "label": "GPU"},
                {"component_id": "storage:0", "label": "Storage"},
                {"component_id": "bmc:memory", "label": "Memory rail"},
            ],
        }
        chart = compile_chart_data(root, report)
        assert chart["contract_id"] == CHART_DATA_CONTRACT_ID and chart["contract_version"] == CONTRACT_VERSION
        assert chart["kind"] == CHART_DATA_KIND and chart["authority"] == "derived_visualization_only"
        assert chart["window_inclusion"] == "analysis_start <= timestamp <= analysis_end"
        assert len(chart["stages"]) == 2 and chart["stages"][0]["analysis_started_monotonic"] == 10
        first = {series["field"]: series for series in chart["stages"][0]["series"]}
        assert "gpu_0_vram_used_gib" in first and "gpu_0_vram_used_gb" not in first
        for field in ("gpu_0_vram_used_gib", "gpu_0_temp_memory_c", "gpu_0_memory_clock_mhz", "gpu_0_memory_busy_percent"):
            assert first[field]["primary"]
        assert first["gpu_0_temp_memory_c"]["metric_label"] == "VRAM temperature"
        assert first["gpu_0_memory_clock_mhz"]["metric_label"] == "VRAM clock" and first["gpu_0_memory_clock_mhz"]["display_unit"] == "GHz"
        assert first["gpu_0_memory_busy_percent"]["metric_label"] == "VRAM utilization"
        assert first["gpu_0_vddgfx_v"]["metric_family"] == "Voltage" and first["gpu_0_vddgfx_v"]["display_unit"] == "V"
        assert first["gpu_0_vddgfx_v"]["primary"] and first["gpu_0_vddgfx_v"]["selector_label"] == "GPU 1 VDDGFX"
        assert not first["gpu_0_memory_voltage_v"]["primary"]
        assert first["gpu_0_memory_voltage_v"]["selector_label"] == "GPU 1 memory voltage"
        assert not any(series["field"].startswith("cpu_") and series["metric_family"] == "Voltage" for series in first.values())
        assert first["gpu_0_utilization_percent"]["metric_family"] == "Utilization" and first["gpu_0_utilization_percent"]["display_unit"] == "%"
        assert first["gpu_0_fan_percent"]["metric_family"] == "Fan duty" and first["gpu_0_fan_percent"]["display_unit"] == "%"
        assert first["gpu_0_fan_percent"]["primary"]
        assert first["gpu_0_power_limit_percent"]["metric_family"] == "Percentage"
        assert first["gpu_0_fan_percent"]["metric_family"] != "Utilization"
        assert first["gpu_0_utilization_percent"]["selector_label"] == "GPU 1 core"
        assert first["gpu_0_memory_busy_percent"]["selector_label"] == "GPU 1 VRAM"
        assert not any("throttle" in field for field in first)
        for stage in chart["stages"]:
            for family in stage["families"]:
                labels = [series["selector_label"] for series in stage["series"] if series["metric_family"] == family]
                assert len(labels) == len(set(labels))
        assert first["gpu_0_temp_hotspot_c"]["primary"] and not first["bmc_memory_power_w"]["primary"]
        gpu_temperatures = [
            first[field] for field in ("gpu_0_temp_core_c", "gpu_0_temp_hotspot_c", "gpu_0_temp_memory_c")
        ]
        assert all(series["primary"] for series in gpu_temperatures)
        assert [series["selector_label"] for series in gpu_temperatures] == ["GPU 1 core", "GPU 1 hotspot", "GPU 1 VRAM"]
        assert len({series["selector_label"] for series in gpu_temperatures}) == 3
        assert first["storage_drive_0_temp_c"]["primary"]
        assert first["storage_drive_0_temp_c"]["metric_label"] == "Composite temperature"
        for field in ("storage_drive_0_sensor_1_temp_c", "storage_drive_0_sensor_2_temp_c", "storage_drive_0_sensor_3_temp_c"):
            assert not first[field]["primary"]
        assert first["storage_drive_0_sensor_1_temp_c"]["metric_label"] == "Sensor 1 temperature"
        assert first["storage_drive_0_sensor_2_temp_c"]["metric_label"] == "Sensor 2 temperature"
        assert first["storage_drive_0_sensor_3_temp_c"]["metric_label"] == "Controller temperature"
        assert "controller" not in first["storage_drive_0_temp_c"]["metric_label"].lower()
        assert "controller" not in first["storage_drive_0_sensor_1_temp_c"]["metric_label"].lower()
        assert "nand" not in first["storage_drive_0_sensor_2_temp_c"]["metric_label"].lower()
        clock_cores = [series for series in chart["stages"][0]["series"] if series["metric_family"] == "Clock" and series["advanced_group"] == "cpu_cores"]
        util_cores = [series for series in chart["stages"][0]["series"] if series["metric_family"] == "Utilization" and series["advanced_group"] == "cpu_cores"]
        assert [series["core_index"] for series in clock_cores] == [0, 2, 10]
        assert [series["core_index"] for series in util_cores] == [0, 2, 10]
        assert all(not series["primary"] for series in clock_cores + util_cores)
        assert all(series["core_class"] is None for series in clock_cores + util_cores)
        assert all(series["display_label"].startswith("CPU core ") for series in clock_cores + util_cores)
        assert "effective" not in canonical_chart_json(chart).lower()
        assert "bmc_status" not in first
        assert {first[field]["metric_family"] for field in ("bmc_temp_c", "bmc_voltage_v", "bmc_current_a", "bmc_memory_power_w", "bmc_fan_rpm", "bmc_percentage")} == {"Temperature", "Voltage", "Current", "Power", "Fan speed", "Percentage"}
        vram = first["gpu_0_vram_used_gib"]
        assert vram["data"]["t"] == [0, 5, 10] and vram["data"]["v"][0] == 0
        assert first["gpu_0_temp_memory_c"]["original_sample_count"] == 2
        second = chart["stages"][1]["series"][0]
        assert second["data"]["t"][0] == 0 and second["data"]["t"][-1] == 10
        assert canonical_chart_json(chart) == canonical_chart_json(compile_chart_data(root, report))
        without_hotspot = {
            **report,
            "chart_catalog": {
                **report["chart_catalog"],
                "series": [item for item in catalog if item["field"] != "gpu_0_temp_hotspot_c"],
            },
        }
        assert not any(
            series["field"] == "gpu_0_temp_hotspot_c"
            for stage in compile_chart_data(root, without_hotspot)["stages"]
            for series in stage["series"]
        )
        (root / "raw_telemetry.csv").unlink()
        unavailable = compile_chart_data(root, report)
        assert not unavailable["available"] and unavailable["unavailable_reason"] == "raw_telemetry_absent"


def run_standalone_report_checks() -> None:
    _run_chart_data_checks()
    with TemporaryDirectory(prefix="lvs_report_smoke_") as temporary:
        root = Path(temporary)
        _build_fixture(root)
        report = compile_report_data(root, generated_at="2026-01-03T00:00:00+00:00")
        assert report["contract_id"] == REPORT_DATA_CONTRACT_ID
        assert report["contract_version"] == CONTRACT_VERSION
        assert report["kind"] == REPORT_DATA_KIND
        assert {
            "generated_at", "generator", "run", "review", "hardware", "hardware_references",
            "components", "stages", "chart_catalog", "provenance", "contract_id",
            "contract_version", "kind",
        }.issubset(report)
        assert report["run"]["report_outcome"] == "PASS"
        assert [stage["stage_id"] for stage in report["stages"]] == ["cpu_stage", "gpu_stage"]
        first = report["stages"][0]
        assert first["display_label"] == "CPU <load>" and first["stage_type"] == "CPU"
        assert first["analysis_started_monotonic"] == 110 and first["analysis_ended_monotonic"] == 190
        assert first["duration_seconds"] == 100 and first["analysis_duration_seconds"] == 80
        assert first["normalization_sources"] == {
            "trim_start_seconds": "recorded_stage_window",
            "trim_end_seconds": "recorded_stage_window",
        }
        assert first["metric_summary_source"] == "raw_telemetry"
        assert first["metric_window_semantics"] == "normalized_analysis_window"
        core_components = {
            component["component_id"]: component for component in report["components"]
            if str(component.get("component_id") or "").startswith("cpu:core:")
        }
        assert core_components["cpu:core:0"]["display_label"] == "P-Core 0"
        assert core_components["cpu:core:2"]["core_class"] == "performance"
        assert core_components["cpu:core:10"]["display_label"] == "E-Core 10"
        assert core_components["cpu:core:10"]["core_class"] == "efficiency"
        assert {field for component in core_components.values() for field in component["telemetry_fields"]} >= {
            "cpu_core_0_clock_mhz", "cpu_core_2_clock_mhz", "cpu_core_10_clock_mhz",
            "cpu_core_0_utilization_percent", "cpu_core_2_utilization_percent", "cpu_core_10_utilization_percent",
        }
        core_metrics = [metric for metric in first["metrics"] if str(metric.get("component_id") or "").startswith("cpu:core:")]
        assert {metric["field"] for metric in core_metrics} >= {"cpu_core_0_clock_mhz", "cpu_core_10_utilization_percent"}
        assert any(metric.get("display_label") == "P-Core 0" for metric in core_metrics)
        assert any(metric.get("display_label") == "E-Core 10" for metric in core_metrics)
        assert report["stages"][1]["analysis_started_monotonic"] == 200
        assert report["stages"][1]["analysis_ended_monotonic"] == 300
        assert report["stages"][1]["analysis_duration_seconds"] == 100
        cpu_temp = next(metric for metric in first["metrics"] if metric["field"] == "cpu_temp_c")
        assert cpu_temp["sample_count"] == 2 and cpu_temp["minimum"] == 50 and cpu_temp["maximum"] == 80
        component_rows = _stage_component_rows(first, _component_index(report["components"]))
        cpu_row = next(row for row in component_rows if row["label"] == "CPU")
        gpu_row = next(row for row in component_rows if row["component_id"] == "gpu:0")
        dimm_row = next(row for row in component_rows if row["component_id"] == "memory_module:0")
        storage_row = next(row for row in component_rows if row["component_id"] == "storage:0")
        assert cpu_row["temperature"]["field"] == "cpu_package_0_temp_c"
        assert gpu_row["temperature"]["field"] == "gpu_0_temp_c"
        assert gpu_row["power"]["field"] == "gpu_0_power_w"
        assert dimm_row["temperature"]["field"] == "memory_module_0_temp_c"
        assert storage_row["temperature"]["field"] == "storage_drive_0_temp_c"
        assert not any(str(row["component_id"]).startswith(("bmc:", "device:", "platform:")) for row in component_rows)
        assert any(item["component_id"] == "gpu:0" for item in report["components"])
        assert any(item["component_id"].startswith("bmc:memory_rail:") for item in report["components"])
        assert report["chart_catalog"]["samples_embedded"] is False
        assert "case_sku" not in report["run"]["metadata"]
        assert "samples" not in report["chart_catalog"]
        assert all(
            {"field", "component_id", "metric_class", "unit", "source_label", "provider", "source"}.issubset(series)
            for series in report["chart_catalog"]["series"]
        )
        catalog_by_field = {series["field"]: series for series in report["chart_catalog"]["series"]}
        for field in (
            "gpu_0_throttle_applications_clocks", "gpu_0_throttle_hw_slowdown",
            "gpu_0_throttle_hw_thermal", "gpu_0_throttle_idle",
            "gpu_0_throttle_sw_thermal", "gpu_0_throttle_sync_boost",
            "gpu_0_throttle_hw_power_brake", "gpu_0_throttle_sw_power_cap",
        ):
            assert catalog_by_field[field]["metric_class"] == "status"
            assert catalog_by_field[field]["unit"] == ""
        assert catalog_by_field["gpu_0_clock_mhz"]["metric_class"] == "clock"
        assert catalog_by_field["gpu_0_memory_clock_mhz"]["metric_class"] == "clock"
        assert catalog_by_field["gpu_0_temp_c"]["metric_class"] == "temperature"
        assert catalog_by_field["gpu_0_power_w"]["metric_class"] == "power"
        assert catalog_by_field["gpu_0_voltage_v"]["metric_class"] == "voltage"
        assert catalog_by_field["gpu_0_utilization_percent"]["metric_class"] == "percentage"
        assert catalog_by_field["memory_used_gb"]["metric_class"] == "memory_usage"
        assert catalog_by_field["gpu_0_vram_used_gb"]["metric_class"] == "memory_usage"
        assert catalog_by_field["gpu_0_fan_percent"]["metric_class"] == "fan_duty"
        assert catalog_by_field["gpu_0_fan_percent"]["unit"] == "percent"
        assert catalog_by_field["gpu_0_power_limit_percent"]["metric_class"] == "percentage"
        assert catalog_by_field["gpu_0_power_limit_percent"]["unit"] == "percent"
        first_chart_window = report["chart_catalog"]["stage_windows"][0]
        assert first_chart_window == {
            "stage_id": "cpu_stage",
            "started_monotonic": 100,
            "ended_monotonic": 200,
            "trim_start_seconds": 10,
            "trim_end_seconds": 10,
            "analysis_started_monotonic": 110,
            "analysis_ended_monotonic": 190,
            "analysis_duration_seconds": 80,
            "analysis_window_valid": True,
            "normalization_sources": {
                "trim_start_seconds": "recorded_stage_window",
                "trim_end_seconds": "recorded_stage_window",
            },
            "metric_summary_source": "raw_telemetry",
            "metric_window_semantics": "normalized_analysis_window",
        }
        assert report["hardware_references"]["clock_capabilities"]
        assert not report["review"]["warnings"]
        assert report == compile_report_data(root, generated_at="2026-01-03T00:00:00+00:00")

        profile_default = root / "profile_default_trim"
        profile_default.mkdir()
        _build_fixture(profile_default)
        default_manifest = json.loads((profile_default / "run_manifest.json").read_text())
        default_manifest["stage_windows"][0].pop("trim_start_seconds")
        default_manifest["stage_windows"][0].pop("trim_end_seconds")
        _write_json(profile_default, "run_manifest.json", default_manifest)
        _write_json(profile_default, "profile_used.json", {
            "profile_name": "Recorded defaults",
            "defaults": {"trim_start_seconds": 12, "trim_end_seconds": 8},
            "stages": [{"id": "cpu_stage", "enabled": True, "normalization": {}}],
        })
        default_stage = compile_report_data(profile_default, generated_at="fixed")["stages"][0]
        assert default_stage["trim_start_seconds"] == 12 and default_stage["trim_end_seconds"] == 8
        assert default_stage["analysis_started_monotonic"] == 112 and default_stage["analysis_ended_monotonic"] == 192
        assert set(default_stage["normalization_sources"].values()) == {"recorded_profile_defaults"}

        stage_override = root / "stage_override_trim"
        stage_override.mkdir()
        _build_fixture(stage_override)
        override_manifest = json.loads((stage_override / "run_manifest.json").read_text())
        override_manifest["stage_windows"][0].pop("trim_start_seconds")
        override_manifest["stage_windows"][0].pop("trim_end_seconds")
        _write_json(stage_override, "run_manifest.json", override_manifest)
        _write_json(stage_override, "profile_used.json", {
            "profile_name": "Recorded override",
            "defaults": {"trim_start_seconds": 4, "trim_end_seconds": 5},
            "stages": [{
                "id": "cpu_stage", "enabled": True,
                "normalization": {"trim_start_seconds": 7, "trim_end_seconds": 9},
            }],
        })
        override_stage = compile_report_data(stage_override, generated_at="fixed")["stages"][0]
        assert override_stage["trim_start_seconds"] == 7 and override_stage["trim_end_seconds"] == 9
        assert override_stage["analysis_started_monotonic"] == 107 and override_stage["analysis_ended_monotonic"] == 191
        assert set(override_stage["normalization_sources"].values()) == {"recorded_profile_stage_normalization"}

        recorded_window = root / "recorded_window_trim"
        recorded_window.mkdir()
        _build_fixture(recorded_window)
        _write_json(recorded_window, "profile_used.json", {
            "profile_name": "Recorded run",
            "defaults": {"trim_start_seconds": 40, "trim_end_seconds": 40},
            "stages": [{
                "id": "cpu_stage", "enabled": True,
                "normalization": {"trim_start_seconds": 35, "trim_end_seconds": 35},
            }],
        })
        (recorded_window / "profiles").mkdir()
        _write_json(recorded_window / "profiles", "test.json", {
            "defaults": {"trim_start_seconds": 49, "trim_end_seconds": 49},
            "stages": [{"id": "cpu_stage", "normalization": {"trim_start_seconds": 48, "trim_end_seconds": 48}}],
        })
        persisted_stage = compile_report_data(recorded_window, generated_at="fixed")["stages"][0]
        assert persisted_stage["trim_start_seconds"] == 10 and persisted_stage["trim_end_seconds"] == 10
        assert set(persisted_stage["normalization_sources"].values()) == {"recorded_stage_window"}

        boundary = root / "normalized_boundaries"
        boundary.mkdir()
        _build_fixture(boundary)
        _write_boundary_telemetry(boundary)
        boundary_report = compile_report_data(boundary, generated_at="fixed")
        boundary_stage = boundary_report["stages"][0]
        boundary_clock = next(metric for metric in boundary_stage["metrics"] if metric["field"] == "cpu_clock_mhz")
        assert boundary_clock["sample_count"] == 2
        assert boundary_clock["minimum"] == 1100 and boundary_clock["maximum"] == 1900
        assert boundary_stage["analysis_started_monotonic"] == 110
        assert boundary_stage["analysis_ended_monotonic"] == 190
        assert boundary_report["stages"][1]["metrics"] == []

        inverted = root / "inverted_normalization"
        inverted.mkdir()
        _build_fixture(inverted)
        inverted_manifest = json.loads((inverted / "run_manifest.json").read_text())
        inverted_manifest["stage_windows"][0]["trim_start_seconds"] = 80
        inverted_manifest["stage_windows"][0]["trim_end_seconds"] = 30
        _write_json(inverted, "run_manifest.json", inverted_manifest)
        with (inverted / "raw_telemetry.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["timestamp", "cpu_clock_mhz"])
            writer.writerow([180, 1800])
        inverted_stage = compile_report_data(inverted, generated_at="fixed")["stages"][0]
        assert inverted_stage["analysis_started_monotonic"] == 180
        assert inverted_stage["analysis_ended_monotonic"] == 180
        assert inverted_stage["analysis_duration_seconds"] == 0
        assert inverted_stage["analysis_window_valid"] is False
        assert inverted_stage["metrics"] == []

        hot_root = root / "hot"
        hot_root.mkdir()
        _build_fixture(hot_root, storage_hot=True)
        hot = compile_report_data(hot_root, generated_at="fixed")
        assert hot["run"]["report_outcome"] == "WARNING"
        assert any(item["category"] == "provider_temperature_warning" for item in hot["review"]["warnings"])
        assert 'review-card warning' in render_report_html(hot)

        for native, expected in (("warning", "WARNING"), ("fail", "FAIL"), ("aborted", "ABORTED"), ("manually_aborted", "MANUALLY_ABORTED")):
            case = root / native
            case.mkdir()
            _build_fixture(case, native=native)
            if native == "warning":
                manifest = json.loads((case / "run_manifest.json").read_text())
                manifest["warning_events"] = [{"severity": "warning", "category": "native_warning", "message": "Authoritative warning"}]
                _write_json(case, "run_manifest.json", manifest)
            result = compile_report_data(case, generated_at="fixed")
            assert result["run"]["native_outcome"] == native and result["run"]["report_outcome"] == expected
            expected_css = "aborted" if "abort" in native else ("fail" if native == "fail" else "warning")
            outcome_html = render_report_html(result)
            assert f'result-tile {expected_css}' in outcome_html
            result_markup = outcome_html[
                outcome_html.index('<div class="result-tile'):
                outcome_html.index('<section class="panel run-details"')
            ]
            assert f'<div class="result-value">{expected.replace("_", " ")}</div>' in result_markup
            assert '<span class="badge' not in result_markup
            if "abort" in native:
                assert not result["review"]["failures"]
                assert ".result-tile.aborted,.result-tile.unknown{background:var(--info-soft);border-color:var(--border-strong)}" in outcome_html

        for stage_abort in ("aborted", "manually_aborted"):
            inconsistent = root / f"stage_{stage_abort}"
            inconsistent.mkdir()
            _build_fixture(inconsistent)
            inconsistent_manifest = json.loads((inconsistent / "run_manifest.json").read_text())
            inconsistent_manifest["verdict"] = "pass"
            inconsistent_manifest["stage_windows"][0]["verdict"] = stage_abort
            _write_json(inconsistent, "run_manifest.json", inconsistent_manifest)
            inconsistent_report = compile_report_data(inconsistent, generated_at="fixed")
            assert inconsistent_report["run"]["native_outcome"] == "pass"
            assert inconsistent_report["run"]["report_outcome"] == stage_abort.upper()

        failed = root / "stage_failed"
        failed.mkdir()
        _build_fixture(failed)
        manifest = json.loads((failed / "run_manifest.json").read_text())
        manifest["stage_windows"][0]["verdict"] = "fail"
        manifest["stage_windows"][0]["failure_reasons"] = ["Worker integrity failed"]
        _write_json(failed, "run_manifest.json", manifest)
        failed_report = compile_report_data(failed, generated_at="fixed")
        assert failed_report["run"]["report_outcome"] == "FAIL"
        failed_html = render_report_html(failed_report)
        assert "Stage evidence" in failed_html and "Worker integrity failed" in failed_html

        fallback = root / "fallback"
        fallback.mkdir()
        _write_json(fallback, "parsed_results_extended.json", _extended())
        fallback_report = compile_report_data(fallback, generated_at="fixed")
        assert len(fallback_report["stages"]) == 1
        assert any(metric["summary_source"] == "parsed_segment_fallback" for metric in fallback_report["stages"][0]["metrics"])
        assert any(component["component_id"] == "cpu:aggregate" for component in fallback_report["components"])
        assert fallback_report["provenance"]["metric_summary_source"] == "parsed_segment_fallback"
        assert fallback_report["chart_catalog"]["raw_artifact"] is None
        assert fallback_report["chart_catalog"]["source_map_artifact"] is None

        fallback_normalized = root / "fallback_normalized"
        fallback_normalized.mkdir()
        _build_fixture(fallback_normalized, raw=False)
        fallback_normalized_report = compile_report_data(fallback_normalized, generated_at="fixed")
        fallback_stage = fallback_normalized_report["stages"][0]
        fallback_cpu_temp = next(metric for metric in fallback_stage["metrics"] if metric["field"] == "cpu_temp_c")
        assert fallback_cpu_temp["minimum"] == 40 and fallback_cpu_temp["average"] == 50 and fallback_cpu_temp["maximum"] == 60
        assert fallback_cpu_temp["sample_count"] == 4
        assert fallback_cpu_temp["summary_source"] == "parsed_segment_fallback"
        assert fallback_stage["metric_summary_source"] == "parsed_segment_fallback"
        assert fallback_stage["metric_window_semantics"] == "existing_parsed_normalized_summary"
        assert fallback_stage["duration_seconds"] == 100 and fallback_stage["analysis_duration_seconds"] == 80
        assert fallback_stage["analysis_started_monotonic"] == 110 and fallback_stage["analysis_ended_monotonic"] == 190
        fallback_chart_window = fallback_normalized_report["chart_catalog"]["stage_windows"][0]
        assert fallback_chart_window["metric_window_semantics"] == "existing_parsed_normalized_summary"
        assert fallback_chart_window["trim_start_seconds"] == 10 and fallback_chart_window["trim_end_seconds"] == 10
        assert fallback_normalized_report["provenance"]["metric_window_semantics"] == "existing_parsed_normalized_summary"

        partial = root / "partial"
        partial.mkdir()
        _write_json(partial, "run_manifest.json", {"verdict": "manually_aborted", "stage_windows": []})
        partial_report = compile_report_data(partial, generated_at="fixed")
        assert partial_report["stages"] == [] and partial_report["run"]["report_outcome"] == "MANUALLY_ABORTED"

        integrated_only = root / "integrated_only"
        integrated_only.mkdir()
        _build_fixture(integrated_only)
        integrated_system = json.loads((integrated_only / "system_info.json").read_text())
        integrated_system["Hardware"]["Gpu"] = [{"Card": "card0", "Name": "Integrated GPU", "Role": "validation"}]
        _write_json(integrated_only, "system_info.json", integrated_system)
        integrated_source = _source_map()
        integrated_source["fields"] = {
            key: value for key, value in integrated_source["fields"].items()
            if key in {"cpu_clock_mhz", "gpu_0_temp_c"}
        }
        integrated_source["gpu_index_map"] = integrated_source["gpu_index_map"][:1]
        _write_json(integrated_only, "telemetry_source_map.json", integrated_source)
        with (integrated_only / "raw_telemetry.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["timestamp", "cpu_clock_mhz", "gpu_0_temp_c"])
            writer.writerow([150, 4000, 50])
        integrated_report = compile_report_data(integrated_only, generated_at="fixed")
        assert len(integrated_report["hardware"]["gpus"]) == 1
        assert {item["component_class"] for item in integrated_report["components"]} == {"cpu", "gpu"}
        assert not any(item["component_class"] in {"memory_module", "storage", "bmc", "board"} for item in integrated_report["components"])

        source_map_absent = root / "source_map_absent"
        source_map_absent.mkdir()
        _build_fixture(source_map_absent)
        (source_map_absent / "telemetry_source_map.json").unlink()
        absent_report = compile_report_data(source_map_absent, generated_at="fixed")
        assert absent_report["stages"] and absent_report["chart_catalog"]["source_map_artifact"] is None
        assert any(metric["summary_source"] == "raw_telemetry" for metric in absent_report["stages"][0]["metrics"])

        metric = {"field": "cpu_temp_c", "component_id": "cpu:aggregate", "sample_count": 1, "minimum": 80, "average": 80, "maximum": 80}
        wrong = evaluate_temperature_context(metric, {"field": "gpu_0_temp_c", "component_id": "gpu:0", "warning_limit_c": 70, "confidence": "high"})
        ambiguous = evaluate_temperature_context(metric, {"field": "cpu_temp_c", "component_id": "cpu:aggregate", "warning_limit_c": 70, "confidence": "ambiguous"})
        sentinel = evaluate_temperature_context(metric, {"field": "cpu_temp_c", "component_id": "cpu:aggregate", "warning_limit_c": 1000, "confidence": "high"})
        missing = evaluate_temperature_context(metric, {"field": "cpu_temp_c", "component_id": "cpu:aggregate", "confidence": "high"})
        critical_only = evaluate_temperature_context(metric, {
            "field": "cpu_temp_c", "component_id": "cpu:aggregate", "provider": "coretemp",
            "source": "cpu_tjmax", "confidence": "high", "critical_limit_c": 70,
            "critical_semantics": "tjmax",
        })
        context_only = evaluate_temperature_context(metric, {
            "field": "cpu_temp_c", "component_id": "cpu:aggregate", "provider": "hwmon",
            "source": "maximum operating value", "confidence": "high", "warning_limit_c": 70,
            "warning_is_context_only": True,
        })
        explicit_warning = evaluate_temperature_context(metric, {
            "field": "cpu_temp_c", "component_id": "cpu:aggregate", "provider": "trusted_provider",
            "source": "explicit warning threshold", "confidence": "trusted", "warning_limit_c": 70,
            "warning_semantics": "provider_warning_threshold",
        })
        assert not wrong["dynamic_warning"] and not ambiguous["dynamic_warning"]
        assert "warning_limit_c" not in sentinel and not missing["dynamic_warning"]
        assert not critical_only["dynamic_warning"] and critical_only["critical_crossed"]
        assert not context_only["dynamic_warning"] and context_only["warning_crossed"]
        assert explicit_warning["dynamic_warning"]
        assert explicit_warning["provider"] == "trusted_provider" and explicit_warning["source"] == "explicit warning threshold"
        assert explicit_warning["confidence"] == "trusted" and explicit_warning["warning_semantics"] == "provider_warning_threshold"
        clock = evaluate_clock_context({"field": "cpu_clock_mhz", "component_id": "cpu:aggregate", "maximum": 3000}, {"component_id": "cpu:aggregate", "hardware_max_frequency_mhz": 5200})
        assert clock["evaluation"] == "informational_only" and clock["warning"] is False

        source_hashes = _hashes(root)
        data_path, chart_path, html_path = generate_report(root, generated_at="fixed")
        assert data_path.name == "lvs_report_data.json" and chart_path.name == "lvs_chart_data.json" and html_path.name == "result_report.html"
        persisted = json.loads(data_path.read_text(encoding="utf-8"))
        persisted_chart = json.loads(chart_path.read_text(encoding="utf-8"))
        html_text = html_path.read_text(encoding="utf-8")
        assert not any(
            "throttle" in series.get("field", "")
            for stage in persisted_chart["stages"]
            for series in stage["series"]
        )
        for stage in persisted_chart["stages"]:
            for family in stage["families"]:
                labels = [series["selector_label"] for series in stage["series"] if series["metric_family"] == family]
                assert len(labels) == len(set(labels))
        persisted_first = {series["field"]: series for series in persisted_chart["stages"][0]["series"]}
        assert persisted_first["gpu_0_fan_percent"]["metric_family"] == "Fan duty"
        assert persisted_first["gpu_0_fan_percent"]["primary"]
        assert persisted_first["gpu_0_voltage_v"]["metric_family"] == "Voltage"
        assert persisted_first["gpu_0_voltage_v"]["primary"]
        assert persisted_first["gpu_0_voltage_v"]["selector_label"] == "GPU 1"
        assert not any(
            series["metric_family"] == "Voltage" and series["component_id"].startswith("cpu:")
            for series in persisted_first.values()
        )
        assert persisted_first["gpu_0_power_limit_percent"]["metric_family"] == "Percentage"
        assert persisted_first["gpu_0_utilization_percent"]["selector_label"] == "GPU 1"
        assert "Throttle applications clocks" in html_text
        throttle_cell = html_text[html_text.index("Throttle applications clocks"):html_text.index("gpu_0_throttle_applications_clocks")]
        assert "Hz" not in throttle_cell and "Clock" not in throttle_cell
        chart_core_series = [
            series for series in persisted_chart["stages"][0]["series"]
            if series.get("advanced_group") == "cpu_cores"
        ]
        assert {series["field"] for series in chart_core_series} >= {"cpu_core_0_clock_mhz", "cpu_core_10_utilization_percent"}
        assert {series.get("core_class") for series in chart_core_series} == {"performance", "efficiency"}
        assert {series.get("display_label") for series in chart_core_series} >= {"P-Core 0", "P-Core 2", "E-Core 10"}
        assert all(not series["primary"] for series in chart_core_series)
        payload_match = re.search(r'<script id="lvs-chart-data" type="application/json" data-encoding="base64">([^<]+)</script>', html_text)
        assert payload_match and json.loads(base64.b64decode(payload_match.group(1))) == persisted_chart
        assert canonical_chart_json(persisted_chart) + "\n" == chart_path.read_text(encoding="utf-8")
        assert persisted_chart["contract_id"] == CHART_DATA_CONTRACT_ID
        assert persisted_chart["kind"] == CHART_DATA_KIND and persisted_chart["contract_version"] == 1
        generate_report(root)
        deterministic_data = data_path.read_bytes()
        deterministic_chart = chart_path.read_bytes()
        deterministic_html = html_path.read_bytes()
        assert json.loads(deterministic_data)["generated_at"] is None
        generate_report(root)
        assert data_path.read_bytes() == deterministic_data
        assert chart_path.read_bytes() == deterministic_chart
        assert html_path.read_bytes() == deterministic_html
        assert not list(root.glob(".*.tmp"))
        for heading in ("System identity", "Review summary", "Stage overview", "Component mapping", "Hardware references and advanced details", "Telemetry explorer"):
            assert heading in html_text
        assert html_text.index("Stage overview") < html_text.index("Telemetry explorer") < html_text.index("Component mapping")
        assert "Component key" not in html_text
        assert ".shell{width:calc(100% - 48px);max-width:1650px" in html_text
        assert "@media(max-width:1599px){.stage-grid{grid-template-columns:repeat(2" in html_text
        assert "@media(max-width:1039px){.stage-grid{grid-template-columns:1fr" in html_text
        assert ".stage-grid{grid-template-columns:repeat(3,minmax(0,1fr))}" in html_text
        assert "grid-template-columns:minmax(0,1.45fr) minmax(0,.78fr) minmax(0,1.25fr) minmax(0,.78fr)" in html_text
        assert "gradient" not in html_text.lower()
        assert ".summary-grid{align-items:stretch}" in html_text
        assert ".summary-grid>.result-tile,.summary-grid>.run-details{height:100%;margin-bottom:0}" in html_text
        assert ".summary-grid>.result-tile,.summary-grid>.run-details{height:auto}" in html_text
        assert not re.search(r"\.summary-grid>[^}]*height:\d+px", html_text)
        assert '<section class="panel run-details">' in html_text
        assert ".result-tile{border:1px solid var(--border-strong);background:var(--info-soft)}" in html_text
        assert html_text.rindex(".result-tile{border:1px solid") > html_text.rindex(".result-tile{padding:13px 16px;border-top:4px")
        assert ".result-tile.pass{background:var(--success-soft);border-color:#b7dfc5}" in html_text
        assert ".result-tile.warning{background:var(--warning-soft);border-color:#ead59c}" in html_text
        assert ".result-tile.fail{background:var(--danger-soft);border-color:#efc2c2}" in html_text
        assert ".run-details{background:var(--bg-surface);border-color:var(--border)}" in html_text
        assert '<details class="component-mapping secondary-disclosure"><summary>Component mapping</summary>' in html_text
        assert '<details class="advanced-telemetry-mapping secondary-disclosure"><summary>Advanced telemetry mapping</summary>' in html_text
        assert '<section class="identity-grid">' in html_text
        assert 'class="review-clean"' in html_text and "No issues found" in html_text
        assert "Stage evidence" not in html_text
        informational_only = json.loads(json.dumps(report))
        informational_only["review"]["information"] = [{"message": "Optional telemetry absent"}]
        assert 'class="review-clean"' in render_report_html(informational_only)
        for identity_class in ("identity-card-system", "identity-card-memory", "identity-card-devices"):
            assert identity_class in html_text
        identity_html = html_text[html_text.index("System identity"):html_text.index("Review summary")]
        assert "Module 1" in identity_html and "Module 2" in identity_html
        assert "Controller0-ChannelA-DIMM1" not in identity_html
        stage_overview = html_text[html_text.index("Stage overview"):html_text.index("Telemetry explorer")]
        assert "component-metric-row" in stage_overview and "Temp max" in stage_overview
        primary_stage_summary = stage_overview[:stage_overview.index("Show full min/avg/max metrics")]
        assert "GPU 1" in primary_stage_summary and "140 W" in primary_stage_summary
        assert "DIMM 1" in primary_stage_summary and "Storage 1" in primary_stage_summary
        assert "Mesa Intel Graphics" not in primary_stage_summary and "NVMe Test" not in primary_stage_summary
        assert "gpu_0_temp_hotspot_c" not in primary_stage_summary
        assert "cpu_temp_c" not in primary_stage_summary and "cpu_package_0_temp_c" not in primary_stage_summary
        assert "bmc_memory_power_w" not in primary_stage_summary
        assert 'stage-card status-pass' in stage_overview
        assert "Duration 1:40" in stage_overview
        titled_report = json.loads(json.dumps(report))
        titled_report["stages"][0]["display_label"] = "Power Auto CPU — measured probe or truthful architecture fallback"
        titled_html = render_report_html(titled_report)
        assert "<h3>Power Auto CPU</h3>" in titled_html
        assert '<p class="stage-description">measured probe or truthful architecture fallback</p>' in titled_html
        assert html_text.count('class="stage-detail-toggle"') == len(report["stages"])
        assert "<h2>Full stage metrics</h2>" not in html_text
        assert 'class="stage-metrics detail-disclosure"' not in stage_overview
        assert stage_overview.count('class="stage-detail-panel status-pass"') == len(report["stages"])
        assert stage_overview.count('class="stage-detail-panel status-pass"') == stage_overview.count(' hidden>')
        assert '<div class="stage-detail-region"' not in stage_overview
        assert "last.insertAdjacentElement('afterend',panel)" in html_text
        assert "item.offsetTop===top" in html_text and "window.addEventListener('resize'" in html_text
        assert "grid-column:1/-1" in html_text and "card.classList.add('active')" in html_text
        assert ".stage-detail-header{position:sticky;top:0;z-index:2" in html_text
        assert "closeAll()" in html_text and "panel.hidden=false" in html_text
        assert "repeat(3,minmax(76px,.52fr)) minmax(52px,.3fr)" in html_text
        assert "<span>Samples</span>" in stage_overview and "samples</small>" not in stage_overview
        assert "4.00 GHz" in html_text and "4,000 MHz" not in html_text
        assert "Stage 1 — CPU &lt;load&gt;</h3><p>Full min/avg/max metrics" in stage_overview
        assert stage_overview.count('class="full-metric-head"') == len(report["stages"])
        assert 'class="full-metric-group-label">CPU</div>' in stage_overview
        assert 'class="full-metric-group-label">GPU 1</div>' in stage_overview
        assert 'class="metric-subgroup nested-disclosure"><summary>Performance cores (2)</summary>' in stage_overview
        assert 'class="metric-subgroup nested-disclosure"><summary>Efficiency cores (1)</summary>' in stage_overview
        assert 'class="full-metric-group-label">BMC / IPMI</div>' in stage_overview
        first_detail = stage_overview[
            stage_overview.index('id="stage-detail-0"'):
            stage_overview.index('id="stage-detail-1"')
        ]
        assert first_detail.index('>CPU</div>') < first_detail.index('Performance cores (2)') < first_detail.index('Efficiency cores (1)') < first_detail.index('>GPU 1</div>')
        assert first_detail.index('>GPU 1</div>') < first_detail.index('>Memory</div>') < first_detail.index('>Storage</div>')
        assert first_detail.index('>Storage</div>') < first_detail.index('>BMC / IPMI</div>')
        assert "Performance cores (2)</summary><div class=\"full-metric-grid\"><div class=\"full-metric-head\"" not in stage_overview
        assert "P-Core 0" in stage_overview and "P-Core 2" in stage_overview and "E-Core 10" in stage_overview
        assert "CPU Core 10" not in stage_overview
        assert "<details open" not in stage_overview
        assert html_text.count("Hide full min/avg/max metrics") == 1
        assert _clock_range({"minimum": 550, "maximum": 550, "unit": "mhz", "field": "cpu_clock_mhz"}) == "550 MHz"
        assert _clock_range({"minimum": 0, "maximum": 1060, "unit": "mhz", "field": "cpu_clock_mhz"}) == "0–1.06 GHz"
        friendly_mapping = html_text[html_text.index('<dl class="component-key-list">'):html_text.index('<details class="advanced-telemetry-mapping')]
        assert "cpu:core:" not in friendly_mapping and "cpu_core_" not in friendly_mapping
        assert "GPU 1" in friendly_mapping and "Mesa Intel Graphics" in friendly_mapping
        assert "GPU 2" in friendly_mapping and "AMD Radeon Test" in friendly_mapping
        assert "<dt>Installed memory</dt>" in friendly_mapping and "<dt>Memory telemetry</dt>" in friendly_mapping
        assert "<strong>A2</strong>" in friendly_mapping and "<strong>B2</strong>" in friendly_mapping
        assert "Kingston KF560C32-48" in friendly_mapping
        assert friendly_mapping.count("Physical module association unavailable") == 1
        assert "Physical slot unresolved" not in friendly_mapping
        assert "Board sensor" not in friendly_mapping and "Wi-Fi sensor" not in friendly_mapping
        component_mapping = html_text[html_text.index("Component mapping"):html_text.index("Hardware references and advanced details")]
        assert "Advanced telemetry mapping" not in component_mapping
        hardware_advanced = html_text[html_text.index("Hardware references and advanced details"):html_text.index("<footer>")]
        assert "Advanced telemetry mapping" in hardware_advanced
        advanced_mapping = hardware_advanced[hardware_advanced.index("Advanced telemetry mapping"):]
        assert 'class="telemetry-group nested-disclosure"' in advanced_mapping
        assert "cpu_core_0_clock_mhz" in advanced_mapping
        assert "BMC / IPMI" in advanced_mapping
        assert 'class="telemetry-map-table"' in advanced_mapping
        assert "Friendly sensor" in advanced_mapping and "Raw field" in advanced_mapping and "Provider/source" in advanced_mapping
        assert 'class="telemetry-component nested-disclosure"' not in advanced_mapping
        assert "<details open" not in advanced_mapping
        assert "CPU Core 0</summary>" not in advanced_mapping and "Board sensor 1</summary>" not in advanced_mapping
        assert "Performance cores (2)" in advanced_mapping and "Efficiency cores (1)" in advanced_mapping
        assert "P-Core 0 clock" in advanced_mapping and "E-Core 10 clock" in advanced_mapping
        assert "cpu_package_0_temp_c" in advanced_mapping and "gpu_0_temp_hotspot_c" in advanced_mapping
        assert '<strong>CPU</strong>' in html_text and "CPU package 0" in html_text and "Temperature" in html_text
        assert "gpu_0_temp_hotspot_c" in html_text and "bmc_memory_power_w" in html_text
        for duplicated_label in ("GPU 1 GPU temperature", "GPU 2 GPU temperature", "DIMM 1 DIMM 1 temperature", "Storage 1 Storage 1 temperature"):
            assert duplicated_label not in html_text
        assert 'class="metric-subgroup nested-disclosure"><summary>Performance cores (2)</summary>' in stage_overview
        expected_fields = {field for component in report["components"] for field in component.get("telemetry_fields", [])}
        assert all(field in advanced_mapping for field in expected_fields)
        assert "&lt;/script&gt;&lt;img" in html_text and "<img src=x" not in html_text
        assert "&quot;" in render_report_html({
            **report,
            "run": {**report["run"], "profile_name": 'Quoted "profile"'},
        })
        topology_html = render_report_html({
            **report,
            "hardware": {
                **report["hardware"],
                "cpu": {
                    **report["hardware"]["cpu"],
                    "Topology": {"Aggregate": {"PhysicalCoreCount": 3, "PCoreCount": 2, "ECoreCount": 1, "UnknownCoreTypeCount": 0}},
                },
            },
        })
        assert "<dt>Cores</dt><dd>3 total · 2 performance · 1 efficiency</dd>" in topology_html
        assert "<dt>Cores</dt>" not in html_text
        assert html_text.lower().count("<script") == 3
        assert "http://" not in html_text and "https://" not in html_text
        assert '<canvas id="telemetry-canvas"' in html_text
        assert '<option value="" selected>Select a stage…</option>' not in html_text
        assert '<option value="cpu_stage" selected>Stage 1 — CPU workload</option>' in html_text
        assert "Loading telemetry graph…" in html_text
        assert "Select a stage above to view its telemetry graph." not in html_text
        assert '<button id="telemetry-view"' not in html_text and ">View<" not in html_text
        assert "stageSelect&&stageSelect.addEventListener('change',syncExplorerFromStageSelect)" in html_text
        assert "window.addEventListener('pageshow',syncExplorerFromStageSelect)" in html_text
        assert "syncExplorerFromStageSelect();" in html_text
        assert "function syncExplorerFromStageSelect()" in html_text
        assert "var resolved=stageById(stageSelect.value),chartable=chartableStages()" in html_text
        assert "if(resolved){stageSelect.value=resolved.stage_id;loadStage(resolved);return;}" in html_text
        assert "chart-frame" in html_text and "chart-empty-state" in html_text
        assert "Stage 1 — CPU &lt;load&gt;" in html_text
        assert "Stage 1 — CPU &lt;load&gt; —" not in html_text
        assert "function defaultSeries(items){selected.clear()" in html_text
        assert "if(choice)selected.add(choice.series_id);" in html_text
        assert "slice(0,3)" not in html_text
        assert "chart.js" not in html_text.lower()
        for behavior in (
            "chart-series-row", "Advanced series", "Performance cores (", "Efficiency cores (", "advanced_group==='cpu_cores'",
            "selected.add", "mouseenter", "deemphasized", "emphasized",
            "context.setLineDash([3,3])", "telemetry-tooltip", "Showing normalized analysis window",
            "Select one or more series to display.", "No chartable telemetry is available for this stage.",
            "ResizeObserver",
        ):
            assert behavior in html_text
        for behavior in (
            "function setCoreGroupSelection(cores,checked,coreList)",
            "coreAction('Select all',cores,true,coreList)",
            "coreAction('Clear',cores,false,coreList)",
            "event.preventDefault();event.stopPropagation()",
            "function tooltipColumnCount(count,width,height)",
            "function positionTooltip(width,height)",
            "entries.join('')", "max-height:calc(100% - 16px)",
            "grid-template-columns:repeat(var(--tooltip-columns,1),minmax(0,1fr))",
            "Math.max(8,Math.min(x,width-tooltipWidth-8))",
            ".chart-legend{display:flex;min-width:0;max-width:100%;flex-wrap:wrap",
        ):
            assert behavior in html_text
        assert "entries.slice" not in html_text and "items.slice" not in html_text
        assert "cores.forEach(function(item){if(checked)selected.add(item.series_id);else selected.delete(item.series_id);})" in html_text
        assert "coreDetails.addEventListener('toggle'" not in html_text
        for core_count, heterogeneous in ((24, True), (64, False), (128, True)):
            dense_html = render_report_html(report, _synthetic_dense_core_chart(core_count, heterogeneous=heterogeneous))
            dense_match = re.search(r'<script id="lvs-chart-data" type="application/json" data-encoding="base64">([^<]+)</script>', dense_html)
            assert dense_match
            dense_payload = json.loads(base64.b64decode(dense_match.group(1)))
            dense_series = dense_payload["stages"][0]["series"]
            assert len(dense_series) == core_count
            assert len({series["selector_label"] for series in dense_series}) == core_count
            assert all(not series["primary"] and series["advanced_group"] == "cpu_cores" for series in dense_series)
            assert "Select all" in dense_html and "Clear" in dense_html
            assert ".chart-series-list{display:flex;min-width:0;max-width:100%;flex-wrap:wrap" in dense_html
        homogeneous = _synthetic_dense_core_chart(64, heterogeneous=False)["stages"][0]["series"]
        assert all(series["core_class"] is None for series in homogeneous)
        heterogeneous = _synthetic_dense_core_chart(24, heterogeneous=True)["stages"][0]["series"]
        assert {series["core_class"] for series in heterogeneous} == {"performance", "efficiency"}
        assert "function niceStep(range,targetTicks)" in html_text
        assert "function axisScale(family,minimum,maximum)" in html_text
        assert "family==='Utilization'&&minimum>=0&&maximum<=100" in html_text
        assert "return {minimum:0,maximum:100,step:20}" in html_text
        assert "'Power','Memory / VRAM','Utilization','Fan speed','Fan duty','Percentage','Voltage','Current','Clock'" in html_text
        assert "nonnegative&&minimum>=0&&lower<0" in html_text
        assert "Temperature" not in html_text[html_text.index("nonnegative=["):html_text.index("].indexOf(family)>=")]
        assert "component+' VRAM'" in html_text and "component+' hotspot'" in html_text
        unavailable_html = render_report_html(report, {"available": False, "unavailable_reason": "raw_telemetry_absent", "stages": []})
        assert "No raw telemetry is available for this run." in unavailable_html
        assert '<option value="" selected>Select a stage…</option>' in unavailable_html
        assert "canvas.addEventListener('click'" not in html_text
        assert "fetch(" not in html_text and "XMLHttpRequest" not in html_text
        assert "<svg" not in html_text.lower() and "new chart" not in html_text.lower()
        topbar = html_text[html_text.index('<header class="topbar">'):html_text.index("</header>")]
        assert "badge" not in topbar
        result_markup = html_text[
            html_text.index('<div class="result-tile'):
            html_text.index('<section class="panel run-details"')
        ]
        assert '<div class="result-value">PASS</div>' in result_markup
        assert '<span class="badge' not in result_markup
        assert ".result-value{display:block;font-size:26px" in html_text
        assert "Run version: 0.2.0" in html_text
        assert "Report generated by Linux Validation Suite" in html_text
        assert ">LVS 0.2.0<" not in html_text
        assert "2026-01-02 00:00:00 +00:00" in html_text
        assert _timestamp("2026-08-14T16:07:32.472842-04:00") == "2026-08-14 16:07:32 -04:00"
        assert "overflow-wrap:anywhere" in html_text
        assert persisted["chart_catalog"]["samples_embedded"] is False
        serialized = json.dumps(persisted).lower()
        for forbidden in ("sku_id", "database_id", "reference_rule", "raw_telemetry_samples"):
            assert forbidden not in serialized
        for forbidden_html in ("Case SKU", "manual override", "action queue", "audit annotation"):
            assert forbidden_html not in html_text
        generate_report(root, generated_at="fixed")
        assert _hashes(root) == source_hashes
        assert {path.name for path in root.iterdir() if path.is_file()} == set(source_hashes) | {"lvs_report_data.json", "lvs_chart_data.json", "result_report.html"}

        telemetry_dimms = [
            {"component_id": "memory_module:0", "component_class": "memory_module", "label": "DIMM 0"},
            {"component_id": "memory_module:1", "component_class": "memory_module", "label": "DIMM 1"},
        ]
        identical = [
            {"Manufacturer": "Kingston", "PartNumber": "KF560C32-48", "Size": "48 GB", "OperatingSpeed": "4800 MT/s", "Position": "A2"},
            {"Manufacturer": "Kingston", "PartNumber": "KF560C32-48", "Size": "48 GB", "OperatingSpeed": "4800 MT/s", "Position": "B2"},
        ]
        inventory, telemetry = _memory_mapping(identical, telemetry_dimms)
        assert "<strong>A2</strong>" in inventory and "<strong>B2</strong>" in inventory
        assert inventory.count("Kingston KF560C32-48") == 2
        assert telemetry.count("Physical module association unavailable") == 2
        no_slot_modules = [{key: value for key, value in item.items() if key != "Position"} for item in identical]
        no_slots, no_slot_telemetry = _memory_mapping(no_slot_modules, telemetry_dimms)
        assert "Physical module 1" in no_slots and "Physical module 2" in no_slots
        assert no_slots.count("Physical slot not reported") == 2
        assert "A1" not in no_slots and "A2" not in no_slots and "B2" not in no_slots
        assert no_slot_telemetry.count("Physical module association unavailable") == 2
        single_inventory, single_telemetry = _memory_mapping([identical[0]], telemetry_dimms[:1])
        assert "<strong>A2</strong>" in single_inventory and "B2" not in single_inventory
        assert "DIMM 1" in single_telemetry and "DIMM 2" not in single_telemetry
        reversed_inventory, unresolved = _memory_mapping(list(reversed(identical)), telemetry_dimms)
        assert "B2" in reversed_inventory and unresolved.count("Physical module association unavailable") == 2
        proven_components = json.loads(json.dumps(telemetry_dimms))
        proven_components[0]["identity"] = {"slot_locator": "B2"}
        _inventory, proven = _memory_mapping(list(reversed(identical)), proven_components)
        assert "DIMM 1" in proven and "Temperature · B2" in proven
        assert "DIMM 2</strong><span>Temperature · Physical module association unavailable" in proven

        alias_metrics = [
            {"field": "cpu_temp_c", "component_id": "cpu:aggregate", "provider": "hwmon", "source_label": "Package id 0", "sample_count": 3, "minimum": 40, "average": 50, "maximum": 60},
            {"field": "cpu_package_0_temp_c", "component_id": "cpu:package:0", "provider": "hwmon", "source_label": "Package id 0", "sample_count": 3, "minimum": 40, "average": 50, "maximum": 60},
            {"field": "memory_used_gb", "component_id": "memory:system", "sample_count": 3, "minimum": 7, "average": 8, "maximum": 9},
            {"field": "memory_used_gib", "component_id": "memory:system", "sample_count": 3, "minimum": 7, "average": 8, "maximum": 9},
            {"field": "gpu_0_busy_percent", "component_id": "gpu:0", "metric_class": "percentage", "sample_count": 3, "minimum": 1, "average": 2, "maximum": 3},
            {"field": "gpu_0_memory_busy_percent", "component_id": "gpu:0", "metric_class": "percentage", "sample_count": 3, "minimum": 4, "average": 5, "maximum": 6},
        ]
        visible_fields = {metric["field"] for metric in _visible_metrics(alias_metrics)}
        assert "cpu_temp_c" not in visible_fields and "cpu_package_0_temp_c" in visible_fields
        assert "memory_used_gb" not in visible_fields and "memory_used_gib" in visible_fields
        semantic_html = _metric_table({"index": 0, "display_label": "GPU semantics", "native_outcome": "pass", "metrics": alias_metrics[-2:]}, {})
        assert "GPU 1" in semantic_html and "Utilization" in semantic_html and "Memory-busy utilization" in semantic_html
        assert "GPU 1 GPU" not in semantic_html and "GPU 1 utilization" not in semantic_html
        advanced_alias_html = _advanced_telemetry_mapping(
            [{"component_id": "memory:system", "component_class": "memory", "identity": {"kind": "procfs"}, "telemetry_fields": ["memory_used_gb", "memory_used_gib"]}],
            {"series": [{"field": "memory_used_gb", "component_id": "memory:system", "metric_class": "other_numeric"}, {"field": "memory_used_gib", "component_id": "memory:system", "metric_class": "memory_usage", "unit": "gib"}]},
            [{"metrics": alias_metrics[2:4]}],
        )
        assert "memory_used_gb" in advanced_alias_html and "memory_used_gib" in advanced_alias_html
        assert "Compatibility alias of memory_used_gib" in advanced_alias_html
        assert "Canonical field; compatibility alias: memory_used_gb" in advanced_alias_html
        assert "other numeric" not in advanced_alias_html.lower()

        memory_detail_html = _metric_table(
            {"index": 0, "display_label": "Memory semantics", "native_outcome": "pass", "metrics": alias_metrics[2:4]}, {}
        )
        assert "System memory" in memory_detail_html and "Used memory" in memory_detail_html
        assert "Memory System" not in memory_detail_html and "System memory used" not in memory_detail_html

        grouped_stage = {
            "index": 0, "display_label": "Semantic ordering", "native_outcome": "pass",
            "metrics": [
                {"field": "other_value", "component_id": "unclassified:0", "metric_class": "other_numeric", "sample_count": 1, "minimum": 1, "average": 1, "maximum": 1},
                {"field": "board_0_temp_c", "component_id": "device:board:0", "metric_class": "temperature", "sample_count": 1, "minimum": 30, "average": 30, "maximum": 30},
                {"field": "bmc_fan_0_rpm", "component_id": "bmc:fan:0", "metric_class": "fan_speed", "sample_count": 1, "minimum": 900, "average": 1000, "maximum": 1100},
                {"field": "storage_drive_0_temp_c", "component_id": "storage:0", "metric_class": "temperature", "sample_count": 1, "minimum": 30, "average": 31, "maximum": 32},
                {"field": "memory_used_gib", "component_id": "memory:system", "metric_class": "memory_usage", "sample_count": 1, "minimum": 7, "average": 8, "maximum": 9},
                {"field": "gpu_1_temp_c", "component_id": "gpu:1", "metric_class": "temperature", "sample_count": 1, "minimum": 40, "average": 41, "maximum": 42},
                {"field": "cpu_core_2_clock_mhz", "component_id": "cpu:core:2", "metric_class": "clock", "unit": "mhz", "sample_count": 1, "minimum": 1000, "average": 2000, "maximum": 3000},
                {"field": "cpu_power_w", "component_id": "cpu:aggregate", "metric_class": "power", "sample_count": 1, "minimum": 20, "average": 30, "maximum": 40},
                {"field": "gpu_0_temp_c", "component_id": "gpu:0", "metric_class": "temperature", "sample_count": 1, "minimum": 40, "average": 41, "maximum": 42},
            ],
        }
        grouped_html = _metric_table(grouped_stage, {})
        ordered_markers = [
            '>CPU</div>', 'CPU cores (1)', '>GPU 1</div>', '>GPU 2</div>', '>Memory</div>',
            '>Storage</div>', '>BMC / IPMI</div>', 'Platform sensors (1)', '>OTHER</div>',
        ]
        ordered_positions = [grouped_html.index(marker) for marker in ordered_markers]
        assert ordered_positions == sorted(ordered_positions)
        assert grouped_html.count("CPU cores (1)") == 1
        assert grouped_html.index("CPU cores (1)") < grouped_html.index(">Storage</div>")
        assert "bmc_fan_0_rpm" in grouped_html[grouped_html.index(">BMC / IPMI</div>"):grouped_html.index("Platform sensors (1)")]

        incomplete_html = _metric_table({
            "index": 0, "display_label": "Incomplete cores", "native_outcome": "pass",
            "metrics": [
                {"field": "cpu_core_0_clock_mhz", "component_id": "cpu:core:0", "metric_class": "clock", "unit": "mhz", "display_label": "P-Core 0", "core_class": "performance", "sample_count": 1, "minimum": 1, "average": 1, "maximum": 1},
                {"field": "cpu_core_1_clock_mhz", "component_id": "cpu:core:1", "metric_class": "clock", "unit": "mhz", "display_label": "Core 1", "sample_count": 1, "minimum": 1, "average": 1, "maximum": 1},
            ],
        }, {})
        assert "Performance cores (1)" in incomplete_html and "Unclassified cores (1)" in incomplete_html
        assert "P-Core 0" in incomplete_html and "Core 1" in incomplete_html

        generic_heterogeneous_html = _metric_table({
            "index": 0, "display_label": "Generic heterogeneous cores", "native_outcome": "pass",
            "metrics": [
                {"field": "cpu_core_0_clock_mhz", "component_id": "cpu:core:0", "metric_class": "clock", "unit": "mhz", "display_label": "Performance core 0", "core_class": "performance", "sample_count": 1, "minimum": 1, "average": 1, "maximum": 1},
                {"field": "cpu_core_1_clock_mhz", "component_id": "cpu:core:1", "metric_class": "clock", "unit": "mhz", "display_label": "Efficiency core 1", "core_class": "efficiency", "sample_count": 1, "minimum": 1, "average": 1, "maximum": 1},
            ],
        }, {})
        assert "Performance cores (1)" in generic_heterogeneous_html and "Efficiency cores (1)" in generic_heterogeneous_html
        assert "Performance core 0" in generic_heterogeneous_html and "Efficiency core 1" in generic_heterogeneous_html
        assert "P-Core 0" not in generic_heterogeneous_html and "E-Core 1" not in generic_heterogeneous_html

        advanced_components = [
            {"component_id": "unclassified:0", "component_class": "unknown", "telemetry_fields": ["other_value"]},
            {"component_id": "device:board:0", "component_class": "board", "telemetry_fields": ["board_0_temp_c"]},
            {"component_id": "bmc:fan:0", "component_class": "platform", "telemetry_fields": ["bmc_fan_0_rpm"]},
            {"component_id": "storage:0", "component_class": "storage", "telemetry_fields": ["storage_drive_0_temp_c"]},
            {"component_id": "memory:system", "component_class": "memory", "telemetry_fields": ["memory_used_gib"]},
            {"component_id": "gpu:1", "component_class": "gpu", "telemetry_fields": ["gpu_1_temp_c"]},
            {"component_id": "cpu:aggregate", "component_class": "cpu", "telemetry_fields": ["cpu_power_w"]},
            {"component_id": "gpu:0", "component_class": "gpu", "telemetry_fields": ["gpu_0_temp_c"]},
        ]
        advanced_series = {"series": [
            {"field": field, "component_id": component["component_id"], "metric_class": "other_numeric"}
            for component in advanced_components for field in component["telemetry_fields"]
        ]}
        ordered_advanced = _advanced_telemetry_mapping(advanced_components, advanced_series, [grouped_stage])
        advanced_markers = [
            ">CPU</summary>", ">GPU 1</summary>", ">GPU 2</summary>", ">Memory telemetry</summary>",
            ">Storage</summary>", ">BMC / IPMI</summary>", ">Platform sensors</summary>", ">Other telemetry</summary>",
        ]
        advanced_positions = [ordered_advanced.index(marker) for marker in advanced_markers]
        assert advanced_positions == sorted(advanced_positions)
        assert "bmc_fan_0_rpm" in ordered_advanced[
            ordered_advanced.index(">BMC / IPMI</summary>"):ordered_advanced.index(">Platform sensors</summary>")
        ]
        assert "<details open" not in ordered_advanced

        storage_metric = {
            "field": "storage_drive_0_temp_c", "component_id": "storage:0", "metric_class": "temperature",
            "source_label": "NVMe composite", "unit": "c", "sample_count": 3,
            "minimum": 30, "average": 35, "maximum": 40,
        }
        storage_sensor = {**storage_metric, "field": "storage_drive_0_sensor_2_temp_c", "source_label": "NVMe Sensor 2"}
        storage_html = _metric_table({"index": 0, "display_label": "Storage", "native_outcome": "pass", "metrics": [storage_metric, storage_sensor]}, {})
        assert "Composite temperature" in storage_html and "Sensor 2 temperature" in storage_html
        assert "Controller temperature" not in storage_html and "NAND temperature" not in storage_html
        assert "Storage 1 Storage" not in storage_html
        explicit_controller = {
            **storage_sensor,
            "field": "storage_drive_0_sensor_3_temp_c",
            "source_label": "NVMe Controller",
        }
        explicit_nand = {
            **storage_sensor,
            "field": "storage_drive_0_sensor_4_temp_c",
            "source_label": "NVMe NAND temperature",
        }
        explicit_storage_html = _metric_table({
            "index": 0, "display_label": "Storage", "native_outcome": "pass",
            "metrics": [storage_metric, explicit_controller, explicit_nand],
        }, {})
        assert "Composite temperature" in explicit_storage_html
        assert "Controller temperature" in explicit_storage_html and "NAND temperature" in explicit_storage_html
        mapping_html = _advanced_telemetry_mapping(
            [{
                "component_id": "storage:0", "component_class": "storage", "label": "NVMe Test",
                "telemetry_fields": [metric["field"] for metric in (storage_metric, storage_sensor, explicit_controller, explicit_nand)],
            }],
            {"series": [storage_metric, storage_sensor, explicit_controller, explicit_nand]},
            [{"metrics": [storage_metric, storage_sensor, explicit_controller, explicit_nand]}],
        )
        assert "NVMe Test composite temperature" in mapping_html
        assert "NVMe Test sensor 2 temperature" in mapping_html
        assert "NVMe Test controller temperature" in mapping_html
        assert "NVMe Test NAND temperature" in mapping_html

        duplicate_description = json.loads(json.dumps(report))
        duplicate_description["run"]["description"] = "  " + duplicate_description["run"]["profile_name"].upper() + "!  "
        duplicate_topbar = render_report_html(duplicate_description).split("</header>", 1)[0]
        assert '<p class="description">' not in duplicate_topbar
        meaningful_description = json.loads(json.dumps(report))
        meaningful_description["run"]["description"] = "Distinct technician guidance"
        assert '<p class="description">Distinct technician guidance</p>' in render_report_html(meaningful_description)

        memory_semantics = json.loads(json.dumps(report))
        memory_semantics["hardware"]["memory"] = {"TotalPhysicalMemoryGB": 93, "Modules": []}
        memory_html = render_report_html(memory_semantics)
        identity_section = memory_html[memory_html.index("System identity"):memory_html.index("Review summary")]
        assert "OS-reported memory</dt><dd>93 GB" in identity_section

        core_stage = {
            "index": 0, "display_label": "Core ordering", "native_outcome": "pass",
            "metrics": [
                {"field": "cpu_core_10_clock_mhz", "component_id": "cpu:core:10", "metric_class": "clock", "unit": "mhz", "minimum": 1000, "average": 2000, "maximum": 3000, "sample_count": 2},
                {"field": "cpu_core_2_clock_mhz", "component_id": "cpu:core:2", "metric_class": "clock", "unit": "mhz", "minimum": 1000, "average": 2000, "maximum": 3000, "sample_count": 2},
            ],
        }
        core_html = _metric_table(core_stage, {})
        assert core_html.index("CPU Core 2") < core_html.index("CPU Core 10")
        assert core_html.count("CPU cores (2)") == 1
        assert "CPU Core 2</summary>" not in core_html and "CPU Core 10</summary>" not in core_html
        assert core_html.count('class="metric-subgroup nested-disclosure"') == 1

        empty_references = json.loads(json.dumps(report))
        empty_references["hardware_references"] = {"temperature_limits": [], "clock_capabilities": []}
        empty_html = render_report_html(empty_references)
        empty_section = empty_html[empty_html.index("Hardware references and advanced details"):empty_html.index("<footer>")]
        assert "No attributable temperature limits were recorded." in empty_section
        assert "No provider-backed clock capability data was recorded." in empty_section
        assert "<th>Warning</th>" not in empty_section and "<th>Semantics</th>" not in empty_section


if __name__ == "__main__":
    run_standalone_report_checks()
    print("standalone report checks passed")
