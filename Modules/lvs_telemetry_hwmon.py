#!/usr/bin/env python3
"""Evidence-first discovery and sampling for direct platform hwmon sensors."""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .lvs_platform_hwmon import (
    platform_hwmon_classification,
    stable_temperature_device_locator,
    valid_platform_temperature,
    normalize_platform_temperature_c,
)


ReadText = Callable[[Path], Optional[str]]
TelemetrySource = Dict[str, Any]

_GPU_HWMON_PROVIDERS = {"amdgpu", "i915", "xe", "nouveau", "nvidia"}
_FAMILY_PATTERNS = {
    "temp": ("temp*_input",),
    "fan": ("fan*_input",),
    "pwm": ("pwm[0-9]*",),
    "voltage": ("in*_input",),
    "current": ("curr*_input",),
    "power": ("power*_input", "power*_average"),
}


def _normalized_label(label: str) -> str:
    value = re.sub(r"[_-]+", " ", str(label or "").strip().lower())
    return re.sub(r"\s+", " ", value)


def _channel(path: Path, family: str) -> int:
    prefix = {"voltage": "in", "current": "curr"}.get(family, family)
    match = re.match(rf"{re.escape(prefix)}(\d+)", path.name)
    return int(match.group(1)) if match else 0


def _raw_label(path: Path, read_text: ReadText) -> str:
    label_path = path.with_name(path.name.replace("_input", "_label"))
    if path.name.startswith("pwm"):
        label_path = path.with_name(f"{path.name}_label")
    return str(read_text(label_path) or "").strip()


def _driver_name(hwmon: Path) -> str:
    for candidate in (hwmon / "device" / "driver", hwmon / "driver"):
        if not candidate.exists() and not candidate.is_symlink():
            continue
        try:
            return candidate.resolve().name
        except Exception:
            continue
    return ""


def _fan_classification(label: str) -> Optional[str]:
    normalized = _normalized_label(label)
    if not normalized:
        return None
    if re.search(r"\b(?:aio|water|w)\s*pump\b|\bpump\s*fan\b|^pump$", normalized):
        return "pump"
    if re.search(r"\bcpu\s*(?:\d+\s*)?fan(?:\s*#?\d+)?\b|^cpu fan", normalized):
        return "cpu_fan"
    if re.search(r"\bgpu\s*(?:\d+\s*)?fan(?:\s*#?\d+)?\b|^gpu fan", normalized):
        return "gpu_fan"
    if re.search(r"\b(?:system|sys|chassis|cha)\s*fan(?:\s*#?\d+)?\b", normalized):
        return "system_fan"
    if re.search(r"\bpsu\s*fan\b|\bpower supply\s*fan\b", normalized):
        return "psu_fan"
    return None


def _voltage_classification(label: str) -> Optional[str]:
    normalized = _normalized_label(label)
    if not normalized or re.fullmatch(r"(?:vin|in|voltage)\s*(?:#\s*)?\d+", normalized):
        return None
    if "vid" in normalized or "requested" in normalized:
        return None
    if re.search(r"\b(?:cpu\s*)?vcore\b|\bcore voltage\b", normalized):
        return "cpu_vcore"
    if re.search(r"\b(?:cpu\s*)?(?:soc|vsoc)\b", normalized):
        return "cpu_soc"
    if re.search(r"\b(?:cpu\s*)?vddp\b", normalized):
        return "cpu_vddp"
    if re.search(r"\bdram\b", normalized):
        return "dram"
    compact = normalized.replace(" ", "")
    if compact.startswith("+"):
        compact = compact[1:]
    if compact in {"12v", "12.0v"}:
        return "motherboard_12v"
    if compact in {"5v", "5.0v"}:
        return "motherboard_5v"
    if compact in {"3.3v", "3v3"}:
        return "motherboard_3v3"
    # A retained explicit rail label is trustworthy identity even when LVS has
    # no narrower cross-provider semantic class. Preserve the label/provenance
    # rather than guessing that it is Vcore or dropping the measurement.
    return "other_voltage_rail"


def normalize_direct_hwmon_value(source: TelemetrySource, raw: Any) -> Optional[float]:
    try:
        value = float(str(raw or "").strip().replace(",", ""))
    except Exception:
        return None
    if not math.isfinite(value):
        return None
    family = str(source.get("family") or "")
    if family == "fan":
        return round(value, 2) if 0.0 <= value <= 1_000_000.0 else None
    if family == "voltage":
        value /= 1000.0
        return round(value, 3) if 0.0 <= value <= 1000.0 else None
    return None


def discover_direct_hwmon_sources(
    *,
    read_text: ReadText,
    hwmon_root: Path = Path("/sys/class/hwmon"),
) -> Tuple[List[TelemetrySource], List[Dict[str, Any]]]:
    """Discover accepted platform fan/rail sources and retain all decisions."""
    accepted: List[TelemetrySource] = []
    candidates: List[Dict[str, Any]] = []
    pending: List[TelemetrySource] = []
    for hwmon in sorted(hwmon_root.glob("hwmon*")):
        provider = str(read_text(hwmon / "name") or "").strip()
        driver = _driver_name(hwmon)
        for family, patterns in _FAMILY_PATTERNS.items():
            paths = sorted({path for pattern in patterns for path in hwmon.glob(pattern)})
            if family == "pwm":
                paths = [path for path in paths if re.fullmatch(r"pwm\d+", path.name)]
            for path in paths:
                raw_value = read_text(path)
                label = _raw_label(path, read_text)
                channel = _channel(path, family)
                locator = stable_temperature_device_locator(path)
                classification: Optional[str] = None
                rejection = "unsupported_family"
                is_accepted = False
                unit = {
                    "temp": "celsius",
                    "fan": "rpm",
                    "pwm": "raw_pwm",
                    "voltage": "volts",
                    "current": "amps",
                    "power": "watts",
                }[family]
                if raw_value is None:
                    rejection = "sentinel_or_invalid"
                elif family == "fan":
                    classification = _fan_classification(label)
                    if provider.lower() in _GPU_HWMON_PROVIDERS:
                        rejection = "gpu_owned_source"
                    elif not label:
                        rejection = "unlabeled"
                    elif not classification:
                        rejection = "unsupported_semantics"
                    else:
                        probe = {"family": family}
                        is_accepted = normalize_direct_hwmon_value(probe, raw_value) is not None
                        rejection = "" if is_accepted else "sentinel_or_invalid"
                elif family == "voltage":
                    classification = _voltage_classification(label)
                    if not label:
                        rejection = "unlabeled"
                    elif not classification:
                        rejection = "unsupported_semantics"
                    else:
                        probe = {"family": family}
                        is_accepted = normalize_direct_hwmon_value(probe, raw_value) is not None
                        rejection = "" if is_accepted else "sentinel_or_invalid"
                elif family == "temp":
                    info = platform_hwmon_classification(provider, label)
                    classification = str(info.get("classification") or "")
                    temp_c = normalize_platform_temperature_c(raw_value)
                    valid_value = valid_platform_temperature(provider, label, temp_c)
                    handled_by_temperature_collector = bool(
                        valid_value
                        and info.get("confidence") in {"high", "medium"}
                        and classification != "generic_channel"
                    )
                    if handled_by_temperature_collector:
                        rejection = "handled_by_existing_temperature_collector"
                    elif not valid_value:
                        rejection = "sentinel_or_invalid"
                    else:
                        rejection = "unlabeled" if not label else "unsupported_semantics"
                candidate = {
                    "family": family,
                    "provider": provider,
                    "driver": driver,
                    "resolved_parent_device": str(Path(locator)),
                    "stable_device_locator": locator,
                    "channel": channel,
                    "raw_label": label,
                    "input_source": path.name,
                    "path": str(path),
                    "readable_value": raw_value,
                    "unit": unit,
                    "accepted": is_accepted,
                }
                if classification:
                    candidate["semantic_classification"] = classification
                if rejection:
                    candidate["rejection_reason"] = rejection
                candidates.append(candidate)
                if is_accepted and family in {"fan", "voltage"}:
                    pending.append({
                        "kind": "direct_hwmon",
                        "path": str(path),
                        "label": label,
                        "raw_label": label,
                        "normalized_label": _normalized_label(label),
                        "provider": provider,
                        "driver": driver,
                        "family": family,
                        "unit": unit,
                        "semantic_classification": classification,
                        "component_classification": classification,
                        "stable_device_locator": locator,
                        "sensor_index": channel,
                        "channel": channel,
                        "kernel_channel": path.name,
                        "source_scope": "direct_platform_hwmon",
                        "measurement_semantics": "measured_or_provider_reported",
                    })

    pending.sort(key=lambda item: (
        str(item.get("semantic_classification") or ""),
        str(item.get("stable_device_locator") or ""),
        str(item.get("provider") or ""),
        int(item.get("sensor_index", 0) or 0),
        str(item.get("normalized_label") or ""),
    ))
    counts: Dict[str, int] = {}
    for source in pending:
        semantic = str(source["semantic_classification"])
        index = counts.get(semantic, 0)
        counts[semantic] = index + 1
        suffix = "rpm" if source["family"] == "fan" else "v"
        source["key"] = f"{semantic}_{index}_{suffix}"
        source["metric"] = "fan_rpm" if source["family"] == "fan" else "voltage_v"
        accepted.append(source)
    candidates.sort(key=lambda item: (
        str(item.get("family") or ""), str(item.get("stable_device_locator") or ""),
        int(item.get("channel", 0) or 0), str(item.get("raw_label") or ""),
    ))
    return accepted, candidates


def read_direct_hwmon_values(
    sources: List[TelemetrySource], read_text: ReadText
) -> Dict[str, Optional[float]]:
    values: Dict[str, Optional[float]] = {}
    for source in sources:
        value = normalize_direct_hwmon_value(source, read_text(Path(str(source.get("path") or ""))))
        if value is not None:
            values[str(source["key"])] = value
    return values
