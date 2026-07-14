#!/usr/bin/env python3
"""Workload-runner GPU worker and VRAM policy adapter methods."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from Modules.lvs_egl_gles_worker import build_egl_gles_workload_script
from Modules.lvs_egl_gles_workers import (
    build_python_gpu_3d_worker as build_egl_gles_gpu_3d_worker,
    build_python_vram_worker as build_egl_gles_vram_worker,
)
from Modules.lvs_external_gpu_workers import (
    build_supervised_external_gpu_command as external_gpu_build_supervised_command,
    external_gpu_backend_command as external_gpu_backend_command_for_runner,
    external_gpu_supervisor_script as external_gpu_supervisor_script_for_runner,
    external_gpu_worker_spec as external_gpu_worker_spec_for_runner,
    gpu_external_process_count as external_gpu_process_count_for_runner,
    gpu_external_target_env as external_gpu_target_env,
    vulkan_gpu_number_for_target as external_vulkan_gpu_number_for_target,
)
from Modules.lvs_gpu_backend_catalog import GPU_3D_INTENSITY_FACTORS, OPENCL_COMPUTE_VARIANTS
from Modules.lvs_gpu_backend_runner import vram_backend_name as backend_vram_backend_name
from Modules.lvs_gpu_worker_materializer import materialize_gpu_worker
from Modules.lvs_gpu_worker_params import (
    gpu_worker_baseline_params,
    gpu_worker_tuned_params,
    vulkan_compute_buffer_bytes as vulkan_compute_buffer_bytes_policy,
    vulkan_compute_dispatch_repeats as vulkan_compute_dispatch_repeats_policy,
    vulkan_compute_rounds as vulkan_compute_rounds_policy,
    vulkan_transfer_buffer_bytes as vulkan_transfer_buffer_bytes_policy,
)
from Modules.lvs_gpu_worker_plan import GpuWorkerSpec, serialize_gpu_worker_spec
from Modules.lvs_gpu_worker_planner import (
    build_gpu_3d_worker_specs,
    build_stage_gpu_worker_specs,
    build_vram_worker_specs,
)
from Modules.lvs_gpu_worker_retune import retune_gpu_worker as retune_gpu_worker_spec
from Modules.lvs_opencl_compute_worker import build_opencl_compute_workload_script
from Modules.lvs_opencl_vram_worker import build_opencl_vram_workload_script
from Modules.lvs_opencl_workers import (
    build_python_opencl_compute_worker as build_opencl_compute_worker_spec,
    build_python_opencl_vram_worker as build_opencl_vram_worker_spec,
)
from Modules.lvs_vram_policy import (
    amd_discrete_target_count as vram_policy_amd_discrete_target_count,
    concurrent_vram_skip_target_labels as vram_policy_concurrent_vram_skip_target_labels,
    opencl_device_looks_like_shared_memory as vram_policy_opencl_device_looks_like_shared_memory,
    resolve_target_vram_allocation_bytes as vram_policy_resolve_target_vram_allocation_bytes,
    route_vulkan_vram_worker_for_target as vram_policy_route_vulkan_vram_worker_for_target,
    shared_memory_gpu_target_total_bytes as vram_policy_shared_memory_gpu_target_total_bytes,
    skip_concurrent_vram_worker_for_target as vram_policy_skip_concurrent_vram_worker_for_target,
)
from Modules.lvs_vulkan_workers import (
    build_python_vulkan_compute_worker as build_vulkan_compute_worker_spec,
    build_python_vulkan_transfer_worker as build_vulkan_transfer_worker_spec,
    build_python_vulkan_vram_worker as build_vulkan_vram_worker_spec,
)


class WorkloadGpuWorkerMixin:
    """GPU worker construction and VRAM policy adapter surface."""

    def _gpu_3d_command(self, gpu: Any, stage: Optional[Any] = None) -> Optional[List[str]]:
        commands = self._gpu_3d_commands(gpu, stage)
        return commands[0] if commands else None

    def _gpu_3d_commands(self, gpu: Any, stage: Optional[Any] = None) -> List[List[str]]:
        return [worker.command for worker in self._gpu_3d_worker_specs(gpu, stage)]

    def _vulkan_gpu_number_for_target(self, target: Optional[Dict[str, Any]]) -> Optional[int]:
        return external_vulkan_gpu_number_for_target(self, target)

    def _external_gpu_backend_command(self, backend: str, target: Optional[Dict[str, Any]] = None) -> List[str]:
        return external_gpu_backend_command_for_runner(self, backend, target)

    def _gpu_external_target_env(
        self,
        target: Optional[Dict[str, Any]],
        backend: str,
    ) -> Dict[str, str]:
        return external_gpu_target_env(target, backend)

    def _gpu_external_process_count(
        self,
        target: Optional[Dict[str, Any]],
        backend: str,
    ) -> int:
        return external_gpu_process_count_for_runner(self, target, backend)

    def _build_supervised_external_gpu_command(
        self,
        *,
        backend: str,
        target: Optional[Dict[str, Any]],
        process_count: int,
        result_file: str = "",
    ) -> List[str]:
        return external_gpu_build_supervised_command(
            self,
            backend=backend,
            target=target,
            process_count=process_count,
            result_file=result_file,
        )

    def _external_gpu_supervisor_script(
        self,
        *,
        backend: str,
        child_command: List[str],
        child_env: Optional[Dict[str, str]],
        target: Optional[Dict[str, Any]],
        target_process_count: int,
        result_file: str = "",
    ) -> str:
        return external_gpu_supervisor_script_for_runner(
            self,
            backend=backend,
            child_command=child_command,
            child_env=child_env,
            target=target,
            target_process_count=target_process_count,
            result_file=result_file,
        )

    def _external_gpu_worker_spec(
        self,
        *,
        workload: str,
        backend: str,
        target: Optional[Dict[str, Any]],
        result_file: str = "",
        profile_mode: str = "",
        profile_intensity: str = "",
    ) -> GpuWorkerSpec:
        return external_gpu_worker_spec_for_runner(
            self,
            workload=workload,
            backend=backend,
            target=target,
            result_file=result_file,
            profile_mode=profile_mode,
            profile_intensity=profile_intensity,
        )

    def _gpu_3d_worker_specs(self, gpu: Any, stage: Optional[Any] = None) -> List[GpuWorkerSpec]:
        return build_gpu_3d_worker_specs(self, gpu, stage)

    def _vram_command(self, vram: Any) -> Optional[List[str]]:
        commands = self._vram_commands(vram)
        return commands[0] if commands else None

    def _vram_backend_name(self, vram: Any) -> str:
        return backend_vram_backend_name(self, vram)

    def _vram_commands(self, vram: Any) -> List[List[str]]:
        return [worker.command for worker in self._vram_worker_specs(vram)]

    def _vram_worker_specs(self, vram: Any, stage: Optional[Any] = None) -> List[GpuWorkerSpec]:
        return build_vram_worker_specs(self, vram, stage)

    def _gpu_worker_specs(self, stage: Any) -> List[GpuWorkerSpec]:
        return build_stage_gpu_worker_specs(self, stage)

    def _wrap_gpu_command(
        self,
        command: List[str],
        target: Optional[Dict[str, Any]],
        extra_env: Optional[Dict[str, str]] = None,
    ) -> List[str]:
        prefix = self._gpu_command_prefix(target, extra_env)
        return [*prefix, *command] if prefix else command

    def _gpu_command_prefix(
        self,
        target: Optional[Dict[str, Any]],
        extra_env: Optional[Dict[str, str]] = None,
    ) -> List[str]:
        env_pairs: List[str] = []
        selector = target.get("dri_prime") if target else ""
        if selector:
            env_pairs.append(f"DRI_PRIME={selector}")
        for key, value in (extra_env or {}).items():
            if not str(key).strip() or value is None:
                continue
            env_pairs.append(f"{key}={value}")
        return ["env", *env_pairs] if env_pairs else []

    def serialize_gpu_worker(self, worker: GpuWorkerSpec) -> Dict[str, Any]:
        return serialize_gpu_worker_spec(worker)

    def _materialize_gpu_worker(self, worker: GpuWorkerSpec, result_file: Optional[str] = None) -> GpuWorkerSpec:
        return materialize_gpu_worker(self, worker, result_file)

    def _normalize_gpu_3d_intensity(self, intensity: str) -> str:
        normalized = str(intensity or "").strip().lower()
        if normalized in GPU_3D_INTENSITY_FACTORS:
            return normalized
        return "extreme"

    def _normalize_opencl_compute_variant(self, variant: str) -> str:
        normalized = str(variant or "").strip().lower().replace("-", "_").replace(" ", "_")
        if normalized in OPENCL_COMPUTE_VARIANTS:
            return normalized
        return "baseline"

    def _normalize_vulkan_compute_variant(self, variant: str) -> str:
        normalized = str(variant or "").strip().lower().replace("-", "_").replace(" ", "_")
        if normalized in {"stress", "stress_hash", "hash_stress", "compute_stress"}:
            return "stress_hash"
        if normalized in {"memory", "memory_mix", "stateful", "stateful_memory"}:
            return "stateful_memory"
        return "hash"

    def _gpu_3d_intensity_factor(self, intensity: str) -> float:
        normalized = self._normalize_gpu_3d_intensity(intensity)
        return float(GPU_3D_INTENSITY_FACTORS.get(normalized, 1.0))

    def _gpu_worker_baseline(
        self,
        target: Optional[Dict[str, Any]],
        backend: str = "",
        workload: str = "gpu_3d",
        profile_intensity: str = "extreme",
        profile_mode: str = "steady",
    ) -> Dict[str, Any]:
        normalized_intensity = self._normalize_gpu_3d_intensity(profile_intensity)
        return gpu_worker_baseline_params(
            target,
            capability=self._gpu_capability_profile(target),
            backend=backend,
            workload=workload,
            normalized_profile_intensity=normalized_intensity,
            profile_intensity_factor=self._gpu_3d_intensity_factor(profile_intensity),
            profile_mode=profile_mode,
            safe_mode_enabled=self._gpu_safe_mode_enabled(),
            safe_max_load_scale=max(0.75, float(self._settings.gpu_safe_max_load_scale or 1.0)),
        )

    def _gpu_worker_tuned_params(
        self,
        target: Optional[Dict[str, Any]],
        tuning_step: int = 0,
        backend: str = "",
        workload: str = "gpu_3d",
        profile_intensity: str = "extreme",
        profile_mode: str = "steady",
    ) -> Dict[str, Any]:
        base = self._gpu_worker_baseline(
            target,
            backend=backend,
            workload=workload,
            profile_intensity=profile_intensity,
            profile_mode=profile_mode,
        )
        return gpu_worker_tuned_params(
            base,
            tuning_step=tuning_step,
            backend=backend,
            workload=workload,
            safe_mode_enabled=self._gpu_safe_mode_enabled(),
        )

    def _build_python_gpu_3d_worker(
        self,
        target: Optional[Dict[str, Any]],
        tuning_step: int = 0,
        result_file: str = "",
        profile_mode: str = "steady",
        profile_intensity: str = "extreme",
        compute_variant: str = "baseline",
    ) -> GpuWorkerSpec:
        return build_egl_gles_gpu_3d_worker(
            self,
            target,
            tuning_step=tuning_step,
            result_file=result_file,
            profile_mode=profile_mode,
            profile_intensity=profile_intensity,
            compute_variant=compute_variant,
        )

    def _build_python_vram_worker(
        self,
        target: Optional[Dict[str, Any]],
        target_vram_bytes: int,
        tuning_step: int = 0,
        result_file: str = "",
    ) -> GpuWorkerSpec:
        return build_egl_gles_vram_worker(
            self,
            target,
            target_vram_bytes,
            tuning_step=tuning_step,
            result_file=result_file,
        )

    def _build_python_opencl_compute_worker(
        self,
        target: Optional[Dict[str, Any]],
        tuning_step: int = 0,
        result_file: str = "",
        profile_mode: str = "steady",
        profile_intensity: str = "extreme",
        compute_variant: str = "baseline",
    ) -> GpuWorkerSpec:
        return build_opencl_compute_worker_spec(
            self,
            target,
            tuning_step=tuning_step,
            result_file=result_file,
            profile_mode=profile_mode,
            profile_intensity=profile_intensity,
            compute_variant=compute_variant,
        )

    def _vulkan_transfer_buffer_bytes(self, target: Optional[Dict[str, Any]], params: Dict[str, Any]) -> int:
        return vulkan_transfer_buffer_bytes_policy(
            target,
            params,
            safe_mode_enabled=self._gpu_safe_mode_enabled(),
        )

    def _vulkan_compute_buffer_bytes(
        self,
        target: Optional[Dict[str, Any]],
        params: Dict[str, Any],
        compute_variant: str = "hash",
        allocation_percent: int = 0,
    ) -> int:
        normalized_variant = self._normalize_vulkan_compute_variant(compute_variant)
        return vulkan_compute_buffer_bytes_policy(
            target,
            params,
            normalized_variant=normalized_variant,
            allocation_percent=allocation_percent,
            safe_mode_enabled=self._gpu_safe_mode_enabled(),
            cap_gpu_vram_target_bytes=self._cap_gpu_vram_target_bytes,
        )

    def _vulkan_compute_rounds(
        self,
        target: Optional[Dict[str, Any]],
        params: Dict[str, Any],
        profile_intensity: str,
        compute_variant: str = "hash",
    ) -> int:
        normalized_variant = self._normalize_vulkan_compute_variant(compute_variant)
        return vulkan_compute_rounds_policy(
            params,
            profile_intensity_factor=self._gpu_3d_intensity_factor(profile_intensity),
            normalized_variant=normalized_variant,
            safe_mode_enabled=self._gpu_safe_mode_enabled(),
        )

    def _vulkan_compute_dispatch_repeats(
        self,
        target: Optional[Dict[str, Any]],
        compute_variant: str = "hash",
    ) -> int:
        normalized_variant = self._normalize_vulkan_compute_variant(compute_variant)
        return vulkan_compute_dispatch_repeats_policy(
            target,
            normalized_variant=normalized_variant,
        )

    def _build_python_vulkan_transfer_worker(
        self,
        target: Optional[Dict[str, Any]],
        tuning_step: int = 0,
        result_file: str = "",
        profile_mode: str = "steady",
        profile_intensity: str = "extreme",
    ) -> GpuWorkerSpec:
        return build_vulkan_transfer_worker_spec(
            self,
            target,
            tuning_step=tuning_step,
            result_file=result_file,
            profile_mode=profile_mode,
            profile_intensity=profile_intensity,
        )

    def _build_python_vulkan_compute_worker(
        self,
        target: Optional[Dict[str, Any]],
        tuning_step: int = 0,
        result_file: str = "",
        profile_mode: str = "steady",
        profile_intensity: str = "extreme",
        compute_variant: str = "hash",
        allocation_percent: int = 0,
        buffer_bytes_override: int = 0,
    ) -> GpuWorkerSpec:
        return build_vulkan_compute_worker_spec(
            self,
            target,
            tuning_step=tuning_step,
            result_file=result_file,
            profile_mode=profile_mode,
            profile_intensity=profile_intensity,
            compute_variant=compute_variant,
            allocation_percent=allocation_percent,
            buffer_bytes_override=buffer_bytes_override,
        )

    def _build_python_vulkan_vram_worker(
        self,
        target: Optional[Dict[str, Any]],
        target_vram_bytes: int,
        tuning_step: int = 0,
        result_file: str = "",
    ) -> GpuWorkerSpec:
        return build_vulkan_vram_worker_spec(
            self,
            target,
            target_vram_bytes,
            tuning_step=tuning_step,
            result_file=result_file,
        )

    def _build_python_opencl_vram_worker(
        self,
        target: Optional[Dict[str, Any]],
        target_vram_bytes: int,
        tuning_step: int = 0,
        result_file: str = "",
    ) -> GpuWorkerSpec:
        return build_opencl_vram_worker_spec(
            self,
            target,
            target_vram_bytes,
            tuning_step=tuning_step,
            result_file=result_file,
        )

    def retune_gpu_worker(self, spec: GpuWorkerSpec) -> Optional[GpuWorkerSpec]:
        return retune_gpu_worker_spec(self, spec)

    def _shared_memory_gpu_target_total_bytes(
        self,
        opencl_global_mem_bytes: int = 0,
        memory_allocation_percent: int = 0,
        concurrent_gpu_3d: bool = False,
        stage_duration_seconds: int = 0,
    ) -> int:
        system_total = self._system_memory_total_bytes()
        return vram_policy_shared_memory_gpu_target_total_bytes(
            opencl_global_mem_bytes=opencl_global_mem_bytes,
            system_total=system_total,
            system_available=self._system_memory_available_bytes() or system_total,
            memory_allocation_percent=memory_allocation_percent,
            concurrent_gpu_3d=concurrent_gpu_3d,
            stage_duration_seconds=stage_duration_seconds,
        )

    def _opencl_device_looks_like_shared_memory(
        self,
        target: Optional[Dict[str, Any]],
        opencl_device: Optional[Dict[str, Any]],
    ) -> bool:
        capability = self._gpu_capability_profile(target)
        device_class = str(capability.get("device_class", "") or "").strip().lower()
        return vram_policy_opencl_device_looks_like_shared_memory(
            device_class=device_class,
            opencl_global_mem_bytes=int((opencl_device or {}).get("global_mem_bytes", 0) or 0),
            system_total=self._system_memory_total_bytes(),
            explicit_vram_total=int((target or {}).get("vram_total") or 0),
        )

    def _target_vram_allocation_bytes(
        self,
        allocation_percent: int,
        target: Optional[Dict[str, Any]] = None,
        memory_allocation_percent: int = 0,
        concurrent_gpu_3d: bool = False,
        stage_duration_seconds: int = 0,
        concurrent_amd_discrete_target_count: int = 0,
        vram_backend: str = "",
    ) -> int:
        return vram_policy_resolve_target_vram_allocation_bytes(
            allocation_percent=allocation_percent,
            target=target,
            memory_allocation_percent=memory_allocation_percent,
            concurrent_gpu_3d=concurrent_gpu_3d,
            stage_duration_seconds=stage_duration_seconds,
            opencl_device_for_target=self._opencl_device_for_target,
            capability_for_target=self._gpu_capability_profile,
            system_memory_total=self._system_memory_total_bytes,
            system_memory_available=self._system_memory_available_bytes,
            sysfs_vram_totals=lambda: (
                value
                for value in (
                    self._safe_read_int(path)
                    for path in Path("/sys/class/drm").glob("card[0-9]*/device/mem_info_vram_total")
                )
                if value and value > 0
            ),
        )

    def _amd_discrete_target_count(self, targets: List[Optional[Dict[str, Any]]]) -> int:
        return vram_policy_amd_discrete_target_count(
            (target, self._gpu_capability_profile(target) if target is not None else {})
            for target in targets
        )

    def _skip_concurrent_vram_worker_for_target(
        self,
        target: Optional[Dict[str, Any]],
        concurrent_gpu_3d: bool = False,
        concurrent_amd_discrete_target_count: int = 0,
        vram_backend: str = "",
    ) -> bool:
        if not concurrent_gpu_3d or target is None:
            return False
        capability = self._gpu_capability_profile(target)
        return vram_policy_skip_concurrent_vram_worker_for_target(
            target=target,
            capability=capability,
            concurrent_gpu_3d=concurrent_gpu_3d,
            concurrent_amd_discrete_target_count=concurrent_amd_discrete_target_count,
            vram_backend=vram_backend,
        )

    def _use_vulkan_vram_worker_for_target(
        self,
        target: Optional[Dict[str, Any]],
        concurrent_gpu_3d: bool = False,
        concurrent_amd_discrete_target_count: int = 0,
        resolved_vram_backend: str = "",
    ) -> bool:
        return vram_policy_route_vulkan_vram_worker_for_target(
            target=target,
            concurrent_gpu_3d=concurrent_gpu_3d,
            concurrent_amd_discrete_target_count=concurrent_amd_discrete_target_count,
            resolved_vram_backend=resolved_vram_backend,
            capability_for_target=self._gpu_capability_profile,
            vram_backend_available=self._vram_backend_available,
            gpu_backend_target_supported=lambda backend, gpu_target, workload: bool(
                self._gpu_backend_target_support(backend, gpu_target, workload).get("supported")
            ),
        )

    def _concurrent_vram_skip_target_labels(
        self,
        targets: List[Optional[Dict[str, Any]]],
        concurrent_gpu_3d: bool = False,
        vram_backend: str = "",
    ) -> List[str]:
        return vram_policy_concurrent_vram_skip_target_labels(
            targets=targets,
            concurrent_gpu_3d=concurrent_gpu_3d,
            vram_backend=vram_backend,
            capability_for_target=self._gpu_capability_profile,
            vram_backend_available=self._vram_backend_available,
            gpu_backend_target_supported=lambda backend, gpu_target, workload: bool(
                self._gpu_backend_target_support(backend, gpu_target, workload).get("supported")
            ),
        )

    def _opencl_compute_workload_script(
        self,
        *,
        target_vendor: str,
        target_vendor_id: str,
        target_name: str,
        target_card: str,
        target_slot: str,
        target_id: str,
        target_gpu_index: int,
        target_vram_total: int,
        worker_params: Optional[Dict[str, Any]] = None,
    ) -> str:
        params = worker_params or {}
        compute_variant = self._normalize_opencl_compute_variant(
            str(params.get("compute_variant", "baseline") or "baseline")
        )
        return build_opencl_compute_workload_script(
            target_vendor=target_vendor,
            target_vendor_id=target_vendor_id,
            target_name=target_name,
            target_card=target_card,
            target_slot=target_slot,
            target_id=target_id,
            target_gpu_index=target_gpu_index,
            target_vram_total=target_vram_total,
            compute_variant=compute_variant,
            worker_params=worker_params,
        )

    def _opencl_vram_workload_script(
        self,
        target_vram_bytes: int,
        target_vendor: str,
        target_vendor_id: str,
        target_name: str,
        target_card: str,
        target_slot: str,
        target_id: str,
        target_gpu_index: int,
        target_vram_total: int,
        worker_params: Optional[Dict[str, Any]] = None,
        result_file: str = "",
    ) -> str:
        return build_opencl_vram_workload_script(
            target_vram_bytes,
            target_vendor,
            target_vendor_id,
            target_name,
            target_card,
            target_slot,
            target_id,
            target_gpu_index,
            target_vram_total,
            worker_params=worker_params,
            result_file=result_file,
        )

    def _egl_gles_workload_script(
        self,
        mode: str,
        target_vram_bytes: int = 0,
        worker_params: Optional[Dict[str, int]] = None,
    ) -> str:
        return build_egl_gles_workload_script(
            mode,
            target_vram_bytes=target_vram_bytes,
            worker_params=worker_params,
        )
