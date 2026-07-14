"""Shared additive PCIe link evidence helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, Optional


ReadText = Callable[[Path], Optional[str]]


def read_pci_slot_name(device_dir: Path, read_text: ReadText) -> str:
    uevent = read_text(device_dir / "uevent") or ""
    for line in uevent.splitlines():
        if line.startswith("PCI_SLOT_NAME="):
            return line.split("=", 1)[1].strip()
    return device_dir.name if ":" in device_dir.name else ""


def normalize_pci_slot_text(slot: object) -> str:
    return str(slot or "").strip().lower()


def pcie_link_matches_slot(pcie_link: Dict[str, Any], slot: object) -> bool:
    link_slot = normalize_pci_slot_text(pcie_link.get("PciSlot"))
    gpu_slot = normalize_pci_slot_text(slot)
    if not pcie_link:
        return False
    if link_slot and gpu_slot:
        return link_slot == gpu_slot
    return True


def trusted_pcie_link_for_slot(pcie_link: Dict[str, Any], slot: object) -> Dict[str, Any]:
    if not pcie_link_matches_slot(pcie_link, slot):
        return {}
    return dict(pcie_link)


def read_pcie_link_info(device_dir: Path, read_text: ReadText) -> Dict[str, Any]:
    values = {
        "MaxLinkSpeed": read_text(device_dir / "max_link_speed"),
        "CurrentLinkSpeed": read_text(device_dir / "current_link_speed"),
        "MaxLinkWidth": read_text(device_dir / "max_link_width"),
        "CurrentLinkWidth": read_text(device_dir / "current_link_width"),
    }
    clean = {key: str(value).strip() for key, value in values.items() if str(value or "").strip()}
    if not clean:
        return {}
    clean["SysfsPath"] = str(device_dir)
    slot = read_pci_slot_name(device_dir, read_text)
    if slot:
        clean["PciSlot"] = slot
    return clean


def pcie_device_dir_for_path(path: Path) -> Optional[Path]:
    try:
        resolved = path.resolve()
    except Exception:
        resolved = path
    for candidate in (resolved, *resolved.parents):
        if (
            (candidate / "max_link_speed").exists()
            or (candidate / "current_link_speed").exists()
            or (candidate / "max_link_width").exists()
            or (candidate / "current_link_width").exists()
        ):
            return candidate
    return None


def pcie_link_info_for_path(path: Path, read_text: ReadText) -> Dict[str, Any]:
    device_dir = pcie_device_dir_for_path(path)
    if device_dir is None:
        return {}
    return read_pcie_link_info(device_dir, read_text)
