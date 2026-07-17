#!/usr/bin/env python3
"""Read-only storage classification and SMART/health enrichment helpers."""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, Optional


RunCommand = Callable[..., Any]
WhichCommand = Callable[[str], Optional[str]]
ReadSysfs = Callable[[Path], Optional[str]]

VIRTUAL_DEVICE_PREFIXES = ("loop", "ram", "zram", "dm-", "md", "nbd", "rbd")
NETWORK_NVME_TRANSPORTS = {"tcp", "rdma", "fc", "loop"}
PERMISSION_MARKERS = ("permission denied", "operation not permitted", "must be root", "permission")
UNSUPPORTED_MARKERS = (
    "unsupported",
    "not supported",
    "unable to detect device type",
    "unknown usb bridge",
    "smart support is: unavailable",
)
STANDBY_MARKERS = ("standby", "sleeping")
SMARTCTL_MISSING_PREFERRED_NOTE = (
    "smartctl: missing preferred — install smartmontools for ATA/SATA/SAS and fallback SMART coverage"
)


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _optional_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return int(value)
    text = str(value or "").strip().replace(",", "")
    match = re.match(r"^-?\d+", text)
    if match is None:
        return None
    try:
        return int(match.group(0))
    except ValueError:
        return None


def _optional_float(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def nvme_data_units_to_tb(value: Any) -> Optional[float]:
    """Convert standard NVMe data units (1,000 * 512 bytes) to decimal TB."""
    units = _optional_int(value)
    if units is None or units < 0:
        return None
    return round((units * 1000 * 512) / 1_000_000_000_000, 6)


def _nvme_temperature_c(value: Any) -> Optional[float]:
    temperature = _optional_float(value)
    if temperature is None or temperature < 0:
        return None
    # nvme-cli JSON commonly reports the protocol's Kelvin value; some
    # versions already normalize it to Celsius.
    if 200 <= temperature < 1000:
        temperature -= 273.15
    return round(temperature, 2)


def _json_messages(payload: Dict[str, Any]) -> str:
    messages = []
    for message in payload.get("messages") or []:
        if isinstance(message, dict):
            text = message.get("string") or message.get("message")
        else:
            text = message
        if text:
            messages.append(str(text))
    return " ".join(messages)


def _status_from_error(text: str) -> str:
    lowered = str(text or "").lower()
    if any(marker in lowered for marker in STANDBY_MARKERS):
        return "unavailable"
    if any(marker in lowered for marker in PERMISSION_MARKERS):
        return "permission_denied"
    if any(marker in lowered for marker in UNSUPPORTED_MARKERS):
        return "unsupported"
    return "unavailable"


def _has_known_error(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(
        marker in lowered
        for marker in (*STANDBY_MARKERS, *PERMISSION_MARKERS, *UNSUPPORTED_MARKERS)
    )


def _base_health(status: str, note: str = "") -> Dict[str, Any]:
    return {
        "smart_available": False,
        "smart_health": "unknown",
        "smart_source": None,
        "health_detail": None,
        "query_status": status,
        "query_notes": [note] if note else [],
    }


def _set_if_number(target: Dict[str, Any], key: str, value: Any) -> None:
    number = _optional_float(value)
    if number is not None:
        target[key] = number


def parse_smartctl_health(payload: Dict[str, Any]) -> Dict[str, Any]:
    health = _base_health("unavailable")
    if not isinstance(payload, dict) or not payload:
        return health
    nvme_log = payload.get("nvme_smart_health_information_log")
    nvme_log = nvme_log if isinstance(nvme_log, dict) else {}
    smart_status = payload.get("smart_status")
    smart_status = smart_status if isinstance(smart_status, dict) else {}
    support = payload.get("smart_support")
    support = support if isinstance(support, dict) else {}
    has_health_data = bool(nvme_log or smart_status or payload.get("ata_smart_attributes"))
    has_partial_data = bool(support or payload.get("device") or payload.get("model_name"))
    health["smart_available"] = bool(support.get("available", has_health_data))
    health["smart_source"] = "smartctl"

    passed = smart_status.get("passed")
    critical_warning = _optional_int(nvme_log.get("critical_warning"))
    if isinstance(passed, bool):
        health["smart_health"] = "passed" if passed else "failed"
    elif critical_warning is not None:
        health["smart_health"] = "passed" if critical_warning == 0 else "failed"
    health["health_detail"] = (
        "SMART overall-health assessment passed"
        if health["smart_health"] == "passed"
        else "SMART overall-health assessment failed"
        if health["smart_health"] == "failed"
        else "SMART overall-health assessment unavailable"
    )

    temperature = payload.get("temperature")
    if isinstance(temperature, dict):
        _set_if_number(health, "temperature_c", temperature.get("current"))
    if "temperature_c" not in health:
        _set_if_number(health, "temperature_c", nvme_log.get("temperature"))
    power_time = payload.get("power_on_time")
    if isinstance(power_time, dict):
        value = _optional_int(power_time.get("hours"))
        if value is not None and value >= 0:
            health["power_on_hours"] = value
    if "power_on_hours" not in health:
        value = _optional_int(nvme_log.get("power_on_hours"))
        if value is not None and value >= 0:
            health["power_on_hours"] = value

    nvme_fields = {
        "unsafe_shutdowns": ("unsafe_shutdowns",),
        "media_errors": ("media_errors",),
        "percentage_used": ("percentage_used", "percent_used"),
        "available_spare_percent": ("available_spare", "available_spare_percent"),
    }
    for output_key, source_keys in nvme_fields.items():
        for source_key in source_keys:
            value = _optional_int(nvme_log.get(source_key))
            if value is not None and value >= 0:
                health[output_key] = value
                break
    if "percentage_used" in health:
        health["wear_percent_used"] = health["percentage_used"]
        health["wear_indicator_source"] = (
            "smartctl:nvme_smart_health_information_log.percentage_used"
        )

    for output_key, source_key in (
        ("host_writes_tb", "data_units_written"),
        ("host_reads_tb", "data_units_read"),
    ):
        converted = nvme_data_units_to_tb(nvme_log.get(source_key))
        if converted is not None:
            health[output_key] = converted
            health[output_key.replace("_tb", "_source")] = (
                f"smartctl:nvme_smart_health_information_log.{source_key}"
            )

    health["query_status"] = (
        "available" if has_health_data else "partial" if has_partial_data else "unavailable"
    )
    messages = _json_messages(payload)
    if messages:
        health["query_notes"].append(messages)
    return health


def parse_nvme_cli_health(payload: Dict[str, Any]) -> Dict[str, Any]:
    health = _base_health("unavailable")
    if not isinstance(payload, dict) or not payload:
        return health
    recognized_keys = {
        "critical_warning",
        "temperature",
        "composite_temperature",
        "power_on_hours",
        "unsafe_shutdowns",
        "media_errors",
        "media_and_data_integrity_errors",
        "percentage_used",
        "percent_used",
        "available_spare",
        "avail_spare",
        "data_units_read",
        "data_units_written",
    }
    if not recognized_keys.intersection(payload):
        return health
    health.update(
        {
            "smart_available": True,
            "smart_source": "nvme_cli",
            "query_status": "available",
        }
    )
    critical_warning = _optional_int(payload.get("critical_warning"))
    if critical_warning is not None:
        health["smart_health"] = "passed" if critical_warning == 0 else "failed"
    health["health_detail"] = (
        "NVMe critical warning is clear"
        if health["smart_health"] == "passed"
        else "NVMe critical warning is set"
        if health["smart_health"] == "failed"
        else "NVMe critical warning unavailable"
    )
    for output_key, source_keys in {
        "power_on_hours": ("power_on_hours",),
        "unsafe_shutdowns": ("unsafe_shutdowns",),
        "media_errors": ("media_errors", "media_and_data_integrity_errors"),
        "percentage_used": ("percentage_used", "percent_used"),
        "available_spare_percent": ("available_spare", "avail_spare"),
    }.items():
        for source_key in source_keys:
            value = _optional_int(payload.get(source_key))
            if value is not None and value >= 0:
                health[output_key] = value
                break
    for source_key in ("temperature", "composite_temperature"):
        temperature_c = _nvme_temperature_c(payload.get(source_key))
        if temperature_c is not None:
            health["temperature_c"] = temperature_c
            break
    if "percentage_used" in health:
        health["wear_percent_used"] = health["percentage_used"]
        health["wear_indicator_source"] = "nvme_cli:smart-log.percentage_used"
    for output_key, source_key in (
        ("host_writes_tb", "data_units_written"),
        ("host_reads_tb", "data_units_read"),
    ):
        converted = nvme_data_units_to_tb(payload.get(source_key))
        if converted is not None:
            health[output_key] = converted
            health[output_key.replace("_tb", "_source")] = f"nvme_cli:smart-log.{source_key}"
    return health


def merge_health(primary: Dict[str, Any], fallback: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(primary)
    primary_usable = primary.get("query_status") in {"available", "partial"}
    fallback_usable = fallback.get("query_status") in {"available", "partial"}
    for key, value in fallback.items():
        if key == "query_notes":
            merged.setdefault(key, [])
            merged[key].extend(note for note in value if note not in merged[key])
        elif key == "smart_available":
            merged[key] = bool(merged.get(key) or value)
        elif key not in merged or merged[key] in (None, "", "unknown"):
            merged[key] = value
    if fallback_usable and not primary_usable:
        merged["smart_source"] = fallback.get("smart_source") or merged.get("smart_source", "")
    if primary.get("query_status") not in {"available", "partial"} and fallback.get("query_status") == "available":
        merged["query_status"] = "available"
    elif primary.get("query_status") == "partial" and fallback.get("query_status") == "available":
        merged["query_status"] = "available"
    return merged


class StorageHealthEnricher:
    """Classify block devices and query optional read-only health tools."""

    def __init__(
        self,
        *,
        read_sysfs: ReadSysfs,
        run_command: RunCommand = subprocess.run,
        which_command: WhichCommand = shutil.which,
        privileged_helper_enabled: bool = False,
        sys_class_nvme: Path = Path("/sys/class/nvme"),
        temperature_by_block: Optional[Dict[str, float]] = None,
    ) -> None:
        self.read_sysfs = read_sysfs
        self.run_command = run_command
        self.which_command = which_command
        self.privileged_helper_enabled = bool(privileged_helper_enabled)
        self.sys_class_nvme = sys_class_nvme
        self.temperature_by_block = dict(temperature_by_block or {})
        self.tool_paths = {
            name: which_command(name)
            for name in ("lsblk", "udevadm", "smartctl", "nvme")
        }
        self.lsblk_devices = self._load_lsblk_devices()

    def _run(self, command: list[str], *, timeout: float = 8.0, privileged: bool = False) -> Any:
        cmd = list(command)
        if (
            privileged
            and self.privileged_helper_enabled
            and hasattr(os, "geteuid")
            and os.geteuid() != 0
            and self.which_command("sudo")
        ):
            cmd = ["sudo", "-n", *cmd]
        try:
            return self.run_command(
                cmd,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except Exception as exc:
            return type("CommandFailure", (), {"returncode": -1, "stdout": "", "stderr": str(exc)})()

    def _load_lsblk_devices(self) -> Dict[str, Dict[str, Any]]:
        path = self.tool_paths.get("lsblk")
        if not path:
            return {}
        completed = self._run(
            [
                path,
                "--json",
                "--bytes",
                "--nodeps",
                "--output",
                "NAME,KNAME,TYPE,SIZE,MODEL,SERIAL,REV,TRAN,RM,HOTPLUG,SUBSYSTEMS",
            ]
        )
        if completed.returncode != 0:
            return {}
        try:
            payload = json.loads(completed.stdout or "{}")
        except Exception:
            return {}
        devices = payload.get("blockdevices") if isinstance(payload, dict) else []
        return {
            str(device.get("kname") or device.get("name") or ""): device
            for device in devices or []
            if isinstance(device, dict) and (device.get("kname") or device.get("name"))
        }

    def _udev_properties(self, device_path: str) -> Dict[str, str]:
        path = self.tool_paths.get("udevadm")
        if not path:
            return {}
        completed = self._run([path, "info", "--query=property", "--name", device_path])
        if completed.returncode != 0:
            return {}
        properties = {}
        for line in str(completed.stdout or "").splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                properties[key.strip()] = value.strip()
        return properties

    def _nvme_transport(self, name: str, resolved_path: str) -> str:
        match = re.match(r"(nvme\d+)", name)
        if match:
            transport = _clean_text(self.read_sysfs(self.sys_class_nvme / match.group(1) / "transport")).lower()
            if transport:
                return transport
        return "pcie" if "pci" in resolved_path.lower() else "nvme"

    def classify(self, block_dir: Path, entry: Dict[str, Any]) -> Dict[str, Any]:
        name = block_dir.name
        lsblk = self.lsblk_devices.get(name, {})
        device_path = str(entry.get("device_path") or entry.get("DevicePath") or f"/dev/{name}")
        udev = self._udev_properties(device_path)
        try:
            resolved_block = str(block_dir.resolve()).lower()
        except Exception:
            resolved_block = str(block_dir).lower()
        try:
            resolved_device = str((block_dir / "device").resolve()).lower()
        except Exception:
            resolved_device = resolved_block
        resolved = f"{resolved_block} {resolved_device}"
        removable_text = self.read_sysfs(block_dir / "removable")
        removable_value = _optional_int(removable_text)
        if removable_value is None:
            removable_value = _optional_int(lsblk.get("rm"))
        is_removable = None if removable_value is None else bool(removable_value)
        transport = _clean_text(lsblk.get("tran") or udev.get("ID_BUS") or entry.get("interface")).lower()
        if name.startswith("nvme"):
            transport = self._nvme_transport(name, resolved)
        is_usb = transport == "usb" or "/usb" in resolved or udev.get("ID_BUS", "").lower() == "usb"
        device_type = _clean_text(lsblk.get("type") or udev.get("DEVTYPE")).lower()
        is_partition = (block_dir / "partition").exists() or device_type == "part"
        is_virtual = "/virtual/block/" in resolved or name.startswith(VIRTUAL_DEVICE_PREFIXES)
        is_optical = name.startswith("sr") or device_type == "rom" or udev.get("ID_CDROM") == "1"
        is_network = transport in {"iscsi", "fcoe"} or (
            name.startswith("nvme") and transport in NETWORK_NVME_TRANSPORTS
        )
        is_whole_physical = not any((is_partition, is_virtual, is_optical, is_network))

        reason = ""
        if not is_whole_physical:
            is_internal: Optional[bool] = False
            reason = "not a local physical whole-disk device"
        elif is_usb or is_removable is True:
            is_internal = False
            reason = "USB or removable device"
        elif is_removable is False and not is_usb:
            is_internal = True
            reason = "local non-removable physical whole-disk device"
        else:
            is_internal = None
            reason = "removable/internal classification is incomplete"
        sources = ["sysfs"]
        if lsblk:
            sources.append("lsblk")
        if udev:
            sources.append("udev")
        return {
            "transport": transport or "unknown",
            "is_internal": is_internal,
            "is_removable": is_removable,
            "is_usb": bool(is_usb),
            "classification_source": "+".join(sources),
            "classification_detail": reason,
            "is_whole_physical_disk": bool(is_whole_physical),
        }

    def _json_command(self, command: list[str], *, privileged: bool = True) -> tuple[Dict[str, Any], str, int]:
        completed = self._run(command, privileged=privileged)
        stderr = str(completed.stderr or "")
        try:
            payload = json.loads(completed.stdout or "{}")
        except Exception:
            payload = {}
            stderr = " ".join(part for part in (stderr, str(completed.stdout or "")) if part)
        return payload if isinstance(payload, dict) else {}, stderr, int(completed.returncode)

    def query_health(self, entry: Dict[str, Any], classification: Dict[str, Any]) -> Dict[str, Any]:
        if classification.get("is_internal") is False:
            return _base_health("skipped_external", str(classification.get("classification_detail") or ""))
        if classification.get("is_internal") is not True:
            return _base_health("skipped_uncertain", str(classification.get("classification_detail") or ""))
        device_path = str(entry.get("device_path") or entry.get("DevicePath") or "")
        transport = str(classification.get("transport") or "").lower()
        smartctl_path = self.tool_paths.get("smartctl")
        health = _base_health("unavailable", SMARTCTL_MISSING_PREFERRED_NOTE)
        if smartctl_path:
            command = [smartctl_path, "--json", "--info", "--health", "--attributes"]
            if transport not in {"nvme", "pcie"}:
                command.extend(["--nocheck", "standby,now"])
            command.append(device_path)
            payload, output, returncode = self._json_command(command)
            payload_error = _clean_text(payload.get("error")) if isinstance(payload, dict) else ""
            messages = " ".join(
                part for part in (_json_messages(payload), payload_error, output) if part
            )
            parsed = parse_smartctl_health(payload)
            if parsed.get("query_status") == "available" or (
                parsed.get("query_status") == "partial" and not _has_known_error(messages)
            ):
                health = parsed
                if returncode:
                    health["query_notes"].append(f"smartctl exit status {returncode}")
            else:
                status = _status_from_error(messages)
                note = messages or f"smartctl exit status {returncode}"
                if any(marker in messages.lower() for marker in STANDBY_MARKERS):
                    note = "drive is in standby; health query skipped without waking it"
                health = _base_health(status, note)
                health["smart_source"] = "smartctl"

        if entry.get("Name", "").startswith("nvme") and self.tool_paths.get("nvme"):
            needs_nvme = health.get("query_status") not in {"available"} or any(
                key not in health
                for key in ("percentage_used", "host_writes_tb", "host_reads_tb")
            )
            if needs_nvme:
                payload, output, returncode = self._json_command(
                    [self.tool_paths["nvme"], "smart-log", device_path, "--output-format=json"]
                )
                if payload:
                    parsed_nvme = parse_nvme_cli_health(payload)
                    error_text = " ".join(
                        part for part in (_clean_text(payload.get("error")), output) if part
                    )
                    if (
                        parsed_nvme.get("query_status") == "unavailable"
                        and health.get("query_status") not in {"available", "partial"}
                        and error_text
                    ):
                        health = _base_health(_status_from_error(error_text), error_text)
                        health["smart_source"] = "nvme_cli"
                    else:
                        health = merge_health(health, parsed_nvme)
                    if returncode:
                        health["query_notes"].append(f"nvme-cli exit status {returncode}")
                elif health.get("query_status") not in {"available", "partial"} and output:
                    health = _base_health(_status_from_error(output), output)
                    health["smart_source"] = "nvme_cli"
        block_name = str(entry.get("Name") or "")
        if "temperature_c" not in health and block_name in self.temperature_by_block:
            health["temperature_c"] = self.temperature_by_block[block_name]
            health["query_notes"].append("temperature source: hwmon")
        return health

    def enrich(self, block_dir: Path, entry: Dict[str, Any]) -> Dict[str, Any]:
        classification = self.classify(block_dir, entry)
        health = self.query_health(entry, classification)
        return {**classification, "storage_health": health}

    def tool_capabilities(self) -> Dict[str, Dict[str, Any]]:
        commands = {
            "lsblk": ["--version"],
            "udevadm": ["--version"],
            "smartctl": ["--version"],
            "nvme_cli": ["version"],
        }
        result = {}
        for key, args in commands.items():
            executable = "nvme" if key == "nvme_cli" else key
            path = self.tool_paths.get(executable)
            version = ""
            if path:
                completed = self._run([path, *args], timeout=3.0)
                first_line = str(completed.stdout or completed.stderr or "").splitlines()
                version = _clean_text(first_line[0] if first_line else "")
            result[key] = {"available": bool(path), "path": path or "", "version": version}
        return result


def storage_health_capability(
    entries: list[Dict[str, Any]],
    tools: Dict[str, Dict[str, Any]],
    *,
    baseline_available: bool = True,
) -> Dict[str, Any]:
    internal = [entry for entry in entries if entry.get("is_internal") is True]
    eligible = [entry for entry in internal if entry.get("is_whole_physical_disk")]
    queried = [
        entry for entry in eligible
        if (entry.get("storage_health") or {}).get("query_status") in {"available", "partial"}
    ]
    permission_limited = sum(
        1 for entry in eligible
        if (entry.get("storage_health") or {}).get("query_status") == "permission_denied"
    )
    unsupported = sum(
        1 for entry in eligible
        if (entry.get("storage_health") or {}).get("query_status") == "unsupported"
    )
    if not eligible:
        status = "not_applicable"
    elif len(queried) == len(eligible) and all(
        (entry.get("storage_health") or {}).get("query_status") == "available" for entry in queried
    ):
        status = "available"
    elif queried or permission_limited or unsupported or tools.get("smartctl", {}).get("available"):
        status = "partial"
    else:
        status = "unavailable"
    return {
        "baseline_sysfs_inventory": {
            "available": bool(baseline_available),
            "drive_count": len(entries),
            "source": "sysfs",
        },
        "internal_drive_count": len(internal),
        "eligible_internal_drive_count": len(eligible),
        "successfully_queried_drive_count": len(queried),
        "permission_limited_count": permission_limited,
        "unsupported_controller_count": unsupported,
        "status": status,
        "tools": tools,
    }
