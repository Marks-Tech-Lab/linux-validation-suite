from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional
from Modules.lvs_backend_readiness import (
    collect_backend_availability_from_runner,
    collect_backend_details_from_runner,
)
from Modules.lvs_gpu_backend_catalog import (
    GPU_3D_BACKEND_CATALOG,
)
from Modules.lvs_opencl_runtime import opencl_compute_safety_profile
from Modules.lvs_vram_policy import (
    cap_gpu_vram_target_bytes as vram_policy_cap_gpu_vram_target_bytes,
    capacity_vram_request_cap_bytes as vram_policy_capacity_vram_request_cap_bytes,
)
from Modules.lvs_intel_gpu_sidecar import (
    collect_intel_gpu_top_details,
)
from Modules.lvs_native_helpers import NativeHelperRuntimeService
from Modules.lvs_profile_models import (
    StageConfig,
    ValidationProfile,
)
from Modules.lvs_settings import (
    GlobalSettings,
)
from Modules.lvs_stage_launch_plan import build_stage_launch_commands
from Modules.lvs_runtime_memory_guard import initialize_runtime_memory_guard
from Modules.lvs_system_memory_budget import (
    apply_stage_system_memory_plan,
    build_stage_system_memory_plan,
)
from Modules.lvs_dry_run import (
    build_dry_run_plan,
    build_stage_diagnostics,
)
from Modules.lvs_stage_process_control import (
    StageProcess,
    launch_stage_processes_from_plan,
    stop_processes as stop_process_list,
    stop_stage_processes as stop_stage_process_list,
)
from Modules.lvs_workload_cpu_memory import WorkloadCpuMemoryMixin
from Modules.lvs_workload_gpu_workers import WorkloadGpuWorkerMixin
from Modules.lvs_workload_gpu_runtime import WorkloadGpuRuntimeMixin



class WorkloadRunner(WorkloadCpuMemoryMixin, WorkloadGpuRuntimeMixin, WorkloadGpuWorkerMixin):
    def __init__(
        self,
        env_overrides: Optional[Dict[str, str]] = None,
        settings: Optional[GlobalSettings] = None,
    ) -> None:
        self._env_overrides = {
            str(key): str(value)
            for key, value in (env_overrides or {}).items()
            if str(key).strip() and value is not None
        }
        self._settings = settings
        self._native_helper_runtime = NativeHelperRuntimeService(command_env=self._command_env)
        self._egl_probe_cache: Optional[Dict[str, Any]] = None
        self._egl_target_probe_cache: Dict[str, Dict[str, Any]] = {}
        self._opencl_probe_cache: Optional[Dict[str, Any]] = None
        self._vulkan_runtime_cache: Optional[Dict[str, Any]] = None
        self._vulkan_native_backend_cache: Optional[Dict[str, Any]] = None
        self._cpu_tuning_cache: Dict[Any, Dict[str, Any]] = {}
        self._cpu_power_tuning_available_cache: Optional[bool] = None
        self._cpu_power_capability_cache: Optional[Dict[str, Any]] = None
        self._gpu_capability_cache: Dict[str, Dict[str, Any]] = {}
        self._gpu_backend_target_support_cache: Dict[tuple[str, str, str], Dict[str, Any]] = {}
        self._pci_device_names: Optional[Dict[str, Dict[str, str]]] = None

    def _gpu_safe_mode_enabled(self) -> bool:
        return bool(self._settings and self._settings.gpu_safe_mode)

    def _gpu_internal_ramp_params(self) -> Dict[str, float]:
        if not self._gpu_safe_mode_enabled():
            return {
                "ramp_step_seconds": 0.0,
                "start_load_fraction": 1.0,
            }
        return {
            "ramp_step_seconds": max(0.0, float(self._settings.gpu_internal_ramp_step_seconds or 0.0)),
            "start_load_fraction": max(0.15, min(1.0, float(self._settings.gpu_safe_start_load_fraction or 1.0))),
        }

    def _gpu_safe_max_tuning_step(self) -> int:
        if not self._gpu_safe_mode_enabled():
            return 8
        return max(0, int(self._settings.gpu_safe_max_tuning_step or 0))

    def _cap_gpu_vram_target_bytes(self, target: Optional[Dict[str, Any]], requested_bytes: int) -> int:
        capability = self._gpu_capability_profile(target) if target else {}
        if str(capability.get("memory_kind") or "") == "shared":
            target_total = int(capability.get("shared_addressable_capacity_bytes") or 0)
        else:
            target_total = int(target.get("vram_total") or 0) if target else 0
        return vram_policy_cap_gpu_vram_target_bytes(
            requested_bytes=requested_bytes,
            target_total=target_total,
            safe_mode_enabled=self._gpu_safe_mode_enabled(),
            safe_max_vram_percent=float(self._settings.gpu_safe_max_vram_percent or 100.0),
        )

    def _capacity_vram_request_cap_bytes(self, target_total: int) -> int:
        return vram_policy_capacity_vram_request_cap_bytes(target_total)

    def runtime_environment(self) -> Dict[str, str]:
        return dict(self._env_overrides)

    def _command_env(
        self,
        extra_env: Optional[Dict[str, str]] = None,
        unset_keys: Optional[List[str]] = None,
    ) -> Dict[str, str]:
        env = os.environ.copy()
        for key in unset_keys or []:
            env.pop(str(key), None)
        env.update(self._env_overrides)
        if extra_env:
            env.update({str(key): str(value) for key, value in extra_env.items()})
        return env

    def detect_backends(self) -> Dict[str, bool]:
        return collect_backend_availability_from_runner(self)

    def _is_high_headroom_discrete_target(self, target: Optional[Dict[str, Any]]) -> bool:
        capability = self._gpu_capability_profile(target)
        vendor = str((target or {}).get("vendor", "") or capability.get("vendor", "") or "").strip().lower()
        if vendor != "amd":
            return False
        return str(capability.get("device_class", "") or "") == "discrete" and (
            int(capability.get("compute_units", 0) or 0) >= 28
            or int(capability.get("max_clock_mhz", 0) or 0) >= 2400
        )

    def _opencl_compute_safety_profile(self) -> Dict[str, Any]:
        return opencl_compute_safety_profile(self._gpu_safe_mode_enabled())

    def backend_details(self) -> Dict[str, Any]:
        return collect_backend_details_from_runner(self, GPU_3D_BACKEND_CATALOG)

    def _ipmi_sensor_details(self) -> Dict[str, Any]:
        device_nodes = [str(path) for path in sorted(Path("/dev").glob("ipmi*")) if path.exists()]
        details: Dict[str, Any] = {
            "available": self._command_exists("ipmitool") or self._command_exists("ipmi-sensors"),
            "ipmitool": self._command_exists("ipmitool"),
            "freeipmi_ipmi_sensors": self._command_exists("ipmi-sensors"),
            "device_nodes": device_nodes,
            "device_node_available": bool(device_nodes or list(Path("/sys/class/ipmi").glob("ipmi*"))),
            "path": "ipmitool" if self._command_exists("ipmitool") else "ipmi-sensors" if self._command_exists("ipmi-sensors") else "",
            "reason": "",
            "telemetry_role": "optional fallback for board/BMC-exposed temperatures such as DIMM/DRAM sensors",
        }
        if not details["available"]:
            if details["device_node_available"]:
                details["reason"] = "IPMI device is present, but ipmitool/freeipmi tools are missing"
            else:
                details["reason"] = "IPMI tools and local IPMI device are not available"
        return details

    def _intel_gpu_top_details(self) -> Dict[str, Any]:
        return collect_intel_gpu_top_details(
            command_exists=self._command_exists,
            command_env=self._command_env,
        )

    def dry_run_plan(self, profile: ValidationProfile, labels: List[str]) -> List[Dict[str, Any]]:
        return build_dry_run_plan(self, profile, labels)

    def stage_diagnostics(self, stage: StageConfig, label: str) -> Dict[str, Any]:
        return build_stage_diagnostics(self, stage, label)

    def launch_stage_processes(
        self,
        stage: StageConfig,
        cpu_kernel_flavor: str = "",
        result_dir: Optional[Path] = None,
        cpu_backend_override: str = "",
    ) -> List[StageProcess]:
        if not stage.enabled:
            return []
        worker_results_dir = result_dir / "worker_results" if result_dir else None
        worker_logs_dir = result_dir / "worker_logs" if result_dir else None
        if worker_results_dir is not None:
            worker_results_dir.mkdir(parents=True, exist_ok=True)
        if worker_logs_dir is not None:
            worker_logs_dir.mkdir(parents=True, exist_ok=True)
        workers = self._gpu_worker_specs(stage)
        stage_memory_plan = self._stage_system_memory_plan(stage, workers)
        if not stage_memory_plan.get("valid", True):
            raise RuntimeError(
                "stage system-memory budget is not launchable: "
                + str(stage_memory_plan.get("resolution_reason") or "insufficient safe memory")
            )
        guard_base = worker_results_dir if worker_results_dir is not None else Path(tempfile.gettempdir())
        guard_path = guard_base / f"{stage.id}_runtime_memory_guard.json"
        stage_memory_plan["runtime_memory_guard_temporary"] = worker_results_dir is None
        initialize_runtime_memory_guard(stage_memory_plan, guard_path)
        resolved_workers = apply_stage_system_memory_plan(workers, stage_memory_plan)
        commands = build_stage_launch_commands(
            self,
            stage,
            cpu_kernel_flavor,
            worker_results_dir,
            cpu_backend_override=cpu_backend_override,
            stage_memory_plan=stage_memory_plan,
            resolved_gpu_workers=resolved_workers,
        )
        command_env = self._command_env({"LVS_RUNTIME_MEMORY_GUARD_PATH": str(guard_path)})
        return launch_stage_processes_from_plan(
            commands,
            stage_id=stage.id,
            worker_logs_dir=worker_logs_dir,
            command_env=command_env,
        )

    def launch_commands(self, stage: StageConfig, cpu_kernel_flavor: str = "") -> List[subprocess.Popen]:
        return [entry.process for entry in self.launch_stage_processes(stage, cpu_kernel_flavor)]

    def stop_stage_processes(self, processes: List[StageProcess]) -> None:
        stop_stage_process_list(processes)
        plan = next(
            (entry.system_memory_plan for entry in processes if getattr(entry, "system_memory_plan", None)),
            None,
        )
        if plan and plan.get("runtime_memory_guard_temporary"):
            guard_path = str((plan.get("runtime_memory_guard") or {}).get("control_path") or "")
            if guard_path:
                Path(guard_path).unlink(missing_ok=True)
                Path(guard_path + ".lock").unlink(missing_ok=True)

    def stop_processes(self, processes: List[subprocess.Popen]) -> None:
        stop_process_list(processes)

    def _enabled_workloads(self, stage: StageConfig) -> List[str]:
        workloads: List[str] = []
        if stage.modules.cpu.enabled:
            workloads.append("cpu")
        if stage.modules.memory.enabled:
            workloads.append("memory")
        if stage.modules.gpu_3d.enabled:
            workloads.append("gpu_3d")
        if stage.modules.vram.enabled:
            workloads.append("vram")
        if stage.modules.storage_benchmark.enabled:
            workloads.append("storage_benchmark")
        return workloads

    def _missing_tools(self, commands: List[List[str]]) -> List[str]:
        missing: List[str] = []
        for cmd in commands:
            if cmd and not self._command_exists(cmd[0]) and cmd[0] not in missing:
                missing.append(cmd[0])
        return missing

    def _build_commands(
        self,
        stage: StageConfig,
        cpu_kernel_flavor: str = "",
        cpu_backend_override: str = "",
        stage_memory_plan: Optional[Dict[str, Any]] = None,
        resolved_gpu_workers: Optional[List[Any]] = None,
    ) -> List[List[str]]:
        return [
            entry.command
            for entry in build_stage_launch_commands(
                self,
                stage,
                cpu_kernel_flavor,
                cpu_backend_override=cpu_backend_override,
                stage_memory_plan=stage_memory_plan,
                resolved_gpu_workers=resolved_gpu_workers,
            )
        ]

    def _stage_system_memory_plan(
        self,
        stage: StageConfig,
        gpu_workers: Optional[List[Any]] = None,
    ) -> Dict[str, Any]:
        workers = list(gpu_workers) if gpu_workers is not None else self._gpu_worker_specs(stage)
        snapshot = self._linux_memory_snapshot()
        return build_stage_system_memory_plan(
            stage=stage,
            gpu_workers=workers,
            total_bytes=int(snapshot.get("mem_total_bytes") or 0),
            available_bytes=int(snapshot.get("mem_available_bytes") or 0),
            memory_snapshot=snapshot,
        )

    def _resolved_stage_gpu_workers(self, stage: StageConfig) -> tuple[Dict[str, Any], List[Any]]:
        workers = self._gpu_worker_specs(stage)
        plan = self._stage_system_memory_plan(stage, workers)
        return plan, apply_stage_system_memory_plan(workers, plan)
