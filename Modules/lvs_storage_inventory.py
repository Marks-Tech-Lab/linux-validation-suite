#!/usr/bin/env python3
"""Pure-ish storage inventory helpers for Linux Validation Suite."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .lvs_pcie_link import pcie_link_info_for_path
from .lvs_storage_health import StorageHealthEnricher


ReadSysfs = Callable[[Path], Optional[str]]


def clean_storage_value(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.lower() in {"unknown", "none", "not specified", "not available"}:
        return ""
    return re.sub(r"\s+", " ", text)


def read_text_sysfs(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="ignore").strip()
    except Exception:
        return None


def block_device_capacity_gb(block_dir: Path, read_sysfs: ReadSysfs = read_text_sysfs) -> int:
    text = read_sysfs(block_dir / "size")
    if not text:
        return 0
    try:
        sectors = int(text)
    except Exception:
        return 0
    return int(round((sectors * 512) / (1024 ** 3)))


def storage_interface_type(name: str, block_dir: Path) -> str:
    if name.startswith("nvme"):
        return "NVMe"
    device_link = ""
    try:
        device_link = str((block_dir / "device").resolve()).lower()
    except Exception:
        device_link = ""
    if "usb" in device_link:
        return "USB"
    if "ata" in device_link or "sata" in device_link:
        return "SATA"
    if name.startswith("sd"):
        return "SCSI/SATA"
    if name.startswith("mmc"):
        return "eMMC/SD"
    return ""


def storage_media_type(
    name: str,
    block_dir: Path,
    interface_type: str,
    read_sysfs: ReadSysfs = read_text_sysfs,
) -> str:
    if name.startswith("nvme"):
        return "NVMe Drives"
    rotational = read_sysfs(block_dir / "queue" / "rotational")
    if rotational == "1":
        return "Hard Disk Drive"
    if rotational == "0":
        return "Solid State Drive"
    return interface_type or ""


def build_storage_device_entry(
    block_dir: Path,
    read_sysfs: ReadSysfs = read_text_sysfs,
) -> Dict[str, Any]:
    name = block_dir.name
    size_gb = block_device_capacity_gb(block_dir, read_sysfs)
    model = clean_storage_value(read_sysfs(block_dir / "device" / "model"))
    serial = clean_storage_value(read_sysfs(block_dir / "device" / "serial"))
    firmware = clean_storage_value(
        read_sysfs(block_dir / "device" / "firmware_rev")
        or read_sysfs(block_dir / "device" / "rev")
    )
    vendor = clean_storage_value(read_sysfs(block_dir / "device" / "vendor"))
    interface_type = storage_interface_type(name, block_dir)
    media_type = storage_media_type(name, block_dir, interface_type, read_sysfs)
    display_model = " ".join(part for part in (vendor, model) if part).strip() or model or name
    device_path = f"/dev/{name}"
    pcie_link = pcie_link_info_for_path(block_dir / "device", read_sysfs)
    entry = {
        "Model": display_model,
        "CapacityGB": size_gb,
        "SizeGB": size_gb,
        "TotalRead": "",
        "TotalWrite": "",
        "Hours": "",
        "Firmware": firmware,
        "Interface": interface_type,
        "InterfaceType": interface_type,
        "MediaType": media_type,
        "SerialNumber": serial,
        "DevicePath": device_path,
        "Name": name,
        "model": display_model,
        "capacity_gb": size_gb,
        "size_gb": size_gb,
        "total_read": "",
        "total_write": "",
        "hours": "",
        "firmware": firmware,
        "interface": interface_type,
        "interface_type": interface_type,
        "media_type": media_type,
        "serial_number": serial,
        "device_path": device_path,
    }
    if pcie_link:
        entry["PcieLink"] = pcie_link
        entry["PcieMaxLinkSpeed"] = pcie_link.get("MaxLinkSpeed", "")
        entry["PcieCurrentLinkSpeed"] = pcie_link.get("CurrentLinkSpeed", "")
        entry["PcieMaxLinkWidth"] = pcie_link.get("MaxLinkWidth", "")
        entry["PcieCurrentLinkWidth"] = pcie_link.get("CurrentLinkWidth", "")
        entry["PcieSlot"] = pcie_link.get("PciSlot", "")
    return entry


def collect_storage_info(
    sys_block: Path = Path("/sys/block"),
    read_sysfs: ReadSysfs = read_text_sysfs,
    *,
    health_enricher: Optional[StorageHealthEnricher] = None,
    privileged_helper_enabled: bool = False,
) -> List[Dict[str, Any]]:
    devices: List[Dict[str, Any]] = []
    if not sys_block.exists():
        return devices
    if health_enricher is None:
        enricher = StorageHealthEnricher(
            read_sysfs=read_sysfs,
            privileged_helper_enabled=privileged_helper_enabled,
        )
    else:
        enricher = health_enricher
    skip_prefixes = ("loop", "ram", "zram", "dm-", "md")
    for block_dir in sorted(sys_block.iterdir()):
        name = block_dir.name
        if name.startswith(skip_prefixes):
            continue
        if not (block_dir / "device").exists() and not name.startswith("nvme"):
            continue
        if block_device_capacity_gb(block_dir, read_sysfs) <= 0:
            continue
        entry = build_storage_device_entry(block_dir, read_sysfs)
        entry.update(enricher.enrich(block_dir, entry))
        devices.append(entry)
    return devices
