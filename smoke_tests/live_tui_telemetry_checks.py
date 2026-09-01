#!/usr/bin/env python3
"""Focused, hardware-free checks for structured live TUI telemetry."""

from __future__ import annotations

from pathlib import Path
import inspect
import subprocess
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Modules.lvs_live_telemetry import build_live_telemetry_snapshot
from Modules.lvs_telemetry_collector import TelemetryCollector
from Modules.lvs_telemetry_samples import Sample
from Modules.lvs_tui_run_presentation import (
    LIVE_SYSTEM_MIN_TERMINAL_WIDTH,
    live_detail_column_count,
    live_detail_content_width,
    live_snapshot_detail_text,
    live_snapshot_is_stale,
    live_snapshot_text,
    live_system_layout,
)


class CachedBmc:
    available = True
    stale_after_seconds = 180.0

    def __init__(self, fresh: bool = True, count: int = 1) -> None:
        self.fresh = fresh
        self.count = count
        self.poll_count = 0

    def source_catalog(self):
        return [
            {
                "key": f"bmc_sensor_{index}", "label": f"BMC Sensor {index + 1}",
                "unit": "rpm" if index == 0 else "celsius", "provider": "ipmi_bmc",
            }
            for index in range(self.count)
        ]

    def latest_snapshot(self, now):
        return object() if self.fresh else None


def fixture_collector(core_count: int = 24, *, bmc_fresh: bool = True):
    topology = {
        index: {
            "core_type": "P" if index < 8 else "E",
            "classification_source": "recorded_core_type",
        }
        for index in range(core_count)
    }
    clock_sources = [{"cpu_index": index, "key": f"cpu_core_{index}_clock_mhz"} for index in range(core_count)]
    utilization_sources = [{"cpu_index": index, "key": f"cpu_core_{index}_utilization_percent"} for index in range(core_count)]
    return SimpleNamespace(
        samples=[], interval_seconds=2.0, memory_total_gib=64.0,
        _cpu_core_topology=topology,
        _cpu_core_clock_sources=clock_sources,
        _cpu_core_utilization_sources=utilization_sources,
        _memory_temp_sources=[{"key": "memory_module_0_temp_c", "label": "DIMM 1", "unit": "celsius", "provider": "hwmon"}],
        _storage_temp_sources=[{"key": "storage_drive_0_temp_c", "label": "NVMe 1 Composite", "unit": "celsius", "provider": "nvme"}],
        _device_temp_sources=[],
        _direct_hwmon_sources=[
            {"key": "cpu_fan_0_rpm", "normalized_label": "CPU Fan", "unit": "rpm", "semantic_classification": "cpu_fan", "provider": "nct6687"},
            {"key": "pump_0_rpm", "normalized_label": "Pump", "unit": "rpm", "semantic_classification": "pump", "provider": "nct6687"},
            {"key": "cpu_vcore_0_v", "normalized_label": "CPU Vcore", "unit": "volts", "semantic_classification": "cpu_vcore", "provider": "nct6687"},
            {"key": "motherboard_12v_0_v", "normalized_label": "+12V", "unit": "volts", "semantic_classification": "motherboard_12v", "provider": "nct6687"},
        ],
        _gpu_sources=[
            {"key": "gpu_1_busy_percent", "gpu_index": 1, "metric": "busy_percent"},
            {"key": "gpu_1_temp_c", "gpu_index": 1, "metric": "temp_core_c"},
            {"key": "gpu_1_hotspot_c", "gpu_index": 1, "metric": "temp_hotspot_c"},
            {"key": "gpu_1_power_w", "gpu_index": 1, "metric": "power_w"},
            {"key": "gpu_1_clock_mhz", "gpu_index": 1, "metric": "clock_mhz"},
            {"key": "gpu_1_memory_busy_percent", "gpu_index": 1, "metric": "memory_busy_percent"},
            {"key": "gpu_1_memory_clock_mhz", "gpu_index": 1, "metric": "memory_clock_mhz"},
            {"key": "gpu_1_vram_used_gb", "gpu_index": 1, "metric": "vram_used_gb"},
            {"key": "gpu_1_fan_percent", "gpu_index": 1, "metric": "fan_percent"},
            {"key": "gpu_1_fan_0_rpm", "gpu_index": 1, "metric": "fan_rpm", "label": "GPU 2 Fan", "unit": "rpm"},
            {"key": "gpu_1_vddgfx_v", "gpu_index": 1, "metric": "vddgfx_v"},
            {"key": "gpu_1_vddnb_v", "gpu_index": 1, "metric": "vddnb_v"},
        ],
        _bmc_provider=CachedBmc(bmc_fresh),
    )


def sample_for(collector, timestamp: float = 100.0) -> Sample:
    values = {
        "cpu_utilization_percent": 82.0, "cpu_temp_c": 74.0, "cpu_power_w": 168.0,
        "cpu_clock_mhz": 5400.0, "cpu_package_0_temp_c": 73.0,
        "cpu_package_0_power_w": 167.0, "memory_used_gb": 20.0,
        "memory_module_0_temp_c": 52.0, "storage_drive_0_temp_c": 48.0,
        "cpu_fan_0_rpm": 1450.0, "pump_0_rpm": 2800.0, "cpu_vcore_0_v": 1.21,
        "motherboard_12v_0_v": 12.1, "gpu_1_busy_percent": 96.0, "gpu_1_temp_c": 68.0,
        "gpu_1_hotspot_c": 84.0, "gpu_1_power_w": 280.0, "gpu_1_clock_mhz": 2450.0,
        "gpu_1_memory_busy_percent": 72.0, "gpu_1_memory_clock_mhz": 1400.0,
        "gpu_1_vram_used_gb": 8.1, "gpu_1_vram_total_gib": 16.0,
        "gpu_1_fan_percent": 45.0, "gpu_1_fan_0_rpm": 1850.0,
        "gpu_1_vddgfx_v": 0.94, "gpu_1_vddnb_v": 0.88, "bmc_sensor_0": 900.0,
    }
    for index in range(len(collector._cpu_core_topology)):
        values[f"cpu_core_{index}_clock_mhz"] = 5000.0 - index
        values[f"cpu_core_{index}_utilization_percent"] = float(index % 100)
    return Sample(timestamp=timestamp, values=values)


def run_live_tui_telemetry_checks() -> None:
    collector = fixture_collector()
    sample = sample_for(collector)
    collector.samples.append(sample)
    snapshot = build_live_telemetry_snapshot(collector, sample)
    assert snapshot.cpu_vcore_v == 1.21
    assert len(snapshot.cpu_packages) == 2
    assert snapshot.gpus[0].hotspot_c == 84.0 and snapshot.gpus[0].fan_duty_percent == 45.0
    assert snapshot.gpus[0].vram_total_gib == 16.0
    assert snapshot.gpus[0].vddnb_v == 0.88
    assert snapshot.gpus[0].fan_rpm[0].value == 1850.0
    assert snapshot.bmc_state == "ok" and collector._bmc_provider.poll_count == 0
    assert len(snapshot.cpu_cores) == 24
    assert snapshot.cpu_cores[0].label == "P-Core 0" and snapshot.cpu_cores[8].label == "E-Core 8"
    compact = live_snapshot_text(snapshot)
    assert "CPU  82%" in compact and "GPU2 96%" in compact and "Pump 2800 RPM" in compact
    assert max(map(len, compact.splitlines())) <= 32
    detail = live_snapshot_detail_text(snapshot)
    for expected in ("Performance cores (8)", "Efficiency cores (16)", "Fan duty: 45 %", "VDDGFX: 0.9 V", "VDDNB: 0.9 V", "+12V"):
        assert expected in detail, expected
    assert live_snapshot_is_stale(snapshot, 105.0) is False
    assert live_snapshot_is_stale(snapshot, 107.0) is True
    assert live_system_layout(terminal_width=123, run_active=True).visible is False
    assert live_system_layout(terminal_width=LIVE_SYSTEM_MIN_TERMINAL_WIDTH, run_active=True).visible is True

    multi = fixture_collector()
    second_gpu_sources = []
    for source in multi._gpu_sources:
        copied = dict(source)
        copied["gpu_index"] = 2
        copied["key"] = str(copied["key"]).replace("gpu_1_", "gpu_2_")
        second_gpu_sources.append(copied)
    multi._gpu_sources.extend(second_gpu_sources)
    multi._memory_temp_sources.append(
        {"key": "memory_module_1_temp_c", "label": "DIMM 2", "unit": "celsius"}
    )
    multi._storage_temp_sources.append(
        {"key": "storage_drive_1_temp_c", "label": "NVMe 2 Composite", "unit": "celsius"}
    )
    multi._direct_hwmon_sources.append(
        {"key": "system_fan_0_rpm", "normalized_label": "System Fan 1", "unit": "rpm", "semantic_classification": "system_fan"}
    )
    multi_sample = sample_for(multi)
    for key, value in list(multi_sample.values.items()):
        if key.startswith("gpu_1_"):
            multi_sample.values[key.replace("gpu_1_", "gpu_2_")] = value
    multi_sample.values.update({
        "memory_module_1_temp_c": 49.0, "storage_drive_1_temp_c": 43.0,
        "system_fan_0_rpm": 820.0,
    })
    multi.samples.append(multi_sample)
    multi_snapshot = build_live_telemetry_snapshot(multi, multi_sample)
    assert len(multi_snapshot.gpus) == 2
    assert len(multi_snapshot.dimm_temperatures) == 2
    assert len(multi_snapshot.storage_temperatures) == 2
    assert len(multi_snapshot.cooling) == 3

    for count in (64, 128):
        large = fixture_collector(count)
        large_sample = sample_for(large)
        large.samples.append(large_sample)
        large_snapshot = build_live_telemetry_snapshot(large, large_sample)
        rendered = live_snapshot_detail_text(large_snapshot)
        assert len(large_snapshot.cpu_cores) == count
        assert f"Efficiency cores ({count - 8})" in rendered
        assert len(rendered.splitlines()) < 150

    expected_core_columns = {80: 1, 100: 2, 123: 3, 124: 2, 160: 3, 200: 4}
    core_items = [f"P-Core {index}  100%  5.4G" for index in range(128)]
    for terminal_width, expected_columns in expected_core_columns.items():
        content_width = live_detail_content_width(terminal_width)
        assert live_detail_column_count(
            core_items, content_width, minimum_cell_width=19
        ) == expected_columns

    dense = fixture_collector(128)
    dense._bmc_provider = CachedBmc(count=24)
    base_gpu_sources = list(dense._gpu_sources)
    for gpu_index in (2, 3, 10):
        for source in base_gpu_sources:
            copied = dict(source)
            copied["gpu_index"] = gpu_index
            copied["key"] = str(copied["key"]).replace("gpu_1_", f"gpu_{gpu_index}_")
            dense._gpu_sources.append(copied)
    for index in range(1, 8):
        dense._memory_temp_sources.append({
            "key": f"memory_module_{index}_temp_c", "label": f"DIMM {index + 1}", "unit": "celsius",
        })
    for index in range(1, 4):
        dense._storage_temp_sources.append({
            "key": f"storage_drive_{index}_temp_c", "label": f"NVMe {index + 1} Composite", "unit": "celsius",
        })
    for index in range(12):
        dense._direct_hwmon_sources.append({
            "key": f"system_fan_{index}_rpm", "normalized_label": f"System Fan {index + 1}",
            "unit": "rpm", "semantic_classification": "system_fan", "provider": "board_hwmon",
        })
    for index in range(8):
        dense._direct_hwmon_sources.append({
            "key": f"other_voltage_rail_{index}_v", "normalized_label": f"Aux Rail {index + 1}",
            "unit": "volts", "semantic_classification": "other_voltage_rail", "provider": "board_hwmon",
        })
    dense_sample = sample_for(dense)
    for gpu_index in (2, 3, 10):
        for key, value in list(dense_sample.values.items()):
            if key.startswith("gpu_1_"):
                dense_sample.values[key.replace("gpu_1_", f"gpu_{gpu_index}_")] = value
    for index in range(1, 8):
        dense_sample.values[f"memory_module_{index}_temp_c"] = 45.0 + index
    for index in range(1, 4):
        dense_sample.values[f"storage_drive_{index}_temp_c"] = 44.0 + index
    for index in range(12):
        dense_sample.values[f"system_fan_{index}_rpm"] = 800.0 + index
    for index in range(8):
        dense_sample.values[f"other_voltage_rail_{index}_v"] = 1.0 + index
    for index in range(24):
        dense_sample.values[f"bmc_sensor_{index}"] = 900.0 + index
    dense.samples.append(dense_sample)
    dense_snapshot = build_live_telemetry_snapshot(dense, dense_sample)
    assert len(dense_snapshot.gpus) == 4
    dense_line_counts = {}
    for terminal_width in (80, 100, 123, 124, 160, 200):
        content_width = live_detail_content_width(terminal_width)
        dense_text = live_snapshot_detail_text(dense_snapshot, content_width=content_width)
        assert max(map(len, dense_text.splitlines())) <= content_width
        dense_line_counts[terminal_width] = len(dense_text.splitlines())
    assert max(map(len, live_snapshot_text(dense_snapshot).splitlines())) <= 32
    assert dense_line_counts[200] < dense_line_counts[80]
    repeated_sensor_items = [f"System Fan {index + 1}: {800 + index} RPM" for index in range(12)]
    assert live_detail_column_count(
        repeated_sensor_items, live_detail_content_width(80), minimum_cell_width=24
    ) == 1
    assert live_detail_column_count(
        repeated_sensor_items, live_detail_content_width(200), minimum_cell_width=24
    ) >= 3
    tui_app_source = (ROOT / "Modules" / "lvs_tui_app.py").read_text(encoding="utf-8")
    assert "#detail" in tui_app_source and "overflow: auto" in tui_app_source
    assert "self._refresh_run_detail()" in tui_app_source

    homogeneous = fixture_collector(32)
    for info in homogeneous._cpu_core_topology.values():
        info["classification_source"] = "homogeneous_fallback"
    homogeneous_sample = sample_for(homogeneous)
    homogeneous.samples.append(homogeneous_sample)
    homogeneous_detail = live_snapshot_detail_text(
        build_live_telemetry_snapshot(homogeneous, homogeneous_sample)
    )
    assert "CPU cores (32)" in homogeneous_detail
    assert "Performance cores" not in homogeneous_detail

    stale_bmc = fixture_collector(bmc_fresh=False)
    stale_sample = sample_for(stale_bmc)
    stale_bmc.samples.append(stale_sample)
    assert build_live_telemetry_snapshot(stale_bmc, stale_sample).bmc_state == "stale"

    cpu_only = fixture_collector()
    cpu_only._gpu_sources = []
    cpu_only._memory_temp_sources = []
    cpu_only._storage_temp_sources = []
    cpu_only._direct_hwmon_sources = []
    cpu_only._bmc_provider = None
    cpu_sample = Sample(timestamp=100.0, values={"cpu_utilization_percent": 50.0})
    cpu_only.samples.append(cpu_sample)
    cpu_snapshot = build_live_telemetry_snapshot(cpu_only, cpu_sample)
    assert "CPU  50%" in live_snapshot_text(cpu_snapshot)
    assert "GPU" not in live_snapshot_text(cpu_snapshot)

    callbacks = []
    minimal = TelemetryCollector.__new__(TelemetryCollector)
    minimal.samples = [sample]
    minimal.interval_seconds = 2.0
    minimal._live_snapshot_callback = callbacks.append
    minimal._live_snapshot_closed = False
    minimal._cpu_core_topology = {}
    minimal._cpu_core_clock_sources = []
    minimal._cpu_core_utilization_sources = []
    minimal._memory_temp_sources = []
    minimal._storage_temp_sources = []
    minimal._direct_hwmon_sources = []
    minimal._gpu_sources = []
    minimal._bmc_provider = None
    minimal.memory_total_gib = None
    minimal._publish_live_snapshot("active")
    minimal.close()
    assert [item.state for item in callbacks] == ["active", "stopped"]

    import Modules.lvs_telemetry_collector as collector_module
    original_builder = collector_module.build_live_telemetry_snapshot
    no_subscriber = TelemetryCollector.__new__(TelemetryCollector)
    no_subscriber.samples = [sample]
    no_subscriber._live_snapshot_callback = None
    try:
        collector_module.build_live_telemetry_snapshot = lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("CLI path constructed a live TUI snapshot")
        )
        no_subscriber._publish_live_snapshot("active")
    finally:
        collector_module.build_live_telemetry_snapshot = original_builder

    cli_import = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import Modules.lvs_telemetry_collector; "
                "assert 'textual' not in sys.modules; "
                "assert not any(name.startswith('Modules.lvs_tui_') for name in sys.modules)"
            ),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert cli_import.returncode == 0, cli_import.stderr

    from Modules.lvs_service_run import SuiteRunServiceMixin
    assert "live_telemetry_callback" in inspect.signature(SuiteRunServiceMixin.run_profile_capture_output).parameters


if __name__ == "__main__":
    run_live_tui_telemetry_checks()
    print("PASS live TUI telemetry checks")
