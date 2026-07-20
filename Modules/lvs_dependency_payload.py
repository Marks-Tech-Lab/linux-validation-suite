#!/usr/bin/env python3
"""Dependency-check payload construction."""

from __future__ import annotations

import getpass
import os
import platform
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from .lvs_core import APP_NAME, APP_VERSION, now_local_iso
from .lvs_output_contract_identity import (
    DEPENDENCY_CHECK_CONTRACT_ID,
    DEPENDENCY_CHECK_KIND,
    stamp_contract_identity,
)


class DependencyCheckPayloadBuilder:
    """Build dependency-check payloads without report text or file writing."""

    def __init__(
        self,
        settings: Any,
        orchestrator: Any,
        drive_readiness: Callable[[], Dict[str, Any]],
        telemetry_factory: Callable[..., Any],
        memory_modules_factory: Callable[[bool], list[Dict[str, Any]]],
        storage_health_factory: Optional[Callable[[bool], Dict[str, Any]]] = None,
        storage_benchmark_factory: Optional[Callable[[bool], Dict[str, Any]]] = None,
    ) -> None:
        self.settings = settings
        self.orchestrator = orchestrator
        self.drive_readiness = drive_readiness
        self.telemetry_factory = telemetry_factory
        self.memory_modules_factory = memory_modules_factory
        self.storage_health_factory = storage_health_factory or storage_health_capability_default
        self.storage_benchmark_factory = storage_benchmark_factory or storage_benchmark_capability_default

    def dependency_check_payload(
        self,
        *,
        sudo_noninteractive_ready: Optional[Callable[[], bool]] = None,
        memory_module_has_identity: Optional[Callable[[Dict[str, Any]], bool]] = None,
    ) -> Dict[str, Any]:
        try:
            user_name = getpass.getuser()
        except Exception:
            user_name = ""
        effective_uid = os.geteuid() if hasattr(os, "geteuid") else None
        helper_requested = bool(getattr(self.settings, "privileged_helper_enabled", False))
        sudo_ready = bool(
            effective_uid == 0
            or (
                helper_requested
                and sudo_noninteractive_ready is not None
                and sudo_noninteractive_ready()
            )
        )
        helper_effective = bool(helper_requested and sudo_ready)
        execution_context = {
            "hostname": platform.node(),
            "user": user_name,
            "effective_uid": effective_uid,
            "is_root": effective_uid == 0,
            "python_executable": sys.executable,
            "python_version": platform.python_version(),
            "cwd": str(Path.cwd()),
            "privileged_helper_enabled": helper_requested,
            "privileged_helper_prompt_for_sudo": getattr(
                self.settings,
                "privileged_helper_prompt_for_sudo",
                False,
            ),
            "privileged_helper_sudo_ready": sudo_ready,
            "privileged_helper_effective": helper_effective,
        }
        workload_runner = self.orchestrator.workload_runner
        backends = workload_runner.detect_backends()
        details = workload_runner.backend_details()
        telemetry = self.telemetry_factory(
            interval_seconds=self.settings.sample_interval_seconds,
            runtime_environment=self.settings.runtime_environment,
            privileged_helper_enabled=helper_effective,
        )
        telemetry_capabilities = telemetry.detect_capabilities()
        memory_modules = self.memory_modules_factory(helper_effective)
        has_identity = memory_module_has_identity or memory_module_has_identity_default
        memory_identity_count = sum(1 for module in memory_modules if has_identity(module))
        memory_identity_sources = sorted(
            {
                str(module.get("source") or "").strip()
                for module in memory_modules
                if has_identity(module) and str(module.get("source") or "").strip()
            }
        )
        return stamp_contract_identity({
            "app_name": APP_NAME,
            "app_version": APP_VERSION,
            "started": now_local_iso(),
            "execution_context": execution_context,
            "runtime_environment": workload_runner.runtime_environment(),
            "backends": backends,
            "backend_details": details,
            "telemetry_capabilities": telemetry_capabilities,
            "memory_modules": memory_modules,
            "memory_identity": {
                "available": memory_identity_count > 0,
                "module_count": len(memory_modules),
                "identified_module_count": memory_identity_count,
                "source": ", ".join(memory_identity_sources) if memory_identity_sources else "not found",
            },
            "storage_health": self.storage_health_factory(helper_effective),
            "storage_benchmark": self.storage_benchmark_factory(helper_effective),
            "gpu_opencl_coverage": gpu_opencl_coverage(workload_runner),
            "google_drive_upload": self.drive_readiness(),
        }, contract_id=DEPENDENCY_CHECK_CONTRACT_ID, kind=DEPENDENCY_CHECK_KIND)


def memory_module_has_identity_default(module: Dict[str, Any]) -> bool:
    return any(
        str(module.get(key) or "").strip()
        and str(module.get(key) or "").strip().lower() not in {"unknown", "not specified", "none"}
        for key in ("display_part_number", "part_number", "PartNumber", "RawPartNumber")
    )


def memory_modules_default(privileged_helper_enabled: bool) -> list[Dict[str, Any]]:
    from .lvs_system_info import SystemInfoCollector

    return SystemInfoCollector(privileged_helper_enabled=privileged_helper_enabled)._memory_modules()


def storage_health_capability_default(privileged_helper_enabled: bool) -> Dict[str, Any]:
    from .lvs_storage_health import StorageHealthEnricher, storage_health_capability
    from .lvs_storage_inventory import collect_storage_info, read_text_sysfs

    sys_block = Path("/sys/block")
    enricher = StorageHealthEnricher(
        read_sysfs=read_text_sysfs,
        privileged_helper_enabled=privileged_helper_enabled,
    )
    entries = collect_storage_info(sys_block, read_text_sysfs, health_enricher=enricher)
    return storage_health_capability(
        entries,
        enricher.tool_capabilities(),
        baseline_available=sys_block.exists(),
    )


def storage_benchmark_capability_default(_privileged_helper_enabled: bool) -> Dict[str, Any]:
    from .lvs_fio_backend import storage_benchmark_capability
    return storage_benchmark_capability()


def gpu_opencl_coverage(workload_runner: Any) -> list[Dict[str, Any]]:
    discover = getattr(workload_runner, "_discover_gpu_cards", None)
    match_device = getattr(workload_runner, "_opencl_device_for_target", None)
    if not callable(discover) or not callable(match_device):
        return []
    gpu_cards = list(discover() or [])
    if len(gpu_cards) <= 1:
        return []
    vendor_fix = {
        "intel": "no matching Intel OpenCL device found after native, Intel ICD, and Rusticl iris probes",
        "nvidia": "no matching NVIDIA OpenCL device found after native and NVIDIA ICD probes",
        "amd": "no matching AMD OpenCL device found after native, AMD ICD, and Rusticl radeonsi probes",
    }
    coverage = []
    for card in gpu_cards:
        vendor = str(card.get("vendor", "") or "").strip().lower()
        target_id = str(card.get("target_id", "") or card.get("slot", "") or "")
        match = match_device(card)
        if match:
            coverage.append(
                {
                    "target_id": target_id,
                    "name": card.get("name") or "",
                    "vendor": card.get("vendor") or "",
                    "available": True,
                    "matched_device": str(match.get("name") or ""),
                    "required_env": match.get("required_env") or {},
                }
            )
        else:
            coverage.append(
                {
                    "target_id": target_id,
                    "name": card.get("name") or "",
                    "vendor": card.get("vendor") or "",
                    "available": False,
                    "fix": vendor_fix.get(
                        vendor,
                        f"no matching OpenCL device found for {vendor or 'this'} GPU after available probes",
                    ),
                }
            )
    return coverage
