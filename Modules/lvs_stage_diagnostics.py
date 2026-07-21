#!/usr/bin/env python3
"""Stage diagnostics payload assembly."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Dict, List

from .lvs_gpu_backend_catalog import OPENCL_COMPUTE_VARIANTS, VULKAN_COMPUTE_VARIANTS
from .lvs_gpu_backend_resolution import gpu_backend_resolution_messages, gpu_excluded_targets_summary
from .lvs_stage_gpu_diagnostics import (
    build_stage_gpu_backend_diagnostics,
    gpu_3d_backend_identity_warnings,
    gpu_3d_intensity_warning,
    gpu_3d_preference_fallback_warning,
    gpu_safe_mode_worker_warnings,
    mixed_stage_gpu_safety_warnings,
    opencl_high_headroom_safety_warning,
    per_target_backend_selection_warning,
    suite_native_gpu_3d_backend_warnings,
    vram_backend_warnings,
    vram_preference_fallback_warning,
)


def build_stage_diagnostics_payload(runner: Any, stage: Any, label: str) -> Dict[str, Any]:
    workloads = runner._enabled_workloads(stage)
    issues: List[str] = []
    warnings: List[str] = []
    storage = stage.modules.storage_benchmark
    if storage.enabled:
        try:
            test_size_gib = int(storage.test_size_gib)
            runs = int(storage.runs)
            estimated_writes_gib = test_size_gib * (1 + 4 * runs)
        except (TypeError, ValueError):
            test_size_gib, runs, estimated_writes_gib = 0, 0, 0
            issues.append("Storage benchmark size/runs must be integers within the supported bounds.")
        max_used_percent: float | None = None
        if storage.target_mode == "all_internal_non_root_low_occupancy":
            try:
                if isinstance(storage.max_used_percent, bool) or not isinstance(
                    storage.max_used_percent, (int, float)
                ):
                    raise ValueError
                parsed_max_used = float(storage.max_used_percent)
                if not math.isfinite(parsed_max_used) or not 0.0 <= parsed_max_used <= 100.0:
                    raise ValueError
                max_used_percent = parsed_max_used
            except (TypeError, ValueError):
                issues.append("Storage benchmark max_used_percent must be a finite number from 0.0 through 100.0.")
        target_preview: Dict[str, Any] = {}
        if storage.target_mode == "all_internal":
            warnings.append("All eligible internal drives will be benchmarked sequentially; no concurrent or staggered fio jobs are used.")
        elif storage.target_mode == "all_internal_non_root_low_occupancy":
            warnings.extend([
                "Dynamically selected internal non-root drives will be benchmarked sequentially and rechecked before execution.",
                "Occupancy is measured from the selected writable filesystem/workspace, not inferred from raw disk contents; unmounted filesystems on the same physical drive are not measured.",
                "Root/system drives are always excluded in this target mode.",
            ])
        if storage.allow_system_drive:
            warnings.append("This profile explicitly allows the root/system drive; the stage verdict will be at least WARN if it is used.")
        capability = {}
        try:
            from .lvs_fio_backend import storage_benchmark_capability
            capability = storage_benchmark_capability()
        except Exception as exc:
            warnings.append(f"Storage benchmark capability could not be checked: {exc}")
        if capability and not capability.get("benchmark_mode_available"):
            warnings.append("fio/libaio is unavailable; the completion stage will report WARN without affecting unrelated stages.")
        try:
            from .lvs_storage_benchmark_target import StorageTargetResolver
            resolver = StorageTargetResolver()
            root_confirmation = "BENCHMARK ROOT" if storage.allow_system_drive else None
            if storage.target_mode == "all_internal":
                preview = resolver.discover_all_eligible(
                    test_size_gib=test_size_gib,
                    root_confirmation=root_confirmation,
                )
                target_preview = {
                    "eligible_target_count": len(preview.targets),
                    "skipped_targets": [
                        {"device": item.device, "reason": item.reason}
                        for item in preview.skipped_targets
                    ],
                }
                if preview.skipped_targets:
                    warnings.append(
                        f"Storage target preview will skip {len(preview.skipped_targets)} drive(s); see diagnostics for reasons."
                    )
            elif storage.target_mode == "all_internal_non_root_low_occupancy":
                preview = resolver.discover_all_internal_non_root_low_occupancy(
                    test_size_gib=test_size_gib,
                    max_used_percent=max_used_percent if max_used_percent is not None else storage.max_used_percent,
                )
                target_preview = {
                    "eligible_target_count": len(preview.targets),
                    "max_used_percent": max_used_percent,
                    "occupancy_basis": "selected_writable_filesystem_workspace",
                    "included_targets": [
                        {
                            "device": item.physical_devices[0],
                            "workspace": str(item.target_path),
                            "filesystem": item.filesystem_type,
                            "used_percent": item.used_percent_at_selection,
                            "max_used_percent": max_used_percent,
                            "free_bytes": item.free_bytes_at_selection,
                            "warning": item.resolution_warning or None,
                            "warning": item.resolution_warning or None,
                        }
                        for item in preview.targets
                    ],
                    "skipped_targets": [
                        {
                            "device": item.device,
                            "reason": item.reason,
                            "workspace": str(item.target_path) if item.target_path else None,
                            "filesystem": item.filesystem_type or None,
                            "used_percent": item.used_percent_at_selection,
                            "max_used_percent": max_used_percent,
                            "free_bytes": item.free_bytes_at_selection,
                        }
                        for item in preview.skipped_targets
                    ],
                }
                if preview.skipped_targets:
                    warnings.append(
                        f"Storage target preview will skip {len(preview.skipped_targets)} drive(s); see diagnostics for reasons."
                    )
            elif storage.target_path:
                selected = resolver.resolve(
                    Path(storage.target_path),
                    test_size_gib=test_size_gib,
                    root_confirmation=root_confirmation,
                )
                target_preview = {
                    "eligible_target_count": 1,
                    "target_device": selected.mount_source,
                    "target_is_system_drive": selected.is_system_drive,
                }
        except Exception as exc:
            target_preview = {"eligible_target_count": 0, "preflight_warning": str(exc)}
            warnings.append(f"Storage target preview: {exc}")
        payload = {
            "stage_id": stage.id,
            "label": label,
            "type": stage.name,
            "enabled": stage.enabled,
            "execution_mode": "completion",
            "duration_seconds": None,
            "trim_start_seconds": 0,
            "trim_end_seconds": 0,
            "workloads": workloads,
            "backend_usage": {"storage_benchmark": "fio"},
            "storage_benchmark": {
                "profile_id": storage.profile_id,
                "target_mode": storage.target_mode,
                "target_path": storage.target_path or None,
                "drive_execution": storage.drive_execution,
                "test_size_gib": test_size_gib,
                "runs": runs,
                "allow_system_drive": storage.allow_system_drive,
                "estimated_max_writes_gib_per_drive": estimated_writes_gib,
                "target_preview": target_preview,
            },
            "issues": issues,
            "warnings": warnings,
            "runnable": bool(stage.enabled and not issues),
        }
        if storage.target_mode == "all_internal_non_root_low_occupancy":
            payload["storage_benchmark"]["max_used_percent"] = max_used_percent
        return payload
    gpu_backend_diagnostics = build_stage_gpu_backend_diagnostics(
        stage=stage,
        stage_gpu_target_mode=runner._stage_gpu_target_mode,
        gpu_targets=runner._gpu_targets,
        normalize_gpu_3d_backend_preference=runner._normalize_gpu_3d_backend_preference,
        normalize_vram_backend_preference=runner._normalize_vram_backend_preference,
        gpu_3d_backend_candidates=runner._gpu_3d_backend_candidates,
        vram_backend_candidates=runner._vram_backend_candidates,
        resolve_gpu_backend_for_targets=runner._resolve_gpu_backend_for_targets,
        cpu_backend_name=runner._cpu_backend_name,
        memory_backend_name=runner._memory_backend_name,
    )
    gpu_target_mode = gpu_backend_diagnostics["gpu_target_mode"]
    gpu_targets = gpu_backend_diagnostics["gpu_targets"]
    gpu_3d_preference = gpu_backend_diagnostics["gpu_3d_preference"]
    vram_preference = gpu_backend_diagnostics["vram_preference"]
    vram_targets = gpu_backend_diagnostics["vram_targets"]
    gpu_3d_candidates = gpu_backend_diagnostics["gpu_3d_candidates"]
    vram_candidates = gpu_backend_diagnostics["vram_candidates"]
    gpu_3d_resolution = gpu_backend_diagnostics["gpu_3d_resolution"]
    vram_resolution = gpu_backend_diagnostics["vram_resolution"]
    backend_usage = gpu_backend_diagnostics["backend_usage"]
    cmds = runner._build_commands(stage)
    gpu_workers = runner._gpu_worker_specs(stage)
    missing_tools = runner._missing_tools(cmds)
    cpu_mode_requested = runner._cpu_helper_mode(stage.modules.cpu) if stage.modules.cpu.enabled else ""
    cpu_mode_resolved = ""
    cpu_kernel_flavor = ""
    cpu_tuning_policy = ""
    cpu_kernel_candidates: List[str] = []
    if stage.modules.cpu.enabled and backend_usage["cpu"] == "cpu_native_helper":
        cpu_preview = runner.resolve_cpu_execution(stage.modules.cpu, tune_max_power=False)
        cpu_mode_resolved = cpu_preview["resolved_mode"]
        cpu_kernel_flavor = cpu_preview["kernel_flavor"]
        cpu_tuning_policy = cpu_preview["tuning_policy"]
        cpu_kernel_candidates = cpu_preview["candidate_kernel_flavors"]

    if stage.enabled and not workloads:
        issues.append("enabled stage has no enabled workloads")
    if stage.modules.cpu.enabled and runner._cpu_command(stage.modules.cpu) is None:
        issues.append("CPU workload selected but no backend is available")
    if stage.modules.memory.enabled and runner._memory_command(stage.modules.memory) is None:
        issues.append("Memory workload selected but no backend is available")
    if stage.modules.gpu_3d.enabled and runner._gpu_3d_command(stage.modules.gpu_3d, stage) is None:
        gpu_3d_messages = gpu_backend_resolution_messages(
            workload_label="3D",
            resolution=gpu_3d_resolution,
            preference=gpu_3d_preference,
        )
        targeted_issue = gpu_3d_messages.get("issue")
        if targeted_issue:
            issues.append(targeted_issue)
        pref = runner._normalize_gpu_3d_backend_preference(stage.modules.gpu_3d.backend_preference)
        if pref == "vulkan" and not targeted_issue:
            vulkan_details = runner._vulkan_transfer_backend()
            loader_state = "loader found" if vulkan_details.get("loader_available") else "loader not found"
            runtime_state = "runtime has GPU devices" if vulkan_details.get("runtime_gpu_device_count") else "runtime has no GPU devices"
            issues.append(
                "3D backend preference 'vulkan' requires the suite-native Vulkan transfer/readback worker, "
                + f"but it is not runnable in this environment ({loader_state}; {runtime_state}; {vulkan_details.get('reason') or 'unknown reason'})"
            )
        elif pref == "vulkan_compute" and not targeted_issue:
            vulkan_details = runner._vulkan_native_backend()
            loader_state = "loader found" if vulkan_details.get("loader_available") else "loader not found"
            runtime_state = "runtime has GPU devices" if vulkan_details.get("runtime_gpu_device_count") else "runtime has no GPU devices"
            issues.append(
                "3D backend preference 'vulkan_compute' requires the suite-native Vulkan compute/readback worker, "
                + f"but it is not runnable in this environment ({loader_state}; {runtime_state}; {vulkan_details.get('reason') or 'unknown reason'})"
            )
        elif not targeted_issue:
            candidates = (
                runner._gpu_3d_backend_candidates_by_preference(pref)
                if pref not in ("auto", "egl", "opencl")
                else []
            )
            external_only = candidates and all(
                candidate in {"glmark2", "vkmark", "vkcube", "glxgears"} for candidate in candidates
            )
            all_missing = external_only and all(not runner._gpu_3d_backend_available(candidate) for candidate in candidates)
            if all_missing:
                missing_tool = candidates[0]
                issues.append(f"3D backend preference '{pref}' requires {missing_tool} which is not installed")
            else:
                details = runner._egl_gpu_backend()
                reason = f" ({details['reason']})" if details.get("reason") else ""
                issues.append(f"3D workload selected but no Linux GPU backend is available{reason}")
    elif stage.modules.gpu_3d.enabled:
        gpu_3d_messages = gpu_backend_resolution_messages(
            workload_label="3D",
            resolution=gpu_3d_resolution,
            preference=gpu_3d_preference,
        )
        targeted_warning = gpu_3d_messages.get("warning")
        if targeted_warning:
            warnings.append(targeted_warning)
    if stage.modules.vram.enabled and runner._vram_command(stage.modules.vram) is None:
        vram_messages = gpu_backend_resolution_messages(
            workload_label="VRAM",
            resolution=vram_resolution,
            preference=vram_preference,
        )
        targeted_issue = vram_messages.get("issue")
        if targeted_issue:
            issues.append(targeted_issue)
        opencl_details = runner._opencl_gpu_backend()
        egl_details = runner._egl_gpu_backend()
        reason = opencl_details.get("reason") or egl_details.get("reason") or ""
        if not targeted_issue:
            issues.append(
                f"VRAM workload selected but no Linux GPU VRAM backend is available{f' ({reason})' if reason else ''}"
            )
    elif stage.modules.vram.enabled:
        vram_messages = gpu_backend_resolution_messages(
            workload_label="VRAM",
            resolution=vram_resolution,
            preference=vram_preference,
        )
        targeted_warning = vram_messages.get("warning")
        if targeted_warning:
            warnings.append(targeted_warning)
    if stage.enabled and workloads and not cmds:
        issues.append("enabled workloads produced no runnable commands")
    if missing_tools:
        issues.append(f"missing tools: {', '.join(missing_tools)}")
    if stage.modules.cpu.enabled and backend_usage["cpu"] == "cpu_native_helper":
        warnings.append(
            f"CPU stage is using the native helper backend ({cpu_mode_requested}, kernel {cpu_kernel_flavor or 'unknown'})"
        )
        if cpu_mode_requested != "auto" and cpu_mode_resolved and cpu_mode_resolved != cpu_mode_requested:
            warnings.append(
                f"CPU instruction request downgraded by hardware support: requested {cpu_mode_requested}, executing {cpu_mode_resolved}"
            )
        if cpu_tuning_policy == "max_power":
            warnings.append(
                "CPU stage will auto-tune at runtime for maximum package power; the executed mode/kernel may differ from the dry-run preview"
            )
        elif cpu_tuning_policy == "highest_supported":
            warnings.append(
                "CPU package power telemetry is unavailable; auto mode will use the highest supported kernel instead of power-based tuning"
            )
    if stage.modules.cpu.enabled and backend_usage["cpu"] == "python_fallback":
        warnings.append("CPU stage is using Python fallback; load strength is approximate")
        if stage.modules.cpu.instruction_set.lower() in {"sse", "avx", "avx2", "avx512"}:
            warnings.append(
                f"CPU instruction set '{stage.modules.cpu.instruction_set.lower()}' is not enforced by the Python fallback"
            )
    if stage.modules.cpu.enabled and backend_usage["cpu"] == "stress_ng":
        warnings.append("CPU stage is using stress-ng")
        if stage.modules.cpu.instruction_set.lower() in {"avx", "avx2", "avx512"}:
            warnings.append(
                f"CPU instruction set '{stage.modules.cpu.instruction_set.lower()}' is only approximate with stress-ng"
            )
    if stage.modules.memory.enabled and backend_usage["memory"] == "python_fallback":
        warnings.append("Memory stage is using Python fallback; behavior is approximate")
    if backend_usage["gpu_3d"] == "python_vulkan_compute":
        gpu_3d_compute_variant = runner._normalize_vulkan_compute_variant(stage.modules.gpu_3d.compute_variant)
    else:
        gpu_3d_compute_variant = runner._normalize_opencl_compute_variant(stage.modules.gpu_3d.compute_variant)
    opencl_details = runner._opencl_gpu_backend() if backend_usage["gpu_3d"] == "python_opencl_compute" else {}
    warnings.extend(
        suite_native_gpu_3d_backend_warnings(
            enabled=stage.modules.gpu_3d.enabled,
            resolved_backend=backend_usage["gpu_3d"],
            compute_variant=gpu_3d_compute_variant,
            allocation_percent=int(stage.modules.gpu_3d.allocation_percent or 0),
            gpu_3d_preference=gpu_3d_preference,
            selected_opencl_context=str(opencl_details.get("selected_context", "") or ""),
            opencl_compute_variants=OPENCL_COMPUTE_VARIANTS,
            vulkan_compute_variants=VULKAN_COMPUTE_VARIANTS,
        )
    )
    if stage.modules.gpu_3d.enabled and backend_usage["gpu_3d"] == "python_opencl_compute":
        if runner._gpu_safe_mode_enabled():
            high_headroom_targets = []
            for worker in gpu_workers:
                if worker.workload != "gpu_3d" or worker.backend != "python_opencl_compute":
                    continue
                target = runner._gpu_target_by_id(worker.target_id)
                if not runner._is_high_headroom_discrete_target(target):
                    continue
                target_label = str(worker.target_id or worker.card or f"gpu{worker.gpu_index}")
                high_headroom_targets.append(target_label)
            high_headroom_warning = opencl_high_headroom_safety_warning(
                enabled=stage.modules.gpu_3d.enabled,
                resolved_backend=backend_usage["gpu_3d"],
                safe_mode_enabled=runner._gpu_safe_mode_enabled(),
                target_labels=high_headroom_targets,
            )
            if high_headroom_warning:
                warnings.append(high_headroom_warning)
    intensity_warning = gpu_3d_intensity_warning(
        enabled=stage.modules.gpu_3d.enabled,
        resolved_backend=backend_usage["gpu_3d"],
        normalized_intensity=runner._normalize_gpu_3d_intensity(stage.modules.gpu_3d.intensity),
    )
    if intensity_warning:
        warnings.append(intensity_warning)
    if stage.modules.gpu_3d.enabled:
        per_target_backends = sorted(
            {
                str(worker.backend or "")
                for worker in gpu_workers
                if worker.workload == "gpu_3d" and str(worker.backend or "")
            }
        )
        per_target_warning = per_target_backend_selection_warning(
            enabled=stage.modules.gpu_3d.enabled,
            per_target_backends=per_target_backends,
        )
        if per_target_warning:
            warnings.append(per_target_warning)
    amd_vulkan_vram_targets: List[str] = []
    fused_vulkan_vram_targets: List[str] = []
    skipped_vram_targets: List[str] = []
    prefer_graphics_mixed_stage = False
    if stage.modules.gpu_3d.enabled and stage.modules.vram.enabled:
        prefer_graphics_mixed_stage = runner._prefer_graphics_backend_for_mixed_stage(stage.modules.gpu_3d, stage)
        amd_vulkan_vram_targets = [
            str(target.get("target_id") or target.get("slot") or target.get("card") or "GPU")
            for target in vram_targets
            if runner._use_vulkan_vram_worker_for_target(
                target,
                concurrent_gpu_3d=True,
                concurrent_amd_discrete_target_count=runner._amd_discrete_target_count(vram_targets),
                resolved_vram_backend=backend_usage["vram"],
            )
        ]
        fused_vulkan_vram_targets = [
            str(worker.target_id or worker.card or "GPU")
            for worker in gpu_workers
            if worker.workload == "vram"
            and worker.backend == "python_vulkan_compute"
            and worker.compute_variant == "stateful_memory"
        ]
        skipped_vram_targets = runner._concurrent_vram_skip_target_labels(
            vram_targets,
            concurrent_gpu_3d=True,
            vram_backend=backend_usage["vram"],
        )
    warnings.extend(
        mixed_stage_gpu_safety_warnings(
            gpu_3d_enabled=stage.modules.gpu_3d.enabled,
            vram_enabled=stage.modules.vram.enabled,
            prefer_graphics_backend_for_mixed_stage=prefer_graphics_mixed_stage,
            gpu_3d_backend=backend_usage["gpu_3d"],
            vram_backend=backend_usage["vram"],
            amd_vulkan_vram_target_labels=amd_vulkan_vram_targets,
            fused_vulkan_vram_target_labels=fused_vulkan_vram_targets,
            skipped_vram_target_labels=skipped_vram_targets,
        )
    )
    if stage.modules.gpu_3d.enabled:
        backend_profile = runner._gpu_3d_backend_catalog_entry(backend_usage["gpu_3d"])
        warnings.extend(
            gpu_3d_backend_identity_warnings(
                enabled=stage.modules.gpu_3d.enabled,
                resolved_backend=backend_usage["gpu_3d"],
                backend_profile=backend_profile,
                gpu_workers=gpu_workers,
                vulkan_runtime_available=bool(runner._vulkan_runtime_details().get("available")),
            )
        )
    vram_opencl_details = runner._opencl_gpu_backend() if backend_usage["vram"] == "python_opencl" else {}
    warnings.extend(
        vram_backend_warnings(
            enabled=stage.modules.vram.enabled,
            resolved_backend=backend_usage["vram"],
            selected_opencl_context=str(vram_opencl_details.get("selected_context", "") or ""),
        )
    )
    gpu_3d_fallback_warning = gpu_3d_preference_fallback_warning(
        enabled=stage.modules.gpu_3d.enabled,
        preference=gpu_3d_preference,
        resolved_backend=backend_usage["gpu_3d"],
    )
    if gpu_3d_fallback_warning:
        warnings.append(gpu_3d_fallback_warning)
    vram_fallback_warning = vram_preference_fallback_warning(
        enabled=stage.modules.vram.enabled,
        preference=vram_preference,
        resolved_backend=backend_usage["vram"],
    )
    if vram_fallback_warning:
        warnings.append(vram_fallback_warning)
    if runner._gpu_safe_mode_enabled():
        vram_cap_entries = []
        if stage.modules.vram.enabled:
            for worker in gpu_workers:
                if worker.workload != "vram":
                    continue
                target = runner._gpu_target_by_id(worker.target_id)
                requested_bytes = runner._target_vram_allocation_bytes(
                    stage.modules.vram.allocation_percent,
                    target,
                    memory_allocation_percent=(
                        int(stage.modules.memory.allocation_percent or 0)
                        if stage.modules.memory.enabled
                        else 0
                    ),
                    concurrent_gpu_3d=bool(stage.modules.gpu_3d.enabled),
                    stage_duration_seconds=int(stage.duration_seconds or 0),
                    concurrent_amd_discrete_target_count=(
                        runner._amd_discrete_target_count(vram_targets)
                        if stage.modules.gpu_3d.enabled
                        else 0
                    ),
                    vram_backend=worker.backend,
                )
                if worker.target_vram_bytes and worker.target_vram_bytes < requested_bytes:
                    vram_cap_entries.append(
                        {
                            "label": worker.target_id or worker.card or "GPU",
                            "requested_bytes": requested_bytes,
                            "capped_bytes": worker.target_vram_bytes,
                        }
                    )
        ramp_params = runner._gpu_internal_ramp_params()
        warnings.extend(
            gpu_safe_mode_worker_warnings(
                safe_mode_enabled=runner._gpu_safe_mode_enabled(),
                internal_worker_present=any(
                    worker.backend
                    in {
                        "python_opencl_compute",
                        "python_opencl",
                        "python_egl_gles2",
                        "python_vulkan_transfer",
                        "python_vulkan_compute",
                    }
                    for worker in gpu_workers
                ),
                ramp_start_load_fraction=ramp_params["start_load_fraction"],
                ramp_step_seconds=ramp_params["ramp_step_seconds"],
                vram_cap_entries=vram_cap_entries,
            )
        )

    return {
        "stage_id": stage.id,
        "label": label,
        "type": stage.name,
        "enabled": stage.enabled,
        "duration_seconds": stage.duration_seconds,
        "trim_start_seconds": stage.normalization.trim_start_seconds,
        "trim_end_seconds": stage.normalization.trim_end_seconds,
        "workloads": workloads,
        "gpu_target_mode": runner._gpu_target_summary(gpu_target_mode),
        "gpu_3d_mode": stage.modules.gpu_3d.mode if stage.modules.gpu_3d.enabled else "",
        "gpu_3d_intensity": runner._normalize_gpu_3d_intensity(stage.modules.gpu_3d.intensity) if stage.modules.gpu_3d.enabled else "",
        "gpu_3d_compute_variant": (
            runner._normalize_vulkan_compute_variant(stage.modules.gpu_3d.compute_variant)
            if backend_usage["gpu_3d"] == "python_vulkan_compute"
            or str(gpu_3d_preference or "").strip().lower() in {"vulkan_compute", "python_vulkan_compute"}
            else runner._normalize_opencl_compute_variant(stage.modules.gpu_3d.compute_variant)
        )
        if stage.modules.gpu_3d.enabled
        else "",
        "gpu_backend_preferences": {
            "gpu_3d": gpu_3d_preference,
            "vram": vram_preference,
        },
        "gpu_backend_fallback_order": {
            "gpu_3d": gpu_3d_candidates,
            "vram": vram_candidates,
        },
        "gpu_backend_catalog": {
            "gpu_3d": [
                runner._gpu_3d_backend_catalog_entry(candidate)
                for candidate in gpu_3d_candidates
            ]
            if stage.modules.gpu_3d.enabled
            else [],
        },
        "gpu_target_support": {
            "gpu_3d": gpu_3d_resolution,
            "vram": vram_resolution,
        },
        "gpu_targets": [target["target_id"] for target in gpu_targets],
        "gpu_effective_targets": sorted(
            {
                str(worker.target_id or worker.card or "")
                for worker in gpu_workers
                if str(worker.target_id or worker.card or "")
            }
        ),
        "gpu_excluded_targets": gpu_excluded_targets_summary(
            gpu_3d_resolution=gpu_3d_resolution,
            vram_resolution=vram_resolution,
        ),
        "gpu_target_details": [
            {
                "card": target["card"],
                "slot": target["slot"],
                "target_id": target["target_id"],
                "vendor": target.get("vendor", ""),
                "vendor_id": target.get("vendor_id", ""),
                "device_id": target.get("device", ""),
                "driver": target.get("driver", ""),
                "vram_total_gb": round((int(target.get("vram_total") or 0) / (1024 ** 3)), 2)
                if target.get("vram_total")
                else 0,
                "vulkan_device_name": (
                    str((runner._vulkan_device_for_target(target).get("device") or {}).get("deviceName", "") or "")
                    if runner._vulkan_runtime_details().get("available")
                    else ""
                ),
                "vulkan_selection_ambiguous": (
                    bool(runner._vulkan_device_for_target(target).get("ambiguous"))
                    if runner._vulkan_runtime_details().get("available")
                    else False
                ),
            }
            for target in gpu_targets
        ],
        "gpu_workers": [runner.serialize_gpu_worker(worker) for worker in gpu_workers],
        "backend_usage": backend_usage,
        "cpu_mode_requested": cpu_mode_requested,
        "cpu_mode_resolved": cpu_mode_resolved,
        "cpu_kernel_flavor": cpu_kernel_flavor,
        "cpu_tuning_policy": cpu_tuning_policy,
        "cpu_kernel_candidates": cpu_kernel_candidates,
        "commands": cmds,
        "missing_tools": missing_tools,
        "issues": issues,
        "warnings": warnings,
        "runnable": (not stage.enabled) or not issues,
    }
