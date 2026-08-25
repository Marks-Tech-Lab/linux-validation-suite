#!/usr/bin/env python3
"""Focused direct-hwmon platform and JC42 telemetry regressions."""

from __future__ import annotations

import csv
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Modules.lvs_hardware_evidence import HardwareEvidenceCollector
from Modules.lvs_platform_hwmon import (
    normalize_platform_temperature_c,
    platform_hwmon_classification,
    valid_platform_temperature,
)
from Modules.lvs_telemetry_device import (
    discover_board_temp_sources,
    discover_device_temp_sources,
    discover_platform_temp_sources,
    read_device_temps,
)
from Modules.lvs_telemetry_memory import (
    direct_memory_temp_sources,
    discover_memory_temp_sources,
    spd5118_memory_temp_sources,
)
from Modules.lvs_telemetry_samples import Sample, telemetry_csv_fieldnames, write_telemetry_csv
from Modules.lvs_telemetry_sources import build_telemetry_source_map


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(value), encoding="utf-8")


def _sensor(root: Path, name: str, provider: str, label: str, value: object) -> Path:
    hwmon = root / name
    _write(hwmon / "name", provider)
    _write(hwmon / "temp1_label", label)
    _write(hwmon / "temp1_input", value)
    return hwmon


def run_platform_sensor_telemetry_checks() -> None:
    expected = {
        "Motherboard": "motherboard",
        "Motherboard Temp": "motherboard",
        "System": "system",
        "System 1": "system",
        "System Temp": "system",
        "PCH": "pch",
        "PCH Temp": "pch",
        "Chipset": "pch",
        "Chipset Temperature": "pch",
        "VRM": "vrm",
        "VRM MOS": "vrm_mos",
        "VRM MOS Temperature": "vrm_mos",
        "PSU": "psu",
        "PSU Temperature": "psu",
        "Power Supply": "psu",
    }
    for label, classification in expected.items():
        result = platform_hwmon_classification("nct-test", label)
        assert result["classification"] == classification
        assert result["confidence"] == "high"
        assert result["owner"] == "platform"
    for label in ("", "MOS", "Temp 1", "Sensor 2", "T_Sensor", "CPU", "GPU", "Memory", "NVMe", "Power"):
        assert platform_hwmon_classification("nct-test", label)["classification"] == "generic_channel"
    assert platform_hwmon_classification("r8169_0_8200:00", "")["classification"] == "nic"

    assert normalize_platform_temperature_c("-274000") is None
    assert normalize_platform_temperature_c("-273150") is None
    assert normalize_platform_temperature_c("251000") is None
    assert valid_platform_temperature("nct-test", "System", -5.0)
    assert not valid_platform_temperature("nct-test", "System", 0.0)
    assert not valid_platform_temperature("asus_wmi_sensors", "T_Sensor", -63.0)

    with TemporaryDirectory(dir="/tmp") as temporary:
        root = Path(temporary)
        hwmon_root = root / "hwmon"
        labels = [
            ("hwmon1", "nct6687", "Motherboard", "35000", "motherboard_0_temp_c"),
            ("hwmon2", "it87", "System", "36000", "system_0_temp_c"),
            ("hwmon3", "it87", "PCH", "42000", "pch_0_temp_c"),
            ("hwmon4", "nct6687", "VRM", "44000", "vrm_0_temp_c"),
            ("hwmon5", "nct6687", "VRM MOS", "46000", "vrm_mos_0_temp_c"),
            ("hwmon6", "corsairpsu", "PSU Temperature", "39000", "psu_0_temp_c"),
        ]
        for name, provider, label, value, _key in labels:
            _sensor(hwmon_root, name, provider, label, value)
        _sensor(hwmon_root, "hwmon7", "nct6687", "", "99000")
        _sensor(hwmon_root, "hwmon8", "nct6687", "MOS", "98000")
        _sensor(hwmon_root, "hwmon9", "nct6687", "System", "0")
        _sensor(hwmon_root, "hwmon10", "nct6687", "System", "-274000")
        _sensor(hwmon_root, "hwmon11", "asus_wmi_sensors", "T_Sensor", "-63000")

        for offset, provider in enumerate(
            ("coretemp", "k10temp", "zenpower", "amdgpu", "i915", "xe", "nouveau", "spd5118", "jc42", "nvme", "drivetemp"),
            start=20,
        ):
            _sensor(hwmon_root, f"hwmon{offset}", provider, "VRM", "50000")

        gigabyte = _sensor(hwmon_root, "hwmon40", "gigabyte_wmi", "", "27000")
        _write(gigabyte / "temp2_input", "41000")
        nic = _sensor(hwmon_root, "hwmon41", "r8169_0_8200:00", "", "51000")
        wifi = _sensor(hwmon_root, "hwmon42", "iwlwifi_1", "", "41000")

        platform = discover_platform_temp_sources(hwmon_root)
        assert {source["key"] for source in platform} == {item[4] for item in labels}
        assert all(source["confidence"] == "high" for source in platform)
        assert not any(source["path"].startswith(str(gigabyte)) for source in platform)
        assert not any(source["path"].startswith(str(nic)) for source in platform)
        assert not any(source["path"].startswith(str(wifi)) for source in platform)

        all_devices = discover_device_temp_sources(hwmon_root)
        assert [source["key"] for source in all_devices if source["kind"] == "board_temp"] == [
            "board_0_temp_c", "board_1_temp_c",
        ]
        assert sum(source["kind"] == "platform_temp" for source in all_devices) == 6
        assert sum(source["kind"] == "nic_temp" for source in all_devices) == 1
        assert sum(source["kind"] == "wifi_temp" for source in all_devices) == 1

        vrm_source = next(source for source in platform if source["key"] == "vrm_0_temp_c")
        assert read_device_temps([vrm_source]) == {"vrm_0_temp_c": 44.0}
        Path(vrm_source["path"]).write_text("", encoding="utf-8")
        assert read_device_temps([vrm_source]) == {}
        Path(vrm_source["path"]).write_text("0", encoding="utf-8")
        assert read_device_temps([vrm_source]) == {}
        Path(vrm_source["path"]).unlink()
        assert read_device_temps([vrm_source]) == {}

        evidence = HardwareEvidenceCollector(
            hwmon_root=hwmon_root,
            cpu_root=root / "cpu",
            thermal_root=root / "thermal",
            drm_root=root / "drm",
            devfreq_root=root / "devfreq",
        )._platform_sensors()
        nic_evidence = next(item for item in evidence["other_component_sensors"] if item["provider"].startswith("r8169"))
        assert nic_evidence["classification"] == "nic"
        assert nic_evidence["confidence"] == "high"

        source_map = build_telemetry_source_map(
            cpu_temp_source=None,
            cpu_package_temp_sources=[],
            cpu_power_source=None,
            cpu_clock_source=None,
            cpu_core_clock_sources=[],
            memory_temp_sources=[],
            storage_temp_sources=[],
            gpu_sources=[],
            gpu_cards=[],
            device_temp_sources=platform,
        )
        pch_record = source_map["fields"]["pch_0_temp_c"]
        assert pch_record["kind"] == "platform_temp"
        assert pch_record["component_classification"] == "pch"
        assert pch_record["provider"] == "it87"
        assert pch_record["raw_label"] == "PCH"
        assert pch_record["normalized_label"] == "pch"
        assert pch_record["kernel_channel"] == "temp1"
        assert pch_record["confidence"] == "high"
        assert pch_record["canonical_identity"].endswith("temp1_input")
        assert pch_record["path"].endswith("temp1_input")
        assert "pch_0_temp_c" in telemetry_csv_fieldnames([Sample(1.0, {"pch_0_temp_c": 42.0})])
        vrm_mos_record = source_map["fields"]["vrm_mos_0_temp_c"]
        assert vrm_mos_record["category"] == "device"
        assert vrm_mos_record["metric"] == "temperature_c"
        assert vrm_mos_record["available"] is True
        assert vrm_mos_record["kind"] == "platform_temp"
        assert vrm_mos_record["component_classification"] == "vrm_mos"

        dimm_root = root / "dimm_hwmon"
        spd = _sensor(dimm_root, "hwmon1", "spd5118", "", "41000")
        _write(spd / "temp1_max", "55000")
        _write(spd / "temp1_crit", "85000")
        jc = _sensor(dimm_root, "hwmon2", "jc42", "", "39000")
        _write(jc / "temp1_max", "0")
        _write(jc / "temp1_crit", "0")
        _write(jc / "temp1_crit_alarm", "1")
        _sensor(dimm_root, "hwmon3", "jc42", "", "0")
        _sensor(dimm_root, "hwmon4", "jc42", "", "-273150")
        (dimm_root / "hwmon5").symlink_to(jc, target_is_directory=True)
        memory_zone = root / "thermal_memory" / "thermal_zone0"
        _write(memory_zone / "type", "mem-thermal")
        _write(memory_zone / "temp", "43000")
        direct_memory = discover_memory_temp_sources(
            hwmon_root=dimm_root,
            thermal_root=root / "thermal_memory",
        )
        assert [(item["provider"], item["key"]) for item in direct_memory] == [
            ("spd5118", "memory_module_0_temp_c"),
            ("jc42", "memory_module_1_temp_c"),
        ]
        assert all(item["kind"] == "memory_temp" for item in direct_memory)
        assert not any("threshold" in key or "alarm" in key for item in direct_memory for key in item)

        assert [item["key"] for item in spd5118_memory_temp_sources(dimm_root)] == [
            "memory_module_0_temp_c",
        ]
        assert [item["key"] for item in direct_memory_temp_sources(dimm_root, providers=("jc42",))] == [
            "memory_module_0_temp_c",
        ]

        broken_jc_root = root / "broken_jc_hwmon"
        _sensor(broken_jc_root, "hwmon1", "spd5118", "", "40250")
        _sensor(broken_jc_root, "hwmon2", "jc42", "", "0")
        broken_jc_direct = discover_memory_temp_sources(
            hwmon_root=broken_jc_root,
            thermal_root=root / "thermal_memory",
        )
        assert [(item["provider"], item["key"]) for item in broken_jc_direct] == [
            ("spd5118", "memory_module_0_temp_c"),
        ]

        # Direct DIMM keys use physical device identity, not changing hwmonN aliases.
        dimm_devices = root / "stable_dimms"
        dimm_spd = _sensor(dimm_devices / "spd" / "hwmon", "hwmon31", "spd5118", "", "40500")
        dimm_jc = _sensor(dimm_devices / "jc42" / "hwmon", "hwmon32", "jc42", "", "39500")
        dimm_view_one = root / "dimm_view_one"
        dimm_view_two = root / "dimm_view_two"
        dimm_view_one.mkdir()
        dimm_view_two.mkdir()
        (dimm_view_one / "hwmon2").symlink_to(dimm_jc, target_is_directory=True)
        (dimm_view_one / "hwmon8").symlink_to(dimm_spd, target_is_directory=True)
        (dimm_view_one / "hwmon9").symlink_to(dimm_spd, target_is_directory=True)
        (dimm_view_two / "hwmon1").symlink_to(dimm_spd, target_is_directory=True)
        (dimm_view_two / "hwmon7").symlink_to(dimm_jc, target_is_directory=True)
        dimm_first = direct_memory_temp_sources(dimm_view_one)
        dimm_second = direct_memory_temp_sources(dimm_view_two)
        assert [(item["provider"], item["key"]) for item in dimm_first] == [
            ("spd5118", "memory_module_0_temp_c"),
            ("jc42", "memory_module_1_temp_c"),
        ]
        assert [item["canonical_identity"] for item in dimm_first] == [
            item["canonical_identity"] for item in dimm_second
        ]
        assert [item["key"] for item in dimm_first] == [item["key"] for item in dimm_second]

        # The same physical sources retain ordering and keys when hwmonN aliases change.
        devices = root / "stable_devices"
        device_a = _sensor(devices / "a" / "hwmon", "hwmon31", "nct6687", "VRM", "45000")
        device_b = _sensor(devices / "b" / "hwmon", "hwmon32", "nct6687", "VRM", "47000")
        view_one = root / "view_one"
        view_two = root / "view_two"
        view_one.mkdir()
        view_two.mkdir()
        (view_one / "hwmon9").symlink_to(device_b, target_is_directory=True)
        (view_one / "hwmon2").symlink_to(device_a, target_is_directory=True)
        (view_one / "hwmon77").symlink_to(device_a, target_is_directory=True)
        # device_a moves hwmon2 -> hwmon8 while enumeration order swaps with device_b.
        (view_two / "hwmon1").symlink_to(device_b, target_is_directory=True)
        (view_two / "hwmon8").symlink_to(device_a, target_is_directory=True)
        first = discover_platform_temp_sources(view_one)
        second = discover_platform_temp_sources(view_two)
        assert [item["key"] for item in first] == ["vrm_0_temp_c", "vrm_1_temp_c"]
        assert [item["canonical_identity"] for item in first] == [item["canonical_identity"] for item in second]
        assert [item["key"] for item in first] == [item["key"] for item in second]
        first_values = read_device_temps(first)
        assert set(first_values) == {"vrm_0_temp_c", "vrm_1_temp_c"}
        Path(first[0]["path"]).write_text("", encoding="utf-8")
        second_values = read_device_temps(first)
        assert second_values == {"vrm_1_temp_c": 47.0}
        csv_path = root / "disappearing_source.csv"
        write_telemetry_csv(
            [Sample(1.0, first_values), Sample(2.0, second_values)],
            csv_path,
        )
        with csv_path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        assert rows[0]["vrm_0_temp_c"] == "45.0"
        assert rows[1]["vrm_0_temp_c"] == ""
        assert rows[1]["vrm_1_temp_c"] == "47.0"
        assert "vrm_0_temp_c" in source_map["fields"]

        # Existing Gigabyte compatibility discovery remains byte-for-byte key compatible.
        assert [source["key"] for source in discover_board_temp_sources(hwmon_root)] == [
            "board_0_temp_c", "board_1_temp_c",
        ]


if __name__ == "__main__":
    run_platform_sensor_telemetry_checks()
    print("platform sensor telemetry checks passed")
