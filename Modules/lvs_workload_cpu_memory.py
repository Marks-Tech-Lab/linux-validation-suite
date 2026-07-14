#!/usr/bin/env python3
"""Workload-runner CPU and memory execution adapter methods."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from Modules.lvs_cpu_execution import (
    benchmark_cpu_kernel_candidate,
    build_cpu_command,
    build_cpu_fallback_script,
    cpu_candidate_kernel_flavors,
    cpu_fallback_params,
    cpu_mode_for_kernel_flavor,
    cpu_power_tuning_available,
    cpu_tuning_policy,
    normalize_cpu_helper_mode,
    resolve_cpu_execution_policy,
)
from Modules.lvs_memory_execution import (
    build_memory_command,
    build_memory_fallback_script,
    memory_target_bytes,
    memory_worker_count,
)
from Modules.lvs_native_helpers import find_c_compiler
from Modules.lvs_telemetry_collector import TelemetryCollector

DEFAULT_NATIVE_DIR = Path("native")
DEFAULT_BUILD_DIR = Path("build")
DEFAULT_CPU_TUNER_SAMPLE_INTERVAL_SECONDS = 0.5
DEFAULT_CPU_TUNER_WARMUP_SECONDS = 1.0
DEFAULT_CPU_TUNER_MEASURE_SECONDS = 3.0


class WorkloadCpuMemoryMixin:
    """CPU/memory command, helper, and execution-resolution adapter surface."""

    def _telemetry_collector_factory(self) -> Any:
        try:
            import linux_validation_suite as lvs

            return getattr(lvs, "TelemetryCollector", TelemetryCollector)
        except Exception:
            return TelemetryCollector

    def _command_exists(self, name: str) -> bool:
        from shutil import which
        if Path(name).exists():
            return os.access(name, os.X_OK)
        return which(name) is not None

    def _compiler_path(self) -> Optional[str]:
        return find_c_compiler()

    def _cpu_helper_source_path(self) -> Path:
        return DEFAULT_NATIVE_DIR / "cpu_stress_helper.c"

    def _cpu_helper_binary_path(self) -> Path:
        return DEFAULT_BUILD_DIR / "cpu_stress_helper"

    def _memory_helper_source_path(self) -> Path:
        return DEFAULT_NATIVE_DIR / "memory_stress_helper.c"

    def _memory_helper_binary_path(self) -> Path:
        return DEFAULT_BUILD_DIR / "memory_stress_helper"

    def _cpu_helper_status(self) -> Dict[str, Any]:
        return self._native_helper_runtime.helper_status(
            cache_key="cpu",
            source=self._cpu_helper_source_path(),
            binary=self._cpu_helper_binary_path(),
            compiler_path=self._compiler_path,
            reason_label="CPU",
        )

    def _memory_helper_status(self) -> Dict[str, Any]:
        return self._native_helper_runtime.helper_status(
            cache_key="memory",
            source=self._memory_helper_source_path(),
            binary=self._memory_helper_binary_path(),
            compiler_path=self._compiler_path,
            reason_label="memory",
        )

    def _python_runtime(self) -> Optional[str]:
        if sys.executable and Path(sys.executable).exists():
            return sys.executable
        return None

    def _cpu_command(
        self,
        cpu: Any,
        cpu_kernel_flavor: str = "",
        result_file: str = "",
    ) -> Optional[List[str]]:
        worker_count = self._cpu_worker_count(cpu)
        helper = self._cpu_helper_status()
        return build_cpu_command(
            worker_count=worker_count,
            helper_available=bool(helper.get("available")),
            helper_path=str(helper.get("path") or ""),
            requested_mode=self._cpu_helper_mode(cpu),
            instruction_set=cpu.instruction_set,
            mode=cpu.mode,
            stress_ng_available=self._command_exists("stress-ng"),
            python_runtime=self._python_runtime() or "",
            cpu_kernel_flavor=cpu_kernel_flavor,
            result_file=result_file,
        )

    def _cpu_backend_name(self, cpu: Any) -> str:
        if self._cpu_helper_status()["available"]:
            return "cpu_native_helper"
        if self._command_exists("stress-ng"):
            return "stress_ng"
        if self._python_runtime():
            return "python_fallback"
        return "none"

    def _cpu_helper_mode(self, cpu: Any) -> str:
        return normalize_cpu_helper_mode(cpu.instruction_set)

    def _cpu_helper_resolved_mode(self, requested_mode: str) -> str:
        return self._native_helper_runtime.cpu_resolved_mode(
            requested_mode,
            helper_status=self._cpu_helper_status,
        )

    def _cpu_helper_default_kernel_flavor(self, requested_mode: str) -> str:
        return self._native_helper_runtime.cpu_default_kernel_flavor(
            requested_mode,
            helper_status=self._cpu_helper_status,
        )

    def _cpu_helper_supports_kernel_flavor(self, flavor: str) -> bool:
        return self._native_helper_runtime.cpu_supports_kernel_flavor(
            flavor,
            helper_status=self._cpu_helper_status,
        )

    def _cpu_supported_kernel_flavors(self) -> List[str]:
        if not self._cpu_helper_status()["available"]:
            return []
        return cpu_candidate_kernel_flavors(
            helper_available=True,
            policy="max_power",
            resolved_mode="",
            supports_kernel_flavor=self._cpu_helper_supports_kernel_flavor,
        )

    def _cpu_mode_for_kernel_flavor(self, flavor: str) -> str:
        return cpu_mode_for_kernel_flavor(flavor)

    def _cpu_power_tuning_available(self) -> bool:
        if self._cpu_power_tuning_available_cache is not None:
            return self._cpu_power_tuning_available_cache
        self._cpu_power_tuning_available_cache = cpu_power_tuning_available(
            telemetry_collector_factory=self._telemetry_collector_factory(),
            interval_seconds=DEFAULT_CPU_TUNER_SAMPLE_INTERVAL_SECONDS,
            runtime_environment=self._env_overrides,
            privileged_helper_enabled=bool(self._settings and self._settings.privileged_helper_enabled),
        )
        return self._cpu_power_tuning_available_cache

    def _cpu_tuning_policy(self, cpu: Any) -> str:
        return cpu_tuning_policy(
            requested_mode=self._cpu_helper_mode(cpu),
            cpu_power_available=self._cpu_power_tuning_available(),
        )

    def _cpu_candidate_kernel_flavors(self, cpu: Any) -> List[str]:
        return cpu_candidate_kernel_flavors(
            helper_available=bool(self._cpu_helper_status()["available"]),
            policy=self._cpu_tuning_policy(cpu),
            resolved_mode=self._cpu_resolved_mode(cpu) or "scalar",
            supports_kernel_flavor=self._cpu_helper_supports_kernel_flavor,
        )

    def resolve_cpu_execution(self, cpu: Any, tune_max_power: bool = False) -> Dict[str, Any]:
        backend = self._cpu_backend_name(cpu)
        requested_mode = self._cpu_helper_mode(cpu)
        resolved_mode = self._cpu_resolved_mode(cpu)
        tuning_policy = self._cpu_tuning_policy(cpu)
        kernel_flavor = self._cpu_helper_default_kernel_flavor(requested_mode) if backend == "cpu_native_helper" else ""
        candidates = self._cpu_candidate_kernel_flavors(cpu) if backend == "cpu_native_helper" else []
        return resolve_cpu_execution_policy(
            backend=backend,
            requested_mode=requested_mode,
            resolved_mode=resolved_mode,
            kernel_flavor=kernel_flavor,
            tuning_policy=tuning_policy,
            candidate_kernel_flavors=candidates,
            tune_max_power=tune_max_power,
            worker_count=lambda: self._cpu_worker_count(cpu),
            power_tuning_available=self._cpu_power_tuning_available,
            benchmark_candidate=lambda flavor: self._benchmark_cpu_kernel(cpu, flavor),
            tuning_cache=self._cpu_tuning_cache,
        )

    def _benchmark_cpu_kernel(self, cpu: Any, kernel_flavor: str) -> Dict[str, Any]:
        return benchmark_cpu_kernel_candidate(
            kernel_flavor=kernel_flavor,
            build_command=lambda flavor, result_path: self._cpu_command(cpu, flavor, result_path),
            command_env=self._command_env(),
            telemetry_collector_factory=self._telemetry_collector_factory(),
            popen_factory=subprocess.Popen,
            stop_processes=self.stop_processes,
            temp_file_factory=tempfile.NamedTemporaryFile,
            interval_seconds=DEFAULT_CPU_TUNER_SAMPLE_INTERVAL_SECONDS,
            warmup_seconds=DEFAULT_CPU_TUNER_WARMUP_SECONDS,
            measure_seconds=DEFAULT_CPU_TUNER_MEASURE_SECONDS,
            runtime_environment=self._env_overrides,
            privileged_helper_enabled=bool(self._settings and self._settings.privileged_helper_enabled),
            stdout_target=subprocess.DEVNULL,
            stderr_target=subprocess.DEVNULL,
        )

    def _cpu_resolved_mode(self, cpu: Any) -> str:
        backend = self._cpu_backend_name(cpu)
        requested = self._cpu_helper_mode(cpu)
        if backend == "cpu_native_helper":
            return self._cpu_helper_resolved_mode(requested) or requested
        if backend == "stress_ng":
            return "approximate"
        if backend == "python_fallback":
            return "approximate"
        return ""

    def _memory_command(self, mem: Any, result_file: str = "") -> Optional[List[str]]:
        helper = self._memory_helper_status()
        return build_memory_command(
            helper_available=bool(helper.get("available")),
            helper_path=str(helper.get("path") or ""),
            target_bytes=self._memory_target_bytes(mem.allocation_percent),
            worker_count=self._memory_worker_count(mem),
            allocation_percent=mem.allocation_percent,
            stress_ng_available=self._command_exists("stress-ng"),
            python_runtime=self._python_runtime() or "",
            result_file=result_file,
        )

    def _memory_backend_name(self, mem: Any) -> str:
        if self._memory_helper_status()["available"]:
            return "memory_native_helper"
        if self._command_exists("stress-ng"):
            return "stress_ng"
        if self._python_runtime():
            return "python_fallback"
        return "none"

    def _memory_worker_count(self, mem: Any) -> int:
        return memory_worker_count(mem.threads, os.cpu_count() or 1)

    def _read_meminfo_kb(self, key: str) -> int:
        try:
            for line in Path("/proc/meminfo").read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.startswith(key + ":"):
                    return int(line.split(":", 1)[1].strip().split()[0])
        except Exception:
            return 0
        return 0

    def _memory_target_bytes(self, allocation_percent: int) -> int:
        total_kb = self._read_meminfo_kb("MemTotal")
        available_kb = self._read_meminfo_kb("MemAvailable")
        return memory_target_bytes(allocation_percent, total_kb, available_kb)

    def _cpu_worker_count(self, cpu: Any) -> int:
        total = max(1, os.cpu_count() or 1)
        threads = (cpu.threads or "all").strip().lower()
        if not threads or threads == "all":
            return total
        try:
            requested = int(threads)
        except Exception:
            return total
        return max(1, min(requested, total))

    def _cpu_fallback_params(self, cpu: Any) -> Dict[str, Any]:
        return cpu_fallback_params(cpu.instruction_set, cpu.mode)

    def _cpu_fallback_script(self, cpu: Any, worker_count: int) -> str:
        return build_cpu_fallback_script(cpu.instruction_set, cpu.mode, worker_count)

    def _memory_fallback_script(self, allocation_percent: int) -> str:
        return build_memory_fallback_script(allocation_percent)

    def _system_memory_total_bytes(self) -> int:
        total_kb = self._read_meminfo_kb("MemTotal")
        return max(0, int(total_kb) * 1024)

    def _system_memory_available_bytes(self) -> int:
        available_kb = self._read_meminfo_kb("MemAvailable")
        return max(0, int(available_kb) * 1024)
