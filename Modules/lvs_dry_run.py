#!/usr/bin/env python3
"""Dry-run/preflight report assembly."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from .lvs_gpu_telemetry_warnings import gpu_telemetry_coverage_warnings
from .lvs_stage_diagnostics import build_stage_diagnostics_payload
from .lvs_telemetry_collector import TelemetryCollector


def build_stage_diagnostics(runner: Any, stage: Any, label: str) -> Dict[str, Any]:
    return build_stage_diagnostics_payload(runner, stage, label)


def build_dry_run_plan(runner: Any, profile: Any, labels: List[str]) -> List[Dict[str, Any]]:
    plan: List[Dict[str, Any]] = []
    for index, stage in enumerate(profile.stages):
        label = labels[index] if index < len(labels) else stage.name
        plan.append(build_stage_diagnostics(runner, stage, label))
    return plan


def build_dry_run_report(
    orchestrator: Any,
    profile_path: Path,
    profile: Any,
    labels: List[str],
) -> Dict[str, Any]:
    validation = orchestrator.validator.validate(profile, labels)
    telemetry = TelemetryCollector(
        interval_seconds=profile.defaults.telemetry_interval_seconds,
        runtime_environment=orchestrator.settings.runtime_environment,
        privileged_helper_enabled=orchestrator.settings.privileged_helper_enabled,
    )
    telemetry_capabilities = telemetry.detect_capabilities()
    plan = build_dry_run_plan(orchestrator.workload_runner, profile, labels)
    profile_errors = list(validation["errors"])
    stage_errors: List[str] = []
    errors = list(profile_errors)
    warnings = list(validation["warnings"])
    enabled_workloads = {
        workload
        for stage in plan
        if stage["enabled"]
        for workload in stage["workloads"]
    }

    for stage in plan:
        if not stage["enabled"]:
            continue
        for issue in stage["issues"]:
            message = f"{stage['label']}: {issue}"
            stage_errors.append(message)
            errors.append(message)
        for warning in stage.get("warnings", []):
            warnings.append(f"{stage['label']}: {warning}")

    enabled_stage_count = sum(1 for stage in plan if stage["enabled"])
    runnable_stage_count = sum(1 for stage in plan if stage["enabled"] and stage.get("runnable"))
    if enabled_stage_count > 0 and runnable_stage_count <= 0:
        no_runnable_message = "no enabled stages are runnable in the current environment"
        profile_errors.append(no_runnable_message)
        errors.append(no_runnable_message)

    if "cpu" in enabled_workloads and not telemetry_capabilities["cpu_temp_c"]["available"]:
        warnings.append("CPU temperature telemetry unavailable; thermal metrics will be blank")
    if {"cpu", "memory"} & enabled_workloads and not telemetry_capabilities["cpu_power_w"]["available"]:
        warnings.append("CPU power telemetry unavailable; CPU package power metrics will be blank")
    if "memory" in enabled_workloads and not telemetry_capabilities["memory_used_gb"]["available"]:
        warnings.append("Memory usage telemetry unavailable; memory usage metrics will be blank")
    if {"gpu_3d", "vram"} & enabled_workloads and not telemetry_capabilities["gpu_temp_c"]["available"]:
        warnings.append("GPU temperature telemetry unavailable; GPU thermal metrics will be blank")
    if {"gpu_3d", "vram"} & enabled_workloads and not telemetry_capabilities["gpu_power_w"]["available"]:
        warnings.append("GPU power telemetry unavailable; GPU power metrics will be blank")
    if "vram" in enabled_workloads and not telemetry_capabilities["gpu_vram_used_gb"]["available"]:
        warnings.append("GPU VRAM usage telemetry unavailable; VRAM usage metrics will be blank")
    warnings.extend(gpu_telemetry_coverage_warnings(telemetry_capabilities, enabled_workloads))
    if any(stage.get("backend_usage", {}).get("cpu") == "python_fallback" for stage in plan if stage["enabled"]):
        helper_reason = orchestrator.workload_runner.backend_details().get("cpu_native_helper", {}).get("reason", "")
        if helper_reason:
            warnings.append(f"Native CPU helper unavailable: {helper_reason}")
        warnings.append("Preferred CPU backend not available; install gcc/build-essential to build the native CPU helper or install stress-ng")
    if any(stage.get("backend_usage", {}).get("memory") == "python_fallback" for stage in plan if stage["enabled"]):
        helper_reason = orchestrator.workload_runner.backend_details().get("memory_native_helper", {}).get("reason", "")
        if helper_reason:
            warnings.append(f"Native memory helper unavailable: {helper_reason}")
        warnings.append("Preferred memory backend not available; install gcc/build-essential to build the native memory helper or install stress-ng")
    if any(
        stage.get("backend_usage", {}).get("gpu_3d") == "python_opencl_compute"
        or stage.get("backend_usage", {}).get("vram") == "python_opencl"
        for stage in plan
        if stage["enabled"]
    ):
        warnings.append("GPU stages are using the suite-native OpenCL compute/verification backend with explicit device selection and readback verification")
    if any(
        stage.get("backend_usage", {}).get("gpu_3d") == "python_egl_gles2"
        or stage.get("backend_usage", {}).get("vram") == "python_egl_gles2"
        for stage in plan
        if stage["enabled"]
    ):
        warnings.append("GPU stages are using the suite-native EGL/GLES render/readback backend; external OpenGL/Vulkan tools remain benchmark/compatibility paths, not preferred stress engines")
    if any(
        stage.get("backend_usage", {}).get("gpu_3d") == "python_vulkan_transfer"
        for stage in plan
        if stage["enabled"]
    ):
        warnings.append("GPU stages are using the suite-native Vulkan transfer/readback backend; this validates Vulkan command and memory paths but is not yet a shader saturation test")
    if any(
        stage.get("backend_usage", {}).get("gpu_3d") == "python_vulkan_compute"
        for stage in plan
        if stage["enabled"]
    ):
        warnings.append("GPU stages are using the suite-native Vulkan compute/readback backend; this is the preferred curated stress family when available")
    if orchestrator.settings.gpu_safe_mode:
        warnings.append(
            "GPU safe mode is enabled: "
            + f"internal backends ramp from {orchestrator.settings.gpu_safe_start_load_fraction * 100:.0f}% load over ~{orchestrator.settings.gpu_internal_ramp_step_seconds * 3:.0f}s, "
            + f"external curated backends are capped at {orchestrator.settings.gpu_external_max_processes} process(es), "
            + f"retuning targets {orchestrator.settings.gpu_retune_warmup_seconds}s warmup with a {orchestrator.settings.gpu_retune_cooldown_seconds}s cooldown, "
            + "but short stages shorten that schedule to avoid restarting workers near the end, "
            + f"retunes are capped at step {orchestrator.settings.gpu_safe_max_tuning_step}, "
            + f"and VRAM targets are capped at {orchestrator.settings.gpu_safe_max_vram_percent:.0f}% of detected VRAM"
        )
    recovery_report = orchestrator._build_gpu_recovery_report()
    safety_marker = recovery_report.get("marker")
    if safety_marker:
        stage_name = str(safety_marker.get("stage_name") or "unknown stage")
        profile_name = str(safety_marker.get("profile_name") or "unknown profile")
        warnings.append(
            f"Previous internal GPU stress run may not have exited cleanly: profile '{profile_name}', stage '{stage_name}'. Review system logs before re-running aggressive GPU tests"
        )
        previous_fault_summary = recovery_report.get("previous_boot_fault_summary", {})
        previous_fault_categories = previous_fault_summary.get("categories", {})
        if previous_fault_summary.get("count"):
            category_summary = ", ".join(
                f"{category}={count}"
                for category, count in sorted(previous_fault_categories.items())
            )
            warnings.append(
                f"Previous-boot kernel faults matched the recovery marker: {category_summary}"
            )
        else:
            warnings.append(
                "No matching previous-boot kernel faults were found for the unclean GPU run marker"
            )
    if orchestrator.settings.target_gpu_busy_min_percent > 0 and orchestrator.settings.target_gpu_busy_sustain_seconds > 0:
        warnings.append(
            f"Target 3D GPU load validation enabled: busy >= {orchestrator.settings.target_gpu_busy_min_percent}% for {orchestrator.settings.target_gpu_busy_sustain_seconds}s"
        )
    if orchestrator.settings.target_gpu_memory_busy_min_percent > 0 and orchestrator.settings.target_gpu_memory_busy_sustain_seconds > 0:
        warnings.append(
            f"Target VRAM GPU load validation enabled: memory busy >= {orchestrator.settings.target_gpu_memory_busy_min_percent}% for {orchestrator.settings.target_gpu_memory_busy_sustain_seconds}s"
        )
    strict_threshold_enabled = any(
        stage_plan["enabled"]
        and orchestrator._stage_strict_threshold_recommendation_warnings(profile, profile.stages[index])
        for index, stage_plan in enumerate(plan)
        if index < len(profile.stages)
    )
    strict_threshold_scope = orchestrator._strict_threshold_warning_scope(profile)
    if strict_threshold_enabled:
        warnings.append(
            "Strict threshold recommendation warnings enabled "
            + f"({strict_threshold_scope} scope): report-only threshold misses will be exported as warning interpretations, not runtime failures"
        )

    return {
        "profile_name": profile.profile_name,
        "profile_file": profile_path.name,
        "menu_description": profile.menu_description,
        "menu_group": profile.menu_group,
        "runnable": not profile_errors,
        "strict_threshold_recommendation_warnings": {
            "enabled_for_any_stage": strict_threshold_enabled,
            "scope": strict_threshold_scope,
        },
        "validation": {
            "errors": errors,
            "warnings": warnings,
            "profile_errors": profile_errors,
            "stage_errors": stage_errors,
        },
        "runtime_environment": orchestrator.workload_runner.runtime_environment(),
        "telemetry_capabilities": telemetry_capabilities,
        "backends": orchestrator.workload_runner.detect_backends(),
        "backend_details": orchestrator.workload_runner.backend_details(),
        "gpu_recovery": recovery_report,
        "plan": plan,
        "enabled_stage_count": enabled_stage_count,
        "runnable_stage_count": runnable_stage_count,
    }
