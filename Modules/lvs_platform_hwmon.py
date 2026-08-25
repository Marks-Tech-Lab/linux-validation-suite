#!/usr/bin/env python3
"""Pure classification helpers for direct platform hwmon temperatures."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Optional


TRUSTED_PLATFORM_TELEMETRY_CLASSES = {
    "motherboard",
    "system",
    "pch",
    "vrm",
    "vrm_mos",
    "psu",
}


def normalize_platform_sensor_label(label: str) -> str:
    return re.sub(r"\s+", " ", str(label or "").strip().lower())


def normalize_platform_temperature_c(raw: Any) -> Optional[float]:
    text = str(raw or "").strip().replace(",", "")
    if not text or text.lower() in {
        "n/a", "na", "none", "unsupported", "[not supported]", "deprecated",
    }:
        return None
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        value = float(match.group(0)) / 1000.0
    except ValueError:
        return None
    if value <= -273.15 or value > 250.0:
        return None
    return round(value, 2)


def valid_platform_temperature(
    provider: str,
    label: str,
    value_c: Optional[float],
) -> bool:
    """Apply the established platform-only sentinel/disconnection policy."""
    if value_c is None or value_c == 0:
        return False
    normalized_label = normalize_platform_sensor_label(label)
    if "t_sensor" in normalized_label and value_c < -40:
        return False
    return True


def platform_hwmon_classification(provider: str, label: str) -> Dict[str, str]:
    """Classify one hwmon temperature without guessing from its value."""
    provider_name = str(provider or "").strip().lower()
    normalized_label = normalize_platform_sensor_label(label)

    owner = ""
    compatibility_owner = "gigabyte_wmi" if provider_name == "gigabyte_wmi" else ""
    if provider_name in {"coretemp", "k10temp", "zenpower", "amd_hsmp_hwmon", "fam15h_power"}:
        owner = "cpu"
    elif provider_name in {"amdgpu", "i915", "xe", "nouveau", "nvidia"}:
        owner = "gpu"
    elif provider_name in {"spd5118", "jc42"}:
        owner = "memory_module"
    elif provider_name in {"nvme", "drivetemp", "scttemp"}:
        owner = "storage"
    elif provider_name.startswith("r8169") or "realtek" in provider_name:
        return {
            "classification": "nic",
            "confidence": "high",
            "owner": "nic",
            "normalized_label": normalized_label,
        }
    elif provider_name.startswith(("iwlwifi", "ath11k")):
        return {
            "classification": "wifi",
            "confidence": "medium",
            "owner": "wifi",
            "normalized_label": normalized_label,
        }
    elif provider_name == "acpitz":
        owner = "thermal_zone"
    if owner:
        return {
            "classification": "generic_channel",
            "confidence": "low",
            "owner": owner,
            "normalized_label": normalized_label,
        }

    classification = ""
    if normalized_label == "motherboard" or normalized_label.startswith("motherboard "):
        classification = "motherboard"
    elif normalized_label == "system" or normalized_label.startswith("system "):
        classification = "system"
    elif (
        normalized_label == "pch"
        or normalized_label.startswith("pch ")
        or normalized_label == "chipset"
        or normalized_label.startswith("chipset ")
    ):
        classification = "pch"
    elif normalized_label == "vrm" or normalized_label.startswith("vrm "):
        classification = "vrm_mos" if "mos" in normalized_label else "vrm"
    elif normalized_label == "psu" or normalized_label.startswith("psu "):
        classification = "psu"
    elif normalized_label == "power supply" or normalized_label.startswith("power supply "):
        classification = "psu"
    elif any(token in normalized_label for token in ("nic", "lan", "ethernet")):
        classification = "nic"
    elif "wifi" in normalized_label or "wi-fi" in normalized_label:
        classification = "wifi"

    if classification:
        return {
            "classification": classification,
            "confidence": "high",
            "owner": compatibility_owner or (
                "platform" if classification in TRUSTED_PLATFORM_TELEMETRY_CLASSES else classification
            ),
            "normalized_label": normalized_label,
        }
    if "psu" in provider_name or "power_supply" in provider_name:
        return {
            "classification": "psu",
            "confidence": "medium",
            "owner": "platform",
            "normalized_label": normalized_label,
        }
    return {
        "classification": "generic_channel",
        "confidence": "low",
        "owner": compatibility_owner,
        "normalized_label": normalized_label,
    }


def canonical_temperature_identity(path: Path) -> str:
    try:
        return str(path.resolve())
    except Exception:
        return str(path)


def stable_temperature_device_locator(path: Path) -> str:
    """Remove volatile hwmonN enumeration while retaining device identity."""
    canonical = canonical_temperature_identity(path)
    without_hwmon = re.sub(r"/hwmon/hwmon\d+(?=/)", "", canonical)
    return str(Path(without_hwmon).parent)
