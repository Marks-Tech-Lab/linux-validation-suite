#!/usr/bin/env python3
"""Focused direct-hwmon fan, pump, voltage, and evidence regressions."""

from __future__ import annotations

import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Modules.lvs_telemetry_gpu import gpu_hwmon_fan_sources, read_gpu_values
from Modules.lvs_telemetry_hwmon import discover_direct_hwmon_sources, read_direct_hwmon_values
from Modules.lvs_telemetry_sources import build_telemetry_source_map


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(value), encoding="utf-8")


def _read(path: Path):
    try:
        return path.read_text(encoding="utf-8").strip()
    except Exception:
        return None


def _hwmon(root: Path, ordinal: int, device: str, provider: str) -> Path:
    target = root / "devices" / device / "hwmon" / f"hwmon{ordinal}"
    _write(target / "name", provider)
    link = root / "class" / "hwmon" / f"hwmon{ordinal}"
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(target, target_is_directory=True)
    return target


def _field(hwmon: Path, prefix: str, index: int, value: object, label: str = "") -> None:
    _write(hwmon / f"{prefix}{index}_input", value)
    if label:
        _write(hwmon / f"{prefix}{index}_label", label)


def _empty_source_map_kwargs():
    return {
        "cpu_temp_source": None,
        "cpu_package_temp_sources": [],
        "cpu_power_source": None,
        "cpu_clock_source": None,
        "cpu_core_clock_sources": [],
        "memory_temp_sources": [],
        "storage_temp_sources": [],
        "gpu_sources": [],
        "gpu_cards": [],
    }


def run_direct_hwmon_telemetry_checks() -> None:
    with TemporaryDirectory(dir="/tmp") as temporary:
        root = Path(temporary)
        board = _hwmon(root, 7, "platform/nct6687.2592", "nct6687")
        for index, (label, value) in enumerate((
            ("CPU Fan", 0),
            ("Pump Fan", 2777),
            ("System Fan #1", 900),
            ("System Fan #2", 880),
            ("System Fan #1", 910),
            ("Pump Fan", 2810),
        ), start=1):
            _field(board, "fan", index, value, label)
        _field(board, "fan", 9, 1200)
        for index, (label, value) in enumerate((
            ("+12V", 12264),
            ("+5V", 4930),
            ("+3.3V", 3340),
            ("CPU Soc", 1194),
            ("CPU Vcore", 1198),
            ("CPU VDDP", 1000),
            ("DRAM", 1350),
            ("CPU 1P8", 1800),
            ("CPU VID", 1100),
            ("VIN0", 900),
        ), start=1):
            _field(board, "in", index, value, label)
        _field(board, "in", 12, 700)
        _field(board, "curr", 1, 1250, "CPU Current")
        _field(board, "power", 1, 65000000, "Board Power")
        _write(board / "pwm1", 128)

        second = _hwmon(root, 2, "platform/other-board", "asus-nb-wmi")
        _field(second, "fan", 1, 1000, "CPU_FAN")
        _field(second, "fan", 2, 0, "GPU_FAN")
        _field(second, "fan", 3, 2800, "AIO_PUMP")

        sources, evidence = discover_direct_hwmon_sources(
            read_text=_read, hwmon_root=root / "class" / "hwmon"
        )
        keys = {source["key"] for source in sources}
        assert {"cpu_fan_0_rpm", "cpu_fan_1_rpm", "pump_0_rpm", "pump_1_rpm", "pump_2_rpm"} <= keys
        assert {"system_fan_0_rpm", "system_fan_1_rpm", "system_fan_2_rpm", "gpu_fan_0_rpm"} <= keys
        assert {
            "cpu_vcore_0_v", "cpu_soc_0_v", "cpu_vddp_0_v", "dram_0_v",
            "motherboard_12v_0_v", "motherboard_5v_0_v", "motherboard_3v3_0_v",
            "other_voltage_rail_0_v",
        } <= keys
        values = read_direct_hwmon_values(sources, _read)
        assert values["cpu_fan_0_rpm"] in {0.0, 1000.0}
        assert 0.0 in {values[key] for key in keys if key.endswith("_rpm")}
        assert values["cpu_vcore_0_v"] == 1.198
        assert values["motherboard_12v_0_v"] == 12.264
        assert all("hwmon7" not in str(source["stable_device_locator"]) for source in sources)
        assert len([source for source in sources if source["semantic_classification"] == "cpu_fan"]) == 2

        evidence_by_label = {item.get("raw_label", ""): item for item in evidence}
        assert evidence_by_label["CPU Fan"]["accepted"] is True
        assert evidence_by_label["CPU Fan"]["unit"] == "rpm"
        unlabeled_fan = next(item for item in evidence if item["family"] == "fan" and not item["raw_label"])
        assert not unlabeled_fan["accepted"] and unlabeled_fan["rejection_reason"] == "unlabeled"
        assert evidence_by_label["CPU Current"]["rejection_reason"] == "unsupported_family"
        assert evidence_by_label["Board Power"]["rejection_reason"] == "unsupported_family"
        assert evidence_by_label["CPU VID"]["rejection_reason"] == "unsupported_semantics"
        assert evidence_by_label["VIN0"]["rejection_reason"] == "unsupported_semantics"
        assert evidence_by_label["CPU 1P8"]["semantic_classification"] == "other_voltage_rail"
        accepted_evidence = [item for item in evidence if item["accepted"]]
        assert len(accepted_evidence) == len(sources)
        assert {item["path"] for item in accepted_evidence} == {source["path"] for source in sources}

        payload = build_telemetry_source_map(
            **_empty_source_map_kwargs(),
            direct_hwmon_sources=sources,
            hwmon_sensor_candidates=evidence,
            bmc_sources=[{
                "key": "bmc_voltage_vcore_cpu1_v",
                "kind": "ipmi_numeric",
                "label": "VCORE_CPU1",
                "metric_class": "voltage",
                "normalized_units": "volts",
                "provider": "ipmitool",
            }, {
                "key": "bmc_fan_system_fan_1_rpm",
                "kind": "ipmi_numeric",
                "label": "SYSTEM_FAN_1",
                "metric_class": "fan_speed",
                "normalized_units": "rpm",
                "provider": "ipmitool",
            }],
        )
        assert payload["fields"]["cpu_vcore_0_v"]["source_scope"] == "direct_platform_hwmon"
        assert payload["fields"]["cpu_vcore_0_v"]["measurement_semantics"] == "measured_or_provider_reported"
        assert payload["fields"]["cpu_vcore_0_v"]["channel"] == 5
        assert payload["fields"]["bmc_voltage_vcore_cpu1_v"]["provider"] == "ipmitool"
        assert payload["fields"]["bmc_fan_system_fan_1_rpm"]["provider"] == "ipmitool"
        assert payload["direct_hwmon_sensor_candidates"] == evidence

        # Volatile class ordinals do not affect canonical keys.
        board_keys = {source["key"] for source in sources if "nct6687.2592" in source["stable_device_locator"]}
        for volatile_ordinal in (0, 99):
            renamed = root / f"class-renamed-{volatile_ordinal}" / "hwmon"
            renamed.mkdir(parents=True)
            (renamed / f"hwmon{volatile_ordinal}").symlink_to(board, target_is_directory=True)
            renamed_sources, _ = discover_direct_hwmon_sources(read_text=_read, hwmon_root=renamed)
            assert {source["key"] for source in renamed_sources} == board_keys

        gpu = _hwmon(root, 20, "pci0000:00/0000:03:00.0", "amdgpu")
        _field(gpu, "fan", 1, 0, "GPU Fan 1")
        _field(gpu, "fan", 2, 2400, "GPU Fan 2")
        gpu_sources = gpu_hwmon_fan_sources(
            gpu,
            card_name="card1",
            gpu_index=1,
            slot="0000:03:00.0",
            read_text=_read,
            sensor_label=lambda path: _read(path.with_name(path.name.replace("_input", "_label"))) or "",
        )
        assert [source["sensor_index"] for source in gpu_sources] == [1, 2]
        for index, source in enumerate(gpu_sources):
            source["key"] = f"gpu_1_fan_{index}_rpm"
            source["sensor_index"] = index
        gpu_values = read_gpu_values(gpu_sources, _read, _read, {}, {}, {}, 1.0)
        assert gpu_values == {"gpu_1_fan_0_rpm": 0.0, "gpu_1_fan_1_rpm": 2400.0}
        assert all(source["unit"] == "rpm" for source in gpu_sources)
        second_gpu_sources = gpu_hwmon_fan_sources(
            gpu,
            card_name="card2",
            gpu_index=2,
            slot="0000:04:00.0",
            read_text=_read,
            sensor_label=lambda path: _read(path.with_name(path.name.replace("_input", "_label"))) or "",
        )
        for index, source in enumerate(second_gpu_sources):
            source["key"] = f"gpu_2_fan_{index}_rpm"
        assert {source["key"] for source in gpu_sources}.isdisjoint(
            {source["key"] for source in second_gpu_sources}
        )

        # The generic platform pass records but does not duplicate GPU-owned fans.
        _, all_evidence = discover_direct_hwmon_sources(read_text=_read, hwmon_root=root / "class" / "hwmon")
        gpu_candidate = next(item for item in all_evidence if item["provider"] == "amdgpu" and item["family"] == "fan")
        assert not gpu_candidate["accepted"]
        assert gpu_candidate["rejection_reason"] == "gpu_owned_source"

        # A disappeared/unreadable accepted path is omitted, never fabricated as zero.
        assert read_direct_hwmon_values(sources, lambda _path: None) == {}

    # NVIDIA remains duty-percent only; no RPM is fabricated by provider naming.
    nvidia_duty = {
        "kind": "nvidia_smi", "metric": "fan_percent", "key": "gpu_0_fan_percent",
        "slot": "0000:01:00.0", "path": "nvidia-smi:0000:01:00.0",
    }
    assert read_gpu_values(
        [nvidia_duty], lambda _path: None, lambda _path: None, {},
        {"0000:01:00.0": {"fan_percent": 45.0}}, {}, 1.0,
    ) == {"gpu_0_fan_percent": 45.0}


if __name__ == "__main__":
    run_direct_hwmon_telemetry_checks()
    print("direct hwmon telemetry checks: PASS")
