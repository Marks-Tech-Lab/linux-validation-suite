#!/usr/bin/env python3
"""Focused provider regressions derived from the accepted probe corpus."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Modules.lvs_hardware_evidence import (
    HardwareEvidenceCollector,
    _temperature_c,
    discover_cpu_frequency,
    discover_cpu_thermals,
    discover_thermal_zones,
    format_hardware_evidence_summary,
    parse_dpm_levels,
    parse_ipmi_temperature_thresholds,
    parse_nvidia_query_csv,
    parse_nvidia_temperature_limits,
    parse_nvme_id_ctrl,
)


FIXTURE = json.loads((ROOT / "smoke_tests" / "fixtures" / "clock_thermal_provider_evidence_trimmed.json").read_text(encoding="utf-8"))


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(value), encoding="utf-8")


def run_clock_thermal_provider_checks() -> None:
    dpm = parse_dpm_levels(FIXTURE["amd_dpm"]["core"])
    assert dpm["active_frequency_level"] == 1
    assert dpm["available_frequency_levels_mhz"] == [500.0, 1200.0, 2491.0]
    assert dpm["available_frequency_levels_mhz"][dpm["active_frequency_level"]] != 2491.0

    absolute = parse_nvidia_temperature_limits(FIXTURE["nvidia_absolute"])["0000:01:00.0"]
    assert absolute["temperature_target_c"] == 83.0
    assert absolute["temperature_max_operating_c"] == 93.0
    assert absolute["temperature_shutdown_c"] == 90.0

    relative = parse_nvidia_temperature_limits(FIXTURE["nvidia_relative"])["0000:02:00.0"]
    assert relative["temperature_limit_margin_c"]["gpu_shutdown_t_limit_temp_specification"] == -5.0
    assert relative["temperature_limit_margin_c"]["gpu_slowdown_t_limit_temp_specification"] == -2.0
    assert relative["temperature_limit_margin_c"]["gpu_max_operating_t_limit_temp_specification"] == 0.0
    assert relative["derived_absolute_temperature_limits"]["gpu_shutdown_t_limit_temp_specification"]["temperature_c"] == 93.0
    assert relative["derived_absolute_temperature_limits"]["gpu_max_operating_t_limit_temp_specification"]["temperature_c"] == 88.0
    assert relative["derived_absolute_temperature_limits"]["gpu_shutdown_t_limit_temp_specification"]["confidence"] == "medium"
    assert relative["temperature_limit_margin_evidence"][0]["label"] == "GPU Shutdown T.Limit Temp Specification"

    nvidia_rows = parse_nvidia_query_csv(FIXTURE["nvidia_query"])
    assert len(nvidia_rows) == 2
    assert nvidia_rows[0]["maximum_frequency_semantics"] == "driver_max"
    assert nvidia_rows[1]["core_current_frequency_mhz"] == 0.0
    assert {row["pci_bus_id"] for row in nvidia_rows} == {"0000:01:00.0", "0000:02:00.0"}

    nvme = parse_nvme_id_ctrl(FIXTURE["nvme_kelvin"])
    assert nvme["storage_warning_temperature_c"] == 69.85
    assert nvme["storage_critical_temperature_c"] == 79.85
    assert "thermal_management_min_temperature_c" not in nvme
    assert "thermal_management_max_temperature_c" not in nvme
    managed = parse_nvme_id_ctrl(FIXTURE["nvme_management"])
    assert managed["thermal_management_min_temperature_c"] == -0.15
    assert managed["thermal_management_max_temperature_c"] == 84.85
    assert _temperature_c(FIXTURE["thermal_invalid"]["absolute_zero_mc"]) is None
    assert _temperature_c(FIXTURE["thermal_invalid"]["probe_sentinel_mc"]) is None
    assert _temperature_c(FIXTURE["thermal_invalid"]["gigantic_mc"]) is None

    bmc = parse_ipmi_temperature_thresholds(FIXTURE["ipmi"])
    assert [item["component_class"] for item in bmc] == ["cpu", "memory_module", "psu"]
    assert bmc[0]["upper_noncritical_c"] == 80.0
    assert bmc[0]["upper_critical_c"] == 90.0
    assert bmc[0]["upper_nonrecoverable_c"] == 100.0
    assert "tjmax" not in json.dumps(bmc).lower()

    with tempfile.TemporaryDirectory() as oryon_temp:
        oryon_root = Path(oryon_temp)
        assert discover_cpu_frequency(oryon_root / "cpu")["policies"] == []
        oryon_zone = oryon_root / "thermal" / "thermal_zone0"
        _write(oryon_zone / "type", "cpuss0-thermal")
        _write(oryon_zone / "temp", "47000")
        _write(oryon_zone / "trip_point_0_type", "critical")
        _write(oryon_zone / "trip_point_0_temp", "110000")
        oryon_thermal = discover_cpu_thermals(oryon_root / "hwmon", oryon_root / "thermal")
        assert oryon_thermal["sensors"] == []
        assert oryon_thermal["platform_thermal_zones"][0]["trip_points"][0]["temperature_c"] == 110.0
        assert "cpu_tjmax_c" not in oryon_thermal

    # Two accepted hybrid signatures exercise authoritative CPUID P/E grouping
    # and CPPC-based favored-policy labeling. No product lookup occurs in the
    # production normalizer.
    for signature_name, signature in FIXTURE["hybrid_policy_signatures"].items():
        with tempfile.TemporaryDirectory() as hybrid_temp:
            hybrid_cpu = Path(hybrid_temp) / "cpu"
            policies = (
                (0, "0", "P", signature["favored_capability"], signature["p_base_khz"], signature["p_max_khz"]),
                (1, "1", "P", signature["p_capability"], signature["p_base_khz"], signature["p_max_khz"] - 200000),
                (2, "2-3", "E", 180, signature["e_base_khz"], signature["e_max_khz"]),
            )
            hybrid_topology = {}
            for policy_id, affected, core_type, capability, base, maximum in policies:
                policy_dir = hybrid_cpu / "cpufreq" / f"policy{policy_id}"
                for field, value in {
                    "affected_cpus": affected, "scaling_driver": "intel_pstate", "cpuinfo_avg_freq": base,
                    "cpuinfo_min_freq": 800000, "cpuinfo_max_freq": maximum,
                    "scaling_min_freq": 800000, "scaling_max_freq": maximum, "base_frequency": base,
                }.items():
                    _write(policy_dir / field, value)
                for cpu in ([0] if policy_id == 0 else ([1] if policy_id == 1 else [2, 3])):
                    hybrid_topology[cpu] = {
                        "core_type": core_type,
                        "classification_source": "intel_cpuid_1a_pinned",
                        "cppc_highest_perf": capability,
                    }
            hybrid = discover_cpu_frequency(hybrid_cpu, cpu_core_topology=hybrid_topology)
            assert len(hybrid["policies"]) == 3, signature_name
            assert {item["core_type"] for item in hybrid["policies"]} == {"P", "E"}, signature_name
            favored = next(item for item in hybrid["policies"] if item.get("higher_capability_policy"))
            assert favored["core_class"].startswith("favored P core"), signature_name
            assert next(item for item in hybrid["policies"] if item["core_type"] == "E")["base_frequency_mhz"] == signature["e_base_khz"] / 1000

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        cpu_root = root / "cpu"
        hwmon_root = root / "hwmon"
        thermal_root = root / "thermal"
        drm_root = root / "drm"
        devfreq_root = root / "devfreq"

        intel_policy = cpu_root / "cpufreq" / "policy0"
        for name, value in {
            "affected_cpus": "0-1", "scaling_driver": "intel_pstate", "cpuinfo_avg_freq": "4199000",
            "scaling_cur_freq": "4000000", "cpuinfo_min_freq": "800000", "cpuinfo_max_freq": "5500000",
            "scaling_min_freq": "800000", "scaling_max_freq": "5300000", "base_frequency": "3700000",
        }.items():
            _write(intel_policy / name, value)
        _write(cpu_root / "intel_pstate" / "no_turbo", "0")
        topology = {
            0: {"core_type": "P", "classification_source": "intel_cpuid_1a_pinned"},
            1: {"core_type": "P", "classification_source": "intel_cpuid_1a_pinned"},
        }
        frequency = discover_cpu_frequency(cpu_root, cpu_core_topology=topology)
        policy = frequency["policies"][0]
        assert policy["current_frequency_mhz"] == 4199.0
        assert policy["base_frequency_mhz"] == 3700.0
        assert policy["hardware_max_frequency_mhz"] == 5500.0
        assert policy["policy_max_frequency_mhz"] == 5300.0
        assert policy["boost_enabled"] is True
        assert "advertised_boost_frequency_mhz" not in json.dumps(frequency)

        amd_policy = cpu_root / "cpufreq" / "policy2"
        for name, value in {
            "affected_cpus": "2-3", "scaling_driver": "amd-pstate-epp", "scaling_cur_freq": "3650000",
            "cpuinfo_min_freq": "400000", "cpuinfo_max_freq": "5700000", "scaling_min_freq": "400000",
            "scaling_max_freq": "5700000",
        }.items():
            _write(amd_policy / name, value)
        frequency = discover_cpu_frequency(cpu_root)
        amd = next(item for item in frequency["policies"] if item["policy_id"] == "policy2")
        assert "base_frequency_mhz" not in amd
        assert amd["current_frequency_mhz"] == 3650.0

        coretemp = hwmon_root / "hwmon0"
        _write(coretemp / "name", "coretemp")
        for name, value in {"temp1_label": "Package id 0", "temp1_input": "48000", "temp1_max": "95000", "temp1_crit": "100000"}.items():
            _write(coretemp / name, value)
        k10 = hwmon_root / "hwmon1"
        _write(k10 / "name", "k10temp")
        for name, value in {"temp1_label": "Tctl", "temp1_input": "52000", "temp1_crit": "115000"}.items():
            _write(k10 / name, value)
        cpu_thermal = discover_cpu_thermals(hwmon_root, thermal_root)
        assert cpu_thermal["cpu_tjmax_c"] == 100.0
        amd_sensor = next(item for item in cpu_thermal["sensors"] if item["provider"] == "k10temp")
        assert "temperature_crit_c" not in amd_sensor
        _write(coretemp / "temp2_label", "Core 0")
        _write(coretemp / "temp2_input", "49000")
        _write(coretemp / "temp2_max", "100000")
        _write(coretemp / "temp2_crit", "105000")
        assert any(
            item.get("temperature_crit_c") == 105.0
            for item in discover_cpu_thermals(hwmon_root, thermal_root)["sensors"]
        )

        zone = thermal_root / "thermal_zone0"
        _write(zone / "type", "cpu-thermal")
        _write(zone / "temp", "45000")
        _write(zone / "trip_point_0_type", "critical")
        _write(zone / "trip_point_0_temp", FIXTURE["thermal_invalid"]["acpi_low_critical_mc"])
        _write(zone / "trip_point_1_type", "hot")
        _write(zone / "trip_point_1_temp", "95000")
        mem_zone = thermal_root / "thermal_zone1"
        _write(mem_zone / "type", "mem-thermal")
        _write(mem_zone / "temp", "43000")
        _write(mem_zone / "trip_point_0_type", "critical")
        _write(mem_zone / "trip_point_0_temp", "105000")
        trips = discover_thermal_zones(thermal_root)[0]["trip_points"]
        assert "temperature_c" not in trips[0]
        assert trips[0]["confidence"] == "do_not_normalize"
        assert trips[1]["temperature_c"] == 95.0

        spd = hwmon_root / "hwmon2"
        _write(spd / "name", "spd5118")
        for name, value in {"temp1_input": "41000", "temp1_max": "55000", "temp1_crit": "85000", "temp1_crit_alarm": "0"}.items():
            _write(spd / name, value)
        jc = hwmon_root / "hwmon3"
        _write(jc / "name", "jc42")
        for name, value in {"temp1_input": "39000", "temp1_max": "0", "temp1_crit": "0", "temp1_crit_alarm": "1"}.items():
            _write(jc / name, value)
        board = hwmon_root / "hwmon4"
        _write(board / "name", "gigabyte_wmi")
        _write(board / "temp1_input", "35000")
        nct = hwmon_root / "hwmon5"
        _write(nct / "name", "nct6687")
        for name, value in {"temp1_label": "VRM MOS", "temp1_input": "44000", "temp1_max": "90000"}.items():
            _write(nct / name, value)
        asus = hwmon_root / "hwmon6"
        _write(asus / "name", "asus_wmi_sensors")
        for name, value in {"temp1_label": "T_Sensor", "temp1_input": "-63000"}.items():
            _write(asus / name, value)

        amd_device = drm_root / "card0" / "device"
        _write(amd_device / "pp_dpm_sclk", FIXTURE["amd_dpm"]["core"])
        _write(amd_device / "pp_dpm_mclk", FIXTURE["amd_dpm"]["memory"])
        amd_hwmon = amd_device / "hwmon" / "hwmon0"
        _write(amd_hwmon / "name", "amdgpu")
        for name, value in {
            "temp1_label": "edge", "temp1_input": "51000",
            "freq1_label": "sclk", "freq1_input": "1000000000",
        }.items():
            _write(amd_hwmon / name, value)

        intel_gt = drm_root / "card1" / "gt" / "gt0"
        for name, value in {
            "rps_cur_freq_mhz": "0", "rps_act_freq_mhz": "0", "rps_min_freq_mhz": "300",
            "rps_max_freq_mhz": "1200", "rps_RP0_freq_mhz": "1250",
            "rps_RP1_freq_mhz": "800", "rps_RPn_freq_mhz": "300", "rps_boost_freq_mhz": "1300",
        }.items():
            _write(intel_gt / name, value)
        _write(intel_gt / ".defaults" / "rps_RP0_freq_mhz", "16777215")

        adreno = devfreq_root / "3d00000.gpu"
        for name, value in {
            "cur_freq": "490000000", "min_freq": "220000000", "max_freq": "903000000",
            "available_frequencies": "220000000 490000000 680000000 903000000", "governor": "msm-adreno-tz",
            "device/uevent": "DRIVER=adreno\nOF_NAME=gpu",
        }.items():
            _write(adreno / name, value)

        gpuss_zone = thermal_root / "thermal_zone2"
        _write(gpuss_zone / "type", "gpuss-thermal")
        _write(gpuss_zone / "temp", "50000")
        _write(gpuss_zone / "trip_point_0_type", "critical")
        _write(gpuss_zone / "trip_point_0_temp", "115000")

        nvme_target = root / "devices" / "nvme0" / "hwmon0"
        _write(nvme_target / "name", "nvme")
        for name, value in {
            "temp1_input": "42000", "temp1_max": "69850", "temp1_crit": "79850",
            "temp2_label": "Sensor 1", "temp2_input": "45000", "temp2_min": "-273150",
            "temp2_max": "65261850",
        }.items():
            _write(nvme_target / name, value)
        (hwmon_root / "hwmon7").symlink_to(nvme_target, target_is_directory=True)
        sata = hwmon_root / "hwmon8"
        _write(sata / "name", "drivetemp")
        _write(sata / "temp1_input", "33000")

        gpu_cards = [
            {"gpu_index": 0, "card": "card0", "slot": "0000:03:00.0", "driver": "amdgpu", "vendor": "AMD"},
            {"gpu_index": 1, "card": "card1", "slot": "0000:00:02.0", "driver": "i915", "vendor": "Intel"},
        ]
        collector = HardwareEvidenceCollector(
            cpu_core_topology=topology, gpu_cards=gpu_cards, cpu_root=cpu_root, hwmon_root=hwmon_root,
            thermal_root=thermal_root, drm_root=drm_root, devfreq_root=devfreq_root,
        )
        evidence = collector.collect()
        amd_gpu = next(item for item in evidence["gpus"] if item["provider"] == "amdgpu")
        assert amd_gpu["clock_domains"]["core"]["active_frequency_level"] == 1
        assert amd_gpu["clock_domains"]["core"]["maximum_frequency_semantics"] == "available_dpm_level_max"
        assert amd_gpu["core_current_frequency_mhz"] == 1000.0
        assert amd_gpu["core_current_frequency_mhz"] != amd_gpu["clock_domains"]["core"]["maximum_frequency_mhz"]
        assert amd_gpu["thermal_domains"][0]["domain"] == "edge"
        assert "temperature_crit_c" not in amd_gpu["thermal_domains"][0]
        intel_gpu = next(item for item in evidence["gpus"] if item["provider"] == "i915")
        assert intel_gpu["clock_domains"]["gt0"]["core_current_frequency_mhz"] == 0.0
        assert intel_gpu["clock_domains"]["gt0"]["maximum_frequency_semantics"] == "rp0"
        assert intel_gpu["clock_domains"]["gt0"]["maximum_frequency_mhz"] == 1250.0
        assert "16777215" not in json.dumps(intel_gpu)
        adreno_gpu = next(item for item in evidence["gpus"] if item["provider"] == "adreno_devfreq")
        assert adreno_gpu["configured_max_frequency_mhz"] == 903.0
        assert adreno_gpu["maximum_frequency_semantics"] == "available_frequency_max"
        assert adreno_gpu["available_frequency_levels_mhz"] == [220.0, 490.0, 680.0, 903.0]
        assert adreno_gpu["thermal_domains"][0]["thermal_domain_semantics"] == "gpu_subsystem_platform_zone"
        assert adreno_gpu["thermal_domains"][0]["association_confidence"] == "medium"

        assert len(evidence["storage_devices"]) == 1
        storage = evidence["storage_devices"][0]
        assert storage["storage_warning_temperature_c"] == 69.85
        assert storage["storage_critical_temperature_c"] == 79.85
        assert storage["additional_temperature_sensors"][0]["temperature_c"] == 45.0
        assert "temperature_max_c" not in storage["additional_temperature_sensors"][0]
        assert all(item["provider"] != "drivetemp" for item in evidence["storage_devices"])
        spd_record = next(item for item in evidence["memory_modules"] if item["provider"] == "spd5118")
        jc_record = next(item for item in evidence["memory_modules"] if item["provider"] == "jc42")
        assert (spd_record["temperature_max_c"], spd_record["temperature_crit_c"]) == (55.0, 85.0)
        assert "temperature_max_c" not in jc_record and jc_record["alarm_state"]["temp1_crit_alarm"] is True
        generic = next(item for item in evidence["board_sensors"] if item["provider"] == "gigabyte_wmi")
        assert generic["classification"] == "generic_channel" and generic["confidence"] == "low"
        vrm = next(item for item in evidence["board_sensors"] if item["provider"] == "nct6687")
        assert vrm["classification"] == "vrm_mos" and vrm["threshold_normalization"] == "do_not_normalize"
        assert not any(item["provider"] == "asus_wmi_sensors" for item in evidence["board_sensors"])
        assert len(evidence["soc_memory_zones"]) == 1
        assert evidence["soc_memory_zones"][0]["zone_type"] == "mem-thermal"
        assert evidence["soc_memory_zones"][0]["trip_points"][0]["temperature_c"] == 105.0
        assert evidence["soc_memory_zones"][0] not in evidence["memory_modules"]
        assert format_hardware_evidence_summary(evidence)


if __name__ == "__main__":
    run_clock_thermal_provider_checks()
    print("clock/thermal provider checks passed")
