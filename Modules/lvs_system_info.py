#!/usr/bin/env python3
"""System hardware inventory collection for Linux Validation Suite."""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from .lvs_core import now_local_iso
from .lvs_cpu_power_limits import (
    build_cpu_power_limit_info,
    format_seconds,
    format_watts,
    read_microseconds,
    read_microunit_watts,
    select_rapl_package_dir,
)
from .lvs_cpu_topology import collect_cpu_topology_info, cpu_package_devices_from_topology
from .lvs_gpu_identity import (
    clean_runtime_gpu_name,
    device_class_from_vulkan_type,
    friendly_pci_gpu_name,
    gpu_vendor_family_from_inventory,
    gpu_vendor_family_from_name,
    is_management_display_adapter,
    is_unhelpful_runtime_gpu_name,
    looks_like_cpu_package_gpu_name,
    normalize_pci_id,
    normalize_pci_slot,
    parse_vulkan_summary_devices,
    pci_slot_sort_key,
    runtime_gpu_name_score,
    select_runtime_gpu_name,
    slot_for_vulkan_device,
    slot_from_mesa_vulkan_uuid,
)
from .lvs_inventory_helpers import (
    apply_inxi_memory_fields,
    build_memory_speed_summary,
    clean_dmi_value,
    memory_module_display_part_number,
    memory_module_has_basic_value,
    normalize_memory_modules_for_export,
    parse_dmidecode_memory_modules,
    parse_inxi_memory_modules,
    parse_memory_capacity_gb,
    parse_memory_speed_mhz,
)
from .lvs_pcie_link import read_pcie_link_info, trusted_pcie_link_for_slot
from .lvs_run_metadata import RunMetadata
from .lvs_storage_inventory import (
    block_device_capacity_gb,
    clean_storage_value,
    collect_storage_info,
    storage_interface_type,
    storage_media_type,
)
from .lvs_system_identity import (
    DMI_KEYS,
    build_bios_info,
    build_linux_os_name,
    build_motherboard_info,
    normalize_dmi_sysfs_value,
    parse_os_release_pretty_name,
)


class SystemInfoCollector:
    def __init__(self, privileged_helper_enabled: bool = False) -> None:
        self._pci_device_names: Optional[Dict[str, Dict[str, str]]] = None
        self._privileged_helper_enabled = bool(privileged_helper_enabled)

    def collect(
        self,
        profile_name: str,
        segment_labels: List[str],
        config_file: str,
        metadata: Optional[RunMetadata] = None,
    ) -> Dict[str, Any]:
        memory_modules = self._memory_modules()
        dmi = self._dmi_info()
        motherboard = self._motherboard_info(dmi)
        bios = self._bios_info(dmi)
        test_name = self._test_name(profile_name, metadata)
        cpu_info = self._cpu_info()
        return {
            "Timestamp": now_local_iso(),
            "Computer": {
                "Name": platform.node(),
                "Domain": platform.node(),
                "Username": self._safe_username(),
                "Manufacturer": dmi.get("sys_vendor", ""),
                "Model": dmi.get("product_name", "") or platform.machine(),
                "SerialNumber": dmi.get("product_serial", ""),
            },
            "Hardware": {
                "Cpu": cpu_info,
                "Memory": {
                    "TotalPhysicalMemoryGB": self._memory_gb(),
                    "Timings": "",
                    "CommandRate": 0,
                    "SpeedSummary": build_memory_speed_summary(memory_modules),
                    "Modules": memory_modules,
                },
                "Motherboard": motherboard,
                "Bios": bios,
                "Gpu": self._gpu_info(),
                "Storage": self._storage_info(),
            },
            "OperatingSystem": {"Name": self._os_name(), "WindowsLicense": []},
            "Drivers": {"ProblemCount": 0, "ProblemDrivers": []},
            "Network": {"Adapters": []},
            "TestInfo": {
                "TestName": test_name,
                "ProfileName": profile_name,
                "ProfileDisplayName": f"{profile_name} Linux Validation",
                "Descriptions": segment_labels,
                "ConfigFile": config_file,
                "MetadataFile": "",
            },
        }

    def _test_name(self, profile_name: str, metadata: Optional[RunMetadata]) -> str:
        if metadata is None:
            return f"{profile_name} Linux Validation"
        case = str(metadata.case_sku or "").strip()
        description = str(metadata.description or "").strip()
        if case or description:
            return f"{case or 'Unknown'}={description or profile_name}"
        return f"{profile_name} Linux Validation"

    def _safe_username(self) -> str:
        try:
            import getpass
            return getpass.getuser()
        except Exception:
            return ""

    def _dmi_info(self) -> Dict[str, str]:
        dmi_dir = Path("/sys/class/dmi/id")
        info: Dict[str, str] = {}
        for key in DMI_KEYS:
            info[key] = normalize_dmi_sysfs_value(self._read_sysfs(dmi_dir / key) or "")
        return info

    def _motherboard_info(self, dmi: Dict[str, str]) -> Dict[str, str]:
        return build_motherboard_info(dmi)

    def _bios_info(self, dmi: Dict[str, str]) -> Dict[str, str]:
        return build_bios_info(dmi)

    def _os_name(self) -> str:
        distro = ""
        try:
            os_release = Path("/etc/os-release").read_text(encoding="utf-8", errors="ignore")
            distro = parse_os_release_pretty_name(os_release)
        except Exception:
            distro = ""
        return build_linux_os_name(distro, platform.system(), platform.release())

    def _cpu_power_limit_info(self) -> Dict[str, Any]:
        candidates = [
            Path("/sys/class/powercap/intel-rapl:0"),
            Path("/sys/devices/virtual/powercap/intel-rapl/intel-rapl:0"),
        ]
        return build_cpu_power_limit_info(select_rapl_package_dir(candidates), self._read_sysfs)

    def _cpu_info(self) -> Dict[str, Any]:
        base_name = self._cpu_name()
        topology = collect_cpu_topology_info(
            cpuinfo_text=self._proc_cpuinfo_text(),
            read_text=self._read_sysfs,
            fallback_name=base_name,
        )
        name = str(topology.get("NameSummary") or base_name or "Unknown CPU")
        return {
            "Name": name,
            "AggregateName": name,
            "BaseName": base_name,
            "Topology": topology,
            "PackageDevices": cpu_package_devices_from_topology(topology),
            "PowerLimits": self._cpu_power_limit_info(),
            "PowerLimitsByPackage": self._cpu_power_limit_info_by_package(),
        }

    def _proc_cpuinfo_text(self) -> str:
        try:
            return Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return ""

    def _cpu_power_limit_info_by_package(self) -> List[Dict[str, Any]]:
        package_dirs: List[Path] = []
        seen: set[str] = set()
        for root in (Path("/sys/class/powercap"), Path("/sys/devices/virtual/powercap")):
            if not root.exists():
                continue
            for package_dir in sorted(root.glob("intel-rapl:*")):
                if not package_dir.is_dir():
                    continue
                # Keep top-level package domains and avoid nested core/uncore domains.
                suffix = package_dir.name.replace("intel-rapl:", "", 1)
                if ":" in suffix:
                    continue
                try:
                    resolved = str(package_dir.resolve())
                except Exception:
                    resolved = str(package_dir)
                if resolved in seen:
                    continue
                seen.add(resolved)
                package_dirs.append(package_dir)
        records: List[Dict[str, Any]] = []
        for package_dir in package_dirs:
            info = build_cpu_power_limit_info(package_dir, self._read_sysfs)
            suffix = package_dir.name.replace("intel-rapl:", "", 1)
            try:
                info["PackageId"] = int(suffix)
            except Exception:
                info["PackageId"] = None
            records.append(info)
        return records

    def _read_microunit_watts(self, path: Path) -> Optional[float]:
        return read_microunit_watts(path, self._read_sysfs)

    def _read_microseconds(self, path: Path) -> Optional[float]:
        return read_microseconds(path, self._read_sysfs)

    def _format_watts(self, watts: Any) -> str:
        return format_watts(watts)

    def _format_seconds(self, seconds: Any) -> str:
        return format_seconds(seconds)

    def _cpu_name(self) -> str:
        try:
            cpuinfo = self._proc_cpuinfo_text()
            for line in cpuinfo.splitlines():
                if line.lower().startswith("model name"):
                    return line.split(":", 1)[1].strip()
        except Exception:
            pass
        return platform.processor() or "Unknown CPU"

    def _memory_gb(self) -> int:
        try:
            pages = os.sysconf("SC_PHYS_PAGES")
            page_size = os.sysconf("SC_PAGE_SIZE")
            return int((pages * page_size) / (1024 ** 3))
        except Exception:
            return 0

    def _storage_info(self) -> List[Dict[str, Any]]:
        return collect_storage_info(
            read_sysfs=self._read_sysfs,
            privileged_helper_enabled=self._privileged_helper_enabled,
        )

    def _block_device_capacity_gb(self, block_dir: Path) -> int:
        return block_device_capacity_gb(block_dir, self._read_sysfs)

    def _storage_interface_type(self, name: str, block_dir: Path) -> str:
        return storage_interface_type(name, block_dir)

    def _storage_media_type(self, name: str, block_dir: Path, interface_type: str) -> str:
        return storage_media_type(name, block_dir, interface_type, self._read_sysfs)

    def _clean_storage_value(self, value: Optional[str]) -> str:
        return clean_storage_value(value)

    def _memory_modules(self) -> List[Dict[str, Any]]:
        dmi_modules = self._dmidecode_memory_modules()
        if dmi_modules:
            return dmi_modules
        inxi_modules = self._inxi_memory_modules()
        if inxi_modules:
            return inxi_modules

        # Temperature-only SPD hub sensors are exported through segment telemetry.
        # Do not synthesize Hardware.Memory.Modules rows from them, because the
        # Legacy importers treat those rows as inventory and would show "DIMM: Unknown".
        return []

    def _inxi_memory_modules(self) -> List[Dict[str, Any]]:
        if shutil.which("inxi") is None:
            return []
        try:
            completed = subprocess.run(
                ["inxi", "-mxx"],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except Exception:
            return []
        if completed.returncode != 0:
            return []
        return self._normalize_memory_modules_for_export(self._parse_inxi_memory_modules(completed.stdout or ""))

    def _parse_inxi_memory_modules(self, text: str) -> List[Dict[str, Any]]:
        return parse_inxi_memory_modules(text)

    def _apply_inxi_memory_fields(self, module: Dict[str, Any], text: str, field_pattern: re.Pattern[str]) -> None:
        apply_inxi_memory_fields(module, text, field_pattern)

    def _memory_module_has_basic_value(self, module: Dict[str, Any]) -> bool:
        return memory_module_has_basic_value(module)

    def _dmidecode_memory_modules(self) -> List[Dict[str, Any]]:
        dmidecode_path = shutil.which("dmidecode")
        if dmidecode_path is None:
            return []
        commands: List[List[str]] = [[dmidecode_path, "-t", "memory"]]
        if self._privileged_helper_enabled and os.geteuid() != 0 and shutil.which("sudo") is not None:
            try:
                sudo_check = subprocess.run(
                    ["sudo", "-n", "true"],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=3,
                )
            except Exception:
                sudo_check = None
            if sudo_check is not None and sudo_check.returncode == 0:
                commands.append(["sudo", "-n", dmidecode_path, "-t", "memory"])
        best_modules: List[Dict[str, Any]] = []
        for command in commands:
            modules = self._run_dmidecode_memory_command(command)
            if modules:
                return modules
            if modules is not None:
                best_modules = modules
        return best_modules

    def _run_dmidecode_memory_command(self, command: List[str]) -> Optional[List[Dict[str, Any]]]:
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except Exception:
            return None
        if completed.returncode != 0:
            return None
        return self._normalize_memory_modules_for_export(self._parse_dmidecode_memory_modules(completed.stdout or ""))

    def _parse_dmidecode_memory_modules(self, text: str) -> List[Dict[str, Any]]:
        return parse_dmidecode_memory_modules(text)

    def _normalize_memory_modules_for_export(self, modules: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return normalize_memory_modules_for_export(modules)

    def _memory_module_display_part_number(self, manufacturer: str, part_number: str) -> str:
        return memory_module_display_part_number(manufacturer, part_number)

    def _parse_memory_capacity_gb(self, value: str) -> int:
        return parse_memory_capacity_gb(value)

    def _parse_memory_speed_mhz(self, value: str) -> int:
        return parse_memory_speed_mhz(value)

    def _clean_dmi_value(self, value: str) -> str:
        return clean_dmi_value(value)

    def _gpu_info(self) -> List[Dict[str, Any]]:
        devices: List[Dict[str, Any]] = []
        drm_gpus = self._discover_drm_gpus()
        vulkan_classes = self._vulkan_gpu_classes_by_slot(drm_gpus)
        for gpu in drm_gpus:
            slot = str(gpu.get("pci_slot", "") or "").lower()
            if slot in vulkan_classes:
                gpu.update(vulkan_classes[slot])
        runtime_names = self._runtime_gpu_names_by_slot(drm_gpus)
        nvidia_gpus = self._discover_nvidia_smi_gpus()
        nvidia_by_slot = {
            gpu.get("pci_slot", "").lower(): gpu
            for gpu in nvidia_gpus
            if gpu.get("pci_slot")
        }
        merged: List[Dict[str, Any]] = []
        used_slots: set[str] = set()
        for gpu in drm_gpus:
            slot = (gpu.get("pci_slot") or "").lower()
            nvidia_gpu = nvidia_by_slot.get(slot)
            if nvidia_gpu:
                used_slots.add(slot)
                merged.append(
                    {
                        **gpu,
                        "name": nvidia_gpu.get("name") or gpu.get("name", ""),
                        "marketing_name": nvidia_gpu.get("name") or gpu.get("marketing_name", "") or gpu.get("name", ""),
                        "name_source": "nvidia_smi",
                        "device_class": "discrete",
                        "device_class_source": "nvidia_smi",
                        "device_class_confidence": "high",
                        "driver": nvidia_gpu.get("driver") or gpu.get("driver", ""),
                        "memory": nvidia_gpu.get("memory") or gpu.get("memory", ""),
                    }
                )
            else:
                runtime_name = runtime_names.get(slot, {})
                if runtime_name.get("name"):
                    merged.append(
                        {
                            **gpu,
                            "name": runtime_name["name"],
                            "marketing_name": runtime_name["name"],
                            "name_source": runtime_name.get("source", "runtime"),
                            "runtime_name_raw": runtime_name.get("raw", ""),
                            "device_class": runtime_name.get("device_class", gpu.get("device_class", "unknown")),
                            "device_class_source": runtime_name.get(
                                "device_class_source",
                                gpu.get("device_class_source", ""),
                            ),
                            "device_class_confidence": runtime_name.get(
                                "device_class_confidence",
                                gpu.get("device_class_confidence", "low"),
                            ),
                        }
                    )
                else:
                    merged.append(gpu)
        for gpu in nvidia_gpus:
            slot = (gpu.get("pci_slot") or "").lower()
            if slot and slot in used_slots:
                continue
            merged.append(gpu)
        merged = [gpu for gpu in merged if self._is_exportable_gpu(gpu)]
        merged = self._sort_gpus_for_export(merged)
        for gpu in merged:
            pcie_link = trusted_pcie_link_for_slot(gpu.get("pcie_link", {}), gpu.get("pci_slot", ""))
            devices.append(
                {
                    "Name": gpu["name"],
                    "GpuModel": gpu["name"],
                    "MarketingName": gpu.get("marketing_name", gpu["name"]),
                    "PciName": gpu.get("pci_name", gpu["name"]),
                    "NameSource": gpu.get("name_source", ""),
                    "RuntimeNameRaw": gpu.get("runtime_name_raw", ""),
                    "DeviceClass": gpu.get("device_class", "unknown"),
                    "DeviceClassSource": gpu.get("device_class_source", ""),
                    "DeviceClassConfidence": gpu.get("device_class_confidence", "low"),
                    "Card": gpu.get("card", ""),
                    "Chipset": gpu["chipset"],
                    "GpuDie": "",
                    "Memory": gpu["memory"],
                    "Interface": gpu["pci_slot"],
                    "PcieLink": pcie_link,
                    "PcieMaxLinkSpeed": pcie_link.get("MaxLinkSpeed", ""),
                    "PcieCurrentLinkSpeed": pcie_link.get("CurrentLinkSpeed", ""),
                    "PcieMaxLinkWidth": pcie_link.get("MaxLinkWidth", ""),
                    "PcieCurrentLinkWidth": pcie_link.get("CurrentLinkWidth", ""),
                    "PcieSlot": pcie_link.get("PciSlot", ""),
                    "DriverVersion": gpu["driver"],
                    "DriverDate": "",
                    "CurrentResolution": "",
                    "MaxRefreshRate": "",
                }
            )
        return devices

    def _vulkan_gpu_classes_by_slot(self, drm_gpus: List[Dict[str, str]]) -> Dict[str, Dict[str, str]]:
        from shutil import which

        if which("vulkaninfo") is None:
            return {}
        try:
            completed = subprocess.run(
                ["vulkaninfo", "--summary"],
                check=False,
                capture_output=True,
                text=True,
                timeout=15,
            )
        except Exception:
            return {}
        text = completed.stdout or ""
        if completed.stderr:
            text += "\n" + completed.stderr
        devices = self._parse_vulkan_summary_devices(text)
        by_slot: Dict[str, Dict[str, str]] = {}
        for device in devices:
            slot = self._slot_for_vulkan_device(device, drm_gpus)
            if not slot:
                continue
            device_class = self._device_class_from_vulkan_type(str(device.get("deviceType", "") or ""))
            if device_class == "unknown":
                continue
            by_slot[slot.lower()] = {
                "device_class": device_class,
                "device_class_source": "vulkaninfo",
                "device_class_confidence": "high",
            }
        return by_slot

    def _discover_drm_gpus(self) -> List[Dict[str, str]]:
        devices: List[Dict[str, str]] = []
        gpu_index = 0
        for card in sorted(Path("/sys/class/drm").glob("card[0-9]*")):
            if "-" in card.name:
                continue
            device_dir = card / "device"
            vendor = self._read_sysfs(device_dir / "vendor") or ""
            device = self._read_sysfs(device_dir / "device") or ""
            vram_bytes = self._read_sysfs_int(device_dir / "mem_info_vram_total")
            slot = ""
            uevent = self._read_sysfs(device_dir / "uevent") or ""
            for line in uevent.splitlines():
                if line.startswith("PCI_SLOT_NAME="):
                    slot = line.split("=", 1)[1].strip()
                    break
            driver_link = device_dir / "driver" / "module"
            driver = driver_link.resolve().name if driver_link.exists() else ""
            vendor_name = self._vendor_name(vendor)
            resolved_name = self._lookup_pci_device_name(vendor, device)
            device_code = self._normalize_pci_id(device).upper()
            pci_name = resolved_name or f"{vendor_name} GPU {device_code}".strip()
            name = self._friendly_pci_gpu_name(vendor_name, pci_name, device_code)
            name_source = "pci_ids" if resolved_name else "vendor_device_id"
            if name != pci_name:
                name_source = f"friendly_{name_source}"
            chipset = f"{vendor_name} {device_code}".strip()
            pcie_link = read_pcie_link_info(device_dir, self._read_sysfs)
            devices.append(
                {
                    "card": card.name,
                    "name": name,
                    "marketing_name": name,
                    "pci_name": pci_name,
                    "name_source": name_source,
                    "chipset": chipset,
                    "driver": driver,
                    "pci_slot": slot,
                    "vendor_id": self._normalize_pci_id(vendor),
                    "device_id": self._normalize_pci_id(device),
                    "device_class": "unknown",
                    "device_class_source": "",
                    "device_class_confidence": "low",
                    "memory": self._format_gib(vram_bytes),
                    "pcie_link": pcie_link,
                }
            )
        return devices

    def _sort_gpus_for_export(self, gpus: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        priority = {
            "discrete": 0,
            "external": 0,
            "virtual": 1,
            "unknown": 2,
            "integrated": 3,
            "apu": 3,
            "cpu": 4,
        }
        return sorted(
            gpus,
            key=lambda gpu: (
                priority.get(str(gpu.get("device_class", "unknown")).lower(), 2),
                self._slot_sort_key(str(gpu.get("pci_slot", "") or "")),
                str(gpu.get("card", "") or ""),
                str(gpu.get("name", "") or ""),
            ),
        )

    def _is_exportable_gpu(self, gpu: Dict[str, Any]) -> bool:
        """Return true for GPUs the suite can reasonably target or report as GPUs.

        Server BMC display adapters commonly appear as DRM cards, but they are not
        meaningful stress-test GPUs. Keep them out of Hardware.Gpu so downstream
        imports do not count them as an extra testable GPU.
        """
        if self._is_management_display_adapter(gpu):
            return False
        device_class = str(gpu.get("device_class", "") or "").strip().lower()
        if device_class in {"discrete", "integrated", "apu", "external", "virtual"}:
            return True
        if self._gpu_vendor_family_from_inventory(gpu) in {"amd", "nvidia", "intel"}:
            return True
        if str(gpu.get("memory", "") or "").strip():
            return True
        return False

    def _is_management_display_adapter(self, gpu: Dict[str, Any]) -> bool:
        return is_management_display_adapter(gpu)

    def _slot_sort_key(self, slot: str) -> tuple[int, int, int, int]:
        return pci_slot_sort_key(slot)

    def _friendly_pci_gpu_name(self, vendor_name: str, pci_name: str, device_code: str) -> str:
        return friendly_pci_gpu_name(vendor_name, pci_name, device_code)

    def _runtime_gpu_names_by_slot(self, drm_gpus: List[Dict[str, str]]) -> Dict[str, Dict[str, str]]:
        candidates_by_slot: Dict[str, List[Dict[str, str]]] = {}
        for source_map in (self._vulkan_gpu_names_by_slot(drm_gpus), self._egl_gpu_names_by_slot(drm_gpus)):
            for slot, detail in source_map.items():
                if detail.get("name"):
                    candidates_by_slot.setdefault(slot.lower(), []).append(detail)

        gpu_by_slot = {
            str(gpu.get("pci_slot", "") or "").lower(): gpu
            for gpu in drm_gpus
            if gpu.get("pci_slot")
        }
        selected: Dict[str, Dict[str, str]] = {}
        for slot, candidates in candidates_by_slot.items():
            best = self._select_runtime_gpu_name(gpu_by_slot.get(slot, {}), candidates)
            if best:
                selected[slot] = best
        return selected

    def _select_runtime_gpu_name(
        self,
        gpu: Dict[str, str],
        candidates: List[Dict[str, str]],
    ) -> Dict[str, str]:
        return select_runtime_gpu_name(gpu, candidates)  # type: ignore[return-value]

    def _runtime_gpu_name_score(self, gpu: Dict[str, str], candidate: Dict[str, str]) -> int:
        return runtime_gpu_name_score(gpu, candidate)

    def _gpu_vendor_family_from_inventory(self, gpu: Dict[str, str]) -> str:
        return gpu_vendor_family_from_inventory(gpu)

    def _gpu_vendor_family_from_name(self, text: str) -> str:
        return gpu_vendor_family_from_name(text)

    def _vulkan_gpu_names_by_slot(self, drm_gpus: List[Dict[str, str]]) -> Dict[str, Dict[str, str]]:
        from shutil import which

        if which("vulkaninfo") is None:
            return {}
        try:
            completed = subprocess.run(
                ["vulkaninfo", "--summary"],
                check=False,
                capture_output=True,
                text=True,
                timeout=15,
            )
        except Exception:
            return {}
        text = completed.stdout or ""
        if completed.stderr:
            text += "\n" + completed.stderr
        devices = self._parse_vulkan_summary_devices(text)

        by_slot: Dict[str, Dict[str, str]] = {}
        for device in devices:
            raw_name = str(device.get("deviceName", "") or "")
            if self._is_unhelpful_runtime_gpu_name(raw_name):
                continue
            slot = self._slot_for_vulkan_device(device, drm_gpus)
            if not slot:
                continue
            name = self._clean_runtime_gpu_name(raw_name)
            if name:
                by_slot[slot.lower()] = {"name": name, "raw": raw_name, "source": "vulkaninfo"}
        return by_slot

    def _parse_vulkan_summary_devices(self, text: str) -> List[Dict[str, str]]:
        return parse_vulkan_summary_devices(text)

    def _device_class_from_vulkan_type(self, device_type: str) -> str:
        return device_class_from_vulkan_type(device_type)

    def _slot_for_vulkan_device(self, device: Dict[str, str], drm_gpus: List[Dict[str, str]]) -> str:
        return slot_for_vulkan_device(device, drm_gpus)

    def _slot_from_mesa_vulkan_uuid(self, uuid_text: str, drm_gpus: List[Dict[str, str]]) -> str:
        return slot_from_mesa_vulkan_uuid(uuid_text, drm_gpus)

    def _egl_gpu_names_by_slot(self, drm_gpus: List[Dict[str, str]]) -> Dict[str, Dict[str, str]]:
        by_slot: Dict[str, Dict[str, str]] = {}
        for gpu in drm_gpus:
            slot = str(gpu.get("pci_slot", "") or "")
            if not slot:
                continue
            dri_prime = "pci-" + slot.replace(":", "_").replace(".", "_")
            renderer = self._egl_renderer_for_dri_prime(dri_prime)
            if self._is_unhelpful_runtime_gpu_name(renderer):
                continue
            name = self._clean_runtime_gpu_name(renderer)
            if name:
                by_slot[slot.lower()] = {"name": name, "raw": renderer, "source": "egl_renderer"}
        return by_slot

    def _egl_renderer_for_dri_prime(self, dri_prime: str) -> str:
        script = r'''
import ctypes
import ctypes.util

EGL = ctypes.CDLL(ctypes.util.find_library("EGL"))
GLES = ctypes.CDLL(ctypes.util.find_library("GLESv2"))
EGLDisplay = ctypes.c_void_p
EGLConfig = ctypes.c_void_p
EGLContext = ctypes.c_void_p
EGLSurface = ctypes.c_void_p
EGLint = ctypes.c_int
EGLenum = ctypes.c_uint
EGLBoolean = ctypes.c_uint
EGL_NO_CONTEXT = EGLContext(0)
EGL_NONE = 0x3038
EGL_SURFACE_TYPE = 0x3033
EGL_PBUFFER_BIT = 0x0001
EGL_RENDERABLE_TYPE = 0x3040
EGL_OPENGL_ES2_BIT = 0x0004
EGL_RED_SIZE = 0x3024
EGL_GREEN_SIZE = 0x3023
EGL_BLUE_SIZE = 0x3022
EGL_ALPHA_SIZE = 0x3021
EGL_CONTEXT_CLIENT_VERSION = 0x3098
EGL_WIDTH = 0x3057
EGL_HEIGHT = 0x3056
EGL_OPENGL_ES_API = 0x30A0
EGL_PLATFORM_SURFACELESS_MESA = 0x31DD
GL_RENDERER = 0x1F01

PFN = ctypes.CFUNCTYPE(EGLDisplay, EGLenum, ctypes.c_void_p, ctypes.POINTER(EGLint))
EGL.eglGetProcAddress.restype = ctypes.c_void_p
addr = EGL.eglGetProcAddress(b"eglGetPlatformDisplayEXT")
get_platform_display = PFN(addr) if addr else None
EGL.eglGetDisplay.restype = EGLDisplay
EGL.eglInitialize.argtypes = [EGLDisplay, ctypes.POINTER(EGLint), ctypes.POINTER(EGLint)]
EGL.eglInitialize.restype = EGLBoolean
EGL.eglBindAPI.argtypes = [EGLenum]
EGL.eglChooseConfig.argtypes = [EGLDisplay, ctypes.POINTER(EGLint), ctypes.POINTER(EGLConfig), EGLint, ctypes.POINTER(EGLint)]
EGL.eglChooseConfig.restype = EGLBoolean
EGL.eglCreatePbufferSurface.argtypes = [EGLDisplay, EGLConfig, ctypes.POINTER(EGLint)]
EGL.eglCreatePbufferSurface.restype = EGLSurface
EGL.eglCreateContext.argtypes = [EGLDisplay, EGLConfig, EGLContext, ctypes.POINTER(EGLint)]
EGL.eglCreateContext.restype = EGLContext
EGL.eglMakeCurrent.argtypes = [EGLDisplay, EGLSurface, EGLSurface, EGLContext]
EGL.eglMakeCurrent.restype = EGLBoolean
GLES.glGetString.argtypes = [ctypes.c_uint]
GLES.glGetString.restype = ctypes.c_char_p

display = get_platform_display(EGL_PLATFORM_SURFACELESS_MESA, None, None) if get_platform_display else EGL.eglGetDisplay(ctypes.c_void_p(0))
major = EGLint()
minor = EGLint()
if not display or not EGL.eglInitialize(display, ctypes.byref(major), ctypes.byref(minor)):
    raise SystemExit(2)
if not EGL.eglBindAPI(EGL_OPENGL_ES_API):
    raise SystemExit(3)
attrs = (EGLint * 13)(
    EGL_SURFACE_TYPE, EGL_PBUFFER_BIT,
    EGL_RENDERABLE_TYPE, EGL_OPENGL_ES2_BIT,
    EGL_RED_SIZE, 8,
    EGL_GREEN_SIZE, 8,
    EGL_BLUE_SIZE, 8,
    EGL_ALPHA_SIZE, 8,
    EGL_NONE,
)
config = EGLConfig()
count = EGLint()
if not EGL.eglChooseConfig(display, attrs, ctypes.byref(config), 1, ctypes.byref(count)) or not count.value:
    raise SystemExit(4)
surf_attrs = (EGLint * 5)(EGL_WIDTH, 16, EGL_HEIGHT, 16, EGL_NONE)
surface = EGL.eglCreatePbufferSurface(display, config, surf_attrs)
ctx_attrs = (EGLint * 3)(EGL_CONTEXT_CLIENT_VERSION, 2, EGL_NONE)
context = EGL.eglCreateContext(display, config, EGL_NO_CONTEXT, ctx_attrs)
if not surface or not context or not EGL.eglMakeCurrent(display, surface, surface, context):
    raise SystemExit(5)
renderer = GLES.glGetString(GL_RENDERER)
print((renderer or b"").decode("utf-8", "ignore"))
'''
        env = os.environ.copy()
        env["DRI_PRIME"] = dri_prime
        try:
            completed = subprocess.run(
                [sys.executable, "-c", script],
                check=False,
                capture_output=True,
                text=True,
                timeout=6,
                env=env,
            )
        except Exception:
            return ""
        return (completed.stdout or "").strip() if completed.returncode == 0 else ""

    def _is_unhelpful_runtime_gpu_name(self, name: str) -> bool:
        return is_unhelpful_runtime_gpu_name(name)

    def _looks_like_cpu_package_gpu_name(self, name: str) -> bool:
        return looks_like_cpu_package_gpu_name(name)

    def _clean_runtime_gpu_name(self, name: str) -> str:
        return clean_runtime_gpu_name(name)

    def _discover_nvidia_smi_gpus(self) -> List[Dict[str, str]]:
        from shutil import which

        if which("nvidia-smi") is None:
            return []
        cmd = [
            "nvidia-smi",
            "--query-gpu=name,pci.bus_id,driver_version,memory.total",
            "--format=csv,noheader,nounits",
        ]
        try:
            completed = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=10)
        except Exception:
            return []
        if completed.returncode != 0:
            return []
        devices: List[Dict[str, str]] = []
        for line in (completed.stdout or "").splitlines():
            parts = [item.strip() for item in line.split(",")]
            if len(parts) < 4:
                continue
            try:
                memory_mb = float(parts[3])
                memory = f"{round(memory_mb / 1024.0, 2)} GB" if memory_mb > 0 else ""
            except Exception:
                memory = ""
            name = parts[0] or "NVIDIA GPU"
            slot = self._normalize_pci_slot(parts[1])
            devices.append(
                {
                    "card": "",
                    "name": name,
                    "chipset": name,
                    "driver": parts[2],
                    "pci_slot": slot,
                    "device_class": "discrete",
                    "device_class_source": "nvidia_smi",
                    "device_class_confidence": "high",
                    "memory": memory,
                    "pcie_link": read_pcie_link_info(Path("/sys/bus/pci/devices") / slot, self._read_sysfs),
                }
            )
        return devices

    def _normalize_pci_slot(self, slot: str) -> str:
        return normalize_pci_slot(slot)

    def _read_sysfs(self, path: Path) -> Optional[str]:
        try:
            return path.read_text(encoding="utf-8", errors="ignore").strip()
        except Exception:
            return None

    def _read_sysfs_int(self, path: Path) -> Optional[int]:
        raw = self._read_sysfs(path)
        if raw is None:
            return None
        try:
            return int(raw)
        except Exception:
            return None

    def _vendor_name(self, vendor_id: str) -> str:
        mapping = {
            "0x1002": "AMD",
            "0x10de": "NVIDIA",
            "0x8086": "Intel",
        }
        return mapping.get(vendor_id.lower(), vendor_id.upper() or "Unknown")

    def _normalize_pci_id(self, value: str) -> str:
        return normalize_pci_id(value)

    def _lookup_pci_device_name(self, vendor_id: str, device_id: str) -> Optional[str]:
        pci_ids = self._load_pci_device_names()
        if not pci_ids:
            return None
        return pci_ids.get(self._normalize_pci_id(vendor_id), {}).get(self._normalize_pci_id(device_id))

    def _load_pci_device_names(self) -> Dict[str, Dict[str, str]]:
        if self._pci_device_names is not None:
            return self._pci_device_names

        self._pci_device_names = {}
        for path in (Path("/usr/share/hwdata/pci.ids"), Path("/usr/share/misc/pci.ids")):
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
                            self._pci_device_names.setdefault(current_vendor, {})
                            continue
                        if current_vendor is None or line.startswith("\t\t"):
                            continue
                        parts = line.strip().split(None, 1)
                        if len(parts) != 2 or len(parts[0]) != 4:
                            continue
                        self._pci_device_names[current_vendor][parts[0].lower()] = parts[1].strip()
            except Exception:
                continue
            if self._pci_device_names:
                break

        return self._pci_device_names

    def _format_gib(self, value_bytes: Optional[int]) -> str:
        if not value_bytes or value_bytes <= 0:
            return ""
        return f"{round(value_bytes / (1024 ** 3), 2)} GB"
