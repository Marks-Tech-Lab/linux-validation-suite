#!/usr/bin/env python3
"""GPU target inventory and selection helpers."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .lvs_gpu_identity import gpu_vendor_name, normalize_pci_id, normalize_pci_slot


CommandExists = Callable[[str], bool]
CommandEnv = Callable[[], Dict[str, str]]
PciNameLookup = Callable[[str, str], Optional[str]]
SafeReadInt = Callable[[Path], Optional[int]]


def discover_platform_gpu_devices(
    sys_platform: Path = Path("/sys/bus/platform/devices"),
) -> List[Dict[str, Any]]:
    devices: List[Dict[str, Any]] = []
    for device in sorted(sys_platform.iterdir() if sys_platform.exists() else []):
        values: Dict[str, str] = {}
        try:
            for line in (device / "uevent").read_text(encoding="utf-8", errors="ignore").splitlines():
                if "=" not in line:
                    continue
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
        except Exception:
            continue
        driver = values.get("DRIVER", "")
        of_name = values.get("OF_NAME", "")
        compatibles = [
            value
            for key, value in sorted(values.items())
            if key.startswith("OF_COMPATIBLE_") and key != "OF_COMPATIBLE_N" and value
        ]
        if of_name.lower() != "gpu" and driver.lower() not in {"adreno", "panfrost", "panthor", "lima"}:
            continue
        devices.append(
            {
                "platform_name": device.name,
                "path": str(device.resolve()),
                "driver": driver,
                "of_name": of_name,
                "of_fullname": values.get("OF_FULLNAME", ""),
                "modalias": values.get("MODALIAS", ""),
                "compatible": compatibles,
            }
        )
    return devices


def dri_prime_selector(slot: Any) -> str:
    text = str(slot or "").strip()
    if not text:
        return ""
    return f"pci-{text.replace(':', '_').replace('.', '_')}"


def load_pci_device_names(
    paths: Optional[List[Path]] = None,
) -> Dict[str, Dict[str, str]]:
    names: Dict[str, Dict[str, str]] = {}
    for path in paths or [Path("/usr/share/hwdata/pci.ids"), Path("/usr/share/misc/pci.ids")]:
        if not path.exists():
            continue
        current_vendor: Optional[str] = None
        try:
            with path.open("r", encoding="utf-8", errors="ignore") as handle:
                for raw_line in handle:
                    line = raw_line.rstrip("\n")
                    if not line or line.startswith("#"):
                        continue
                    if not line.startswith("\t"):
                        parts = line.split(None, 1)
                        if len(parts) != 2 or len(parts[0]) != 4:
                            current_vendor = None
                            continue
                        current_vendor = parts[0].lower()
                        names.setdefault(current_vendor, {})
                        continue
                    if current_vendor is None or line.startswith("\t\t"):
                        continue
                    parts = line.strip().split(None, 1)
                    if len(parts) != 2 or len(parts[0]) != 4:
                        continue
                    names[current_vendor][parts[0].lower()] = parts[1].strip()
        except Exception:
            continue
        if names:
            break
    return names


def lookup_pci_device_name(
    pci_device_names: Dict[str, Dict[str, str]],
    vendor_id: Any,
    device_id: Any,
) -> Optional[str]:
    if not pci_device_names:
        return None
    return pci_device_names.get(normalize_pci_id(vendor_id), {}).get(normalize_pci_id(device_id))


def discover_nvidia_smi_gpus(
    command_exists: CommandExists,
    command_env: CommandEnv,
) -> List[Dict[str, Any]]:
    if not command_exists("nvidia-smi"):
        return []
    cmd = [
        "nvidia-smi",
        "--query-gpu=index,pci.bus_id,uuid,name,driver_version,memory.total",
        "--format=csv,noheader,nounits",
    ]
    try:
        completed = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
            env=command_env(),
        )
    except Exception:
        return []
    if completed.returncode != 0:
        return []
    gpus: List[Dict[str, Any]] = []
    for line in (completed.stdout or "").splitlines():
        parts = [item.strip() for item in line.split(",")]
        if len(parts) < 6:
            continue
        try:
            memory_mb = float(parts[5])
        except Exception:
            memory_mb = 0.0
        gpus.append(
            {
                "index": parts[0],
                "slot": normalize_pci_slot(parts[1]),
                "uuid": parts[2],
                "name": parts[3],
                "driver": parts[4],
                "memory_mb": memory_mb,
            }
        )
    return gpus


def discover_gpu_cards(
    *,
    sys_drm: Path = Path("/sys/class/drm"),
    pci_name_lookup: Optional[PciNameLookup] = None,
    safe_read_int: Optional[SafeReadInt] = None,
    nvidia_smi_gpus: Optional[List[Dict[str, Any]]] = None,
    sys_platform: Path = Path("/sys/bus/platform/devices"),
) -> List[Dict[str, Any]]:
    cards: List[Dict[str, Any]] = []
    gpu_index = 0
    read_int = safe_read_int or _default_safe_read_int
    lookup_name = pci_name_lookup or (lambda _vendor_id, _device_id: None)
    for card in sorted(sys_drm.glob("card[0-9]*")):
        if "-" in card.name:
            continue
        device_dir = card / "device"
        vendor = ""
        device = ""
        slot = ""
        driver = ""
        of_name = ""
        of_fullname = ""
        drm_compatible: List[str] = []
        try:
            for line in (device_dir / "uevent").read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.startswith("PCI_ID="):
                    pci_id = line.split("=", 1)[1].strip()
                    if ":" in pci_id:
                        vendor, device = [part.strip() for part in pci_id.split(":", 1)]
                if line.startswith("PCI_SLOT_NAME="):
                    slot = line.split("=", 1)[1].strip()
                if line.startswith("DRIVER="):
                    driver = line.split("=", 1)[1].strip()
                if line.startswith("OF_NAME="):
                    of_name = line.split("=", 1)[1].strip()
                if line.startswith("OF_FULLNAME="):
                    of_fullname = line.split("=", 1)[1].strip()
                if line.startswith("OF_COMPATIBLE_") and not line.startswith("OF_COMPATIBLE_N="):
                    drm_compatible.append(line.split("=", 1)[1].strip())
        except Exception:
            pass
        vendor_name = gpu_vendor_name(vendor)
        device_code = device.upper() if device else ""
        vendor_id = normalize_pci_id(vendor)
        if vendor_id == "1a03" or driver.strip().lower() == "ast":
            continue
        resolved_name = lookup_name(vendor_id, device_code)
        vram_total_value = read_int(device_dir / "mem_info_vram_total")
        vram_used_value = read_int(device_dir / "mem_info_vram_used")
        cards.append(
            {
                "card": card.name,
                "slot": slot,
                "vram_total": vram_total_value or 0,
                "vram_total_source": "drm_mem_info_vram_total" if vram_total_value is not None else "",
                "vram_used": vram_used_value,
                "vram_used_source": "drm_mem_info_vram_used" if vram_used_value is not None else "",
                "dri_prime": dri_prime_selector(slot),
                "driver": driver,
                "drm_driver": driver,
                "drm_device_role": "display_controller" if "display" in of_name.lower() else "gpu",
                "drm_of_name": of_name,
                "drm_of_fullname": of_fullname,
                "drm_compatible": drm_compatible,
                "vendor": vendor_name,
                "vendor_id": vendor_id,
                "device": device_code,
                "name": resolved_name or f"{vendor_name} GPU {device_code}".strip(),
                "target_id": slot or card.name,
                "gpu_index": gpu_index,
            }
        )
        gpu_index += 1
    platform_gpus = discover_platform_gpu_devices(sys_platform)
    non_pci_cards = [card for card in cards if not str(card.get("slot") or "").strip()]
    if len(platform_gpus) == 1 and len(non_pci_cards) == 1:
        platform_gpu = platform_gpus[0]
        card = non_pci_cards[0]
        platform_driver = str(platform_gpu.get("driver") or "")
        compatible = list(platform_gpu.get("compatible") or [])
        card.update(
            {
                "driver": platform_driver or str(card.get("driver") or ""),
                "platform_gpu_driver": platform_driver,
                "platform_gpu_compatible": compatible,
                "platform_gpu_path": str(platform_gpu.get("path") or ""),
                "platform_gpu_name": str(platform_gpu.get("platform_name") or ""),
                "platform_gpu_of_name": str(platform_gpu.get("of_name") or ""),
                "platform_gpu_of_fullname": str(platform_gpu.get("of_fullname") or ""),
                "platform_gpu_modalias": str(platform_gpu.get("modalias") or ""),
                "platform_gpu_identity_source": "unique_platform_gpu_device",
                "gpu_identity_source": "platform_device_tree",
                "gpu_device_role": "3d_gpu",
                "physical_gpu_id": f"platform:{platform_gpu.get('platform_name') or Path(str(platform_gpu.get('path') or '')).name}",
            }
        )
        if str(card.get("name") or "").strip().lower() in {"", "unknown gpu"} and platform_driver:
            card["name"] = f"{platform_driver.title()} platform GPU"
        if str(card.get("vendor") or "").strip().lower() in {"", "unknown"} and any(
            value.lower().startswith("qcom,") for value in compatible
        ):
            card["vendor"] = "Qualcomm"
    associated_platform_paths = {
        str(card.get("platform_gpu_path") or "") for card in cards if card.get("platform_gpu_path")
    }
    for platform_gpu in platform_gpus:
        platform_path = str(platform_gpu.get("path") or "")
        if platform_path in associated_platform_paths:
            continue
        compatible = list(platform_gpu.get("compatible") or [])
        platform_driver = str(platform_gpu.get("driver") or "")
        vendor_name = "Qualcomm" if any(value.lower().startswith("qcom,") for value in compatible) else "Unknown"
        cards.append(
            {
                "card": "",
                "slot": "",
                "vram_total": 0,
                "vram_total_source": "",
                "vram_used": None,
                "vram_used_source": "",
                "dri_prime": "",
                "driver": platform_driver,
                "drm_driver": "",
                "drm_device_role": "",
                "vendor": vendor_name,
                "vendor_id": "",
                "device": "",
                "name": f"{platform_driver.title()} platform GPU" if platform_driver else "Platform GPU",
                "target_id": f"platform:{platform_gpu.get('platform_name') or Path(platform_path).name}",
                "gpu_index": gpu_index,
                "platform_gpu_driver": platform_driver,
                "platform_gpu_compatible": compatible,
                "platform_gpu_path": platform_path,
                "platform_gpu_name": str(platform_gpu.get("platform_name") or ""),
                "platform_gpu_of_name": str(platform_gpu.get("of_name") or ""),
                "platform_gpu_of_fullname": str(platform_gpu.get("of_fullname") or ""),
                "platform_gpu_modalias": str(platform_gpu.get("modalias") or ""),
                "platform_gpu_identity_source": "platform_gpu_device",
                "gpu_identity_source": "platform_device_tree",
                "gpu_device_role": "3d_gpu",
                "physical_gpu_id": f"platform:{platform_gpu.get('platform_name') or Path(platform_path).name}",
            }
        )
        gpu_index += 1
    cards = [
        card
        for card in cards
        if card.get("gpu_device_role") == "3d_gpu"
        or card.get("drm_device_role") != "display_controller"
    ]
    for index, card in enumerate(cards):
        card["gpu_index"] = index
    nvidia_by_slot = {
        str(gpu.get("slot", "") or "").lower(): gpu
        for gpu in nvidia_smi_gpus or []
        if gpu.get("slot")
    }
    for card in cards:
        slot = str(card.get("slot", "") or "").lower()
        if not slot:
            continue
        nvidia_gpu = nvidia_by_slot.get(slot)
        if not nvidia_gpu:
            continue
        if int(card.get("vram_total") or 0) <= 0:
            memory_mb = float(nvidia_gpu.get("memory_mb", 0.0) or 0.0)
            if memory_mb > 0:
                card["vram_total"] = int(memory_mb * 1024 * 1024)
                card["vram_total_source"] = "nvidia_smi_memory_total"
        if str(card.get("vendor", "") or "").strip().lower() == "nvidia":
            card["name"] = str(nvidia_gpu.get("name", "") or card.get("name", ""))
            card["nvidia_index"] = str(nvidia_gpu.get("index", "") or "")
            card["nvidia_uuid"] = str(nvidia_gpu.get("uuid", "") or "")
        if not str(card.get("driver", "") or "").strip():
            card["driver"] = str(nvidia_gpu.get("driver", "") or "")
    return cards


def likely_discrete_gpu_cards(cards: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if len(cards) <= 1:
        return [] if cards and gpu_card_class(cards[0]) == "integrated" else cards[:]
    explicit_discrete = [card for card in cards if gpu_card_class(card) == "discrete"]
    if explicit_discrete:
        return explicit_discrete
    candidates = [card for card in cards if gpu_card_class(card) != "integrated"]
    max_vram = max((int(card.get("vram_total") or 0) for card in candidates), default=0)
    threshold = max(1024 ** 3, int(max_vram * 0.25)) if max_vram > 0 else 1024 ** 3
    discrete = [card for card in candidates if int(card.get("vram_total") or 0) >= threshold]
    return discrete or cards[:]


def gpu_card_class(card: Dict[str, Any]) -> str:
    authoritative_class = str(
        card.get("device_class")
        or card.get("DeviceClass")
        or card.get("vulkan_device_class")
        or ""
    ).strip().lower()
    if authoritative_class in {"integrated", "apu", "uma"}:
        return "integrated"
    if authoritative_class == "discrete":
        return "discrete"
    vendor = str(card.get("vendor", "") or "").strip().lower()
    driver = str(card.get("driver", "") or "").strip().lower()
    platform_driver = str(card.get("platform_gpu_driver", "") or "").strip().lower()
    identity = " ".join(
        str(card.get(key, "") or "").strip().lower()
        for key in ("vendor", "name", "driver", "platform_gpu_driver")
    )
    if vendor == "nvidia" or driver == "nvidia":
        return "discrete"
    if driver in {"i915", "xe", "adreno", "panfrost", "panthor", "lima"}:
        return "integrated"
    if platform_driver in {"adreno", "panfrost", "panthor", "lima"}:
        return "integrated"
    if any(token in identity for token in ("amd apu", "radeon graphics")):
        return "integrated"
    return ""


def enrich_gpu_cards_with_vulkan_device_classes(
    cards: List[Dict[str, Any]],
    devices: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Attach authoritative Vulkan physical-device class before selection."""
    from Modules.lvs_vulkan_targeting import vulkan_device_is_hardware_gpu, vulkan_device_pci_slot

    enriched = [dict(card) for card in cards]
    by_slot = {
        normalize_pci_slot(str(card.get("slot", "") or "")): card
        for card in enriched
        if normalize_pci_slot(str(card.get("slot", "") or ""))
    }
    for device in devices:
        if not vulkan_device_is_hardware_gpu(device):
            continue
        device_type = str(device.get("deviceType", "") or "").strip().lower()
        device_class = "integrated" if "integrated" in device_type else "discrete" if "discrete" in device_type else ""
        if not device_class:
            continue
        slot = vulkan_device_pci_slot(device, enriched)
        target = by_slot.get(normalize_pci_slot(slot)) if slot else None
        if target is None:
            vendor_id = normalize_pci_id(str(device.get("vendorID", "") or ""))
            device_id = normalize_pci_id(str(device.get("deviceID", "") or ""))
            candidates = [
                card for card in enriched
                if normalize_pci_id(str(card.get("vendor_id", "") or "")) == vendor_id
                and normalize_pci_id(str(card.get("device", "") or "")) == device_id
            ]
            target = candidates[0] if len(candidates) == 1 else None
        if target is not None:
            target["device_class"] = device_class
            target["device_class_source"] = "vulkan_physical_device_type"
    return enriched


def gpu_targets(selection: Any, cards: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not cards:
        return []
    mode = (str(selection or "all")).strip().lower()
    if mode == "all":
        return cards
    if mode in {"integrated_all", "igpu_all", "shared_all"}:
        return [card for card in cards if gpu_card_class(card) == "integrated"]
    if mode in {"discrete_all", "dgpu_all"}:
        return likely_discrete_gpu_cards(cards)
    if mode in {"discrete_max_vram", "dgpu_max_vram"}:
        candidates = likely_discrete_gpu_cards(cards)
        if not candidates:
            return []
        best = max(candidates, key=lambda card: (card["vram_total"], card["slot"]))
        return [best]
    if mode.startswith("slots:"):
        requested_slots = {
            item.strip().lower()
            for item in mode.split(":", 1)[1].split(",")
            if item.strip()
        }
        return [card for card in cards if card["slot"].lower() in requested_slots]
    if mode.startswith("cards:"):
        requested_cards = {
            item.strip().lower()
            for item in mode.split(":", 1)[1].split(",")
            if item.strip()
        }
        return [card for card in cards if card["card"].lower() in requested_cards]
    return cards


def gpu_target_summary(selection: Any) -> str:
    text = str(selection or "")
    mode = (text or "all").strip().lower()
    if mode == "all":
        return "all"
    if mode in {"integrated_all", "igpu_all", "shared_all"}:
        return "integrated_all"
    if mode in {"discrete_all", "dgpu_all"}:
        return "discrete_all"
    if mode in {"discrete_max_vram", "dgpu_max_vram"}:
        return "discrete_max_vram"
    if mode.startswith("slots:"):
        slot_list = [item.strip() for item in text.split(":", 1)[1].split(",") if item.strip()]
        return f"slots:{','.join(slot_list)}"
    if mode.startswith("cards:"):
        card_list = [item.strip() for item in text.split(":", 1)[1].split(",") if item.strip()]
        return f"cards:{','.join(card_list)}"
    return text or "all"


def gpu_target_display_label(card: Dict[str, Any]) -> str:
    memory_gib = round((int(card.get("vram_total") or 0) / (1024 ** 3)), 2) if card.get("vram_total") else 0
    slot = card.get("slot") or "no-pci-slot"
    return f"{card['card']} | {slot} | {card.get('vendor') or 'GPU'} | {memory_gib} GB"


def gpu_target_by_id(cards: List[Dict[str, Any]], target_id: Any) -> Optional[Dict[str, Any]]:
    normalized = str(target_id or "").strip().lower()
    for card in cards:
        if str(card.get("target_id", "") or "").lower() == normalized:
            return card
    return None


def _default_safe_read_int(path: Path) -> Optional[int]:
    try:
        return int(path.read_text(encoding="utf-8", errors="ignore").strip())
    except Exception:
        return None
