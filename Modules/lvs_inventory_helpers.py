#!/usr/bin/env python3
"""Pure hardware inventory parsing/normalization helpers."""

from __future__ import annotations

import re
from typing import Any, Dict, List


def clean_dmi_value(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.lower() in {
        "unknown",
        "not specified",
        "not provided",
        "none",
        "n/a",
        "to be filled by o.e.m.",
        "default string",
        "<redacted>",
        "0000",
        "00000000",
        "ffffffff",
    }:
        return ""
    compact = re.sub(r"[\s:_-]+", "", text).lower()
    if compact and set(compact) in ({"0"}, {"f"}):
        return ""
    return text


def memory_module_display_part_number(manufacturer: Any, part_number: Any) -> str:
    manufacturer_text = clean_dmi_value(manufacturer)
    part_text = clean_dmi_value(part_number)
    if manufacturer_text and part_text:
        if part_text.lower().startswith(manufacturer_text.lower()):
            return part_text
        return f"{manufacturer_text} {part_text}"
    return part_text or manufacturer_text


def parse_memory_capacity_gb(value: Any) -> int:
    text = str(value or "").strip().lower()
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(gib|gb|mib|mb)", text)
    if not match:
        return 0
    number = float(match.group(1))
    unit = match.group(2)
    if unit in {"mib", "mb"}:
        number /= 1024.0
    return int(round(number))


def parse_memory_speed_mhz(value: Any) -> int:
    text = str(value or "").strip().lower()
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(mt/s|mhz)?", text)
    if not match:
        return 0
    return int(round(float(match.group(1))))


def build_memory_speed_summary(modules: List[Dict[str, Any]]) -> Dict[str, Any]:
    operating_values = sorted(
        {
            int(module.get("OperatingSpeedMTs") or 0)
            for module in modules
            if int(module.get("OperatingSpeedMTs") or 0) > 0
        }
    )
    configured_values = sorted(
        {
            int(module.get("ConfiguredSpeedMTs") or 0)
            for module in modules
            if int(module.get("ConfiguredSpeedMTs") or 0) > 0
        }
    )
    rated_values = sorted(
        {
            int(module.get("RatedSpeedMTs") or 0)
            for module in modules
            if int(module.get("RatedSpeedMTs") or 0) > 0
        }
    )
    return {
        "ModuleCount": len(modules),
        "OperatingSpeedMTs": operating_values[0] if len(operating_values) == 1 else 0,
        "OperatingSpeedValuesMTs": operating_values,
        "ConfiguredSpeedMTs": configured_values[0] if len(configured_values) == 1 else 0,
        "ConfiguredSpeedValuesMTs": configured_values,
        "RatedSpeedMTs": rated_values[0] if len(rated_values) == 1 else 0,
        "RatedSpeedValuesMTs": rated_values,
        "MixedOperatingSpeeds": len(operating_values) > 1,
        "Source": "memory module inventory",
    }


def memory_module_has_basic_value(module: Dict[str, Any]) -> bool:
    return any(
        str(module.get(key) or "").strip()
        for key in ("position", "manufacturer", "part_number", "size", "type", "base_speed")
    )


def apply_inxi_memory_fields(module: Dict[str, Any], text: Any, field_pattern: re.Pattern[str]) -> None:
    for key, value in field_pattern.findall(str(text or "")):
        normalized_key = key.lower()
        cleaned = clean_dmi_value(value)
        if not cleaned:
            continue
        if normalized_key == "type":
            module["type"] = cleaned
        elif normalized_key == "size":
            module["size"] = cleaned
        elif normalized_key == "speed":
            module["base_speed"] = cleaned
        elif normalized_key == "volts":
            module["voltage"] = cleaned
        elif normalized_key == "manufacturer":
            module["manufacturer"] = cleaned
        elif normalized_key in {"part-no", "part"}:
            module["part_number"] = cleaned
        elif normalized_key == "serial":
            module["serial_number"] = cleaned


def parse_inxi_memory_modules(text: Any) -> List[Dict[str, Any]]:
    modules: List[Dict[str, Any]] = []
    current: Dict[str, Any] | None = None

    def flush() -> None:
        nonlocal current
        if not current:
            return
        if memory_module_has_basic_value(current):
            current["module_number"] = len(modules)
            modules.append(current)
        current = None

    device_pattern = re.compile(r"^\s*Device-\d+:\s+(\S+)\s*(.*)$", re.IGNORECASE)
    field_pattern = re.compile(
        r"\b(type|size|speed|volts|manufacturer|part-no|part|serial):\s+(.+?)(?=\s+\b(?:type|size|speed|volts|manufacturer|part-no|part|serial):|$)",
        re.IGNORECASE,
    )
    for raw_line in str(text or "").splitlines():
        line = raw_line.rstrip()
        match = device_pattern.match(line)
        if match:
            flush()
            current = {
                "module_number": len(modules),
                "type": "",
                "form_factor": "",
                "manufacturer": "",
                "chip_manufacturer": "",
                "part_number": "",
                "serial_number": "",
                "size": "",
                "timing": "",
                "base_speed": "",
                "position": clean_dmi_value(match.group(1)),
                "bank_locator": "",
                "voltage": "",
                "command_rate": 0,
                "ecc": False,
                "source": "inxi",
            }
            apply_inxi_memory_fields(current, match.group(2), field_pattern)
            continue
        if current is not None:
            apply_inxi_memory_fields(current, line, field_pattern)
    flush()
    return modules


def parse_dmidecode_memory_modules(text: Any) -> List[Dict[str, Any]]:
    modules: List[Dict[str, Any]] = []
    current: Dict[str, str] = {}

    def flush() -> None:
        nonlocal current
        if not current:
            return
        if current.get("_section") != "memory_device":
            current = {}
            return
        size = clean_dmi_value(current.get("Size", ""))
        if not size or size.lower().startswith("no module"):
            current = {}
            return
        manufacturer = clean_dmi_value(current.get("Manufacturer", ""))
        part_number = clean_dmi_value(current.get("Part Number", ""))
        serial_number = clean_dmi_value(current.get("Serial Number", ""))
        locator = clean_dmi_value(current.get("Locator", "")) or f"DIMM {len(modules)}"
        bank_locator = clean_dmi_value(current.get("Bank Locator", ""))
        position = locator
        if bank_locator and bank_locator.lower() not in locator.lower():
            position = f"{bank_locator}/{locator}"
        configured_speed = clean_dmi_value(current.get("Configured Memory Speed", ""))
        rated_speed = clean_dmi_value(current.get("Speed", ""))
        speed = configured_speed or rated_speed
        module_type = clean_dmi_value(current.get("Type", ""))
        form_factor = clean_dmi_value(current.get("Form Factor", ""))
        type_detail = clean_dmi_value(current.get("Type Detail", ""))
        modules.append(
            {
                "module_number": len(modules),
                "type": module_type,
                "form_factor": form_factor,
                "manufacturer": manufacturer,
                "chip_manufacturer": "",
                "part_number": part_number,
                "serial_number": serial_number,
                "size": size,
                "timing": "",
                "base_speed": speed,
                "configured_speed": configured_speed,
                "rated_speed": rated_speed,
                "position": position,
                "bank_locator": bank_locator,
                "voltage": clean_dmi_value(current.get("Configured Voltage", ""))
                or clean_dmi_value(current.get("Minimum Voltage", "")),
                "command_rate": 0,
                "ecc": "ecc" in type_detail.lower(),
                "type_detail": type_detail,
                "rank": clean_dmi_value(current.get("Rank", "")),
                "asset_tag": clean_dmi_value(current.get("Asset Tag", "")),
                "module_manufacturer_id": clean_dmi_value(current.get("Module Manufacturer ID", "")),
                "module_product_id": clean_dmi_value(current.get("Module Product ID", "")),
                "memory_technology": clean_dmi_value(current.get("Memory Technology", "")),
                "source": "dmidecode -t memory",
            }
        )
        current = {}

    for raw_line in str(text or "").splitlines():
        line = raw_line.rstrip()
        if not line:
            continue
        if not line.startswith(("\t", " ")):
            flush()
            current = {"_section": "memory_device" if line.strip() == "Memory Device" else ""}
            continue
        stripped = line.strip()
        if ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        current[key.strip()] = value.strip()
    flush()
    return modules


def normalize_memory_modules_for_export(modules: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for index, raw_module in enumerate(modules):
        module = dict(raw_module)
        module_number = int(module.get("module_number") or index)
        manufacturer = clean_dmi_value(module.get("manufacturer", ""))
        part_number = clean_dmi_value(module.get("part_number", ""))
        chip_manufacturer = clean_dmi_value(module.get("chip_manufacturer", ""))
        display_part_number = memory_module_display_part_number(manufacturer, part_number)
        size = clean_dmi_value(module.get("size", ""))
        base_speed = clean_dmi_value(module.get("base_speed", ""))
        configured_speed = clean_dmi_value(module.get("configured_speed", ""))
        rated_speed = clean_dmi_value(module.get("rated_speed", ""))
        voltage = clean_dmi_value(module.get("voltage", ""))
        position = clean_dmi_value(module.get("position", "")) or f"Slot {module_number + 1}"
        module_type = clean_dmi_value(module.get("type", ""))
        capacity_gb = parse_memory_capacity_gb(size)
        speed_mhz = parse_memory_speed_mhz(base_speed)
        configured_speed_mts = parse_memory_speed_mhz(configured_speed)
        rated_speed_mts = parse_memory_speed_mhz(rated_speed)
        source = str(module.get("source") or "")
        operating_speed = configured_speed if configured_speed_mts else (base_speed if source == "inxi" else "")
        operating_speed_mts = parse_memory_speed_mhz(operating_speed)

        module.update(
            {
                "module_number": module_number,
                "type": module_type,
                "manufacturer": manufacturer,
                "chip_manufacturer": chip_manufacturer,
                "part_number": part_number,
                "display_part_number": display_part_number,
                "size": size,
                "base_speed": base_speed,
                "configured_speed": configured_speed,
                "rated_speed": rated_speed,
                "operating_speed": operating_speed,
                "position": position,
                "voltage": voltage,
                "capacity_gb": capacity_gb,
                "speed": speed_mhz,
                "speed_mts": speed_mhz,
                "configured_speed_mts": configured_speed_mts,
                "rated_speed_mts": rated_speed_mts,
                "operating_speed_mts": operating_speed_mts,
                "ModuleNumber": module_number,
                "Type": module_type,
                "Manufacturer": manufacturer,
                "ChipManufacturer": chip_manufacturer,
                "PartNumber": display_part_number or part_number,
                "RawPartNumber": part_number,
                "Size": size,
                "CapacityGB": capacity_gb,
                "Timing": clean_dmi_value(module.get("timing", "")),
                "BaseSpeed": base_speed,
                "ConfiguredSpeed": configured_speed,
                "RatedSpeed": rated_speed,
                "OperatingSpeed": operating_speed,
                "Position": position,
                "Voltage": voltage,
                "Speed": speed_mhz,
                "SpeedMTs": speed_mhz,
                "ConfiguredSpeedMTs": configured_speed_mts,
                "RatedSpeedMTs": rated_speed_mts,
                "OperatingSpeedMTs": operating_speed_mts,
                "Ecc": bool(module.get("ecc")),
            }
        )
        normalized.append(module)
    return normalized
