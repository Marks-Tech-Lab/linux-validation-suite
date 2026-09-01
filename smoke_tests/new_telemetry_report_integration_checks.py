#!/usr/bin/env python3
"""Synthetic report integration checks for direct cooling and voltage telemetry."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Modules.lvs_report import generate_report


def _write_json(root: Path, name: str, payload: dict) -> None:
    (root / name).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _direct(field: str, label: str, semantic: str, *, provider: str = "nct6687") -> dict:
    unit = "rpm" if field.endswith("_rpm") else "volts"
    return {
        "category": "platform", "metric": "fan_rpm" if unit == "rpm" else "voltage_v",
        "provider": provider, "kind": "direct_hwmon", "label": label, "raw_label": label,
        "normalized_label": label.lower(), "normalized_units": unit,
        "semantic_classification": semantic, "component_classification": semantic,
        "source_scope": "direct_platform_hwmon", "measurement_semantics": "measured_or_provider_reported",
        "stable_device_locator": f"pci:0000:00:{len(field):02x}.0", "channel": 1,
        "path": f"/sys/devices/test/{field}",
    }


def _fixture(root: Path) -> None:
    fields = {
        "cpu_fan_0_rpm": _direct("cpu_fan_0_rpm", "CPU Fan", "cpu_fan"),
        "cpu_fan_1_rpm": _direct("cpu_fan_1_rpm", "CPU Fan 2", "cpu_fan"),
        "pump_0_rpm": _direct("pump_0_rpm", "Pump Fan", "pump"),
        "pump_1_rpm": _direct("pump_1_rpm", "Pump Fan 2", "pump"),
        "cpu_vcore_0_v": _direct("cpu_vcore_0_v", "CPU Vcore", "cpu_vcore"),
        "cpu_soc_0_v": _direct("cpu_soc_0_v", "CPU Soc", "cpu_soc"),
        "cpu_vddp_0_v": _direct("cpu_vddp_0_v", "CPU VDDP", "cpu_vddp"),
        "dram_0_v": _direct("dram_0_v", "DRAM", "dram"),
        "motherboard_12v_0_v": _direct("motherboard_12v_0_v", "+12V", "motherboard_12v"),
        "motherboard_5v_0_v": _direct("motherboard_5v_0_v", "+5V", "motherboard_5v"),
        "motherboard_3v3_0_v": _direct("motherboard_3v3_0_v", "+3.3V", "motherboard_3v3"),
        "other_voltage_rail_0_v": _direct("other_voltage_rail_0_v", "CPU 1P8", "other_voltage_rail"),
    }
    for index in range(6):
        field = f"system_fan_{index}_rpm"
        fields[field] = _direct(field, f"System Fan #{index + 1}", "system_fan")
    for gpu_index in range(2):
        fields[f"gpu_{gpu_index}_fan_0_rpm"] = {
            **_direct(f"gpu_{gpu_index}_fan_0_rpm", f"GPU {gpu_index + 1} Fan", "gpu_fan", provider="amdgpu"),
            "category": "gpu", "gpu_index": gpu_index, "source_scope": "direct_gpu_hwmon",
        }
        fields[f"gpu_{gpu_index}_vddgfx_v"] = {
            "category": "gpu", "gpu_index": gpu_index, "metric": "vddgfx_v", "provider": "amdgpu",
            "label": "VDDGFX", "normalized_units": "v",
        }
        fields[f"gpu_{gpu_index}_vddnb_v"] = {
            "category": "gpu", "gpu_index": gpu_index, "metric": "vddnb_v", "provider": "amdgpu",
            "label": "VDDNB", "normalized_units": "v",
        }
    fields["gpu_0_fan_percent"] = {
        "category": "gpu", "gpu_index": 0, "metric": "fan_percent", "provider": "nvidia_smi",
        "label": "GPU fan duty", "normalized_units": "percent", "query_field": "fan.speed",
    }
    fields["bmc_cpu_vcore_v"] = {
        "category": "bmc", "metric": "voltage_v", "provider": "ipmitool", "raw_label": "VCORE_CPU1",
        "normalized_units": "v", "component_classification": "cpu_rail", "component_locator": "cpu1_vcore",
        "semantic_classification": "cpu_vcore", "source_scope": "bmc_ipmi",
        "measurement_semantics": "measured_or_provider_reported",
    }
    source_map = {
        "contract_id": "linux_validation_suite.telemetry_source_map", "contract_version": 1,
        "kind": "telemetry_source_map", "fields": fields,
        "gpu_index_map": [
            {"gpu_index": 0, "card": "card0", "device_name": "GPU One"},
            {"gpu_index": 1, "card": "card1", "device_name": "GPU Two"},
        ],
        "direct_hwmon_sensor_candidates": [{
            "family": "fan", "raw_label": "", "accepted": False, "rejection_reason": "unlabeled",
            "input_source": "fan9_input",
        }],
    }
    _write_json(root, "telemetry_source_map.json", source_map)
    _write_json(root, "run_manifest.json", {
        "contract_id": "linux_validation_suite.run_manifest", "contract_version": 1,
        "kind": "run_manifest", "profile_name": "Direct telemetry fixture", "verdict": "pass",
        "started": "2026-09-01T00:00:00Z", "ended": "2026-09-01T00:00:10Z", "elapsed_seconds": 10,
        "stage_windows": [{
            "stage_id": "stage", "stage_type": "CPU", "display_name": "Cooling and rail fixture",
            "started_monotonic": 0, "ended_monotonic": 10, "duration_seconds": 10,
            "trim_start_seconds": 0, "trim_end_seconds": 0, "verdict": "pass",
        }],
    })
    _write_json(root, "profile_used.json", {"profile_name": "Direct telemetry fixture"})
    _write_json(root, "parsed_results_extended.json", {"compatibility_export": {"Result": "PASS", "Segments": []}})
    _write_json(root, "system_info.json", {"Hardware": {"Cpu": {"Name": "Synthetic CPU"}, "Gpu": []}})
    ordered = list(fields)
    with (root / "raw_telemetry.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["timestamp", *ordered])
        writer.writeheader()
        for timestamp, offset in ((0, 0), (5, 1), (10, 2)):
            row = {"timestamp": timestamp}
            for index, field in enumerate(ordered):
                if field.endswith("_rpm"):
                    row[field] = 1000 + index * 10 + offset
                elif field.endswith("fan_percent"):
                    row[field] = 40 + offset
                else:
                    row[field] = 1.0 + index / 100 + offset / 1000
            writer.writerow(row)


def run_new_telemetry_report_integration_checks() -> None:
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        _fixture(root)
        data_path, chart_path, html_path = generate_report(root, generated_at="2026-09-01T00:00:00Z")
        report = json.loads(data_path.read_text(encoding="utf-8"))
        chart = json.loads(chart_path.read_text(encoding="utf-8"))
        html = html_path.read_text(encoding="utf-8")

        catalog = {item["field"]: item for item in report["chart_catalog"]["series"]}
        assert catalog["cpu_fan_0_rpm"]["semantic_subtype"] == "cpu_fan"
        assert catalog["cpu_vcore_0_v"]["measurement_semantics"] == "measured_or_provider_reported"
        assert catalog["cpu_vcore_0_v"]["stable_device_locator"]
        assert "fan9_input" not in catalog
        report_metrics = {item["field"]: item for item in report["stages"][0]["metrics"]}
        assert report_metrics["cpu_fan_0_rpm"]["metric_class"] == "fan_speed"
        assert report_metrics["cpu_vcore_0_v"]["semantic_subtype"] == "cpu_vcore"

        stage = chart["stages"][0]
        by_field = {item["field"]: item for item in stage["series"]}
        fan_speed = [item for item in stage["series"] if item["metric_family"] == "Fan speed"]
        fan_duty = [item for item in stage["series"] if item["metric_family"] == "Fan duty"]
        voltage = [item for item in stage["series"] if item["metric_family"] == "Voltage"]
        for family in stage["families"]:
            labels = [item["selector_label"] for item in stage["series"] if item["metric_family"] == family]
            assert len(labels) == len(set(labels)), family
        assert len(fan_speed) == 12 and all(item["display_unit"] == "RPM" for item in fan_speed)
        assert len(fan_duty) == 1 and fan_duty[0]["display_unit"] == "%"
        assert all(item["primary"] for item in fan_speed)
        assert {item["selector_label"] for item in fan_speed} == {
            "CPU fan", "CPU fan 2", "Pump", "Pump 2",
            *(f"System fan {index}" for index in range(1, 7)),
            "GPU 1 fan 1", "GPU 2 fan 1",
        }
        assert by_field["cpu_vcore_0_v"]["primary"]
        assert by_field["gpu_0_vddgfx_v"]["primary"] and by_field["gpu_1_vddgfx_v"]["primary"]
        for field in (
            "cpu_soc_0_v", "cpu_vddp_0_v", "dram_0_v", "motherboard_12v_0_v",
            "motherboard_5v_0_v", "motherboard_3v3_0_v", "other_voltage_rail_0_v",
            "gpu_0_vddnb_v", "gpu_1_vddnb_v", "bmc_cpu_vcore_v",
        ):
            assert not by_field[field]["primary"], field
        assert by_field["gpu_0_vddgfx_v"]["selector_label"] == "GPU 1 VDDGFX"
        assert by_field["gpu_0_vddnb_v"]["selector_label"] == "GPU 1 VDDNB"
        assert by_field["cpu_soc_0_v"]["selector_label"] == "CPU SoC"
        assert by_field["other_voltage_rail_0_v"]["selector_label"] == "CPU 1P8"
        assert by_field["cpu_vcore_0_v"]["selector_label"].startswith("CPU Vcore · nct6687")
        assert by_field["bmc_cpu_vcore_v"]["selector_label"].startswith("CPU Vcore · ipmitool")
        assert by_field["cpu_vcore_0_v"]["provider"] != by_field["bmc_cpu_vcore_v"]["provider"]
        assert len({item["selector_label"] for item in voltage}) == len(voltage)
        for item in stage["series"]:
            assert item.get("semantic_subtype", "") == catalog[item["field"]].get("semantic_subtype", "")
        assert "if(item.selector_label)return item.selector_label" in html
        for label in ("CPU fan", "CPU fan 2", "System fan 6", "Pump", "Pump 2", "GPU 2 fan 1", "CPU Vcore", "CPU SoC", "CPU VDDP", "DRAM", "+12V", "+5V", "+3.3V", "VDDGFX", "VDDNB"):
            assert label in html, label
        advanced_mapping = html[html.index("Advanced telemetry mapping"):]
        for field in ("cpu_fan_0_rpm", "pump_1_rpm", "cpu_vcore_0_v", "cpu_soc_0_v", "bmc_cpu_vcore_v"):
            assert field in advanced_mapping, field
        assert "fan9_input" not in html


if __name__ == "__main__":
    run_new_telemetry_report_integration_checks()
    print("PASS new telemetry report integration checks")
