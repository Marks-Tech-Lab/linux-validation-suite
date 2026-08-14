#!/usr/bin/env python3
"""Workload-runner CPU and memory execution adapter methods."""

from __future__ import annotations

import copy
import json
import math
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from Modules.lvs_cpu_architecture import (
    cpu_native_power_probe_kernel_order,
    cpu_instruction_set_policy,
    current_cpu_architecture,
    native_cpu_helper_binary_name,
    normalize_cpu_instruction_intent,
    python_cpu_fallback_policy,
    resolve_cpu_instruction_intent,
)
from Modules.lvs_cpu_backend_policy import (
    CPU_BACKEND_IDENTITIES,
    normalize_cpu_backend_preference,
    select_cpu_backend,
)
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
from Modules.lvs_cpu_power_selection import (
    power_cpu_candidate_inventory,
    select_power_cpu_candidate,
)
from Modules.lvs_cpu_targeting import (
    common_kernel_capabilities,
    discover_linux_cpu_sets,
    mode_for_common_kernel,
    resolve_target_cpu_ids,
    select_common_kernel,
)
from Modules.lvs_memory_execution import (
    build_memory_command,
    build_memory_fallback_script,
    memory_target_bytes,
    memory_worker_count,
    normalize_memory_backend_preference,
    select_memory_backend,
)
from Modules.lvs_memory_architecture import native_memory_helper_binary_name
from Modules.lvs_external_process_evidence import build_stress_ng_cpu_evidence
from Modules.lvs_linux_memory import read_linux_memory_snapshot
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
        return DEFAULT_BUILD_DIR / native_cpu_helper_binary_name(self._cpu_machine())

    def _memory_helper_source_path(self) -> Path:
        return DEFAULT_NATIVE_DIR / "memory_stress_helper.c"

    def _memory_helper_binary_path(self) -> Path:
        return DEFAULT_BUILD_DIR / native_memory_helper_binary_name(self._cpu_machine())

    def _cpu_helper_status(self) -> Dict[str, Any]:
        return self._native_helper_runtime.helper_status(
            cache_key="cpu",
            source=self._cpu_helper_source_path(),
            binary=self._cpu_helper_binary_path(),
            compiler_path=self._compiler_path,
            reason_label="CPU",
            readiness_command=lambda path: [path, "--mode", "scalar", "--print-resolved-mode"],
        )

    def _memory_helper_status(self) -> Dict[str, Any]:
        return self._native_helper_runtime.helper_status(
            cache_key="memory",
            source=self._memory_helper_source_path(),
            binary=self._memory_helper_binary_path(),
            compiler_path=self._compiler_path,
            reason_label="memory",
            readiness_command=lambda path: [path, "--help"],
        )

    def _python_runtime(self) -> Optional[str]:
        if sys.executable and Path(sys.executable).exists():
            return sys.executable
        return None

    def _cpu_machine(self) -> str:
        return current_cpu_architecture()

    def _cpu_python_fallback_policy(self, cpu: Any) -> Dict[str, Any]:
        return python_cpu_fallback_policy(self._cpu_machine(), cpu.instruction_set)

    def _cpu_instruction_set_policy(self, cpu: Any) -> Dict[str, Any]:
        return cpu_instruction_set_policy(self._cpu_machine(), cpu.instruction_set)

    def _cpu_backend_preference(self, cpu: Any) -> str:
        return normalize_cpu_backend_preference(getattr(cpu, "backend_preference", "auto"))

    def _cpu_backend_availability(self, cpu: Any) -> Dict[str, bool]:
        instruction_policy = self._cpu_instruction_set_policy(cpu)
        if not instruction_policy.get("allowed"):
            return {
                "cpu_native_helper": False,
                "stress_ng": False,
                "python_fallback": False,
            }
        python_policy = self._cpu_python_fallback_policy(cpu)
        requested_mode = str(instruction_policy.get("requested_mode") or "auto")
        helper_available = bool(self._cpu_helper_status().get("available"))
        capability = self._cpu_capability_plan(cpu) if helper_available else {}
        helper_available = helper_available and bool(capability.get("selected_kernel_flavor"))
        instruction_intent = self._cpu_instruction_intent(cpu)
        if instruction_intent:
            return {
                "cpu_native_helper": helper_available,
                "stress_ng": False,
                "python_fallback": False,
            }
        generic_backend_request = requested_mode == "auto"
        return {
            "cpu_native_helper": helper_available,
            "stress_ng": generic_backend_request and self._command_exists("stress-ng"),
            "python_fallback": (
                generic_backend_request
                and bool(self._python_runtime())
                and bool(python_policy.get("allowed"))
            ),
        }

    def _cpu_unavailable_reason(self, cpu: Any) -> str:
        if self._cpu_backend_name(cpu) != "none":
            return ""
        instruction_policy = self._cpu_instruction_set_policy(cpu)
        if not instruction_policy.get("allowed"):
            return str(instruction_policy.get("reason") or "")
        instruction_intent = self._cpu_instruction_intent(cpu)
        if instruction_intent:
            helper = self._cpu_helper_status()
            if not helper.get("available"):
                helper_reason = str(helper.get("reason") or "native CPU helper is unavailable")
                return f"CPU instruction intent '{instruction_intent}' requires the native CPU helper: {helper_reason}"
            capability = self._cpu_capability_plan(cpu)
            evidence = dict(capability.get("instruction_intent_evidence") or {})
            return str(
                evidence.get("fail_closed_reason")
                or f"CPU instruction intent '{instruction_intent}' requires a common native vector implementation"
            )
        policy = self._cpu_python_fallback_policy(cpu)
        preference = self._cpu_backend_preference(cpu)
        requested_mode = str(instruction_policy.get("requested_mode") or "auto")
        if requested_mode != "auto" and preference in {"python_fallback", "stress_ng"}:
            return (
                f"Explicit CPU instruction set '{requested_mode}' requires the native CPU helper; "
                f"backend '{preference}' does not enforce that ISA"
            )
        if preference == "python_fallback" and not policy.get("allowed"):
            return str(policy.get("reason") or "")
        if preference != "auto":
            backend = CPU_BACKEND_IDENTITIES[preference]
            if preference == "native":
                requested_mode = str(instruction_policy.get("requested_mode") or "auto")
                helper = self._cpu_helper_status()
                if requested_mode == "neon" and helper.get("available"):
                    return (
                        "Requested CPU mode 'neon' is unavailable: the native helper did not "
                        "detect Linux AArch64 ASIMD/NEON capability"
                    )
                helper_reason = str(helper.get("reason") or "")
                if helper.get("available"):
                    capability = self._cpu_capability_plan(cpu)
                    if not capability.get("selected_kernel_flavor"):
                        return str(capability.get("unavailable_reason") or "requested CPU ISA is not valid across all target CPUs")
                return f"Requested CPU backend '{preference}' is unavailable" + (
                    f": {helper_reason}" if helper_reason else ""
                )
            return f"Requested CPU backend '{backend}' is unavailable"
        if requested_mode != "auto":
            return (
                f"Explicit CPU instruction set '{requested_mode}' requires the native CPU helper "
                "and must be valid across every selected CPU"
            )
        return str(policy.get("reason") or "") if not policy.get("allowed") else ""

    def _cpu_command(
        self,
        cpu: Any,
        cpu_kernel_flavor: str = "",
        result_file: str = "",
        backend_override: str = "",
    ) -> Optional[List[str]]:
        target_plan = self._cpu_target_plan(cpu)
        target_cpu_ids = list(target_plan.get("target_cpu_ids") or [])
        worker_count = len(target_cpu_ids)
        backend = str(backend_override or self._cpu_backend_name(cpu))
        if backend == "none":
            return None
        helper = self._cpu_helper_status()
        python_runtime = self._python_runtime() or ""
        if backend == "cpu_native_helper":
            capability = self._cpu_capability_plan(cpu, target_plan=target_plan)
            common = set(capability.get("common_kernel_flavors") or [])
            if cpu_kernel_flavor and cpu_kernel_flavor not in common:
                raise RuntimeError(
                    f"CPU target set changed before launch; kernel '{cpu_kernel_flavor}' is not safe "
                    f"across target CPUs {target_cpu_ids}"
                )
            cpu_kernel_flavor = cpu_kernel_flavor or str(capability.get("selected_kernel_flavor") or "")
            if not cpu_kernel_flavor:
                return None
        return build_cpu_command(
            worker_count=worker_count,
            helper_available=backend == "cpu_native_helper",
            helper_path=str(helper.get("path") or ""),
            requested_mode=self._cpu_helper_mode(cpu),
            instruction_set=cpu.instruction_set,
            mode=cpu.mode,
            stress_ng_available=backend == "stress_ng",
            python_runtime=python_runtime if backend == "python_fallback" else "",
            cpu_kernel_flavor=cpu_kernel_flavor,
            result_file=result_file,
            resolved_mode=self._cpu_resolved_mode(cpu),
            target_cpu_ids=target_cpu_ids,
        )

    def _cpu_backend_name(self, cpu: Any) -> str:
        return select_cpu_backend(self._cpu_backend_preference(cpu), self._cpu_backend_availability(cpu))

    def _cpu_helper_mode(self, cpu: Any) -> str:
        return normalize_cpu_helper_mode(cpu.instruction_set)

    def _cpu_instruction_intent(self, cpu: Any) -> str:
        return normalize_cpu_instruction_intent(getattr(cpu, "instruction_intent", ""))

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

    def _cpu_helper_supports_kernel_flavor(self, flavor: str, cpu_id: Optional[int] = None) -> bool:
        return self._native_helper_runtime.cpu_supports_kernel_flavor(
            flavor,
            helper_status=self._cpu_helper_status,
            cpu_id=cpu_id,
        )

    def _cpu_helper_supported_kernel_flavors(self, cpu_id: Optional[int] = None) -> List[str]:
        return self._native_helper_runtime.cpu_supported_kernel_flavors(
            helper_status=self._cpu_helper_status,
            cpu_id=cpu_id,
        )

    def _cpu_target_plan(self, cpu: Any) -> Dict[str, Any]:
        return resolve_target_cpu_ids(discover_linux_cpu_sets(), getattr(cpu, "threads", "all"))

    def _cpu_capability_plan(
        self,
        cpu: Any,
        *,
        target_plan: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        target = dict(target_plan or self._cpu_target_plan(cpu))
        target_ids = list(target.get("target_cpu_ids") or [])
        architecture = self._cpu_machine()
        flavors = list(cpu_native_power_probe_kernel_order(architecture))
        per_cpu: Dict[int, List[str]] = {}
        if architecture == "arm64":
            # Linux AArch64 HWCAP is the process-safe common capability set;
            # it is intentionally not inferred from per-core model names.
            supported_global = set(self._cpu_helper_supported_kernel_flavors())
            common_global = [flavor for flavor in flavors if flavor in supported_global]
            if common_global:
                per_cpu = {cpu_id: list(common_global) for cpu_id in target_ids}
            capability_scope = "linux_aarch64_hwcap_common_set"
        else:
            for cpu_id in target_ids:
                supported = set(self._cpu_helper_supported_kernel_flavors(cpu_id))
                if supported:
                    per_cpu[cpu_id] = [flavor for flavor in flavors if flavor in supported]
            capability_scope = "per_cpu_affinity_pinned_cpuid"
        intersection = common_kernel_capabilities(target_ids, per_cpu)
        requested = self._cpu_helper_mode(cpu)
        instruction_intent = self._cpu_instruction_intent(cpu)
        intent_evidence: Dict[str, Any] = {}
        if instruction_intent:
            intent_evidence = resolve_cpu_instruction_intent(
                architecture,
                instruction_intent,
                intersection["common_kernel_flavors"],
            )
            selected = str(intent_evidence.get("resolved_kernel_flavor") or "")
            helper = self._cpu_helper_status()
            if not helper.get("available"):
                selected = ""
                intent_evidence["resolved_backend"] = "none"
                intent_evidence["resolved_isa"] = ""
                intent_evidence["resolved_kernel_flavor"] = ""
                intent_evidence["fail_closed_reason"] = (
                    f"CPU instruction intent '{instruction_intent}' requires the native CPU helper: "
                    + str(helper.get("reason") or "native CPU helper is unavailable")
                )
        else:
            selected = select_common_kernel(
                architecture=architecture,
                requested_mode=requested,
                common_flavors=intersection["common_kernel_flavors"],
            )
        reason = ""
        if not target_ids:
            reason = "no online CPUs are available within the process affinity/cpuset"
        elif not selected and instruction_intent:
            reason = str(intent_evidence.get("fail_closed_reason") or "")
        elif not selected:
            reason = (
                f"CPU instruction set '{requested}' is not supported across the complete target CPU set "
                f"{target_ids}"
            )
        return {
            **target,
            **intersection,
            "capability_scope": capability_scope,
            "common_safe_instruction_set": mode_for_common_kernel(selected),
            "selected_kernel_flavor": selected,
            "instruction_intent": instruction_intent,
            "instruction_intent_evidence": {
                **intent_evidence,
                "target_cpu_ids": target_ids,
                "actual_worker_count": len(target_ids),
                "capability_scope": capability_scope,
                "capability_intersection_complete": bool(intersection["capability_intersection_complete"]),
                "per_cpu_capabilities": dict(intersection["per_cpu_capabilities"]),
            }
            if instruction_intent
            else {},
            "capability_intersection_reason": (
                "intersection_of_all_target_cpu_capabilities"
                if intersection["capability_intersection_complete"]
                else "incomplete_per_cpu_capability_evidence"
            ),
            "unavailable_reason": reason,
        }

    def _cpu_supported_kernel_flavors(self) -> List[str]:
        if not self._cpu_helper_status()["available"]:
            return []
        cpu = type("CpuRequest", (), {"threads": "all", "instruction_set": "auto"})()
        return list(self._cpu_capability_plan(cpu).get("common_kernel_flavors") or [])

    def _cpu_core_type_probe(self) -> Dict[str, Any]:
        if current_cpu_architecture() != "x86_64":
            return {
                "evidence_source": "unsupported_architecture",
                "architecture": current_cpu_architecture(),
                "logical_cpus": [],
                "probe_failures": [],
                "complete": False,
                "hybrid_flag": False,
            }
        target_ids = sorted(int(cpu_id) for cpu_id in os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else list(range(os.cpu_count() or 1))
        return self._native_helper_runtime.cpu_core_type_probe(
            target_ids,
            helper_status=self._cpu_helper_status,
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

    def _cpu_power_capability(self) -> Dict[str, Any]:
        if self._cpu_power_capability_cache is not None:
            return dict(self._cpu_power_capability_cache)
        capabilities = self._telemetry_collector_factory()(
            interval_seconds=DEFAULT_CPU_TUNER_SAMPLE_INTERVAL_SECONDS,
            runtime_environment=self._env_overrides,
            privileged_helper_enabled=bool(self._settings and self._settings.privileged_helper_enabled),
        ).detect_capabilities()
        capability = dict(capabilities.get("cpu_power_w", {}) or {})
        self._cpu_power_capability_cache = capability
        self._cpu_power_tuning_available_cache = bool(capability.get("available"))
        return dict(capability)

    def _cpu_tuning_policy(self, cpu: Any) -> str:
        if bool(getattr(cpu, "power_auto", False)):
            return "power_auto"
        if self._cpu_instruction_intent(cpu):
            return "instruction_intent"
        return cpu_tuning_policy(
            requested_mode=self._cpu_helper_mode(cpu),
            cpu_power_available=self._cpu_power_tuning_available(),
        )

    def _cpu_candidate_kernel_flavors(self, cpu: Any) -> List[str]:
        capability = self._cpu_capability_plan(cpu)
        if self._cpu_instruction_intent(cpu):
            selected = str(capability.get("selected_kernel_flavor") or "")
            return [selected] if selected else []
        common = set(capability.get("common_kernel_flavors") or [])
        return cpu_candidate_kernel_flavors(
            helper_available=bool(self._cpu_helper_status()["available"]),
            policy=self._cpu_tuning_policy(cpu),
            resolved_mode=self._cpu_resolved_mode(cpu) or "scalar",
            supports_kernel_flavor=lambda flavor: flavor in common,
            architecture=self._cpu_machine(),
        )

    def resolve_cpu_execution(self, cpu: Any, tune_max_power: bool = False) -> Dict[str, Any]:
        if bool(getattr(cpu, "power_auto", False)) and self._cpu_helper_mode(cpu) == "auto":
            return self._resolve_power_cpu_execution(cpu, probe_candidates=tune_max_power)
        backend = self._cpu_backend_name(cpu)
        requested_mode = self._cpu_helper_mode(cpu)
        resolved_mode = self._cpu_resolved_mode(cpu)
        tuning_policy = self._cpu_tuning_policy(cpu)
        kernel_flavor = self._cpu_helper_default_kernel_flavor(requested_mode) if backend == "cpu_native_helper" else ""
        capability = (
            self._cpu_capability_plan(cpu)
            if backend == "cpu_native_helper" or self._cpu_instruction_intent(cpu)
            else self._cpu_target_plan(cpu)
        )
        if backend == "cpu_native_helper":
            kernel_flavor = str(capability.get("selected_kernel_flavor") or "")
        candidates = self._cpu_candidate_kernel_flavors(cpu) if backend == "cpu_native_helper" else []
        execution = resolve_cpu_execution_policy(
            backend=backend,
            requested_mode=requested_mode,
            resolved_mode=resolved_mode,
            kernel_flavor=kernel_flavor,
            tuning_policy=tuning_policy,
            candidate_kernel_flavors=candidates,
            tune_max_power=tune_max_power,
            worker_count=lambda: tuple(capability.get("target_cpu_ids") or []),
            power_tuning_available=self._cpu_power_tuning_available,
            benchmark_candidate=lambda flavor: self._benchmark_cpu_kernel(cpu, flavor),
            tuning_cache=self._cpu_tuning_cache,
        ) | {
            key: capability.get(key)
            for key in (
                "available_cpu_ids",
                "online_cpu_ids",
                "allowed_cpu_ids",
                "target_cpu_ids",
                "requested_thread_count",
                "actual_worker_count",
                "capability_scope",
                "common_safe_instruction_set",
                "per_cpu_capabilities",
                "capability_probe_failures",
                "capability_intersection_reason",
                "instruction_intent",
                "instruction_intent_evidence",
            )
        }
        if self._cpu_instruction_intent(cpu):
            execution["selection_evidence"] = dict(capability.get("instruction_intent_evidence") or {})
        return execution

    def _resolve_power_cpu_execution(self, cpu: Any, *, probe_candidates: bool) -> Dict[str, Any]:
        architecture = self._cpu_machine()
        target_plan = self._cpu_target_plan(cpu)
        availability = self._cpu_backend_availability(cpu)
        capability = self._cpu_capability_plan(cpu) if availability.get("cpu_native_helper") else dict(target_plan)
        native_flavors = list(capability.get("common_kernel_flavors") or [])
        selected_native = str(capability.get("selected_kernel_flavor") or "")
        viable, unavailable = power_cpu_candidate_inventory(
            architecture=architecture,
            availability=availability,
            native_kernel_flavors=native_flavors,
            selected_native_kernel=selected_native,
        )
        telemetry = self._cpu_power_capability()
        telemetry_evidence = {
            "available": bool(telemetry.get("available")),
            "source": str(telemetry.get("source") or telemetry.get("details") or ""),
            "permission_issue": bool(telemetry.get("permission_issue")),
        }
        cache_key = (
            "power_auto",
            architecture,
            tuple(target_plan.get("target_cpu_ids") or []),
            tuple(item.get("candidate_id") for item in viable),
            bool(telemetry_evidence["available"]),
        )
        cached = self._cpu_tuning_cache.get(cache_key) if probe_candidates else None
        if cached is not None:
            return dict(cached)
        started = time.monotonic()
        candidate_results = (
            [self._benchmark_power_cpu_candidate(cpu, candidate) for candidate in viable]
            if probe_candidates and telemetry_evidence["available"]
            else []
        )
        selection = select_power_cpu_candidate(
            architecture=architecture,
            viable_candidates=viable,
            unavailable_candidates=unavailable,
            telemetry=telemetry_evidence,
            candidate_results=candidate_results,
            probe_duration_seconds=time.monotonic() - started,
        )
        selection["target_cpu_ids"] = list(target_plan.get("target_cpu_ids") or [])
        selection["requested_thread_count"] = target_plan.get("requested_thread_count")
        selection["actual_worker_count"] = target_plan.get("actual_worker_count")
        if not probe_candidates and telemetry_evidence["available"]:
            selection["selection_mechanism"] = "power_probe_pending"
            selection["fallback_reason"] = ""
            selection["telemetry"]["trustworthy_usable"] = False
        selected = dict(selection.get("selected_candidate") or {})
        backend = str(selected.get("backend") or "none")
        kernel = str(selected.get("kernel_flavor") or "")
        resolved_mode = str(selected.get("resolved_mode") or "")
        if backend == "cpu_native_helper" and not resolved_mode:
            resolved_mode = self._cpu_mode_for_kernel_flavor(kernel)
        selection["selected_isa"] = (
            resolved_mode if backend == "cpu_native_helper" else "not_explicitly_enforced" if selected else ""
        )
        selection["selected_resolved_mode"] = resolved_mode
        execution = {
            "backend": backend,
            "requested_mode": "auto",
            "resolved_mode": resolved_mode,
            "kernel_flavor": kernel,
            "tuning_policy": "power_auto",
            "candidate_kernel_flavors": native_flavors,
            "tuned": selection.get("selection_mechanism") == "power_probe",
            "tuned_avg_power_w": next(
                (
                    item.get("avg_cpu_power_w")
                    for item in candidate_results
                    if item.get("candidate_id") == selected.get("candidate_id")
                ),
                None,
            ),
            "candidate_results": candidate_results,
            "selection_evidence": selection,
        } | {
            key: capability.get(key)
            for key in (
                "available_cpu_ids", "online_cpu_ids", "allowed_cpu_ids", "target_cpu_ids",
                "requested_thread_count", "actual_worker_count", "capability_scope",
                "common_safe_instruction_set", "per_cpu_capabilities", "capability_probe_failures",
                "capability_intersection_reason",
            )
        }
        if probe_candidates:
            self._cpu_tuning_cache[cache_key] = dict(execution)
        return execution

    def _benchmark_power_cpu_candidate(self, cpu: Any, candidate: Dict[str, Any]) -> Dict[str, Any]:
        backend = str(candidate.get("backend") or "")
        probe_cpu = copy.copy(cpu)
        probe_cpu.backend_preference = {
            "cpu_native_helper": "native",
            "stress_ng": "stress_ng",
            "python_fallback": "python_fallback",
        }.get(backend, "auto")
        result_path = ""
        stdout_path = ""
        stderr_path = ""
        process = None
        command: List[str] = []
        samples: List[float] = []
        started = time.monotonic()
        result_payload: Dict[str, Any] = {}
        output = ""
        try:
            with tempfile.NamedTemporaryFile(prefix="lvs_power_cpu_", suffix=".json", delete=False) as handle:
                result_path = handle.name
            with tempfile.NamedTemporaryFile(prefix="lvs_power_cpu_", suffix=".stdout", delete=False) as handle:
                stdout_path = handle.name
            with tempfile.NamedTemporaryFile(prefix="lvs_power_cpu_", suffix=".stderr", delete=False) as handle:
                stderr_path = handle.name
            command = self._cpu_command(
                probe_cpu,
                str(candidate.get("kernel_flavor") or ""),
                result_path,
            )
            if not command:
                raise RuntimeError("candidate command could not be materialized")
            telemetry = self._telemetry_collector_factory()(
                interval_seconds=DEFAULT_CPU_TUNER_SAMPLE_INTERVAL_SECONDS,
                runtime_environment=self._env_overrides,
                privileged_helper_enabled=bool(self._settings and self._settings.privileged_helper_enabled),
            )
            with open(stdout_path, "wb") as stdout_handle, open(stderr_path, "wb") as stderr_handle:
                process = subprocess.Popen(command, stdout=stdout_handle, stderr=stderr_handle, env=self._command_env())
                warmup_deadline = time.monotonic() + DEFAULT_CPU_TUNER_WARMUP_SECONDS
                measure_deadline = warmup_deadline + DEFAULT_CPU_TUNER_MEASURE_SECONDS
                while time.monotonic() < measure_deadline:
                    if process.poll() is not None:
                        break
                    telemetry.collect_once()
                    value = telemetry.samples[-1].values.get("cpu_power_w") if telemetry.samples else None
                    if time.monotonic() >= warmup_deadline and isinstance(value, (int, float)):
                        value = float(value)
                        if math.isfinite(value) and 0.0 < value <= 1000.0:
                            samples.append(value)
                    time.sleep(DEFAULT_CPU_TUNER_SAMPLE_INTERVAL_SECONDS)
        except Exception as exc:
            result_payload = {"status": "error", "error_count": 1, "last_error": str(exc)}
        finally:
            if process is not None:
                self.stop_processes([process])
            try:
                output = "\n".join(
                    Path(path).read_text(encoding="utf-8", errors="replace")
                    for path in (stdout_path, stderr_path)
                    if path and Path(path).exists()
                )
            except Exception:
                output = ""
            if backend == "stress_ng" and process is not None:
                result_payload = build_stress_ng_cpu_evidence(command, output)
            elif result_path and Path(result_path).exists():
                try:
                    loaded = json.loads(Path(result_path).read_text(encoding="utf-8"))
                    if isinstance(loaded, dict):
                        result_payload = loaded
                except Exception:
                    pass
            for path in (result_path, stdout_path, stderr_path):
                if path:
                    Path(path).unlink(missing_ok=True)
        error_count = int(result_payload.get("error_count") or result_payload.get("verification_error_count") or 0)
        status = str(result_payload.get("status") or "").lower()
        if backend == "stress_ng":
            meaningful = sum(
                float(row.get("bogo_ops") or 0)
                for row in list(result_payload.get("stressor_metrics") or [])
            ) > 0
        elif backend == "python_fallback":
            meaningful = int(result_payload.get("verification_passes") or 0) > 0 and sum(
                int(item.get("completed_pbkdf2_iterations") or 0)
                for item in list(result_payload.get("worker_progress") or [])
            ) > 0
        else:
            meaningful = int(result_payload.get("verify_passes") or 0) > 0
        target_cpu_ids = list(self._cpu_target_plan(cpu).get("target_cpu_ids") or [])
        worker_count = int(
            result_payload.get("actual_worker_count")
            or result_payload.get("requested_stressor_count")
            or 0
        )
        affinity_failed_count = int(result_payload.get("affinity_failed_count") or 0)
        worker_topology_valid = bool(target_cpu_ids) and worker_count == len(target_cpu_ids)
        verification_valid = (
            bool(result_payload)
            and status == "ok"
            and error_count == 0
            and affinity_failed_count == 0
            and worker_topology_valid
        )
        failure_reason = str(result_payload.get("last_error") or "")
        if not failure_reason and not worker_topology_valid:
            failure_reason = (
                f"probe worker count {worker_count} did not match target CPU count {len(target_cpu_ids)}"
            )
        elif not failure_reason and affinity_failed_count:
            failure_reason = f"{affinity_failed_count} probe worker affinity operation(s) failed"
        return {
            **dict(candidate),
            "command": command,
            "target_cpu_ids": target_cpu_ids,
            "avg_cpu_power_w": round(statistics.mean(samples), 2) if samples else None,
            "max_cpu_power_w": round(max(samples), 2) if samples else None,
            "power_sample_count": len(samples),
            "probe_elapsed_seconds": round(time.monotonic() - started, 3),
            "return_code": process.returncode if process is not None else None,
            "verification_valid": verification_valid,
            "meaningful_work": meaningful,
            "valid": verification_valid and meaningful and bool(samples),
            "verification_status": status,
            "verification_error_count": error_count,
            "verification_passes": int(
                result_payload.get("verification_passes")
                or result_payload.get("verify_passes")
                or result_payload.get("passed_stressor_count")
                or 0
            ),
            "worker_count": worker_count,
            "affinity_failed_count": affinity_failed_count,
            "failure_reason": failure_reason,
        }

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
            return str(self._cpu_capability_plan(cpu).get("common_safe_instruction_set") or "")
        if backend == "stress_ng":
            return "approximate"
        if backend == "python_fallback":
            return str(self._cpu_python_fallback_policy(cpu).get("resolved_mode") or "")
        return ""

    def _memory_command(
        self,
        mem: Any,
        result_file: str = "",
        resolved_target_bytes: Optional[int] = None,
    ) -> Optional[List[str]]:
        helper = self._memory_helper_status()
        target_bytes = (
            self._memory_target_bytes(mem.allocation_percent)
            if resolved_target_bytes is None
            else max(0, int(resolved_target_bytes))
        )
        if target_bytes <= 0:
            return None
        return build_memory_command(
            helper_available=bool(helper.get("available")),
            helper_path=str(helper.get("path") or ""),
            target_bytes=target_bytes,
            worker_count=self._memory_worker_count(mem),
            allocation_percent=mem.allocation_percent,
            stress_ng_available=self._command_exists("stress-ng"),
            python_runtime=self._python_runtime() or "",
            result_file=result_file,
            backend_preference=getattr(mem, "backend_preference", "auto"),
        )

    def _memory_backend_name(self, mem: Any) -> str:
        helper = self._memory_helper_status()
        selected = select_memory_backend(
            normalize_memory_backend_preference(getattr(mem, "backend_preference", "auto")),
            helper_available=bool(helper.get("available")),
            stress_ng_available=self._command_exists("stress-ng"),
            python_runtime=self._python_runtime() or "",
        )
        return "memory_native_helper" if selected == "native" else selected

    def _memory_worker_count(self, mem: Any) -> int:
        return memory_worker_count(mem.threads, os.cpu_count() or 1)

    def _memory_target_bytes(self, allocation_percent: int) -> int:
        snapshot = self._linux_memory_snapshot()
        return memory_target_bytes(
            allocation_percent,
            int(snapshot.get("mem_total_bytes") or 0) // 1024,
            int(snapshot.get("mem_available_bytes") or 0) // 1024,
        )

    def _cpu_worker_count(self, cpu: Any) -> int:
        return len(self._cpu_target_plan(cpu).get("target_cpu_ids") or [])

    def _cpu_fallback_params(self, cpu: Any) -> Dict[str, Any]:
        return cpu_fallback_params(cpu.instruction_set, cpu.mode)

    def _cpu_fallback_script(self, cpu: Any, worker_count: int) -> str:
        return build_cpu_fallback_script(
            cpu.instruction_set,
            cpu.mode,
            worker_count,
            list(self._cpu_target_plan(cpu).get("target_cpu_ids") or []),
        )

    def _memory_fallback_script(self, target_bytes: int, result_file: str = "") -> str:
        return build_memory_fallback_script(target_bytes, result_file)

    def _system_memory_total_bytes(self) -> int:
        return int(self._linux_memory_snapshot().get("mem_total_bytes") or 0)

    def _system_memory_available_bytes(self) -> int:
        return int(self._linux_memory_snapshot().get("mem_available_bytes") or 0)

    def _linux_memory_snapshot(self) -> Dict[str, Any]:
        return read_linux_memory_snapshot()
