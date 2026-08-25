#!/usr/bin/env python3
"""Provider-aware Linux clock and thermal-limit normalization.

This module deliberately keeps discovery evidence separate from the legacy
``SystemInfoCollector`` payload.  Every normalized value retains a provider and
raw source; unsupported concepts are omitted instead of guessed from device
names or unrelated limits.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

from .lvs_gpu_identity import normalize_pci_slot
from .lvs_platform_hwmon import (
    normalize_platform_temperature_c,
    platform_hwmon_classification,
    valid_platform_temperature,
)
from .lvs_telemetry_cpu import parse_cpu_list


ReadText = Callable[[Path], Optional[str]]
CommandEnv = Callable[[], Dict[str, str]]


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="ignore").strip()
    except Exception:
        return None


def _number(raw: Any) -> Optional[float]:
    text = str(raw or "").strip().replace(",", "")
    if not text or text.lower() in {"n/a", "na", "none", "unsupported", "[not supported]", "deprecated"}:
        return None
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _temperature_c(raw: Any, raw_units: str = "millidegrees_c") -> Optional[float]:
    if raw_units == "millidegrees_c":
        return normalize_platform_temperature_c(raw)
    value = _number(raw)
    if value is None:
        return None
    if raw_units == "kelvin":
        value -= 273.15
    # Below absolute zero is universally invalid. Other negative values require
    # provider-specific handling (notably NVIDIA relative T.Limit margins).
    if value <= -273.15 or value > 250.0:
        return None
    return round(value, 2)


def _frequency_mhz(raw: Any, raw_units: str) -> Optional[float]:
    value = _number(raw)
    if value is None or value < 0:
        return None
    if raw_units == "khz":
        value /= 1000.0
    elif raw_units == "hz":
        value /= 1_000_000.0
    if value > 100_000:
        return None
    return round(value, 2)


def _evidence(
    *,
    provider: str,
    source: str,
    raw_field: str,
    raw_value: Any,
    raw_units: str,
    normalized_value: Any,
    normalized_units: str,
    semantics: str,
    confidence: str = "high",
    derived: bool = False,
    derivation_inputs: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "provider": provider,
        "source": source,
        "raw_field": raw_field,
        "raw_value": raw_value,
        "raw_units": raw_units,
        "normalized_value": normalized_value,
        "normalized_units": normalized_units,
        "semantic_classification": semantics,
        "confidence": confidence,
        "derived": bool(derived),
    }
    if derivation_inputs:
        result["derivation_inputs"] = derivation_inputs
    return result


def _set_value(record: Dict[str, Any], field: str, value: Any, evidence: Dict[str, Any]) -> None:
    if value is None:
        return
    record[field] = value
    record.setdefault("evidence", {})[field] = evidence


def parse_cpu_frequency_policy(
    policy_dir: Path,
    read_text: ReadText = _read_text,
    cpu_core_topology: Optional[Dict[int, Dict[str, Any]]] = None,
    boost_state: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Normalize one cpufreq policy without conflating hardware and policy limits."""
    affected_text = read_text(policy_dir / "affected_cpus")
    if affected_text is None:
        affected_text = read_text(policy_dir / "related_cpus")
    affected = parse_cpu_list(affected_text or "")
    if not affected and not any(read_text(policy_dir / name) is not None for name in ("scaling_driver", "scaling_cur_freq")):
        return None
    record: Dict[str, Any] = {
        "policy_id": policy_dir.name,
        "source_path": str(policy_dir),
        "affected_logical_cpus": affected,
    }
    provider = read_text(policy_dir / "scaling_driver")
    if provider:
        record["frequency_provider"] = provider
    topology = cpu_core_topology or {}
    core_types = {str(topology[cpu].get("core_type") or "U") for cpu in affected if cpu in topology}
    classifications = {str(topology[cpu].get("classification_source") or "") for cpu in affected if cpu in topology}
    trustworthy_classification = bool(classifications) and classifications != {"homogeneous_fallback"}
    if len(core_types) == 1 and core_types <= {"P", "E"} and trustworthy_classification:
        record["core_type"] = next(iter(core_types))
        record["core_class"] = "P core" if record["core_type"] == "P" else "E core"
        record["core_classification_sources"] = sorted(item for item in classifications if item)
    capability_values = {
        int(topology[cpu]["cppc_highest_perf"])
        for cpu in affected
        if cpu in topology and isinstance(topology[cpu].get("cppc_highest_perf"), int)
    }
    if len(capability_values) == 1:
        record["performance_capability"] = next(iter(capability_values))
        record["performance_capability_provider"] = "acpi_cppc_highest_perf"

    specs = (
        ("current_frequency_mhz", "cpuinfo_avg_freq", "average_runtime_frequency"),
        ("current_frequency_mhz", "scaling_cur_freq", "runtime_frequency"),
        ("hardware_min_frequency_mhz", "cpuinfo_min_freq", "hardware_minimum"),
        ("hardware_max_frequency_mhz", "cpuinfo_max_freq", "hardware_maximum"),
        ("policy_min_frequency_mhz", "scaling_min_freq", "configured_policy_minimum"),
        ("policy_max_frequency_mhz", "scaling_max_freq", "configured_policy_maximum"),
        ("base_frequency_mhz", "base_frequency", "base_frequency"),
    )
    for field, raw_field, semantics in specs:
        if field in record:
            continue
        path = policy_dir / raw_field
        raw = read_text(path)
        value = _frequency_mhz(raw, "khz")
        if value is None:
            continue
        _set_value(
            record,
            field,
            value,
            _evidence(
                provider=provider or "linux_cpufreq",
                source=str(path),
                raw_field=raw_field,
                raw_value=raw,
                raw_units="khz",
                normalized_value=value,
                normalized_units="mhz",
                semantics=semantics,
                confidence="high" if raw_field != "scaling_cur_freq" else "medium",
            ),
        )
    if boost_state and isinstance(boost_state.get("boost_enabled"), bool):
        record["boost_enabled"] = boost_state["boost_enabled"]
        record.setdefault("evidence", {})["boost_enabled"] = dict(boost_state["evidence"])
    return record


def discover_cpu_frequency(
    cpu_root: Path = Path("/sys/devices/system/cpu"),
    read_text: ReadText = _read_text,
    cpu_core_topology: Optional[Dict[int, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    cpufreq_root = cpu_root / "cpufreq"
    boost_state: Optional[Dict[str, Any]] = None
    for path, invert, provider in (
        (cpufreq_root / "boost", False, "linux_cpufreq"),
        (cpu_root / "intel_pstate" / "no_turbo", True, "intel_pstate"),
    ):
        raw = read_text(path)
        if raw not in {"0", "1"}:
            continue
        enabled = (raw == "0") if invert else (raw == "1")
        boost_state = {
            "boost_enabled": enabled,
            "evidence": _evidence(
                provider=provider,
                source=str(path),
                raw_field=path.name,
                raw_value=raw,
                raw_units="boolean_state",
                normalized_value=enabled,
                normalized_units="boolean",
                semantics="boost_enabled_state",
            ),
        }
        break
    policies = [
        item
        for item in (
            parse_cpu_frequency_policy(path, read_text, cpu_core_topology, boost_state)
            for path in sorted(cpufreq_root.glob("policy*"))
        )
        if item is not None
    ]
    result: Dict[str, Any] = {"policies": policies}
    if not policies:
        cpuinfo = read_text(Path("/proc/cpuinfo")) if cpu_root == Path("/sys/devices/system/cpu") else None
        current_fallbacks: List[Dict[str, Any]] = []
        cpu_index: Optional[int] = None
        for line in str(cpuinfo or "").splitlines():
            if ":" not in line:
                continue
            key, raw = [part.strip() for part in line.split(":", 1)]
            if key in {"processor", "Processor"}:
                try:
                    cpu_index = int(raw)
                except ValueError:
                    cpu_index = None
            elif key.lower() == "cpu mhz" and cpu_index is not None:
                value = _frequency_mhz(raw, "mhz")
                if value is not None:
                    current_fallbacks.append({
                        "logical_cpu": cpu_index,
                        "current_frequency_mhz": value,
                        "confidence": "low",
                        "provider": "proc_cpuinfo",
                        "source": "/proc/cpuinfo",
                        "raw_field": "cpu MHz",
                    })
        if current_fallbacks:
            result["logical_cpu_current_frequency_fallbacks"] = current_fallbacks
    if boost_state:
        result["boost_enabled"] = boost_state["boost_enabled"]
        result["boost_evidence"] = boost_state["evidence"]
    if policies:
        p_capabilities = [
            int(item["performance_capability"])
            for item in policies
            if item.get("core_type") == "P" and isinstance(item.get("performance_capability"), int)
        ]
        if len(set(p_capabilities)) > 1:
            highest_capability = max(p_capabilities)
            for item in policies:
                if item.get("core_type") == "P" and item.get("performance_capability") == highest_capability:
                    item["higher_capability_policy"] = True
                    item["core_class"] = "favored P core / higher-capability P policy"
        result["policy_groups"] = group_cpu_frequency_policies(policies)
        maxima = [float(item["hardware_max_frequency_mhz"]) for item in policies if "hardware_max_frequency_mhz" in item]
        if maxima:
            result["highest_policy_hardware_max_frequency_mhz"] = max(maxima)
            result["highest_policy_hardware_max_frequency_semantics"] = "derived_highest_policy_hardware_maximum"
    return result


def group_cpu_frequency_policies(policies: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    fields = (
        "core_class",
        "base_frequency_mhz",
        "hardware_min_frequency_mhz",
        "hardware_max_frequency_mhz",
        "policy_min_frequency_mhz",
        "policy_max_frequency_mhz",
        "frequency_provider",
    )
    groups: Dict[tuple[Any, ...], Dict[str, Any]] = {}
    for policy in policies:
        key = tuple(policy.get(field) for field in fields)
        group = groups.setdefault(key, {field: policy[field] for field in fields if field in policy})
        group.setdefault("policy_ids", []).append(policy.get("policy_id"))
        group.setdefault("affected_logical_cpus", []).extend(policy.get("affected_logical_cpus") or [])
        if "current_frequency_mhz" in policy:
            group.setdefault("current_frequency_values_mhz", []).append(float(policy["current_frequency_mhz"]))
    results: List[Dict[str, Any]] = []
    for group in groups.values():
        currents = group.pop("current_frequency_values_mhz", [])
        group["policy_ids"] = sorted(group["policy_ids"])
        group["affected_logical_cpus"] = sorted(set(group["affected_logical_cpus"]))
        if currents:
            group["current_frequency_min_mhz"] = min(currents)
            group["current_frequency_max_mhz"] = max(currents)
        results.append(group)
    return results


def _thermal_value(
    record: Dict[str, Any], field: str, path: Path, read_text: ReadText, provider: str, semantics: str,
    confidence: str = "high",
) -> None:
    raw = read_text(path)
    value = _temperature_c(raw)
    if value is None:
        return
    _set_value(record, field, value, _evidence(
        provider=provider, source=str(path), raw_field=path.name, raw_value=raw,
        raw_units="millidegrees_c", normalized_value=value, normalized_units="c",
        semantics=semantics, confidence=confidence,
    ))


def discover_thermal_zones(
    thermal_root: Path = Path("/sys/class/thermal"),
    read_text: ReadText = _read_text,
) -> List[Dict[str, Any]]:
    zones: List[Dict[str, Any]] = []
    for zone in sorted(thermal_root.glob("thermal_zone*")):
        zone_type = read_text(zone / "type") or ""
        raw_temp = read_text(zone / "temp")
        current = _temperature_c(raw_temp)
        if current is None:
            continue
        record: Dict[str, Any] = {
            "zone_id": zone.name,
            "zone_type": zone_type,
            "provider": "linux_thermal_zone",
            "source_path": str(zone),
            "temperature_c": current,
            "trip_points": [],
            "evidence": {
                "temperature_c": _evidence(
                    provider="linux_thermal_zone", source=str(zone / "temp"), raw_field="temp",
                    raw_value=raw_temp, raw_units="millidegrees_c", normalized_value=current,
                    normalized_units="c", semantics="platform_zone_current", confidence="medium",
                )
            },
        }
        for trip_path in sorted(zone.glob("trip_point_*_temp")):
            match = re.match(r"trip_point_(\d+)_temp", trip_path.name)
            if not match:
                continue
            index = match.group(1)
            raw = read_text(trip_path)
            value = _temperature_c(raw)
            trip_type = (read_text(zone / f"trip_point_{index}_type") or "unknown").lower()
            # The corpus contained -274 C sentinels and ACPI critical trips near
            # 20.8 C. The latter remain raw evidence but are not normalized.
            valid = value is not None and not (trip_type == "critical" and value < 30.0)
            trip: Dict[str, Any] = {
                "trip_index": int(index), "trip_type": trip_type, "raw_value": raw,
                "raw_units": "millidegrees_c", "source": str(trip_path),
                "confidence": "medium" if valid else "do_not_normalize",
            }
            if valid:
                trip["temperature_c"] = value
            else:
                trip["validation_reason"] = "invalid_or_implausible_platform_trip"
            record["trip_points"].append(trip)
        zones.append(record)
    return zones


def discover_cpu_thermals(
    hwmon_root: Path = Path("/sys/class/hwmon"),
    thermal_root: Path = Path("/sys/class/thermal"),
    read_text: ReadText = _read_text,
) -> Dict[str, Any]:
    sensors: List[Dict[str, Any]] = []
    package_tjmax: List[float] = []
    for hwmon in sorted(hwmon_root.glob("hwmon*")):
        provider = (read_text(hwmon / "name") or "").lower()
        if provider not in {"coretemp", "k10temp", "zenpower"}:
            continue
        for input_path in sorted(hwmon.glob("temp*_input")):
            stem = input_path.name.removesuffix("_input")
            raw = read_text(input_path)
            current = _temperature_c(raw)
            if current is None:
                continue
            label = read_text(hwmon / f"{stem}_label") or stem
            record: Dict[str, Any] = {
                "provider": provider,
                "source_path": str(input_path),
                "label": label,
                "temperature_c": current,
                "evidence": {"temperature_c": _evidence(
                    provider=provider, source=str(input_path), raw_field=input_path.name,
                    raw_value=raw, raw_units="millidegrees_c", normalized_value=current,
                    normalized_units="c", semantics="cpu_temperature",
                )},
            }
            if provider == "coretemp":
                _thermal_value(record, "temperature_max_c", hwmon / f"{stem}_max", read_text, provider, "control_threshold")
                _thermal_value(record, "temperature_crit_c", hwmon / f"{stem}_crit", read_text, provider, "tjmax")
                if "temperature_crit_c" in record:
                    record["threshold_semantics"] = "tjmax"
                    if label.lower().startswith("package id"):
                        package_tjmax.append(float(record["temperature_crit_c"]))
            # AMD k10temp/zenpower thresholds are intentionally not normalized.
            sensors.append(record)
    cpu_zones = [
        zone
        for zone in discover_thermal_zones(thermal_root, read_text)
        if any(token in zone["zone_type"].lower() for token in ("cpu", "package", "pkg"))
    ]
    result: Dict[str, Any] = {"sensors": sensors, "platform_thermal_zones": cpu_zones}
    if len(package_tjmax) == 1:
        result["cpu_tjmax_c"] = package_tjmax[0]
        result["cpu_tjmax_semantics"] = "coretemp_package_temp_crit_alias"
    return result


def parse_dpm_levels(text: Optional[str]) -> Dict[str, Any]:
    levels: List[Dict[str, Any]] = []
    for line in str(text or "").splitlines():
        match = re.match(r"\s*(\d+):\s*([0-9.]+)\s*([GMk]?Hz)(?:\s+\*)?", line, re.IGNORECASE)
        if not match:
            continue
        scale = {"ghz": 1000.0, "mhz": 1.0, "khz": 0.001, "hz": 0.000001}.get(match.group(3).lower(), 1.0)
        levels.append({"level": int(match.group(1)), "frequency_mhz": round(float(match.group(2)) * scale, 2), "active": "*" in line})
    return {
        "available_frequency_levels_mhz": [item["frequency_mhz"] for item in levels],
        "active_frequency_level": next((item["level"] for item in levels if item["active"]), None),
        "levels": levels,
    }


def parse_nvidia_query_csv(text: str) -> List[Dict[str, Any]]:
    fields = (
        "pci_bus_id", "core_current_frequency_mhz", "sm_current_frequency_mhz",
        "memory_current_frequency_mhz", "core_maximum_frequency_mhz", "sm_maximum_frequency_mhz",
        "memory_maximum_frequency_mhz", "temperature_c",
    )
    rows: List[Dict[str, Any]] = []
    for line in str(text or "").splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < len(fields):
            continue
        row: Dict[str, Any] = {
            "pci_bus_id": normalize_pci_slot(parts[0]).lower(),
            "provider": "nvidia_smi",
            "evidence": {},
        }
        raw_fields = (
            "clocks.current.graphics", "clocks.current.sm", "clocks.current.memory",
            "clocks.max.graphics", "clocks.max.sm", "clocks.max.memory", "temperature.gpu",
        )
        for field, raw_field, raw in zip(fields[1:], raw_fields, parts[1:]):
            value = _number(raw)
            if value is not None and value >= 0:
                row[field] = round(value, 2)
                units = "c" if field == "temperature_c" else "mhz"
                row["evidence"][field] = _evidence(
                    provider="nvidia_smi", source="nvidia-smi --query-gpu", raw_field=raw_field,
                    raw_value=raw, raw_units=units, normalized_value=round(value, 2),
                    normalized_units=units, semantics=raw_field.replace(".", "_"),
                )
        if "core_maximum_frequency_mhz" in row:
            row["maximum_frequency_mhz"] = row["core_maximum_frequency_mhz"]
            row["maximum_frequency_semantics"] = "driver_max"
        rows.append(row)
    return rows


def parse_nvidia_temperature_limits(text: str) -> Dict[str, Dict[str, Any]]:
    """Parse both absolute legacy thresholds and signed relative T.Limit specs."""
    result: Dict[str, Dict[str, Any]] = {}
    current_slot = ""
    current_temp: Optional[float] = None
    current_margin: Optional[float] = None
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        bus_match = re.search(r"Bus Id\s*:\s*(\S+)", line, re.IGNORECASE)
        if bus_match is None:
            bus_match = re.fullmatch(r"GPU\s+([0-9a-fA-F:.]+)", line)
        if bus_match:
            current_slot = normalize_pci_slot(bus_match.group(1)).lower()
            result.setdefault(current_slot, {"provider": "nvidia_smi", "pci_bus_id": current_slot})
            current_temp = None
            current_margin = None
            continue
        if not current_slot or ":" not in line:
            continue
        label, raw_value = [part.strip() for part in line.split(":", 1)]
        normalized_label = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
        value = _number(raw_value)
        if value is None:
            continue
        record = result[current_slot]
        if normalized_label in {"gpu_current_temp", "gpu_temperature", "temperature_gpu"}:
            current_temp = value
            record["temperature_c"] = value
        elif "current" in normalized_label and "t_limit" in normalized_label:
            current_margin = value
            record["temperature_limit_current_margin_c"] = value
        elif "t_limit" in normalized_label:
            # Signed -5/-2/0 values are valid because the provider labels this a
            # relative specification, not an absolute Celsius temperature.
            margins = record.setdefault("temperature_limit_margin_c", {})
            margins[normalized_label] = value
            record.setdefault("temperature_limit_margin_evidence", []).append({
                "provider": "nvidia_smi", "source": "nvidia-smi -q -d TEMPERATURE",
                "label": label, "raw_value": raw_value, "margin_c": value,
                "semantic_classification": "relative_temperature_limit_margin",
                "confidence": "high", "derived": False,
            })
        else:
            absolute_fields = {
                "gpu_target_temperature": "temperature_target_c",
                "gpu_slowdown_temp": "temperature_slowdown_c",
                "gpu_max_operating_temp": "temperature_max_operating_c",
                "gpu_shutdown_temp": "temperature_shutdown_c",
            }
            for needle, field in absolute_fields.items():
                if needle in normalized_label:
                    record[field] = value
                    record.setdefault("temperature_limit_evidence", {})[field] = {
                        "provider": "nvidia_smi", "source": "nvidia-smi -q -d TEMPERATURE",
                        "label": label, "raw_value": raw_value, "normalized_value": value,
                        "normalized_units": "c", "semantic_classification": field.removesuffix("_c"),
                        "confidence": "high", "derived": False,
                    }
                    break
        if current_temp is not None and current_margin is not None and record.get("temperature_limit_margin_c"):
            base_limit = current_temp + current_margin
            derived: Dict[str, Any] = {}
            for name, spec_margin in record["temperature_limit_margin_c"].items():
                derived[name] = {
                    "temperature_c": round(base_limit - float(spec_margin), 2),
                    "derived": True,
                    "confidence": "medium",
                    "derivation_inputs": {
                        "current_temperature_c": current_temp,
                        "current_temperature_limit_margin_c": current_margin,
                        "relative_specification_margin_c": spec_margin,
                    },
                }
            record["derived_absolute_temperature_limits"] = derived
    return result


def parse_nvme_id_ctrl(text: str) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    mappings = {
        "wctemp": ("storage_warning_temperature_c", "warning_temperature"),
        "cctemp": ("storage_critical_temperature_c", "critical_temperature"),
        "mntmt": ("thermal_management_min_temperature_c", "thermal_management_minimum"),
        "mxtmt": ("thermal_management_max_temperature_c", "thermal_management_maximum"),
    }
    for line in str(text or "").splitlines():
        if ":" not in line:
            continue
        key, raw = [part.strip() for part in line.split(":", 1)]
        key = key.lower()
        if key not in mappings:
            continue
        number = _number(raw)
        if number is None or number == 0:
            continue
        # nvme-cli commonly renders these as Kelvin with a trailing K.
        value = _temperature_c(number, "kelvin") if number > 200 else round(number, 2)
        if value is None or value < -50 or value > 200:
            continue
        field, semantics = mappings[key]
        result[field] = value
        result.setdefault("evidence", {})[field] = _evidence(
            provider="nvme_id_ctrl", source="nvme id-ctrl", raw_field=key, raw_value=raw,
            raw_units="kelvin" if number > 200 else "c", normalized_value=value,
            normalized_units="c", semantics=semantics, confidence="medium",
        )
    return result


def parse_ipmi_temperature_thresholds(text: str) -> List[Dict[str, Any]]:
    """Parse ipmitool sensor's named upper threshold columns without inventing TjMax."""
    records: List[Dict[str, Any]] = []
    for line in str(text or "").splitlines():
        if "|" not in line:
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) < 10 or "degree" not in parts[2].lower():
            continue
        label = parts[0]
        current = _number(parts[1])
        if current is None or current <= -273.15 or current > 250:
            continue
        lowered = label.lower()
        component = "cpu" if "cpu" in lowered else (
            "memory_module" if any(token in lowered for token in ("dimm", "ddr", "dram", "memory")) else (
                "vrm" if "vrm" in lowered else ("pch" if "pch" in lowered or "chipset" in lowered else (
                    "psu" if "psu" in lowered else ("nic" if "nic" in lowered or "lan" in lowered else "platform")
                ))
            )
        )
        record: Dict[str, Any] = {
            "component_class": component,
            "provider": "ipmi_bmc",
            "label": label,
            "temperature_c": round(current, 2),
            "source": "ipmitool sensor",
            "evidence": {
                "temperature_c": _evidence(
                    provider="ipmi_bmc", source="ipmitool sensor", raw_field=label,
                    raw_value=parts[1], raw_units=parts[2], normalized_value=round(current, 2),
                    normalized_units="c", semantics="bmc_sensor_current",
                )
            },
        }
        # ipmitool columns: lnr, lcr, lnc, unc, ucr, unr.
        for index, field in ((7, "upper_noncritical_c"), (8, "upper_critical_c"), (9, "upper_nonrecoverable_c")):
            value = _number(parts[index])
            if value is not None and 0 < value <= 250:
                record[field] = round(value, 2)
                record["evidence"][field] = _evidence(
                    provider="ipmi_bmc", source="ipmitool sensor", raw_field=field.removesuffix("_c"),
                    raw_value=parts[index], raw_units=parts[2], normalized_value=round(value, 2),
                    normalized_units="c", semantics=field.removesuffix("_c"),
                )
        records.append(record)
    return records


def _run(command: List[str], command_env: CommandEnv, timeout: int = 10) -> str:
    try:
        completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=timeout, env=command_env())
    except Exception:
        return ""
    return completed.stdout if completed.returncode == 0 else ""


class HardwareEvidenceCollector:
    """Read-only provider-aware discovery attached to ``TelemetryCollector``."""

    def __init__(
        self,
        *,
        cpu_core_topology: Optional[Dict[int, Dict[str, Any]]] = None,
        gpu_cards: Optional[List[Dict[str, Any]]] = None,
        read_text: ReadText = _read_text,
        command_env: Callable[[], Dict[str, str]] = lambda: {},
        cpu_root: Path = Path("/sys/devices/system/cpu"),
        hwmon_root: Path = Path("/sys/class/hwmon"),
        thermal_root: Path = Path("/sys/class/thermal"),
        drm_root: Path = Path("/sys/class/drm"),
        devfreq_root: Path = Path("/sys/class/devfreq"),
    ) -> None:
        self.topology = cpu_core_topology or {}
        self.gpu_cards = gpu_cards or []
        self.read_text = read_text
        self.command_env = command_env
        self.cpu_root = cpu_root
        self.hwmon_root = hwmon_root
        self.thermal_root = thermal_root
        self.drm_root = drm_root
        self.devfreq_root = devfreq_root

    def collect(self) -> Dict[str, Any]:
        zones = discover_thermal_zones(self.thermal_root, self.read_text)
        local_ipmi = any(path.exists() for path in (Path("/dev/ipmi0"), Path("/dev/ipmi/0"), Path("/dev/ipmidev/0")))
        ipmi_text = (
            _run(["ipmitool", "sensor"], self.command_env, timeout=8)
            if local_ipmi and shutil.which("ipmitool")
            else ""
        )
        platform_sensors = self._platform_sensors()
        return {
            "schema_version": 1,
            "cpu": {
                "frequency": discover_cpu_frequency(self.cpu_root, self.read_text, self.topology),
                "thermal": discover_cpu_thermals(self.hwmon_root, self.thermal_root, self.read_text),
            },
            "platform_thermal_zones": zones,
            "gpus": self._gpus(zones),
            "storage_devices": self._storage(),
            "memory_modules": self._memory_modules(),
            "soc_memory_zones": [zone for zone in zones if zone["zone_type"].lower().replace("_", "-") in {"mem-thermal", "memory-thermal"}],
            "board_sensors": platform_sensors["board_sensors"],
            "other_component_sensors": platform_sensors["other_component_sensors"],
            "bmc_thermal_sensors": parse_ipmi_temperature_thresholds(ipmi_text),
        }

    def _gpus(self, zones: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        records: List[Dict[str, Any]] = []
        for card_info in self.gpu_cards:
            card_name = str(card_info.get("card") or "")
            card = self.drm_root / card_name
            device = card / "device"
            driver = str(card_info.get("driver") or self.read_text(device / "uevent") or "").lower()
            record: Dict[str, Any] = {
                "gpu_index": card_info.get("gpu_index"), "card": card_name,
                "pci_bus_id": str(card_info.get("slot") or "").lower(),
                "provider": driver,
                "physical_device_identity": {
                    key: value
                    for key, value in card_info.items()
                    if re.fullmatch(r"[a-z][a-z0-9_]*", str(key))
                    and isinstance(value, (str, int, float, bool, list, type(None)))
                },
                "clock_domains": {}, "thermal_domains": [],
            }
            if "amdgpu" in driver:
                for filename, domain in (("pp_dpm_sclk", "core"), ("pp_dpm_mclk", "memory")):
                    path = device / filename
                    raw = self.read_text(path)
                    parsed = parse_dpm_levels(raw)
                    if parsed["levels"]:
                        parsed.update({
                            "clock_provider": "amdgpu_dpm", "source": str(path),
                            "maximum_frequency_mhz": max(parsed["available_frequency_levels_mhz"]),
                            "maximum_frequency_semantics": "available_dpm_level_max",
                        })
                        record["clock_domains"][domain] = parsed
                self._gpu_hwmon(record, card, "amdgpu")
            elif "i915" in driver:
                self._i915(record, device, card)
                self._gpu_hwmon(record, card, "i915", thermal_limits=False)
            records.append(record)
        nvidia_rows = self._nvidia()
        by_slot = {str(item.get("pci_bus_id") or "").lower(): item for item in records}
        for row in nvidia_rows:
            slot = str(row.get("pci_bus_id") or "").lower()
            if slot in by_slot:
                by_slot[slot].update(row)
                by_slot[slot]["provider"] = "nvidia_smi"
            else:
                records.append(row)
        for platform_record in self._platform_devfreq(zones, len(records)):
            platform_name = str(platform_record.get("physical_device_identity", {}).get("platform_name") or "")
            existing = next(
                (
                    item for item in records
                    if platform_name
                    and (
                        item.get("physical_device_identity", {}).get("platform_gpu_name") == platform_name
                        or item.get("physical_device_identity", {}).get("platform_name") == platform_name
                    )
                ),
                None,
            )
            if existing is None:
                records.append(platform_record)
            else:
                identity = existing.get("physical_device_identity", {})
                platform_record["gpu_index"] = existing.get("gpu_index")
                existing.update(platform_record)
                existing["physical_device_identity"] = {**identity, **platform_record.get("physical_device_identity", {})}
        return records

    def _gpu_hwmon(self, record: Dict[str, Any], card: Path, provider: str, thermal_limits: bool = True) -> None:
        for hwmon in sorted((card / "device" / "hwmon").glob("hwmon*")):
            for input_path in sorted(hwmon.glob("temp*_input")):
                stem = input_path.name.removesuffix("_input")
                label = (self.read_text(hwmon / f"{stem}_label") or stem).lower()
                domain = "junction" if "junction" in label or "hotspot" in label else ("memory" if label in {"mem", "memory"} else "edge")
                current = _temperature_c(self.read_text(input_path))
                if current is None:
                    continue
                thermal: Dict[str, Any] = {
                    "domain": domain, "label": label, "provider": provider,
                    "source_path": str(input_path), "temperature_c": current, "confidence": "high",
                    "evidence": {"temperature_c": _evidence(
                        provider=provider, source=str(input_path), raw_field=input_path.name,
                        raw_value=self.read_text(input_path), raw_units="millidegrees_c",
                        normalized_value=current, normalized_units="c", semantics=f"gpu_{domain}_temperature",
                    )},
                }
                if thermal_limits:
                    _thermal_value(thermal, "temperature_crit_c", hwmon / f"{stem}_crit", self.read_text, provider, "critical_threshold")
                    _thermal_value(thermal, "temperature_emergency_c", hwmon / f"{stem}_emergency", self.read_text, provider, "emergency_threshold")
                record["thermal_domains"].append(thermal)
            for freq_path in sorted(hwmon.glob("freq*_input")):
                freq_label = (self.read_text(freq_path.with_name(freq_path.name.replace("_input", "_label"))) or "").lower()
                field = "memory_current_frequency_mhz" if "mem" in freq_label else "core_current_frequency_mhz"
                raw = self.read_text(freq_path)
                value = _frequency_mhz(raw, "hz")
                if value is not None:
                    record[field] = value
                    record.setdefault("evidence", {})[field] = _evidence(
                        provider=provider, source=str(freq_path), raw_field=freq_path.name,
                        raw_value=raw, raw_units="hz", normalized_value=value,
                        normalized_units="mhz", semantics=f"gpu_{field}",
                    )

    def _i915(self, record: Dict[str, Any], device: Path, card: Optional[Path] = None) -> None:
        gt_candidates = list((device / "gt").glob("gt*"))
        if card is not None:
            gt_candidates.extend((card / "gt").glob("gt*"))
        gt_candidates.extend(device.glob("drm/card*/gt/gt*"))
        gt_dirs: List[Path] = []
        seen_gt_paths: set[str] = set()
        for candidate in sorted(gt_candidates):
            key = str(candidate.resolve())
            if key not in seen_gt_paths:
                seen_gt_paths.add(key)
                gt_dirs.append(candidate)
        if not gt_dirs:
            gt_dirs = [path for path in (card, device) if path is not None]
        for index, gt in enumerate(gt_dirs):
            domain: Dict[str, Any] = {"gt_id": gt.name if gt != device else f"gt{index}", "clock_provider": "i915"}
            candidates = {
                "core_current_frequency_mhz": ("rps_cur_freq_mhz", "gt_cur_freq_mhz", "rps_cur_freq"),
                "active_frequency_mhz": ("rps_act_freq_mhz", "gt_act_freq_mhz", "rps_act_freq"),
                "configured_min_frequency_mhz": ("rps_min_freq_mhz", "gt_min_freq_mhz", "rps_min_freq"),
                "configured_max_frequency_mhz": ("rps_max_freq_mhz", "gt_max_freq_mhz", "rps_max_freq"),
                "rp0_frequency_mhz": ("rps_RP0_freq_mhz", "gt_RP0_freq_mhz", "rps_RP0_freq"),
                "rp1_frequency_mhz": ("rps_RP1_freq_mhz", "gt_RP1_freq_mhz", "rps_RP1_freq"),
                "rpn_frequency_mhz": ("rps_RPn_freq_mhz", "gt_RPn_freq_mhz", "rps_RPn_freq"),
                "boost_frequency_mhz": ("rps_boost_freq_mhz", "gt_boost_freq_mhz", "rps_boost_freq"),
            }
            for field, names in candidates.items():
                for name in names:
                    path = gt / name
                    raw = self.read_text(path)
                    value = _frequency_mhz(raw, "mhz")
                    if value is not None:  # zero is valid when the GT is power-gated
                        domain[field] = value
                        domain.setdefault("raw_sources", {})[field] = {"path": str(path), "raw_field": name, "raw_value": raw}
                        break
            if "rp0_frequency_mhz" in domain:
                domain["maximum_frequency_mhz"] = domain["rp0_frequency_mhz"]
                domain["maximum_frequency_semantics"] = "rp0"
            record["clock_domains"][domain["gt_id"]] = domain

    def _nvidia(self) -> List[Dict[str, Any]]:
        if shutil.which("nvidia-smi") is None:
            return []
        fields = [
            "pci.bus_id", "clocks.current.graphics", "clocks.current.sm", "clocks.current.memory",
            "clocks.max.graphics", "clocks.max.sm", "clocks.max.memory", "temperature.gpu",
        ]
        query = _run(["nvidia-smi", f"--query-gpu={','.join(fields)}", "--format=csv,noheader,nounits"], self.command_env)
        rows = parse_nvidia_query_csv(query)
        limits = parse_nvidia_temperature_limits(_run(["nvidia-smi", "-q", "-d", "TEMPERATURE"], self.command_env))
        for row in rows:
            slot = str(row.get("pci_bus_id") or "")
            row.update(limits.get(slot, {}))
            row["clock_provider"] = "nvidia_smi"
            row["maximum_frequency_semantics"] = "driver_max"
        return rows

    def _platform_devfreq(self, zones: List[Dict[str, Any]], start_index: int) -> List[Dict[str, Any]]:
        records: List[Dict[str, Any]] = []
        for devfreq in sorted(self.devfreq_root.glob("*")):
            name = devfreq.name.lower()
            uevent = self.read_text(devfreq / "device" / "uevent") or ""
            if "adreno" not in name and "DRIVER=adreno" not in uevent and "OF_NAME=gpu" not in uevent:
                continue
            current = _frequency_mhz(self.read_text(devfreq / "cur_freq"), "hz")
            available_raw = self.read_text(devfreq / "available_frequencies") or ""
            available = [value for value in (_frequency_mhz(token, "hz") for token in available_raw.split()) if value is not None]
            record: Dict[str, Any] = {
                "gpu_index": start_index + len(records), "provider": "adreno_devfreq",
                "physical_device_identity": {"platform_name": devfreq.name, "source_path": str(devfreq)},
                "clock_provider": "devfreq", "available_frequency_levels_mhz": sorted(set(available)),
                "governor": self.read_text(devfreq / "governor"), "thermal_domains": [],
                "raw_sources": {},
            }
            if current is not None:
                record["core_current_frequency_mhz"] = current
                record["raw_sources"]["core_current_frequency_mhz"] = str(devfreq / "cur_freq")
            for field, filename in (("configured_min_frequency_mhz", "min_freq"), ("configured_max_frequency_mhz", "max_freq")):
                value = _frequency_mhz(self.read_text(devfreq / filename), "hz")
                if value is not None:
                    record[field] = value
                    record["raw_sources"][field] = str(devfreq / filename)
            if available:
                record["maximum_frequency_mhz"] = max(available)
                record["maximum_frequency_semantics"] = "available_frequency_max"
            records.append(record)
        if len(records) == 1:
            records[0]["thermal_domains"] = [
                {**zone, "association_confidence": "medium", "thermal_domain_semantics": "gpu_subsystem_platform_zone"}
                for zone in zones if zone["zone_type"].lower().startswith("gpuss")
            ]
        return records

    def _storage(self) -> List[Dict[str, Any]]:
        devices: List[Dict[str, Any]] = []
        for hwmon in sorted(self.hwmon_root.glob("hwmon*")):
            if (self.read_text(hwmon / "name") or "").lower() != "nvme":
                continue
            raw_current = self.read_text(hwmon / "temp1_input")
            current = _temperature_c(raw_current)
            if current is None:
                continue
            resolved = str(hwmon.resolve())
            match = re.search(r"/(nvme\d+)(?:/|$)", resolved)
            controller = match.group(1) if match else ""
            record: Dict[str, Any] = {"component_class": "storage_device", "provider": "nvme_hwmon", "controller": controller, "source_path": str(hwmon)}
            _thermal_value(record, "temperature_c", hwmon / "temp1_input", self.read_text, "nvme_hwmon", "composite_current")
            _thermal_value(record, "storage_warning_temperature_c", hwmon / "temp1_max", self.read_text, "nvme_hwmon", "warning_temperature")
            _thermal_value(record, "storage_critical_temperature_c", hwmon / "temp1_crit", self.read_text, "nvme_hwmon", "critical_temperature")
            additional: List[Dict[str, Any]] = []
            for input_path in sorted(hwmon.glob("temp*_input")):
                if input_path.name == "temp1_input":
                    continue
                value = _temperature_c(self.read_text(input_path))
                if value is None:
                    continue
                stem = input_path.name.removesuffix("_input")
                additional.append({
                    "label": self.read_text(hwmon / f"{stem}_label") or stem,
                    "temperature_c": value,
                    "source_path": str(input_path),
                    "threshold_normalization": "not_inferred_from_sensor_min_max",
                })
            if additional:
                record["additional_temperature_sensors"] = additional
            if controller and shutil.which("nvme") and Path(f"/dev/{controller}").exists():
                controller_evidence = parse_nvme_id_ctrl(
                    _run(["nvme", "id-ctrl", f"/dev/{controller}"], self.command_env)
                )
                if controller_evidence:
                    record["nvme_id_ctrl"] = controller_evidence
                    comparisons: Dict[str, str] = {}
                    for field in ("storage_warning_temperature_c", "storage_critical_temperature_c"):
                        if field in record and field in controller_evidence:
                            comparisons[field] = (
                                "agree" if abs(float(record[field]) - float(controller_evidence[field])) <= 0.1 else "disagree"
                            )
                    if comparisons:
                        record["provider_comparison"] = comparisons
            devices.append(record)
        return devices

    def _memory_modules(self) -> List[Dict[str, Any]]:
        modules: List[Dict[str, Any]] = []
        for hwmon in sorted(self.hwmon_root.glob("hwmon*")):
            provider = (self.read_text(hwmon / "name") or "").lower()
            if provider not in {"spd5118", "jc42"}:
                continue
            for input_path in sorted(hwmon.glob("temp*_input")):
                current = _temperature_c(self.read_text(input_path))
                if current is None:
                    continue
                stem = input_path.name.removesuffix("_input")
                record: Dict[str, Any] = {
                    "component_class": "memory_module", "provider": provider,
                    "canonical_identity": str(hwmon.resolve()), "source_path": str(input_path),
                    "temperature_c": current,
                    "evidence": {"temperature_c": _evidence(
                        provider=provider, source=str(input_path), raw_field=input_path.name,
                        raw_value=self.read_text(input_path), raw_units="millidegrees_c",
                        normalized_value=current, normalized_units="c",
                        semantics="memory_module_temperature",
                    )},
                }
                max_value = _temperature_c(self.read_text(hwmon / f"{stem}_max"))
                crit_value = _temperature_c(self.read_text(hwmon / f"{stem}_crit"))
                # Observed jc42 zero thresholds with asserted alarms are an
                # uninitialized pattern, not 0 C safety limits.
                if provider == "spd5118" or ((max_value or 0) > 0 and (crit_value or 0) > 0):
                    if max_value is not None and max_value > 0:
                        record["temperature_max_c"] = max_value
                        record["evidence"]["temperature_max_c"] = _evidence(
                            provider=provider, source=str(hwmon / f"{stem}_max"), raw_field=f"{stem}_max",
                            raw_value=self.read_text(hwmon / f"{stem}_max"), raw_units="millidegrees_c",
                            normalized_value=max_value, normalized_units="c", semantics="module_maximum_threshold",
                        )
                    if crit_value is not None and crit_value > 0:
                        record["temperature_crit_c"] = crit_value
                        record["evidence"]["temperature_crit_c"] = _evidence(
                            provider=provider, source=str(hwmon / f"{stem}_crit"), raw_field=f"{stem}_crit",
                            raw_value=self.read_text(hwmon / f"{stem}_crit"), raw_units="millidegrees_c",
                            normalized_value=crit_value, normalized_units="c", semantics="module_critical_threshold",
                        )
                alarms = {}
                for alarm_path in sorted(hwmon.glob(f"{stem}_*_alarm")):
                    raw = self.read_text(alarm_path)
                    if raw in {"0", "1"}:
                        alarms[alarm_path.name] = raw == "1"
                if alarms:
                    record["alarm_state"] = alarms
                modules.append(record)
        return modules

    def _platform_sensors(self) -> Dict[str, List[Dict[str, Any]]]:
        records: List[Dict[str, Any]] = []
        other_records: List[Dict[str, Any]] = []
        excluded = {"coretemp", "k10temp", "zenpower", "amdgpu", "i915", "xe", "nouveau", "nvme", "drivetemp", "spd5118", "jc42"}
        for hwmon in sorted(self.hwmon_root.glob("hwmon*")):
            provider = (self.read_text(hwmon / "name") or "").lower()
            if provider in excluded:
                continue
            for input_path in sorted(hwmon.glob("temp*_input")):
                stem = input_path.name.removesuffix("_input")
                label = (self.read_text(hwmon / f"{stem}_label") or "").strip()
                current = _temperature_c(self.read_text(input_path))
                classified = platform_hwmon_classification(provider, label)
                if classified["owner"] in {"cpu", "gpu", "memory_module", "storage"}:
                    continue
                if not valid_platform_temperature(provider, label, current):
                    continue
                component = classified["classification"]
                record: Dict[str, Any] = {
                    "provider": provider, "source_path": str(input_path), "label": label or stem,
                    "temperature_c": current,
                    "classification": component,
                    "confidence": classified["confidence"],
                }
                # NCT6687 limits are retained as raw provider evidence only.
                if provider == "nct6687":
                    raw_limits = {suffix: self.read_text(hwmon / f"{stem}_{suffix}") for suffix in ("min", "max", "crit")}
                    record["raw_thresholds"] = {key: value for key, value in raw_limits.items() if value is not None}
                    record["threshold_normalization"] = "do_not_normalize"
                elif component in {"motherboard", "system", "pch", "vrm", "vrm_mos"}:
                    _thermal_value(record, "temperature_max_c", hwmon / f"{stem}_max", self.read_text, provider or "hwmon", "provider_maximum", "medium")
                    _thermal_value(record, "temperature_crit_c", hwmon / f"{stem}_crit", self.read_text, provider or "hwmon", "provider_critical", "medium")
                if component in {"nic", "wifi", "psu"}:
                    other_records.append(record)
                else:
                    records.append(record)
        return {"board_sensors": records, "other_component_sensors": other_records}


def format_hardware_evidence_summary(evidence: Dict[str, Any]) -> List[str]:
    """Small operator-facing summary with truthful provider semantics."""
    lines: List[str] = []
    groups = evidence.get("cpu", {}).get("frequency", {}).get("policy_groups", [])
    for group in groups:
        label = group.get("core_class") or "CPU policies"
        values = []
        for field, display in (
            ("base_frequency_mhz", "base"), ("hardware_max_frequency_mhz", "hardware max"),
            ("policy_max_frequency_mhz", "configured max"),
        ):
            if field in group:
                values.append(f"{display} {float(group[field]) / 1000:.2f} GHz")
        if values:
            current_min = group.get("current_frequency_min_mhz")
            current_max = group.get("current_frequency_max_mhz")
            if current_min is not None and current_max is not None:
                current_text = f"current {float(current_min) / 1000:.2f} GHz"
                if float(current_max) != float(current_min):
                    current_text += f"–{float(current_max) / 1000:.2f} GHz"
                values.append(current_text)
            lines.append(f"{label}: " + ", ".join(values))
    for gpu in evidence.get("gpus", []):
        label = gpu.get("pci_bus_id") or gpu.get("card") or gpu.get("provider") or "GPU"
        values = []
        if "core_current_frequency_mhz" in gpu:
            values.append(f"current {gpu['core_current_frequency_mhz']} MHz")
        if "maximum_frequency_mhz" in gpu:
            semantic = str(gpu.get("maximum_frequency_semantics") or "provider maximum").replace("_", " ")
            values.append(f"{semantic} {gpu['maximum_frequency_mhz']} MHz")
        if values:
            lines.append(f"GPU {label}: " + ", ".join(values))
        for domain_name, domain in gpu.get("clock_domains", {}).items():
            domain_values = []
            for field, display in (
                ("core_current_frequency_mhz", "current"),
                ("configured_min_frequency_mhz", "configured min"),
                ("configured_max_frequency_mhz", "configured max"),
                ("maximum_frequency_mhz", str(domain.get("maximum_frequency_semantics") or "provider maximum").replace("_", " ")),
            ):
                if field in domain:
                    domain_values.append(f"{display} {domain[field]} MHz")
            if domain_values:
                lines.append(f"GPU {label} {domain_name}: " + ", ".join(domain_values))
        for thermal in gpu.get("thermal_domains", []):
            thermal_values = []
            for field, display in (
                ("temperature_c", "current"), ("temperature_max_c", "max/control"),
                ("temperature_crit_c", "critical"), ("temperature_emergency_c", "emergency"),
            ):
                if field in thermal:
                    thermal_values.append(f"{display} {thermal[field]} C")
            if thermal_values:
                domain = thermal.get("domain") or thermal.get("zone_type") or "thermal"
                lines.append(f"GPU {label} {domain}: " + ", ".join(thermal_values))
        for field, display in (
            ("temperature_target_c", "target"), ("temperature_slowdown_c", "slowdown"),
            ("temperature_max_operating_c", "max operating"), ("temperature_shutdown_c", "shutdown"),
        ):
            if field in gpu:
                lines.append(f"GPU {label} {display}: {gpu[field]} C")
        for margin_label, margin in gpu.get("temperature_limit_margin_c", {}).items():
            lines.append(f"GPU {label} {margin_label.replace('_', ' ')}: {margin:+g} C relative margin")

    cpu_sensors = evidence.get("cpu", {}).get("thermal", {}).get("sensors", [])
    summary_cpu_sensors = [
        sensor for sensor in cpu_sensors
        if str(sensor.get("label") or "").lower().startswith("package")
        or str(sensor.get("label") or "").lower() in {"tctl", "tdie"}
    ] or cpu_sensors[:1]
    for sensor in summary_cpu_sensors:
        values = []
        for field, display in (
            ("temperature_c", "current"), ("temperature_max_c", "max/control"),
            ("temperature_crit_c", "critical/TjMax"),
        ):
            if field in sensor:
                values.append(f"{display} {sensor[field]} C")
        if values:
            lines.append(f"CPU {sensor.get('label') or sensor.get('provider')}: " + ", ".join(values))
    for storage in evidence.get("storage_devices", []):
        values = []
        for field, display in (
            ("temperature_c", "current"), ("storage_warning_temperature_c", "warning"),
            ("storage_critical_temperature_c", "critical"),
        ):
            if field in storage:
                values.append(f"{display} {storage[field]} C")
        if values:
            lines.append(f"Storage {storage.get('controller') or storage.get('source_path')}: " + ", ".join(values))
    for module in evidence.get("memory_modules", []):
        values = []
        for field, display in (
            ("temperature_c", "current"), ("temperature_max_c", "max"),
            ("temperature_crit_c", "critical"),
        ):
            if field in module:
                values.append(f"{display} {module[field]} C")
        if values:
            lines.append(f"Memory module {module.get('canonical_identity') or module.get('provider')}: " + ", ".join(values))
    for sensor in evidence.get("board_sensors", []):
        if sensor.get("classification") == "generic_channel":
            continue
        values = [f"current {sensor['temperature_c']} C"]
        for field, display in (("temperature_max_c", "max"), ("temperature_crit_c", "critical")):
            if field in sensor:
                values.append(f"{display} {sensor[field]} C")
        lines.append(f"{sensor.get('label') or sensor.get('classification')}: " + ", ".join(values))
    return lines
