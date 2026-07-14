#!/usr/bin/env python3
"""GPU telemetry source discovery and sampling helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

from .lvs_gpu_identity import gpu_vendor_name
from .lvs_pcie_link import read_pcie_link_info
from .lvs_telemetry_cpu import read_energy_power_source, read_temperature_path
from .lvs_telemetry_sampling import (
    parse_gpu_clock_text,
    parse_percent_text,
    parse_power_text_w,
    parse_vram_used_gb_from_bytes_text,
)


ReadText = Callable[[Path], Optional[str]]
SensorLabel = Callable[[Path], str]
HwmonTempThresholds = Callable[[Path], tuple[Optional[float], Optional[float], str]]
CommandExists = Callable[[str], bool]
NvidiaGpuDiscovery = Callable[[], List[Dict[str, Any]]]
IntelGpuTopMetrics = Callable[[], Dict[str, Optional[float]]]


def gpu_temp_metric(label: str, hwmon_name: str = "", path: Optional[Path] = None) -> Optional[str]:
    if label == "edge" or label == "gpu":
        return "temp_core_c"
    if "junction" in label or "hotspot" in label:
        return "temp_hotspot_c"
    if label == "mem" or "memory" in label:
        return "temp_memory_c"
    hwmon_text = (hwmon_name or "").lower()
    if not label and path is not None and path.name == "temp1_input" and hwmon_text in {"i915", "xe", "amdgpu", "nouveau"}:
        return "temp_core_c"
    return None


def pci_slot_from_device_dir(device_dir: Path) -> str:
    try:
        for line in (device_dir / "uevent").read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("PCI_SLOT_NAME="):
                return line.split("=", 1)[1].strip()
    except Exception:
        pass
    return ""


def gpu_hwmon_dirs(
    card: Path,
    read_text: ReadText,
    hwmon_root: Path = Path("/sys/class/hwmon"),
) -> List[Path]:
    device_dir = card / "device"
    candidates: List[Path] = []
    for hwmon in sorted((device_dir / "hwmon").glob("hwmon*")):
        candidates.append(hwmon)
    slot = pci_slot_from_device_dir(device_dir)
    try:
        resolved_device = device_dir.resolve()
    except Exception:
        resolved_device = device_dir
    resolved_device_text = str(resolved_device)
    for hwmon in sorted(hwmon_root.glob("hwmon*")):
        if hwmon in candidates:
            continue
        try:
            resolved_hwmon = hwmon.resolve()
        except Exception:
            resolved_hwmon = hwmon
        resolved_hwmon_text = str(resolved_hwmon)
        if (
            resolved_device_text
            and (
                resolved_hwmon_text.startswith(resolved_device_text + "/")
                or resolved_hwmon_text == resolved_device_text
            )
        ):
            candidates.append(hwmon)
            continue
        if slot and slot in resolved_hwmon_text:
            candidates.append(hwmon)
    unique: List[Path] = []
    seen: set[str] = set()
    for hwmon in candidates:
        try:
            key = str(hwmon.resolve())
        except Exception:
            key = str(hwmon)
        if key in seen:
            continue
        seen.add(key)
        unique.append(hwmon)
    return unique


def intel_gpu_clock_path(device_dir: Path, read_text: ReadText) -> Optional[Path]:
    candidates = [
        device_dir / "gt" / "gt0" / "rps_cur_freq_mhz",
        device_dir / "gt" / "gt0" / "rps_cur_freq",
        device_dir / "gt_cur_freq_mhz",
        device_dir / "gt_cur_freq",
    ]
    for path in candidates:
        if read_text(path) is not None:
            return path
    for path in sorted(device_dir.glob("drm/card*/gt/gt*/rps_cur_freq_mhz")):
        if read_text(path) is not None:
            return path
    for path in sorted(device_dir.glob("drm/card*/gt/gt*/rps_cur_freq")):
        if read_text(path) is not None:
            return path
    return None


def gpu_voltage_metric(label: str) -> Optional[str]:
    normalized = (label or "").strip().lower()
    if normalized == "vddgfx":
        return "vddgfx_v"
    if normalized == "vddnb":
        return "vddnb_v"
    return None


def parse_voltage_text_v(raw: Any) -> Optional[float]:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        value = float(text)
    except Exception:
        return None
    if value > 100.0:
        value /= 1000.0
    return round(value, 3) if 0.0 < value < 10.0 else None


def discover_gpu_cards(
    drm_root: Path = Path("/sys/class/drm"),
) -> List[Dict[str, Any]]:
    def _read_sysfs(path: Path) -> Optional[str]:
        try:
            return path.read_text(encoding="utf-8", errors="ignore").strip()
        except Exception:
            return None

    cards: List[Dict[str, Any]] = []
    gpu_index = 0
    for card in sorted(drm_root.glob("card[0-9]*")):
        if "-" in card.name:
            continue
        device_dir = card / "device"
        slot = ""
        vendor = ""
        driver = ""
        try:
            for line in (device_dir / "uevent").read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.startswith("PCI_SLOT_NAME="):
                    slot = line.split("=", 1)[1].strip()
                elif line.startswith("PCI_ID="):
                    pci_id = line.split("=", 1)[1].strip()
                    if ":" in pci_id:
                        vendor = pci_id.split(":", 1)[0].strip()
                elif line.startswith("DRIVER="):
                    driver = line.split("=", 1)[1].strip()
        except Exception:
            pass
        vendor_id = vendor.lower().removeprefix("0x")
        if vendor_id == "1a03" or driver.strip().lower() == "ast":
            continue
        cards.append(
            {
                "card": card.name,
                "slot": slot,
                "vendor": gpu_vendor_name(vendor),
                "driver": driver,
                "gpu_index": gpu_index,
                "pcie_link": read_pcie_link_info(device_dir, _read_sysfs),
            }
        )
        gpu_index += 1
    return cards


def discover_gpu_sources(
    read_text: ReadText,
    sensor_label: SensorLabel,
    hwmon_temp_thresholds: HwmonTempThresholds,
    command_exists: CommandExists,
    discover_nvidia_smi_gpus: NvidiaGpuDiscovery,
    intel_gpu_top_json_sample_metrics: IntelGpuTopMetrics,
    drm_root: Path = Path("/sys/class/drm"),
    hwmon_root: Path = Path("/sys/class/hwmon"),
) -> List[Dict[str, Any]]:
    sources: List[Dict[str, Any]] = []
    gpu_index = 0
    for card in sorted(drm_root.glob("card[0-9]*")):
        if "-" in card.name:
            continue
        device_dir = card / "device"
        slot = pci_slot_from_device_dir(device_dir)
        hwmons = gpu_hwmon_dirs(card, read_text, hwmon_root)
        for hwmon in hwmons:
            hwmon_name = read_text(hwmon / "name") or ""
            for path in sorted(hwmon.glob("temp*_input")):
                if read_text(path) is None:
                    continue
                label = (sensor_label(path) or "").lower()
                metric = gpu_temp_metric(label, hwmon_name, path)
                if not metric:
                    continue
                warn_threshold_c, fail_threshold_c, threshold_source = hwmon_temp_thresholds(path)
                sources.append(
                    {
                        "kind": "gpu_sensor",
                        "path": str(path),
                        "label": f"{card.name} {label or path.name}".strip(),
                        "gpu_index": gpu_index,
                        "card": card.name,
                        "slot": slot.lower(),
                        "metric": metric,
                        "key": f"gpu_{gpu_index}_{metric}",
                        "warn_threshold_c": warn_threshold_c,
                        "fail_threshold_c": fail_threshold_c,
                        "threshold_source": threshold_source,
                    }
                )
            direct_power_found = False
            for pattern in ("power*_average", "power*_input"):
                for path in sorted(hwmon.glob(pattern)):
                    if read_text(path) is None:
                        continue
                    label = sensor_label(path) or "power"
                    direct_power_found = True
                    sources.append(
                        {
                            "kind": "gpu_sensor",
                            "path": str(path),
                            "label": f"{card.name} {label}".strip(),
                            "gpu_index": gpu_index,
                            "card": card.name,
                            "slot": slot.lower(),
                            "metric": "power_w",
                            "key": f"gpu_{gpu_index}_power_w",
                        }
                    )
            if not direct_power_found:
                for path in sorted(hwmon.glob("energy*_input")):
                    if read_text(path) is None:
                        continue
                    label = sensor_label(path) or path.name
                    sources.append(
                        {
                            "kind": "gpu_energy",
                            "path": str(path),
                            "label": f"{card.name} {label}".strip(),
                            "gpu_index": gpu_index,
                            "card": card.name,
                            "slot": slot.lower(),
                            "metric": "power_w",
                            "key": f"gpu_{gpu_index}_power_w",
                        }
                    )
            for path in sorted(hwmon.glob("in*_input")):
                if read_text(path) is None:
                    continue
                label = sensor_label(path) or path.name
                metric = gpu_voltage_metric(label)
                if not metric:
                    continue
                sources.append(
                    {
                        "kind": "gpu_sensor",
                        "path": str(path),
                        "label": f"{card.name} {label}".strip(),
                        "gpu_index": gpu_index,
                        "card": card.name,
                        "slot": slot.lower(),
                        "metric": metric,
                        "key": f"gpu_{gpu_index}_{metric}",
                    }
                )
        clock_path = device_dir / "pp_dpm_sclk"
        if read_text(clock_path) is not None:
            sources.append(_gpu_path_source(card.name, gpu_index, slot, clock_path, "clock_mhz", "pp_dpm_sclk"))
        intel_clock = intel_gpu_clock_path(device_dir, read_text)
        if intel_clock is not None:
            sources.append(_gpu_path_source(card.name, gpu_index, slot, intel_clock, "clock_mhz", "Intel GT current frequency"))
        memory_clock_path = device_dir / "pp_dpm_mclk"
        if read_text(memory_clock_path) is not None:
            sources.append(_gpu_path_source(card.name, gpu_index, slot, memory_clock_path, "memory_clock_mhz", "pp_dpm_mclk"))
        for metric_name, metric_key in (
            ("gpu_busy_percent", "busy_percent"),
            ("mem_busy_percent", "memory_busy_percent"),
            ("mem_info_vram_used", "vram_used_gb"),
        ):
            metric_path = device_dir / metric_name
            if read_text(metric_path) is None:
                continue
            sources.append(_gpu_path_source(card.name, gpu_index, slot, metric_path, metric_key, metric_name, kind="gpu_value"))
        gpu_index += 1

    cards = discover_gpu_cards(drm_root)
    slot_index_map = {
        (source.get("slot") or "").lower(): source.get("gpu_index")
        for source in cards
        if source.get("slot")
    }
    next_gpu_index = max((int(source["gpu_index"]) for source in sources), default=-1) + 1
    for gpu in discover_nvidia_smi_gpus():
        slot = (gpu.get("slot") or "").lower()
        mapped_gpu_index = slot_index_map.get(slot)
        if mapped_gpu_index is None:
            mapped_gpu_index = next_gpu_index
            next_gpu_index += 1
        label_prefix = gpu.get("name") or gpu.get("card") or f"GPU {mapped_gpu_index}"
        metric_specs = (
            ("temp_core_c", "temperature.gpu", "temperature"),
            ("power_w", "power.draw", "power"),
            ("clock_mhz", "clocks.current.graphics", "graphics clock"),
            ("memory_clock_mhz", "clocks.current.memory", "memory clock"),
            ("busy_percent", "utilization.gpu", "gpu utilization"),
            ("memory_busy_percent", "utilization.memory", "memory utilization"),
            ("vram_used_gb", "memory.used", "memory used"),
            ("fan_percent", "fan.speed", "fan speed"),
        )
        for metric, query_field, label in metric_specs:
            sources.append(
                {
                    "kind": "nvidia_smi",
                    "path": f"nvidia-smi:{slot or mapped_gpu_index}",
                    "label": f"{label_prefix} {label}",
                    "gpu_index": int(mapped_gpu_index),
                    "card": str(gpu.get("card", "") or ""),
                    "metric": metric,
                    "key": f"gpu_{mapped_gpu_index}_{metric}",
                    "slot": slot,
                    "query_field": query_field,
                }
            )
        for event_source in gpu.get("clock_event_reason_fields", []) or []:
            metric = str(event_source.get("metric") or "")
            query_field = str(event_source.get("query_field") or "")
            if not metric or not query_field:
                continue
            sources.append(
                {
                    "kind": "nvidia_smi",
                    "path": f"nvidia-smi:{slot or mapped_gpu_index}",
                    "label": f"{label_prefix} {event_source.get('label') or metric}",
                    "gpu_index": int(mapped_gpu_index),
                    "card": str(gpu.get("card", "") or ""),
                    "metric": metric,
                    "key": f"gpu_{mapped_gpu_index}_{metric}",
                    "slot": slot,
                    "query_field": query_field,
                    "evidence_only": True,
                }
            )
        if gpu.get("memory_temperature_c") is not None:
            sources.append(
                {
                    "kind": "nvidia_smi",
                    "path": f"nvidia-smi:{slot or mapped_gpu_index}",
                    "label": f"{label_prefix} memory temperature",
                    "gpu_index": int(mapped_gpu_index),
                    "card": str(gpu.get("card", "") or ""),
                    "metric": "temp_memory_c",
                    "key": f"gpu_{mapped_gpu_index}_temp_memory_c",
                    "slot": slot,
                    "query_field": "temperature.memory",
                }
            )

    intel_cards = [
        card
        for card in cards
        if str(card.get("vendor", "") or "").strip().lower() == "intel"
    ]
    if len(intel_cards) == 1 and command_exists("intel_gpu_top") and intel_gpu_top_json_sample_metrics():
        card = intel_cards[0]
        mapped_gpu_index = int(card.get("gpu_index", 0) or 0)
        label_prefix = card.get("slot") or card.get("card") or f"GPU {mapped_gpu_index}"
        sources.append(
            {
                "kind": "intel_gpu_top",
                "path": "intel_gpu_top:-J -o -",
                "label": f"{label_prefix} Intel engine busy",
                "gpu_index": mapped_gpu_index,
                "metric": "busy_percent",
                "key": f"gpu_{mapped_gpu_index}_busy_percent",
                "slot": str(card.get("slot", "") or "").lower(),
            }
        )
    return sources


def _gpu_path_source(
    card_name: str,
    gpu_index: int,
    slot: str,
    path: Path,
    metric: str,
    label: str,
    *,
    kind: str = "gpu_clock",
) -> Dict[str, Any]:
    return {
        "kind": kind,
        "path": str(path),
        "label": f"{card_name} {label}",
        "gpu_index": gpu_index,
        "card": card_name,
        "slot": slot.lower(),
        "metric": metric,
        "key": f"gpu_{gpu_index}_{metric}",
    }


def read_gpu_clock(path: Path, read_text: ReadText) -> Optional[float]:
    raw = read_text(path)
    if raw is None:
        return None
    return parse_gpu_clock_text(raw)


def read_gpu_values(
    gpu_sources: Iterable[Dict[str, Any]],
    read_text: ReadText,
    read_text_sudo: ReadText,
    energy_source_state: Dict[str, Dict[str, float]],
    nvidia_snapshot: Dict[str, Dict[str, Optional[float]]],
    intel_gpu_top_snapshot: Dict[int, Dict[str, Optional[float]]],
    sample_time: Optional[float] = None,
) -> Dict[str, Optional[float]]:
    values: Dict[str, Optional[float]] = {}
    for source in gpu_sources:
        metric = source.get("metric")
        value: Optional[float] = None
        if source["kind"] == "nvidia_smi":
            slot = str(source.get("slot") or "").lower()
            nvidia_values = nvidia_snapshot.get(slot, {})
            value = nvidia_values.get(metric)
        elif source["kind"] == "intel_gpu_top":
            intel_values = intel_gpu_top_snapshot.get(int(source.get("gpu_index", 0)), {})
            value = intel_values.get(metric)
        elif source["kind"] == "gpu_energy":
            value = None if sample_time is None else read_energy_power_source(
                source,
                sample_time,
                energy_source_state,
                read_text,
                read_text_sudo,
                max_watts=2000.0,
            )
        elif source["metric"] in {"temp_core_c", "temp_hotspot_c", "temp_memory_c"}:
            value = read_temperature_path(Path(str(source.get("path") or "")), read_text)
        elif source["metric"] == "power_w":
            raw = read_text(Path(str(source.get("path") or "")))
            if raw is not None:
                value = parse_power_text_w(raw, max_watts=2000.0)
        elif source["metric"] in {"clock_mhz", "memory_clock_mhz"}:
            value = read_gpu_clock(Path(str(source.get("path") or "")), read_text)
        elif source["metric"] in {"busy_percent", "memory_busy_percent"}:
            raw = read_text(Path(str(source.get("path") or "")))
            if raw is not None:
                value = parse_percent_text(raw)
        elif source["metric"] == "fan_percent":
            raw = read_text(Path(str(source.get("path") or "")))
            if raw is not None:
                value = parse_percent_text(raw)
        elif source["metric"] == "vram_used_gb":
            raw = read_text(Path(str(source.get("path") or "")))
            if raw is not None:
                value = parse_vram_used_gb_from_bytes_text(raw)
        elif source["metric"] in {"vddgfx_v", "vddnb_v"}:
            raw = read_text(Path(str(source.get("path") or "")))
            if raw is not None:
                value = parse_voltage_text_v(raw)
        if value is not None:
            values[str(source["key"])] = value
    return values
