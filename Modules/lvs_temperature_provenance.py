#!/usr/bin/env python3
"""Evidence-based component provenance for Linux temperature sensors."""

from __future__ import annotations

import re
from typing import Dict


CPU_PACKAGE_TEMPERATURE = "cpu_package_temperature"
CPU_CORE_TEMPERATURE = "cpu_core_temperature"
CPU_SUBSYSTEM_TEMPERATURE = "cpu_subsystem_temperature"
SOC_TEMPERATURE = "soc_temperature"
PLATFORM_ZONE_TEMPERATURE = "platform_thermal_zone_temperature"
UNKNOWN_TEMPERATURE = "unknown_temperature"


def _record(classification: str, scope: str, confidence: str) -> Dict[str, str]:
    return {
        "semantic_classification": classification,
        "component_scope": scope,
        "confidence": confidence,
    }


def classify_thermal_zone_type(zone_type: str) -> Dict[str, str]:
    """Classify a thermal-zone name without inferring ownership from ACPI."""
    normalized = str(zone_type or "").strip().lower().replace("_", "-")
    if "x86-pkg-temp" in normalized or re.search(r"(?:^|-)package(?:-|$)|(?:^|-)pkg(?:-|$)", normalized):
        return _record(CPU_PACKAGE_TEMPERATURE, "cpu_package", "high")
    if re.fullmatch(r"cpu\d+-\d+-(?:top|btm)-thermal", normalized):
        return _record(CPU_CORE_TEMPERATURE, "cpu_core", "high")
    if re.fullmatch(r"cpuss\d*-(?:top|btm)-thermal", normalized) or "cpu" in normalized:
        return _record(CPU_SUBSYSTEM_TEMPERATURE, "cpu_subsystem", "high")
    if re.search(r"(?:^|-)soc(?:-|$)", normalized):
        return _record(SOC_TEMPERATURE, "soc", "high")
    if normalized == "acpitz" or normalized.startswith("acpi"):
        return _record(PLATFORM_ZONE_TEMPERATURE, "platform", "medium")
    return _record(UNKNOWN_TEMPERATURE, "unknown", "low")


def classify_hwmon_temperature(provider: str, label: str) -> Dict[str, str]:
    """Classify one hwmon temperature only from explicit provider/label evidence."""
    provider_name = str(provider or "").strip().lower()
    normalized = re.sub(r"[_-]+", " ", str(label or "").strip().lower())
    text = f"{provider_name} {normalized}".strip()
    if provider_name == "coretemp":
        if re.search(r"\bpackage\s*id\s*\d+\b|\bcpu package\b", normalized):
            return _record(CPU_PACKAGE_TEMPERATURE, "cpu_package", "high")
        if re.search(r"\bcore\s*\d+\b", normalized):
            return _record(CPU_CORE_TEMPERATURE, "cpu_core", "high")
    if provider_name in {"k10temp", "zenpower"} and normalized in {"tctl", "tdie", "tctl/tdie"}:
        return _record(CPU_PACKAGE_TEMPERATURE, "cpu_package", "high")
    if re.search(r"\b(?:cpu )?package\b|\bpackage id\b|\btdie\b|\btctl\b", text):
        return _record(CPU_PACKAGE_TEMPERATURE, "cpu_package", "high")
    if re.search(r"\bcpu\s*core\s*\d+\b|\bcore\s*\d+\b", normalized) and provider_name in {
        "coretemp", "k10temp", "zenpower"
    }:
        return _record(CPU_CORE_TEMPERATURE, "cpu_core", "high")
    if "cpu" in normalized and normalized:
        return _record(CPU_SUBSYSTEM_TEMPERATURE, "cpu_subsystem", "medium")
    if re.search(r"\bsoc\b", normalized):
        return _record(SOC_TEMPERATURE, "soc", "medium")
    if provider_name == "acpitz":
        return _record(PLATFORM_ZONE_TEMPERATURE, "platform", "medium")
    return _record(UNKNOWN_TEMPERATURE, "unknown", "low")


def is_cpu_temperature_provenance(record: Dict[str, str]) -> bool:
    return str(record.get("component_scope") or "").startswith("cpu_")
