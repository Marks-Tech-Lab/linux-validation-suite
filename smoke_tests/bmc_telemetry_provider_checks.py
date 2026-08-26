#!/usr/bin/env python3
"""Focused BMC/IPMI parsing, background, and compatibility regressions."""

from __future__ import annotations

import csv
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import Modules.lvs_telemetry_bmc as bmc_module
from Modules.lvs_core import JsonStore
from Modules.lvs_hardware_evidence import HardwareEvidenceCollector
from Modules.lvs_profile_models import ValidationProfile
from Modules.lvs_run_artifacts import write_final_run_artifacts
from Modules.lvs_telemetry_bmc import (
    BmcCommandResult,
    BmcSnapshot,
    BmcSnapshotProvider,
    append_static_bmc_discrete_sensors,
    attach_bmc_thresholds,
    bmc_sensor_identity,
    build_bmc_source_catalog,
    classify_bmc_component,
    classify_bmc_status,
    normalize_bmc_discrete_state,
    parse_ipmitool_sdr_elist,
    parse_ipmitool_sensor,
)
from Modules.lvs_telemetry_collector import TelemetryCollector
from Modules.lvs_telemetry_samples import Sample, extended_telemetry_metric_field_names, write_telemetry_csv
from Modules.lvs_telemetry_sources import build_telemetry_source_map


SDR_TEXT = """
TEMP_CPU         | 2Ah | ok | 65.1 | 42 degrees C
TEMP_DDR5_A1     | 50h | ok | 32.1 | 29 degrees C
TEMP_DDR5_C1     | 34h | ok | 32.1 | 29 degrees C
POWER_DDR5_C1    | 34h | ok | 10.0 | 2.10 Watts
POWER_DDR5_A1    | 30h | ok | 10.0 | 1.70 Watts
Memory_Power     | F4h | ok | 19.0 | 8 Watts
DDR VDD          | 61h | ok | 32.1 | 1.10 Volts
MEM VDDQ         | 62h | ok | 32.1 | 0.00 Volts
DDR VPP          | 63h | ok | 32.1 | 1.80 Volts
Memory VRM Temp  | 64h | ok | 32.1 | 48 degrees C
Memory VRM Power | 65h | ok | 32.1 | 12 Watts
VOLT_VCORE0      | 41h | ok | 65.1 | 1.05 Volts
CUR_PSU1_IOUT    | 42h | ok | 10.1 | 0.00 Amps
PSU1 Power In    | DFh | ok | 10.1 | 144 Watts
PSU1 Power Out   | 5Ah | ok | 10.1 | 112 Watts
PSU1 Temp        | 5Bh | ns | 10.1 | No Reading
FAN1             | 20h | ok | 29.1 | 5200 RPM
PUMP1            | 21h | ok | 29.2 | 0 RPM
Utilization      | 22h | ok | 7.1 | 0 percent
VRM Temp         | 23h | ok | 7.1 | 51 degrees C
PCH Temp         | 24h | ok | 7.1 | 44 degrees C
Motherboard Temp | 25h | ok | 7.1 | 35 degrees C
System Temp      | 26h | ok | 7.1 | 34 degrees C
Inlet Temp       | 27h | ok | 55.0 | 21 degrees C
Ambient Temp     | 28h | ok | 55.1 | 22 degrees C
PSU1 Status      | 70h | ok | 10.1 | Presence detected
Bad Numeric      | 71h | ns | 7.1 | NaN Watts
malformed row
""".strip()

SENSOR_TEXT = """
TEMP_CPU | 42.000 | degrees C | ok | 5.000 | 10.000 | 15.000 | 90.000 | 95.000 | 100.000
TEMP_DDR5_A1 | 29.000 | degrees C | ok | na | na | na | 84.000 | 85.000 | na
TEMP_DDR5_C1 | 29.000 | degrees C | ok | na | na | na | 84.000 | 85.000 | na
POWER_DDR5_C1 | 2.100 | Watts | ok | na | na | na | na | na | na
POWER_DDR5_A1 | 1.700 | Watts | ok | na | na | na | na | na | na
Memory_Power | 8.000 | Watts | ok | na | na | na | na | na | na
DDR VDD | 1.100 | Volts | ok | 0.900 | na | na | 1.200 | 1.250 | 1.300
MEM VDDQ | 0.000 | Volts | ok | na | na | na | na | na | na
DDR VPP | 1.800 | Volts | ok | na | na | na | na | na | na
Memory VRM Temp | 48.000 | degrees C | ok | na | na | na | 80 | 90 | 100
Memory VRM Power | 12.000 | Watts | ok | na | na | na | na | na | na
VOLT_VCORE0 | 1.050 | Volts | ok | na | na | na | na | na | na
CUR_PSU1_IOUT | 0.000 | Amps | ok | na | na | na | na | na | na
PSU1 Power In | 144.000 | Watts | ok | na | na | na | na | na | na
PSU1 Power Out | 112.000 | Watts | ok | na | na | na | 3040 | 3200 | 3360
PSU1 Temp | na | degrees C | ns | na | na | na | na | na | na
FAN1 | 5200 | RPM | ok | 0 | 500 | 1000 | 12000 | 14000 | 16000
PUMP1 | 0 | RPM | ok | na | na | na | na | na | na
Utilization | 0 | percent | ok | na | na | na | na | na | na
VRM Temp | 51 | degrees C | ok | na | na | na | 90 | 100 | 110
PCH Temp | 44 | degrees C | ok | na | na | na | 85 | 95 | 105
Motherboard Temp | 35 | degrees C | ok | na | na | na | 70 | 80 | 90
System Temp | 34 | degrees C | ok | na | na | na | 70 | 80 | 90
Inlet Temp | 21 | degrees C | ok | na | na | na | 37 | 40 | 60
Ambient Temp | 22 | degrees C | ok | na | na | na | 37 | 40 | 60
PSU1 Status | 0x01 | discrete | ok | na | na | na | na | na | na
""".strip()


def _wait_for_snapshot(provider: BmcSnapshotProvider, timeout: float = 2.0) -> BmcSnapshot:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snapshot = provider.poll()
        if snapshot is not None:
            return snapshot
        time.sleep(0.005)
    raise AssertionError("BMC snapshot did not complete")


def run_bmc_telemetry_provider_checks() -> None:
    parsed = parse_ipmitool_sdr_elist(SDR_TEXT)
    thresholds = parse_ipmitool_sensor(SENSOR_TEXT)
    parsed = attach_bmc_thresholds(parsed, thresholds)
    by_label = {sensor.raw_label: sensor for sensor in parsed}

    assert by_label["TEMP_CPU"].normalized_value == 42.0
    assert by_label["VOLT_VCORE0"].metric_class == "voltage"
    assert by_label["CUR_PSU1_IOUT"].normalized_value == 0.0
    assert by_label["PSU1 Power In"].metric_class == "power"
    assert by_label["FAN1"].normalized_value == 5200.0
    assert by_label["PUMP1"].normalized_value == 0.0
    assert by_label["Utilization"].normalized_value == 0.0
    assert by_label["PSU1 Temp"].normalized_value is None
    assert by_label["PSU1 Temp"].metric_class == "temperature"
    assert by_label["PSU1 Status"].discrete_state == "Presence detected"
    assert "Bad Numeric" in by_label and by_label["Bad Numeric"].metric_class == ""
    static_discrete = parse_ipmitool_sensor("PSU Fault | 0x01 | discrete | ok | na | na | na | na | na | na")
    merged_discrete = append_static_bmc_discrete_sensors(parsed, static_discrete)
    static_fault = next(sensor for sensor in merged_discrete if sensor.raw_label == "PSU Fault")
    assert static_fault.discrete_state == "0x01"
    assert static_fault.observation_mode == "static"
    assert normalize_bmc_discrete_state("0x01") == "unknown"
    assert normalize_bmc_discrete_state("State Deasserted") == "deasserted"
    assert normalize_bmc_discrete_state("Asserted") == "asserted"
    assert normalize_bmc_discrete_state("Presence detected") == "present"
    assert classify_bmc_status("PSU1 Failure") == ("psu", "power_supply")
    assert classify_bmc_status("PROCHOT_CPU") == ("cpu", "cpu_throttle")
    assert classify_bmc_status("WATCHDOG2") == ("bmc", "watchdog")
    assert classify_bmc_status("CPU1_ECC1") == ("memory", "ecc_memory")
    assert classify_bmc_status("PowerUnit") == ("other_platform", "unknown")
    duplicate_provenance = append_static_bmc_discrete_sensors(
        parse_ipmitool_sdr_elist("PSU Fault | 72h | ok | 10.1 | State Deasserted"),
        parse_ipmitool_sensor(
            "PSU Fault | 0x01 | discrete | ok | na | na | na | na | na | na"
        ),
    )
    assert [sensor.observation_mode for sensor in duplicate_provenance] == ["recurring", "static"]
    duplicate_provenance_provider = BmcSnapshotProvider(enabled=False)
    duplicate_provenance_provider._record_status_snapshot_locked(
        BmcSnapshot(
            "ipmi_bmc", "ipmitool sdr elist", "direct", "duplicate", 1.0, "ok", duplicate_provenance
        )
    )
    duplicate_status = duplicate_provenance_provider.status_evidence()
    assert [item["observation_mode"] for item in duplicate_status["start"]["sensors"]] == [
        "recurring"
    ]
    duplicate_provenance_provider.close()

    cpu_thresholds = by_label["TEMP_CPU"].thresholds
    assert cpu_thresholds == {
        "lower_nonrecoverable": 5.0,
        "lower_critical": 10.0,
        "lower_noncritical": 15.0,
        "upper_noncritical": 90.0,
        "upper_critical": 95.0,
        "upper_nonrecoverable": 100.0,
    }
    assert by_label["TEMP_DDR5_A1"].thresholds["lower_nonrecoverable"] is None

    unique_sdr = parse_ipmitool_sdr_elist("CPU Temp | 01h | ok | 3.1 | 40 degrees C")
    unique_static = parse_ipmitool_sensor(
        "CPU Temp | 40 | degrees C | ok | na | na | na | 80 | 90 | 100"
    )
    assert attach_bmc_thresholds(unique_sdr, unique_static)[0].thresholds["upper_critical"] == 90.0
    duplicate_sdr = parse_ipmitool_sdr_elist(
        "CPU Temp | 01h | ok | 3.1 | 40 degrees C\n"
        "CPU Temp | 02h | ok | 3.2 | 41 degrees C"
    )
    assert all(not sensor.thresholds for sensor in attach_bmc_thresholds(duplicate_sdr, unique_static))
    cross_metric_static = parse_ipmitool_sensor(
        "Rail-A | 1.1 | Volts | ok | na | na | na | 1.2 | 1.3 | 1.4"
    )
    cross_metric_sdr = parse_ipmitool_sdr_elist("Rail A | 03h | ok | 3.1 | 35 degrees C")
    assert not attach_bmc_thresholds(cross_metric_sdr, cross_metric_static)[0].thresholds

    assert classify_bmc_component("DIMM A1 Temp", "temperature")[0] == "memory_module"
    assert classify_bmc_component("CPU1_DIMMB2_Temp", "temperature")[0] == "memory_module"
    assert classify_bmc_component("DDR VDD", "voltage")[0] == "memory_rail"
    assert classify_bmc_component("MEM VDDQ", "voltage")[0] == "memory_rail"
    assert classify_bmc_component("DDR VPP", "voltage")[0] == "memory_rail"
    assert classify_bmc_component("Memory_Power", "power")[0] == "memory_rail"
    assert classify_bmc_component("Memory VRM Temp", "temperature")[0] == "memory_vrm"
    assert classify_bmc_component("Memory VRM Power", "power")[0] == "memory_vrm"
    for label, expected in (
        ("VRM Temp", "vrm"),
        ("PCH Temp", "pch"),
        ("Motherboard Temp", "motherboard"),
        ("System Temp", "system"),
        ("Inlet Temp", "inlet"),
        ("Ambient Temp", "ambient"),
        ("PSU1 Temp", "psu"),
        ("FAN1", "fan"),
        ("PUMP1", "pump"),
    ):
        assert classify_bmc_component(label, "rotational" if expected in {"fan", "pump"} else "temperature")[0] == expected

    # Real-corpus identity condition: one sensor number can identify distinct
    # temperature and power sensors, so the full tuple must remain distinct.
    assert by_label["TEMP_DDR5_C1"].sensor_number == by_label["POWER_DDR5_C1"].sensor_number == "34"
    assert bmc_sensor_identity(by_label["TEMP_DDR5_C1"]) != bmc_sensor_identity(by_label["POWER_DDR5_C1"])

    catalog = build_bmc_source_catalog(parsed)
    keys = {source["label"]: source["key"] for source in catalog}
    assert keys["TEMP_DDR5_A1"] == "bmc_temp_ddr5_a1_c"
    assert keys["POWER_DDR5_A1"] == "bmc_power_ddr5_a1_w"
    assert keys["Memory_Power"] == "bmc_memory_power_w"
    assert keys["PSU1 Power In"] == "bmc_psu1_power_in_w"
    assert keys["FAN1"] == "bmc_fan1_rpm"
    reordered = build_bmc_source_catalog(reversed(parsed))
    assert [(item["key"], item["canonical_identity"]) for item in catalog] == [
        (item["key"], item["canonical_identity"]) for item in reordered
    ]
    # Equivalent Full Sensor Records retain identical numeric semantics whether
    # delivered by unqualified elist or the older elist-full command.
    unqualified_numeric = parse_ipmitool_sdr_elist(SDR_TEXT)
    full_numeric = parse_ipmitool_sdr_elist(SDR_TEXT)
    assert unqualified_numeric == full_numeric
    assert build_bmc_source_catalog(unqualified_numeric) == build_bmc_source_catalog(full_numeric)
    compact_only = parse_ipmitool_sdr_elist(
        "PSU Failure | 80h | ok | 10.1 | State Deasserted\n"
        "Event Only | 81h | ns | 10.2 | No Reading"
    )
    assert build_bmc_source_catalog(compact_only) == ()
    assert all(sensor.normalized_value is None and not sensor.metric_class for sensor in compact_only)

    duplicate_text = "\n".join(
        (
            "System Temp | 01h | ok | 7.1 | 30 degrees C",
            "System-Temp | 02h | ok | 7.2 | 31 degrees C",
        )
    )
    duplicate_catalog = build_bmc_source_catalog(parse_ipmitool_sdr_elist(duplicate_text))
    assert [source["key"] for source in duplicate_catalog] == [
        "bmc_system_temp_0_c",
        "bmc_system_temp_1_c",
    ]
    assert [source["key"] for source in duplicate_catalog] == [
        source["key"] for source in build_bmc_source_catalog(reversed(parse_ipmitool_sdr_elist(duplicate_text)))
    ]

    # Evidence-only status tracking uses recurring SDR identity, ignores static
    # sensor-table rows, and compares only successful observable snapshots.
    status_provider = BmcSnapshotProvider(enabled=False)

    def status_snapshot(text: str, captured_at: str, captured_monotonic: float) -> BmcSnapshot:
        recurring = parse_ipmitool_sdr_elist(text)
        static = parse_ipmitool_sensor(
            "Static PSU Fault | 0x01 | discrete | ok | na | na | na | na | na | na"
        )
        return BmcSnapshot(
            "ipmi_bmc",
            "ipmitool sdr elist",
            "direct",
            captured_at,
            captured_monotonic,
            "ok",
            append_static_bmc_discrete_sensors(recurring, static),
        )

    first_status = status_snapshot(
        "PSU Failure | 80h | ok | 10.1 | State Deasserted\n"
        "Unknown State | 81h | ok | 10.2 | 0x01\n"
        "Omitted State | 84h | ok | 10.6 | State Asserted\n"
        "Reset Identity | 85h | ok | 10.7 | State Deasserted\n"
        "Collision | 82h | ok | 10.3 | State Deasserted\n"
        "Collision | 82h | ok | 10.4 | State Asserted\n"
        "Ambiguous | 83h | ok | 10.5 | State Deasserted\n"
        "Ambiguous | 83h | ok | 10.5 | State Asserted",
        "status-1",
        1.0,
    )
    second_status = status_snapshot(
        "Collision | 82h | ok | 10.4 | State Asserted\n"
        "PSU Failure | 80h | ok | 10.1 | State Asserted\n"
        "Unknown State | 81h | ok | 10.2 |  0X1  \n"
        "Reset Identity | 85h | ok | 10.7 | State Deasserted\n"
        "Reset Identity | 85h | ok | 10.7 | State Asserted\n"
        "Collision | 82h | ok | 10.3 | State Deasserted",
        "status-2",
        61.0,
    )
    returned_status = status_snapshot(
        "Unknown State | 81h | ok | 10.2 | 0x40\n"
        "PSU Failure | 80h | ok | 10.1 | State Asserted\n"
        "Reset Identity | 85h | ok | 10.7 | State Asserted",
        "status-3",
        121.0,
    )
    final_status = status_snapshot(
        "Unknown State | 81h | ok | 10.2 | 0x40\n"
        "PSU Failure | 80h | ok | 10.1 | State Asserted\n"
        "Reset Identity | 85h | ok | 10.7 | State Deasserted",
        "status-4",
        181.0,
    )
    status_provider._record_status_snapshot_locked(first_status)
    assert status_provider.status_evidence()["transitions"] == []
    status_provider._record_status_snapshot_locked(second_status)
    status_provider._record_status_snapshot_locked(second_status)
    status_provider._record_status_snapshot_locked(returned_status)
    assert not any(
        item["raw_label"] == "Reset Identity"
        for item in status_provider.status_evidence()["transitions"]
    )
    status_provider._record_status_snapshot_locked(final_status)
    status_evidence = status_provider.status_evidence()
    assert status_evidence["start"]["captured_at"] == "status-1"
    assert status_evidence["end"]["captured_at"] == "status-4"
    end_status_by_label = {item["raw_label"]: item for item in status_evidence["end"]["sensors"]}
    assert end_status_by_label["Omitted State"]["raw_state"] == "State Asserted"
    assert end_status_by_label["Omitted State"]["last_observed_at"] == "status-1"
    assert not any(sensor["raw_label"] == "Static PSU Fault" for sensor in status_evidence["start"]["sensors"])
    assert not any(sensor["raw_label"] == "Ambiguous" for sensor in status_evidence["start"]["sensors"])
    assert len([sensor for sensor in status_evidence["start"]["sensors"] if sensor["raw_label"] == "Collision"]) == 2
    transitions = status_evidence["transitions"]
    assert len(transitions) == 3
    assert transitions[0]["raw_label"] == "PSU Failure"
    assert transitions[0]["previous_normalized_state"] == "deasserted"
    assert transitions[0]["current_normalized_state"] == "asserted"
    assert transitions[1]["raw_label"] == "Unknown State"
    assert transitions[1]["previous_raw_state"] == "0X1"
    assert transitions[1]["current_raw_state"] == "0x40"
    assert transitions[1]["previous_normalized_state"] == "unknown"
    assert transitions[1]["current_normalized_state"] == "unknown"
    assert transitions[1]["previous_observed_at"] == "status-2"
    assert transitions[2]["raw_label"] == "Reset Identity"
    assert transitions[2]["previous_observed_at"] == "status-3"
    assert transitions[2]["observed_at"] == "status-4"
    mutable_evidence = status_provider.status_evidence()
    mutable_evidence["transitions"][0]["canonical_identity"].append("caller mutation")
    assert "caller mutation" not in status_provider.status_evidence()["transitions"][0]["canonical_identity"]
    status_provider.close()

    ambiguous_fallback = parse_ipmitool_sensor(
        "Duplicate | State Deasserted | discrete | ok\n"
        "Duplicate | State Asserted | discrete | ok"
    )
    ambiguous_provider = BmcSnapshotProvider(enabled=False)
    ambiguous_provider._record_status_snapshot_locked(
        BmcSnapshot("ipmi_bmc", "ipmitool sensor", "direct", "fallback", 1.0, "ok", ambiguous_fallback)
    )
    assert ambiguous_provider.status_evidence() == {}
    ambiguous_provider.close()

    static_only_provider = BmcSnapshotProvider(enabled=False)
    static_only_provider._record_status_snapshot_locked(
        BmcSnapshot(
            "ipmi_bmc",
            "ipmitool sdr elist full",
            "direct",
            "static-only",
            1.0,
            "ok",
            tuple(replace(sensor, observation_mode="static") for sensor in ambiguous_fallback[:1]),
        )
    )
    assert static_only_provider.status_evidence() == {}
    static_only_provider.close()

    numeric_only_provider = BmcSnapshotProvider(enabled=False)
    numeric_only_provider._record_status_snapshot_locked(
        BmcSnapshot(
            "ipmi_bmc",
            "ipmitool sdr elist",
            "direct",
            "numeric-only",
            1.0,
            "ok",
            parse_ipmitool_sdr_elist("CPU Temp | 01h | ok | 3.1 | 40 degrees C"),
        )
    )
    assert numeric_only_provider.status_evidence() == {}
    numeric_only_provider.close()

    # The first refresh blocks in the worker while the caller stays immediate.
    release = threading.Event()
    started = threading.Event()
    commands: list[tuple[str, ...]] = []
    clock = [0.0]
    in_flight = [0]
    maximum_in_flight = [0]
    refresh_count = [0]

    def slow_command(command, _timeout, environment):
        assert environment["LC_ALL"] == "C"
        command_tuple = tuple(command)
        commands.append(command_tuple)
        in_flight[0] += 1
        maximum_in_flight[0] = max(maximum_in_flight[0], in_flight[0])
        try:
            if command_tuple[-2:] == ("sdr", "elist"):
                refresh_count[0] += 1
                if refresh_count[0] == 1:
                    started.set()
                    release.wait(1.5)
                    text = SDR_TEXT
                elif refresh_count[0] == 2:
                    text = "TEMP_CPU | 2Ah | ok | 65.1 | 43 degrees C\nFAN1 | 20h | ok | 29.1 | 5300 RPM"
                elif refresh_count[0] == 3:
                    return BmcCommandResult(command_tuple, -1, stderr="BMC busy", timed_out=True)
                else:
                    text = SDR_TEXT.replace("42 degrees C", "44 degrees C")
                return BmcCommandResult(command_tuple, 0, text)
            if command_tuple[-1:] == ("sensor",):
                return BmcCommandResult(command_tuple, 0, SENSOR_TEXT)
            return BmcCommandResult(command_tuple, 1, stderr="unsupported")
        finally:
            in_flight[0] -= 1

    provider = BmcSnapshotProvider(
        command_exists=lambda _name: True,
        local_available=lambda: True,
        run_command=slow_command,
        command_env=lambda: {},
        monotonic=lambda: clock[0],
        wall_clock=lambda: f"snapshot-{refresh_count[0]}",
    )
    assert started.wait(0.5)
    before = time.monotonic()
    assert provider.sample_values(0.0) == {}
    assert time.monotonic() - before < 0.1
    provider.request_refresh(0.0)
    assert maximum_in_flight[0] == 1
    release.set()
    first = _wait_for_snapshot(provider)
    assert first.access_mode == "direct"
    assert commands[0][-2:] == ("sdr", "elist")
    assert sum(command[-1:] == ("sensor",) for command in commands) == 1
    first_values = provider.sample_values(0.0)
    assert first_values["bmc_temp_cpu_c"] == 42.0
    assert first_values["bmc_cur_psu1_iout_a"] == 0.0
    assert first_values["bmc_pump1_rpm"] == 0.0
    assert "bmc_psu1_temp_c" in first_values and first_values["bmc_psu1_temp_c"] is None
    # Human-facing wall time does not participate in cadence or staleness.
    provider._wall_clock = lambda: "wall-clock-jumped-backward"
    assert provider.latest_snapshot(179.0) is first

    clock[0] = 61.0
    provider.request_refresh(61.0)
    deadline = time.monotonic() + 1.0
    while refresh_count[0] < 2 and time.monotonic() < deadline:
        time.sleep(0.005)
    second = _wait_for_snapshot(provider)
    second_values = provider.sample_values(61.0)
    assert second_values["bmc_temp_cpu_c"] == 43.0
    assert second_values["bmc_temp_ddr5_a1_c"] is None
    assert {source["key"] for source in provider.source_catalog()} == set(first_values)
    assert sum(command[-1:] == ("sensor",) for command in commands) == 1
    assert maximum_in_flight[0] == 1
    clock[0] = 122.0
    provider.request_refresh(122.0)
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        provider.poll(122.0)
        if provider._future is None:
            break
        time.sleep(0.005)
    assert provider.latest_snapshot(122.0) is second
    assert provider.sample_values(122.0)["bmc_temp_cpu_c"] == 43.0
    clock[0] = 242.0
    stale_values = provider.sample_values(242.0)
    assert stale_values and all(value is None for value in stale_values.values())
    provider_status = provider.status_evidence()
    assert provider_status["transitions"] == []
    assert any(item["raw_label"] == "PSU1 Status" for item in provider_status["end"]["sensors"])
    provider.close()
    assert provider._executor is None

    # Unsupported preferred elist falls back once to elist-full; total failure never
    # publishes an empty replacement snapshot.
    fallback_commands: list[tuple[str, ...]] = []

    def fallback_command(command, _timeout, _environment):
        command_tuple = tuple(command)
        fallback_commands.append(command_tuple)
        if command_tuple[-2:] == ("sdr", "elist"):
            return BmcCommandResult(command_tuple, 1, stderr="Invalid command")
        if command_tuple[-3:] == ("sdr", "elist", "full"):
            return BmcCommandResult(command_tuple, 0, SDR_TEXT)
        return BmcCommandResult(command_tuple, 0, SENSOR_TEXT)

    fallback_provider = BmcSnapshotProvider(
        command_exists=lambda _name: True,
        local_available=lambda: True,
        run_command=fallback_command,
        command_env=lambda: {},
    )
    fallback_snapshot = _wait_for_snapshot(fallback_provider)
    assert fallback_snapshot.command == "ipmitool sdr elist full"
    assert fallback_commands[0][-2:] == ("sdr", "elist")
    assert fallback_commands[1][-3:] == ("sdr", "elist", "full")
    fallback_provider.close()

    # Static threshold failure cannot invalidate a usable recurring SDR snapshot.
    def no_threshold_command(command, _timeout, _environment):
        command_tuple = tuple(command)
        if command_tuple[-2:] == ("sdr", "elist"):
            return BmcCommandResult(command_tuple, 0, SDR_TEXT)
        return BmcCommandResult(command_tuple, 1, stderr="threshold command unavailable")

    no_threshold_provider = BmcSnapshotProvider(
        command_exists=lambda _name: True,
        local_available=lambda: True,
        run_command=no_threshold_command,
        command_env=lambda: {},
    )
    no_threshold_snapshot = _wait_for_snapshot(no_threshold_provider)
    assert any(sensor.normalized_value is not None for sensor in no_threshold_snapshot.sensors)
    assert all(not sensor.thresholds for sensor in no_threshold_snapshot.sensors)
    no_threshold_provider.close()

    failed_calls: list[tuple[str, ...]] = []

    def failed_command(command, _timeout, _environment):
        failed_calls.append(tuple(command))
        return BmcCommandResult(tuple(command), 1, stderr="BMC busy")

    failed_provider = BmcSnapshotProvider(
        command_exists=lambda _name: True,
        local_available=lambda: True,
        run_command=failed_command,
        command_env=lambda: {},
    )
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        failed_provider.poll()
        if failed_provider._future is None:
            break
        time.sleep(0.005)
    assert failed_provider.latest_snapshot() is None
    assert failed_provider.source_catalog() == []
    failed_provider.close()

    # Permission fallback is attempted once, then the successful sudo mode is remembered.
    access_commands: list[tuple[str, ...]] = []
    old_geteuid = bmc_module.os.geteuid
    old_which = bmc_module.shutil.which
    bmc_module.os.geteuid = lambda: 1000
    bmc_module.shutil.which = lambda name: f"/usr/bin/{name}"
    try:
        def access_command(command, _timeout, _environment):
            command_tuple = tuple(command)
            access_commands.append(command_tuple)
            if command_tuple[0] == "ipmitool":
                return BmcCommandResult(command_tuple, 1, stderr="Permission denied")
            return BmcCommandResult(command_tuple, 0, SENSOR_TEXT if command_tuple[-1] == "sensor" else SDR_TEXT)

        access_provider = BmcSnapshotProvider(
            command_exists=lambda _name: True,
            local_available=lambda: True,
            privileged_helper_enabled=True,
            run_command=access_command,
            command_env=lambda: {},
            refresh_interval_seconds=0,
        )
        access_snapshot = _wait_for_snapshot(access_provider)
        assert access_snapshot.access_mode == "sudo"
        direct_attempts = sum(command[0] == "ipmitool" for command in access_commands)
        access_provider.request_refresh()
        _wait_for_snapshot(access_provider)
        assert sum(command[0] == "ipmitool" for command in access_commands) == direct_attempts == 1
        assert all("-n" in command for command in access_commands if command[0] == "sudo")
        access_provider.close()

        denied_commands: list[tuple[str, ...]] = []

        def denied_command(command, _timeout, _environment):
            denied_commands.append(tuple(command))
            return BmcCommandResult(tuple(command), 1, stderr="Permission denied")

        denied_provider = BmcSnapshotProvider(
            command_exists=lambda _name: True,
            local_available=lambda: True,
            privileged_helper_enabled=True,
            run_command=denied_command,
            command_env=lambda: {},
            refresh_interval_seconds=0,
        )
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            denied_provider.poll()
            if denied_provider._future is None:
                break
            time.sleep(0.005)
        assert [command[0] for command in denied_commands] == ["ipmitool", "sudo"]
        denied_provider.request_refresh()
        time.sleep(0.01)
        assert len(denied_commands) == 2
        denied_provider.close()
    finally:
        bmc_module.os.geteuid = old_geteuid
        bmc_module.shutil.which = old_which

    no_bmc_commands: list[tuple[str, ...]] = []
    unavailable = BmcSnapshotProvider(
        command_exists=lambda _name: False,
        local_available=lambda: False,
        run_command=lambda command, _timeout, _environment: no_bmc_commands.append(tuple(command)),
    )
    assert not unavailable.available
    assert unavailable.sample_values() == {}
    assert unavailable.status_evidence() == {}
    unavailable.close()
    assert no_bmc_commands == []

    # Closing a very short run waits only for its active bounded worker and
    # leaves no executor thread or post-close publication behind.
    close_started = threading.Event()
    close_release = threading.Event()
    closing_commands: list[tuple[str, ...]] = []

    def closing_command(command, _timeout, _environment):
        closing_commands.append(tuple(command))
        close_started.set()
        close_release.wait(1.0)
        return BmcCommandResult(tuple(command), 0, SDR_TEXT)

    closing_provider = BmcSnapshotProvider(
        command_exists=lambda _name: True,
        local_available=lambda: True,
        run_command=closing_command,
        command_env=lambda: {},
    )
    assert close_started.wait(0.5)
    closer = threading.Thread(target=closing_provider.close)
    closer.start()
    time.sleep(0.02)
    assert closer.is_alive()
    close_release.set()
    closer.join(1.0)
    assert not closer.is_alive()
    assert closing_provider._executor is None
    assert closing_provider.latest_snapshot() is None
    assert closing_provider.source_catalog() == []
    assert not closing_provider._thresholds
    assert len(closing_commands) == 1

    # An asynchronous BMC DIMM catalog can create the legacy alias without a
    # synchronous temperature-only command. Other BMC memory metrics remain.
    snapshot = BmcSnapshot("ipmi_bmc", "ipmitool sdr elist full", "direct", "now", 1.0, "ok", parsed)

    class FinishedProvider:
        current_values = {
            source["key"]: by_label[source["label"]].normalized_value for source in catalog
        }

        def poll(self, _now=None):
            return snapshot

        def source_catalog(self):
            return [dict(item) for item in catalog]

        def sample_values(self, _now=None):
            return dict(self.current_values)

    collector = object.__new__(TelemetryCollector)
    collector._bmc_provider = FinishedProvider()
    collector._memory_temp_sources = []
    collector._direct_memory_temp_sources_present = False
    collector._bmc_memory_aliases_initialized = False
    collector._bmc_memory_aliases = {}
    alias_values = collector._read_bmc_values(1.0)
    assert alias_values["memory_module_0_temp_c"] == 29.0
    assert alias_values["memory_module_1_temp_c"] == 29.0
    assert "bmc_temp_ddr5_a1_c" not in alias_values
    assert alias_values["bmc_power_ddr5_a1_w"] == 1.7
    assert alias_values["bmc_memory_power_w"] == 8.0
    alias_source_map = build_telemetry_source_map(
        cpu_temp_source=None,
        cpu_package_temp_sources=[],
        cpu_power_source=None,
        cpu_clock_source=None,
        cpu_core_clock_sources=[],
        memory_temp_sources=collector._memory_temp_sources,
        storage_temp_sources=[],
        gpu_sources=[],
        gpu_cards=[],
        bmc_sources=[
            source for source in catalog if source["key"] not in collector._bmc_memory_aliases
        ],
    )
    assert alias_source_map["fields"]["memory_module_0_temp_c"]["provider"] == "ipmi_bmc"
    assert alias_source_map["fields"]["memory_module_1_temp_c"]["provider"] == "ipmi_bmc"
    assert "bmc_temp_ddr5_a1_c" not in alias_source_map["fields"]
    FinishedProvider.current_values = {
        key: (None if key in collector._bmc_memory_aliases else value)
        for key, value in FinishedProvider.current_values.items()
    }
    disappeared_alias_values = collector._read_bmc_values(2.0)
    assert disappeared_alias_values["memory_module_0_temp_c"] is None
    assert disappeared_alias_values["memory_module_1_temp_c"] is None
    assert sorted(collector._bmc_memory_aliases.values()) == [
        "memory_module_0_temp_c",
        "memory_module_1_temp_c",
    ]
    FinishedProvider.current_values = {
        source["key"]: by_label[source["label"]].normalized_value for source in catalog
    }

    direct_collector = object.__new__(TelemetryCollector)
    direct_collector._bmc_provider = FinishedProvider()
    direct_collector._memory_temp_sources = [{"key": "memory_module_0_temp_c", "kind": "memory_temp"}]
    direct_collector._direct_memory_temp_sources_present = True
    direct_collector._bmc_memory_aliases_initialized = False
    direct_collector._bmc_memory_aliases = {}
    direct_values = direct_collector._read_bmc_values(1.0)
    assert direct_values["bmc_temp_ddr5_a1_c"] == 29.0
    assert direct_collector._memory_temp_sources == [{"key": "memory_module_0_temp_c", "kind": "memory_temp"}]

    direct_collector.samples = [Sample(0.0, {})]
    direct_collector.finalize_sources()
    assert "bmc_temp_cpu_c" in direct_collector.samples[0].values
    assert direct_collector.samples[0].values["bmc_temp_cpu_c"] is None

    with TemporaryDirectory(dir="/tmp") as temporary:
        root = Path(temporary)
        evidence_collector = HardwareEvidenceCollector(
            cpu_root=root / "cpu",
            hwmon_root=root / "hwmon",
            thermal_root=root / "thermal",
            drm_root=root / "drm",
            devfreq_root=root / "devfreq",
            bmc_snapshot=snapshot,
        )
        evidence_collector._storage = lambda: []
        evidence = evidence_collector.collect()
        assert len(evidence["bmc_sensors"]) == len(parsed)
        thermal = {item["label"]: item for item in evidence["bmc_thermal_sensors"]}
        assert thermal["TEMP_CPU"]["upper_critical_c"] == 95.0
        assert not any("upper_critical_c" in item for item in evidence["bmc_sensors"] if item["metric_class"] != "temperature")

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
            bmc_sources=[
                {
                    **source,
                    "command": snapshot.command,
                    "access_mode": "direct",
                    "last_successful_snapshot_at": "now",
                }
                for source in catalog
            ],
        )
        cpu_record = source_map["fields"]["bmc_temp_cpu_c"]
        assert source_map["contract_version"] == 1
        assert cpu_record["provider"] == "ipmi_bmc"
        assert cpu_record["sensor_number"] == "2a"
        assert cpu_record["entity_id"] == 65
        assert cpu_record["entity_instance"] == 1
        assert cpu_record["sampling_mode"] == "latest_completed_snapshot"
        assert cpu_record["native_refresh_interval_seconds"] == 60.0
        assert cpu_record["stale_after_seconds"] == 180.0
        assert cpu_record["thresholds"]["upper_critical"] == 95.0
        assert "upper_critical" not in source_map["fields"]

        csv_path = root / "raw.csv"
        write_telemetry_csv(
            [
                Sample(1.0, {}),
                Sample(2.0, {"bmc_temp_cpu_c": 42.0}),
                Sample(3.0, {"bmc_temp_cpu_c": 42.0}),
                Sample(181.0, {"bmc_temp_cpu_c": None}),
            ],
            csv_path,
        )
        with csv_path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        assert rows[0]["bmc_temp_cpu_c"] == ""
        assert rows[1]["bmc_temp_cpu_c"] == rows[2]["bmc_temp_cpu_c"] == "42.0"
        assert rows[3]["bmc_temp_cpu_c"] == ""
        assert "PSU1 Status" not in rows[1]
        assert "bmc_temp_cpu_c" not in extended_telemetry_metric_field_names(
            [Sample(2.0, {"bmc_temp_cpu_c": 42.0})]
        )

    # Exercise the actual final artifact writer after asynchronous discovery:
    # early rows are backfilled blank, late values persist, and both source-map
    # and normalized evidence consume the same provider snapshot.
    artifact_release = threading.Event()
    artifact_started = threading.Event()
    artifact_commands: list[tuple[str, ...]] = []
    artifact_clock = [0.0]
    artifact_refresh_count = [0]

    def artifact_command(command, _timeout, _environment):
        command_tuple = tuple(command)
        artifact_commands.append(command_tuple)
        if command_tuple[-2:] == ("sdr", "elist"):
            artifact_refresh_count[0] += 1
            if artifact_refresh_count[0] == 1:
                artifact_started.set()
                artifact_release.wait(1.0)
            state = "State Deasserted" if artifact_refresh_count[0] == 1 else "State Asserted"
            return BmcCommandResult(
                command_tuple,
                0,
                f"{SDR_TEXT}\nPSU Failure | 80h | ok | 10.1 | {state}",
            )
        if command_tuple[-1:] == ("sensor",):
            return BmcCommandResult(command_tuple, 0, SENSOR_TEXT)
        return BmcCommandResult(command_tuple, 1, stderr="unsupported")

    artifact_provider = BmcSnapshotProvider(
        command_exists=lambda _name: True,
        local_available=lambda: True,
        run_command=artifact_command,
        command_env=lambda: {},
        monotonic=lambda: artifact_clock[0],
        wall_clock=lambda: f"snapshot-{artifact_refresh_count[0]}",
    )
    assert artifact_started.wait(0.5)
    artifact_collector = TelemetryCollector(enable_bmc_provider=False)
    artifact_collector._bmc_provider.close()
    artifact_collector._bmc_provider = artifact_provider
    artifact_collector.samples = [Sample(0.0, {})]
    artifact_release.set()
    _wait_for_snapshot(artifact_provider)
    artifact_collector.samples.append(Sample(1.0, artifact_collector._read_bmc_values(1.0)))
    early_evidence = artifact_collector.normalized_hardware_evidence()
    assert early_evidence["bmc_status"]["end"]["captured_at"] == "snapshot-1"
    for expected_count, sample_time in ((2, 61.0), (3, 122.0)):
        artifact_clock[0] = sample_time
        artifact_provider.request_refresh(sample_time)
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            artifact_provider.poll(sample_time)
            status = artifact_provider.status_evidence()
            if status.get("end", {}).get("captured_at") == f"snapshot-{expected_count}":
                break
            time.sleep(0.005)
        else:
            raise AssertionError("BMC status refresh did not complete")
        artifact_collector.samples.append(
            Sample(sample_time, artifact_collector._read_bmc_values(sample_time))
        )
    # Finalization may harvest completed work but must not schedule a fourth
    # command merely because another refresh is due.
    artifact_clock[0] = 200.0

    class ArtifactParser:
        def summarize(self, *_args):
            return {}

    class ArtifactExporter:
        def build(self, *_args):
            return {"Result": "Finished"}

    class ArtifactSummary:
        def build(self, _payload):
            return "Result: Finished\n"

    try:
        with TemporaryDirectory(dir="/tmp") as temporary:
            run_dir = Path(temporary)
            artifact_result = write_final_run_artifacts(
                run_dir=run_dir,
                manifest_payload={"profile_name": "BMC fixture"},
                app_name="LVS",
                app_version="test",
                profile=ValidationProfile(profile_name="BMC fixture"),
                metadata=ValidationProfile(profile_name="BMC fixture"),
                started_iso="2026-01-01T00:00:00+00:00",
                ended_iso="2026-01-01T00:00:01+00:00",
                total_elapsed=1.0,
                system_info={"Hardware": {"Gpu": [], "Cpu": {}}},
                telemetry=artifact_collector,
                stage_windows=[],
                executed_plan=[],
                recovery_report={},
                skipped_stages=[],
                run_aborted=False,
                keep_raw_telemetry=True,
                export_compatibility_json=False,
                export_extended_json=True,
                segment_parser=ArtifactParser(),
                exporter=ArtifactExporter(),
                summary_exporter=ArtifactSummary(),
                stage_sensor_events=lambda _window: [],
                stage_faults=lambda _window: [],
                capture_run_end=lambda **_kwargs: None,
            )
            with (run_dir / "raw_telemetry.csv").open(newline="", encoding="utf-8") as handle:
                persisted_rows = list(csv.DictReader(handle))
            persisted_map = JsonStore.read(run_dir / "telemetry_source_map.json", {})
            persisted_extended = JsonStore.read(run_dir / "parsed_results_extended.json", {})
            persisted_manifest = JsonStore.read(run_dir / "run_manifest.json", {})
            assert persisted_rows[0]["bmc_temp_cpu_c"] == ""
            assert persisted_rows[1]["bmc_temp_cpu_c"] == "42.0"
            assert "PSU Failure" not in persisted_rows[1]
            assert not any(key.startswith("bmc_psu_failure") for key in persisted_rows[1])
            assert persisted_map["fields"]["bmc_temp_cpu_c"]["provider"] == "ipmi_bmc"
            persisted_evidence = persisted_extended["normalized_hardware_evidence"]
            assert any(item["raw_label"] == "TEMP_CPU" for item in persisted_evidence["bmc_sensors"])
            assert any(item["label"] == "TEMP_CPU" for item in persisted_evidence["bmc_thermal_sensors"])
            status = persisted_evidence["bmc_status"]
            start_states = {item["raw_label"]: item for item in status["start"]["sensors"]}
            end_states = {item["raw_label"]: item for item in status["end"]["sensors"]}
            assert start_states["PSU Failure"]["raw_state"] == "State Deasserted"
            assert end_states["PSU Failure"]["raw_state"] == "State Asserted"
            psu_transitions = [
                item for item in status["transitions"] if item["raw_label"] == "PSU Failure"
            ]
            assert len(psu_transitions) == 1
            assert psu_transitions[0]["previous_normalized_state"] == "deasserted"
            assert psu_transitions[0]["current_normalized_state"] == "asserted"
            assert psu_transitions[0]["previous_observed_at"] == "snapshot-1"
            assert psu_transitions[0]["observed_at"] == "snapshot-2"
            assert psu_transitions[0]["observation_semantics"] == "state_change_observed_by_snapshot"
            assert persisted_manifest["events"] == []
            assert artifact_result.all_events == []
            assert sum(command[-2:] == ("sdr", "elist") for command in artifact_commands) == 3
            assert sum(command[-1:] == ("sensor",) for command in artifact_commands) == 1
    finally:
        artifact_collector.close()


if __name__ == "__main__":
    run_bmc_telemetry_provider_checks()
    print("BMC telemetry provider checks passed")
