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
        except Exception:
            pass
        vendor_name = gpu_vendor_name(vendor)
        device_code = device.upper() if device else ""
        vendor_id = normalize_pci_id(vendor)
        if vendor_id == "1a03" or driver.strip().lower() == "ast":
            continue
        resolved_name = lookup_name(vendor_id, device_code)
        cards.append(
            {
                "card": card.name,
                "slot": slot,
                "vram_total": read_int(device_dir / "mem_info_vram_total") or 0,
                "dri_prime": dri_prime_selector(slot),
                "driver": driver,
                "vendor": vendor_name,
                "vendor_id": vendor_id,
                "device": device_code,
                "name": resolved_name or f"{vendor_name} GPU {device_code}".strip(),
                "target_id": slot or card.name,
                "gpu_index": gpu_index,
            }
        )
        gpu_index += 1
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
        if str(card.get("vendor", "") or "").strip().lower() == "nvidia":
            card["name"] = str(nvidia_gpu.get("name", "") or card.get("name", ""))
            card["nvidia_index"] = str(nvidia_gpu.get("index", "") or "")
            card["nvidia_uuid"] = str(nvidia_gpu.get("uuid", "") or "")
        if not str(card.get("driver", "") or "").strip():
            card["driver"] = str(nvidia_gpu.get("driver", "") or "")
    return cards


def likely_discrete_gpu_cards(cards: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if len(cards) <= 1:
        return cards[:]
    explicit_discrete = [card for card in cards if gpu_card_class(card) == "discrete"]
    if explicit_discrete:
        return explicit_discrete
    candidates = [card for card in cards if gpu_card_class(card) != "integrated"]
    max_vram = max((int(card.get("vram_total") or 0) for card in candidates), default=0)
    threshold = max(1024 ** 3, int(max_vram * 0.25)) if max_vram > 0 else 1024 ** 3
    discrete = [card for card in candidates if int(card.get("vram_total") or 0) >= threshold]
    return discrete or cards[:]


def gpu_card_class(card: Dict[str, Any]) -> str:
    vendor = str(card.get("vendor", "") or "").strip().lower()
    driver = str(card.get("driver", "") or "").strip().lower()
    if vendor == "nvidia" or driver == "nvidia":
        return "discrete"
    return ""


def gpu_targets(selection: Any, cards: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not cards:
        return []
    mode = (str(selection or "all")).strip().lower()
    if mode == "all":
        return cards
    if mode in {"discrete_all", "dgpu_all"}:
        discrete_cards = likely_discrete_gpu_cards(cards)
        return discrete_cards or cards
    if mode in {"discrete_max_vram", "dgpu_max_vram"}:
        candidates = likely_discrete_gpu_cards(cards) or cards
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
