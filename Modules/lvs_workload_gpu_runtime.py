#!/usr/bin/env python3
"""Workload-runner GPU runtime, backend, and target adapter methods."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from Modules.lvs_backend_readiness import build_vulkan_transfer_backend_payload
from Modules.lvs_egl_probe_script import build_egl_probe_script
from Modules.lvs_egl_target_probe import (
    egl_gpu_backend_for_target as egl_gpu_backend_for_target_runner,
    egl_target_identity_env as egl_target_identity_env_for_runner,
    is_software_renderer as egl_is_software_renderer,
    mesa_egl_vendor_json as egl_mesa_egl_vendor_json,
    probe_egl_runtime_backend,
    renderer_matches_gpu_target as egl_renderer_matches_gpu_target,
    run_egl_target_probe as run_egl_target_probe_for_runner,
)
from Modules.lvs_gpu_backend_catalog import (
    GpuBackendAvailabilityContext,
    gpu_3d_backend_candidates_by_preference,
    gpu_3d_backend_catalog_entry,
    gpu_3d_backend_load_class,
    gpu_3d_backend_preference_catalog,
    normalize_gpu_3d_backend_preference,
    normalize_vram_backend_preference,
    vram_backend_candidates,
)
from Modules.lvs_gpu_backend_runner import (
    allow_per_target_auto_gpu_3d_backends_for_runner,
    effective_gpu_targets as backend_effective_gpu_targets,
    gpu_3d_backend_available as backend_gpu_3d_backend_available,
    gpu_3d_backend_candidates as backend_gpu_3d_backend_candidates,
    gpu_3d_backend_name as backend_gpu_3d_backend_name,
    gpu_backend_availability_context as backend_gpu_backend_availability_context,
    gpu_backend_support_summary as backend_gpu_backend_support_summary,
    gpu_backend_target_support as backend_gpu_backend_target_support,
    gpu_target_cache_key as backend_gpu_target_cache_key,
    prefer_graphics_backend_for_mixed_stage as backend_prefer_graphics_backend_for_mixed_stage,
    resolve_gpu_backend_for_targets as backend_resolve_gpu_backend_for_targets,
    vram_backend_available as backend_vram_backend_available,
)
from Modules.lvs_gpu_capability import (
    build_gpu_capability_profile,
    gpu_capability_cache_key,
    likely_discrete_target_ids,
)
from Modules.lvs_gpu_identity import gpu_vendor_name, normalize_pci_id, normalize_pci_slot
from Modules.lvs_gpu_target_resolution import (
    gpu_vendor_matches_text_for_runner as target_resolution_gpu_vendor_matches_text,
    opencl_best_device_for_target as target_resolution_opencl_best_device_for_target,
    opencl_device_for_target as target_resolution_opencl_device_for_target,
    opencl_device_score_for_target as target_resolution_opencl_device_score_for_target,
    slot_from_mesa_style_vulkan_uuid as target_resolution_slot_from_mesa_style_vulkan_uuid,
    vulkan_device_class as target_resolution_vulkan_device_class,
    vulkan_device_for_target as target_resolution_vulkan_device_for_target,
    vulkan_device_pci_slot as target_resolution_vulkan_device_pci_slot,
    vulkan_device_score_for_target as target_resolution_vulkan_device_score_for_target,
)
from Modules.lvs_gpu_targets import (
    discover_gpu_cards as discover_gpu_target_cards,
    discover_nvidia_smi_gpus as discover_nvidia_smi_target_gpus,
    dri_prime_selector,
    gpu_card_class,
    gpu_target_by_id,
    gpu_target_display_label,
    gpu_target_summary,
    gpu_targets,
    likely_discrete_gpu_cards,
    load_pci_device_names,
    lookup_pci_device_name,
)
from Modules.lvs_opencl_probe_script import build_opencl_probe_script
from Modules.lvs_opencl_runtime import discover_opencl_backend, probe_opencl_runtime_context
from Modules.lvs_opencl_targeting import (
    append_opencl_probe_devices,
    gpu_vendor_aliases,
    opencl_device_identity_key,
    opencl_discover_icds,
    opencl_env_candidates_for_target,
    opencl_find_icd,
    opencl_runtime_context_candidates,
)
from Modules.lvs_vulkan_runtime import (
    build_vulkan_native_runtime_backend,
    collect_vulkan_native_physical_devices,
    collect_vulkan_runtime_details,
    resolve_vulkan_library,
)

DEFAULT_NATIVE_DIR = Path("native")


class WorkloadGpuRuntimeMixin:
    """GPU runtime/target adapter surface used by workload planning modules."""

    def _normalize_pci_id(self, value: str) -> str:
        return normalize_pci_id(value)

    def _load_pci_device_names(self) -> Dict[str, Dict[str, str]]:
        if self._pci_device_names is not None:
            return self._pci_device_names
        self._pci_device_names = load_pci_device_names()
        return self._pci_device_names

    def _lookup_pci_device_name(self, vendor_id: str, device_id: str) -> Optional[str]:
        return lookup_pci_device_name(self._load_pci_device_names(), vendor_id, device_id)

    def _vulkan_runtime_details(self) -> Dict[str, Any]:
        if self._vulkan_runtime_cache is not None:
            return self._vulkan_runtime_cache
        self._vulkan_runtime_cache = collect_vulkan_runtime_details(
            command_exists=self._command_exists,
            command_env=self._command_env,
        )
        return self._vulkan_runtime_cache

    def _resolve_vulkan_library(self) -> str:
        return resolve_vulkan_library()

    def _vulkan_native_physical_devices(self, library: str) -> Dict[str, Any]:
        return collect_vulkan_native_physical_devices(library)

    def _vulkan_native_backend(self) -> Dict[str, Any]:
        return build_vulkan_native_runtime_backend(
            runtime=self._vulkan_runtime_details(),
            worker_path=DEFAULT_NATIVE_DIR / "vulkan_compute_worker.py",
            library_resolver=self._resolve_vulkan_library,
            native_inventory_collector=self._vulkan_native_physical_devices,
        )

    def _vulkan_transfer_backend(self) -> Dict[str, Any]:
        return build_vulkan_transfer_backend_payload(
            self._vulkan_native_backend(),
            worker_path=DEFAULT_NATIVE_DIR / "vulkan_transfer_worker.py",
        )

    def _normalize_gpu_3d_backend_preference(self, preference: str) -> str:
        return normalize_gpu_3d_backend_preference(preference)

    def _normalize_vram_backend_preference(self, preference: str) -> str:
        return normalize_vram_backend_preference(preference)

    def _gpu_3d_backend_catalog_entry(self, backend: str) -> Dict[str, Any]:
        return gpu_3d_backend_catalog_entry(backend)

    def _gpu_3d_backend_preference_catalog(self, preference: str) -> List[Dict[str, Any]]:
        return gpu_3d_backend_preference_catalog(preference)

    def _gpu_3d_backend_candidates_by_preference(self, preference: str) -> List[str]:
        return gpu_3d_backend_candidates_by_preference(preference)

    def _prefer_graphics_backend_for_mixed_stage(self, gpu: Any, stage: Optional[Any]) -> bool:
        return backend_prefer_graphics_backend_for_mixed_stage(self, gpu, stage)

    def _gpu_3d_backend_candidates(self, gpu: Any, stage: Optional[Any] = None) -> List[str]:
        return backend_gpu_3d_backend_candidates(self, gpu, stage)

    def _allow_per_target_auto_gpu_3d_backends(self, gpu: Any, stage: Optional[Any]) -> bool:
        return allow_per_target_auto_gpu_3d_backends_for_runner(self, gpu, stage)

    def _gpu_3d_backend_load_class(self, backend: str) -> str:
        return gpu_3d_backend_load_class(backend)

    def _vram_backend_candidates(self, vram: Any) -> List[str]:
        return vram_backend_candidates(vram.backend_preference)

    def _gpu_backend_availability_context(self) -> GpuBackendAvailabilityContext:
        return backend_gpu_backend_availability_context(self)

    def _gpu_3d_backend_available(self, backend: str) -> bool:
        return backend_gpu_3d_backend_available(self, backend)

    def _vram_backend_available(self, backend: str) -> bool:
        return backend_vram_backend_available(self, backend)

    def _gpu_target_cache_key(self, target: Optional[Dict[str, Any]]) -> str:
        return backend_gpu_target_cache_key(target)

    def _renderer_matches_gpu_target(
        self,
        renderer_text: str,
        target: Optional[Dict[str, Any]],
    ) -> bool:
        return egl_renderer_matches_gpu_target(renderer_text, target)

    def _mesa_egl_vendor_json(self) -> str:
        return egl_mesa_egl_vendor_json()

    def _egl_target_identity_env(self, target: Optional[Dict[str, Any]]) -> Dict[str, str]:
        return egl_target_identity_env_for_runner(self, target)

    def _run_egl_target_probe(
        self,
        target: Dict[str, Any],
        extra_env: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        return run_egl_target_probe_for_runner(self, target, extra_env)

    def _egl_gpu_backend_for_target(self, target: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        return egl_gpu_backend_for_target_runner(self, target)

    def _gpu_backend_target_support(
        self,
        backend: str,
        target: Optional[Dict[str, Any]],
        workload: str,
    ) -> Dict[str, Any]:
        return backend_gpu_backend_target_support(self, backend, target, workload)

    def _gpu_backend_support_summary(
        self,
        backend: str,
        targets: List[Dict[str, Any]],
        workload: str,
    ) -> Dict[str, Any]:
        return backend_gpu_backend_support_summary(self, backend, targets, workload)

    def _resolve_gpu_backend_for_targets(
        self,
        *,
        candidates: List[str],
        targets: List[Dict[str, Any]],
        workload: str,
    ) -> Dict[str, Any]:
        return backend_resolve_gpu_backend_for_targets(
            self,
            candidates=candidates,
            targets=targets,
            workload=workload,
        )

    def _gpu_3d_backend_name(self, gpu: Any, stage: Optional[Any] = None) -> str:
        return backend_gpu_3d_backend_name(self, gpu, stage)

    def _effective_gpu_targets(
        self,
        targets: List[Dict[str, Any]],
        resolution: Optional[Dict[str, Any]],
    ) -> List[Optional[Dict[str, Any]]]:
        return backend_effective_gpu_targets(targets, resolution)

    def _opencl_target_env(self, target: Optional[Dict[str, Any]], base_env: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        env = dict(base_env or {})
        if not target:
            return env
        if str(target.get("vendor", "") or "").strip().lower() == "nvidia":
            visible_source = ""
            if visible_source is None or str(visible_source).strip() == "":
                visible_source = target.get("nvidia_index")
            if visible_source is None or str(visible_source).strip() == "":
                visible_source = target.get("nvidia_uuid")
            visible_id = str(visible_source if visible_source is not None else "").strip()
            if visible_id:
                # CUDA_VISIBLE_DEVICES accepts NVML/NVIDIA ordinals or UUIDs,
                # not the raw OpenCL index. If nvidia-smi has already dropped a
                # card, using the OpenCL index here can hide every device from
                # the worker. Without a valid NVML identity, leave all devices
                # visible and let the worker select by PCI slot.
                env.setdefault("CUDA_DEVICE_ORDER", "PCI_BUS_ID")
                env["CUDA_VISIBLE_DEVICES"] = visible_id
        return env

    def _preferred_gpu_target(self) -> Optional[Dict[str, Any]]:
        targets = self._gpu_targets("discrete_max_vram")
        return targets[0] if targets else None

    def _stage_gpu_target_mode(self, stage: Any) -> str:
        if stage.modules.vram.enabled:
            return stage.modules.vram.gpus
        if stage.modules.gpu_3d.enabled:
            return stage.modules.gpu_3d.gpus
        return ""

    def _gpu_targets(self, selection: str) -> List[Dict[str, Any]]:
        return gpu_targets(selection, self._discover_gpu_cards())

    def _discover_gpu_cards(self) -> List[Dict[str, Any]]:
        return discover_gpu_target_cards(
            pci_name_lookup=self._lookup_pci_device_name,
            safe_read_int=self._safe_read_int,
            nvidia_smi_gpus=self._discover_nvidia_smi_gpus(),
        )

    def _gpu_vendor_name(self, vendor_id: str) -> str:
        return gpu_vendor_name(vendor_id)

    def _normalize_pci_slot(self, slot: str) -> str:
        return normalize_pci_slot(slot)

    def _discover_nvidia_smi_gpus(self) -> List[Dict[str, Any]]:
        return discover_nvidia_smi_target_gpus(self._command_exists, self._command_env)

    def _likely_discrete_gpu_cards(self, cards: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return likely_discrete_gpu_cards(cards)

    def _gpu_card_class(self, card: Dict[str, Any]) -> str:
        return gpu_card_class(card)

    def _gpu_target_summary(self, selection: str) -> str:
        return gpu_target_summary(selection)

    def _gpu_target_display_label(self, card: Dict[str, Any]) -> str:
        return gpu_target_display_label(card)

    def _gpu_target_by_id(self, target_id: str) -> Optional[Dict[str, Any]]:
        return gpu_target_by_id(self._discover_gpu_cards(), target_id)

    def _opencl_device_score_for_target(self, device: Dict[str, Any], target: Optional[Dict[str, Any]]) -> float:
        return target_resolution_opencl_device_score_for_target(self, device, target)

    def _opencl_best_device_for_target(
        self,
        devices: List[Dict[str, Any]],
        target: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        return target_resolution_opencl_best_device_for_target(self, devices, target)

    def _opencl_device_for_target(self, target: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        return target_resolution_opencl_device_for_target(self, target)

    def _gpu_vendor_aliases(self, vendor: str) -> set[str]:
        return gpu_vendor_aliases(vendor)

    def _gpu_vendor_matches_text(self, vendor: str, *texts: str) -> bool:
        return target_resolution_gpu_vendor_matches_text(vendor, *texts)

    def _vulkan_device_score_for_target(self, device: Dict[str, Any], target: Optional[Dict[str, Any]]) -> float:
        return target_resolution_vulkan_device_score_for_target(self, device, target)

    def _vulkan_device_pci_slot(self, device: Dict[str, Any]) -> str:
        return target_resolution_vulkan_device_pci_slot(self, device)

    def _slot_from_mesa_style_vulkan_uuid(self, uuid_text: str) -> str:
        return target_resolution_slot_from_mesa_style_vulkan_uuid(self, uuid_text)

    def _vulkan_device_for_target(self, target: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        return target_resolution_vulkan_device_for_target(self, target)

    def _vulkan_device_class(self, target: Optional[Dict[str, Any]]) -> str:
        return target_resolution_vulkan_device_class(self, target)

    def _gpu_capability_profile(self, target: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        cache_key = gpu_capability_cache_key(target)
        cached = self._gpu_capability_cache.get(cache_key)
        if cached is not None:
            return dict(cached)
        profile = build_gpu_capability_profile(
            target=target,
            likely_discrete_ids=likely_discrete_target_ids(
                self._likely_discrete_gpu_cards(self._discover_gpu_cards())
            ),
            explicit_device_class=self._gpu_card_class(target or {}),
            vulkan_device_class=self._vulkan_device_class(target),
            opencl_device=self._opencl_device_for_target(target),
        )
        self._gpu_capability_cache[cache_key] = dict(profile)
        return dict(profile)

    def _vulkan_target_env(self, target: Optional[Dict[str, Any]]) -> Dict[str, str]:
        if not target:
            return {}
        vendor_id = str(target.get("vendor_id", "") or "").strip().lower().removeprefix("0x")
        device_id = str(target.get("device", "") or "").strip().lower().removeprefix("0x")
        if vendor_id and device_id:
            duplicate_count = sum(
                1
                for device in (self._vulkan_runtime_details().get("devices") or [])
                if str(device.get("vendorID", "") or "").strip().lower().removeprefix("0x") == vendor_id
                and str(device.get("deviceID", "") or "").strip().lower().removeprefix("0x") == device_id
            )
            if duplicate_count > 1:
                # MESA_VK_DEVICE_SELECT can only express vendor:device here,
                # which is not unique for identical multi-GPU systems. Leaving
                # all devices visible lets the worker choose by PCI slot when
                # available, or by planned target index as a fallback.
                return {}
        if vendor_id and device_id:
            return {"MESA_VK_DEVICE_SELECT": f"{vendor_id}:{device_id}"}
        return {}

    def _dri_prime_selector(self, slot: str) -> str:
        return dri_prime_selector(slot)

    def _egl_gpu_backend(self) -> Dict[str, Any]:
        if self._egl_probe_cache is not None:
            return self._egl_probe_cache
        self._egl_probe_cache = probe_egl_runtime_backend(
            python_runtime=self._python_runtime(),
            probe_script=self._egl_probe_script(),
            preferred_target=self._preferred_gpu_target(),
            command_env=self._command_env,
            software_renderer_check=self._is_software_renderer,
        )
        return self._egl_probe_cache

    def _egl_probe_script(self) -> str:
        return build_egl_probe_script()

    def _is_software_renderer(self, renderer: str) -> bool:
        return egl_is_software_renderer(renderer)

    def _opencl_runtime_context_candidates(self, native_probe: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        return opencl_runtime_context_candidates(
            env_overrides=self._env_overrides,
            gpu_cards=self._discover_gpu_cards(),
            native_probe=native_probe,
        )

    def _opencl_probe_attempt(self, context_name: str, extra_env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        return probe_opencl_runtime_context(
            context_name=context_name,
            extra_env=extra_env,
            python_runtime=self._python_runtime(),
            probe_script=self._opencl_probe_script(),
            command_env=self._command_env,
        )

    def _opencl_discover_icds(self) -> List[Dict[str, Any]]:
        return opencl_discover_icds()

    def _opencl_find_icd(self, icds: List[Dict[str, Any]], keywords: Iterable[str]) -> Optional[Dict[str, Any]]:
        return opencl_find_icd(icds, keywords)

    def _opencl_env_candidates_for_target(
        self,
        target: Dict[str, Any],
        icds: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        return opencl_env_candidates_for_target(target, icds)

    def _opencl_device_identity_key(self, device: Dict[str, Any], required_env: Optional[Dict[str, str]] = None) -> tuple:
        return opencl_device_identity_key(device, required_env)

    def _append_opencl_probe_devices(
        self,
        devices: List[Dict[str, Any]],
        probe: Dict[str, Any],
        required_env: Dict[str, str],
        seen: set,
    ) -> None:
        append_opencl_probe_devices(devices, probe, required_env, seen)

    def _opencl_gpu_backend(self) -> Dict[str, Any]:
        if self._opencl_probe_cache is not None:
            return self._opencl_probe_cache
        self._opencl_probe_cache = discover_opencl_backend(
            probe_attempt=self._opencl_probe_attempt,
            runtime_context_candidates=self._opencl_runtime_context_candidates,
            gpu_cards=self._discover_gpu_cards(),
            discover_icds=self._opencl_discover_icds,
            best_device_for_target=self._opencl_best_device_for_target,
            env_candidates_for_target=self._opencl_env_candidates_for_target,
            device_identity_key=self._opencl_device_identity_key,
            append_probe_devices=self._append_opencl_probe_devices,
        )
        return self._opencl_probe_cache

    def _safe_read_int(self, path: Path) -> Optional[int]:
        try:
            return int(path.read_text(encoding="utf-8", errors="ignore").strip())
        except Exception:
            return None

    def _opencl_probe_script(self) -> str:
        return build_opencl_probe_script()
