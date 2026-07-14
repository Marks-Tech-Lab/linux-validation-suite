#!/usr/bin/env python3
"""Pure system identity formatting helpers."""

from __future__ import annotations

from typing import Dict


DMI_KEYS = (
    "sys_vendor",
    "product_name",
    "product_version",
    "product_family",
    "product_serial",
    "board_vendor",
    "board_name",
    "board_version",
    "board_asset_tag",
    "board_serial",
    "bios_vendor",
    "bios_version",
    "bios_date",
)


def normalize_dmi_sysfs_value(value: object) -> str:
    text = str(value or "").strip()
    if text.lower() in {"none", "unknown", "to be filled by o.e.m.", "default string"}:
        return ""
    return text


def build_motherboard_info(dmi: Dict[str, str]) -> Dict[str, str]:
    system_vendor = dmi.get("sys_vendor", "")
    board_vendor = dmi.get("board_vendor", "")
    manufacturer = system_vendor or board_vendor
    board_name = dmi.get("board_name", "") or dmi.get("product_name", "")
    version = dmi.get("board_version", "") or dmi.get("product_version", "")
    product = " ".join(part for part in (manufacturer, board_name) if part).strip() or board_name
    description_parts = [part for part in (product, version) if part]
    return {
        "Manufacturer": manufacturer,
        "BoardVendor": board_vendor,
        "SystemVendor": system_vendor,
        "BoardName": board_name,
        "Product": product,
        "ProductRaw": board_name,
        "DisplayName": product,
        "Version": version,
        "Description": " ".join(description_parts),
        "AssetTag": dmi.get("board_asset_tag", ""),
        "SerialNumber": dmi.get("board_serial", ""),
    }


def build_bios_info(dmi: Dict[str, str]) -> Dict[str, str]:
    vendor = dmi.get("bios_vendor", "")
    version = dmi.get("bios_version", "")
    full_name = " ".join(part for part in (vendor, version) if part)
    return {
        "Name": version or full_name or vendor,
        "Vendor": vendor,
        "Version": version,
        "FullName": full_name or version or vendor,
        "ReleaseDate": dmi.get("bios_date", ""),
        "SerialNumber": dmi.get("product_serial", ""),
    }


def parse_os_release_pretty_name(text: object) -> str:
    values: Dict[str, str] = {}
    for line in str(text or "").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"')
    return values.get("PRETTY_NAME") or values.get("NAME") or ""


def build_linux_os_name(distro_name: str, platform_system: str, platform_release: str) -> str:
    base = str(distro_name or "").strip() or str(platform_system or "").strip()
    if "linux" not in base.lower():
        base = f"{base} Linux"
    return f"{base} {str(platform_release or '').strip()}".strip()
