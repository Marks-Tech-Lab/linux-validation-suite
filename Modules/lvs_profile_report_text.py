#!/usr/bin/env python3
"""Profile report text rendering helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List


def profile_summary_text(profile_path: Path, profile: Any, labels: List[str], menu_group_label: Any) -> str:
    lines: List[str] = [
        f"Profile: {profile.profile_name}",
        f"File: {profile_path.name}",
        f"Group: {menu_group_label(profile.menu_group)}",
        f"Stages: {len(profile.stages)}",
        "",
    ]
    for index, stage in enumerate(profile.stages, start=1):
        label = labels[index - 1] if index - 1 < len(labels) else stage.name
        workloads = []
        if stage.modules.cpu.enabled:
            cpu = stage.modules.cpu
            instruction_text = (
                f"intent:{cpu.instruction_intent}"
                if str(getattr(cpu, "instruction_intent", "") or "")
                else cpu.instruction_set
            )
            cpu_text = (
                f"CPU/{cpu.backend_preference}/{instruction_text}/{cpu.threads}"
                if cpu.backend_preference != "auto"
                else f"CPU/{instruction_text}/{cpu.threads}"
            )
            workloads.append(cpu_text + ("/PowerAuto" if cpu.power_auto else ""))
        if stage.modules.memory.enabled:
            memory = stage.modules.memory
            workloads.append(
                f"RAM/{memory.backend_preference}/{memory.allocation_percent}%"
                if memory.backend_preference != "auto"
                else f"RAM/{memory.allocation_percent}%"
            )
        if stage.modules.gpu_3d.enabled:
            workloads.append(f"3D/{stage.modules.gpu_3d.backend_preference}/{stage.modules.gpu_3d.gpus}")
        if stage.modules.vram.enabled:
            workloads.append(
                f"VRAM/{stage.modules.vram.backend_preference}/{stage.modules.vram.allocation_percent}%/{stage.modules.vram.gpus}"
            )
        if stage.modules.storage_benchmark.enabled:
            storage = stage.modules.storage_benchmark
            workloads.append(
                f"StorageBenchmark/{storage.target_mode}/{storage.drive_execution}/{storage.test_size_gib}GiB/{storage.runs}runs"
            )
        state = "enabled" if stage.enabled else "disabled"
        execution = "completion-based" if stage.modules.storage_benchmark.enabled else f"{stage.duration_seconds}s"
        lines.append(
            f"{index}. {label} [{stage.name}] {execution}, {state}"
            + (f" | {', '.join(workloads)}" if workloads else "")
        )
    return "\n".join(lines)


def profile_audit_item_status(item: Dict[str, Any]) -> str:
    status = "runnable" if item.get("runnable") else "blocked"
    if not item.get("loaded"):
        status = "load_failed"
    return status


def profile_audit_item_line(item: Dict[str, Any]) -> str:
    return f"- {item.get('profile_file')}: {profile_audit_item_status(item)}, stages={item.get('stage_count', 0)}"


def legacy_profile_audit_text(payload: Dict[str, Any]) -> str:
    counts = payload.get("counts") if isinstance(payload.get("counts"), dict) else {}
    total_errors = int(counts.get("validation_errors") or 0)
    total_warnings = int(counts.get("validation_warnings") or 0)
    lines = [
        "Profile Audit",
        "=============",
        f"Profiles: {counts.get('profiles', 0)}",
        f"Runnable: {counts.get('runnable', 0)}",
        f"Blocked: {counts.get('blocked', 0)}",
        f"Validation: {total_errors} error(s), {total_warnings} warning(s)",
        "",
    ]
    for item in payload.get("profiles") or []:
        lines.append(profile_audit_item_line(item))
        for error in list(item.get("errors") or [])[:3]:
            lines.append(f"  [error] {error}")
        for warning in list(item.get("warnings") or [])[:3]:
            lines.append(f"  [warn] {warning}")
    return "\n".join(lines) + "\n"


def dry_run_plan_line(stage: Dict[str, Any]) -> str:
    label = stage.get("label") or stage.get("stage_id") or "stage"
    runnable = "runnable" if stage.get("runnable") else "blocked"
    backend_usage = stage.get("backend_usage") if isinstance(stage.get("backend_usage"), dict) else {}
    backends = ", ".join(f"{key}={value}" for key, value in backend_usage.items() if value)
    return f"- {label}: {runnable}" + (f" | {backends}" if backends else "")


def profile_execution_stage_status(stage: Dict[str, Any]) -> str:
    enabled = bool(stage.get("enabled"))
    runnable = bool(stage.get("runnable"))
    return "disabled" if not enabled else "runnable" if runnable else "blocked"


def profile_execution_stage_header_line(stage: Dict[str, Any]) -> str:
    label = stage.get("label") or stage.get("stage_id") or "stage"
    workloads = ", ".join(stage.get("workloads") or []) or "-"
    duration = "completion-based" if stage.get("execution_mode") == "completion" else f"{stage.get('duration_seconds', 0)}s"
    return (
        f"- {label}: {stage.get('type') or '-'} | {duration} | "
        f"{profile_execution_stage_status(stage)} | workloads={workloads}"
    )


def profile_execution_trim_line(stage: Dict[str, Any]) -> str:
    return f"  trim: start={stage.get('trim_start_seconds', 0)}s, end={stage.get('trim_end_seconds', 0)}s"


def profile_execution_cpu_line(stage: Dict[str, Any]) -> str:
    backend_usage = stage.get("backend_usage") or {}
    cpu_backend = backend_usage.get("cpu") or "-"
    cpu_requested = stage.get("cpu_mode_requested") or "-"
    cpu_resolved = stage.get("cpu_mode_resolved") or "-"
    cpu_kernel = stage.get("cpu_kernel_flavor") or "-"
    cpu_preference = stage.get("cpu_backend_preference") or "auto"
    cpu_intent = stage.get("cpu_instruction_intent") or ""
    intent_text = f", intent={cpu_intent}" if cpu_intent else ""
    if cpu_preference == "auto":
        return f"  cpu: backend={cpu_backend}{intent_text}, mode={cpu_requested}->{cpu_resolved}, kernel={cpu_kernel}"
    return f"  cpu: requested_backend={cpu_preference}, backend={cpu_backend}{intent_text}, mode={cpu_requested}->{cpu_resolved}, kernel={cpu_kernel}"


def profile_execution_memory_line(stage: Dict[str, Any]) -> str:
    backend_usage = stage.get("backend_usage") or {}
    memory_backend = backend_usage.get("memory") or "-"
    return f"  memory: backend={memory_backend}"


def profile_execution_system_memory_lines(stage: Dict[str, Any]) -> List[str]:
    plan = stage.get("system_memory_plan") if isinstance(stage.get("system_memory_plan"), dict) else {}
    if not plan:
        return []

    def gib(value: Any) -> str:
        return f"{float(value or 0) / (1024 ** 3):.2f}GiB"

    lines = [
        "  system memory: "
        + f"total={gib(plan.get('system_memory_total_bytes'))}, "
        + f"available={gib(plan.get('system_memory_available_bytes'))}, "
        + f"available_source={plan.get('mem_available_source') or '-'}, "
        + f"reserve={gib(plan.get('system_memory_safety_reserve_bytes'))}, "
        + f"pool={gib(plan.get('system_memory_budget_bytes'))}",
    ]
    for consumer in plan.get("consumers") or []:
        lines.append(
            "  system memory commitment: "
            + f"{consumer.get('consumer_id')} target={gib(consumer.get('requested_target_bytes'))}"
            + (f" x{consumer.get('target_multiplier')}" if int(consumer.get('target_multiplier') or 1) > 1 else "")
            + f", requested_commitment={gib(consumer.get('requested_bytes'))}, "
            + f"resolved_target={gib(consumer.get('resolved_target_bytes'))}, "
            + f"resolved_commitment={gib(consumer.get('resolved_bytes'))}"
        )
    lines.append(
        "  system memory total: "
        + f"planned={gib(plan.get('total_planned_system_memory_bytes'))}, "
        + f"remaining={gib(plan.get('remaining_system_memory_headroom_bytes'))}, "
        + f"resolution={plan.get('resolution_reason') or '-'}"
    )
    guard = plan.get("runtime_memory_guard_policy") or {}
    if guard.get("enabled"):
        lines.append(
            "  runtime memory guard: "
            + f"warning_below={gib(guard.get('warning_mem_available_bytes'))} for "
            + f"{guard.get('warning_consecutive_samples')} samples, "
            + f"emergency_below={gib(guard.get('emergency_mem_available_bytes'))} for "
            + f"{guard.get('emergency_consecutive_samples')} samples"
        )
    return lines


def profile_execution_gpu_3d_line(stage: Dict[str, Any]) -> str:
    gpu_backend_preferences = stage.get("gpu_backend_preferences") or {}
    backend_usage = stage.get("backend_usage") or {}
    gpu_3d_backend = backend_usage.get("gpu_3d") or "-"
    return (
        "  3d: "
        + f"preference={gpu_backend_preferences.get('gpu_3d') or '-'}, resolved={gpu_3d_backend}, "
        + f"mode={stage.get('gpu_3d_mode') or '-'}, intensity={stage.get('gpu_3d_intensity') or '-'}, "
        + f"variant={stage.get('gpu_3d_compute_variant') or '-'}"
    )


def profile_execution_vram_line(stage: Dict[str, Any]) -> str:
    gpu_backend_preferences = stage.get("gpu_backend_preferences") or {}
    backend_usage = stage.get("backend_usage") or {}
    vram_backend = backend_usage.get("vram") or "-"
    workers = [worker for worker in stage.get("gpu_workers") or [] if worker.get("workload") == "vram"]
    target_gb_values = [
        round(float(worker.get("target_vram_bytes") or 0) / (1024 ** 3), 2)
        for worker in workers
        if float(worker.get("target_vram_bytes") or 0) > 0
    ]
    target_text = ", ".join(f"{value}GB" for value in target_gb_values[:6]) or "-"
    return (
        "  vram: "
        + f"preference={gpu_backend_preferences.get('vram') or '-'}, resolved={vram_backend}, target_allocations={target_text}"
    )


def profile_execution_gpu_detail_lines(stage: Dict[str, Any]) -> List[str]:
    lines: List[str] = []
    effective_targets = stage.get("gpu_effective_targets") or []
    requested_targets = stage.get("gpu_targets") or []
    lines.append(
        f"  gpu targets: mode={stage.get('gpu_target_mode') or '-'}, requested={len(requested_targets)}, effective={len(effective_targets)}"
    )
    if effective_targets:
        lines.append(f"  effective target ids: {', '.join(str(item) for item in effective_targets[:8])}")
    excluded = stage.get("gpu_excluded_targets") or {}
    excluded_flat = [
        f"{kind}:{target}"
        for kind, targets in excluded.items()
        for target in (targets or [])
        if target
    ]
    if excluded_flat:
        lines.append(f"  excluded targets: {', '.join(excluded_flat[:8])}")
    fallback = stage.get("gpu_backend_fallback_order") or {}
    fallback_parts = []
    if fallback.get("gpu_3d"):
        fallback_parts.append("3d=" + " > ".join(fallback.get("gpu_3d") or []))
    if fallback.get("vram"):
        fallback_parts.append("vram=" + " > ".join(fallback.get("vram") or []))
    if fallback_parts:
        lines.append(f"  backend fallback: {'; '.join(fallback_parts)}")
    workers = stage.get("gpu_workers") or []
    dedicated_workers = [
        worker
        for worker in workers
        if worker.get("gpu_memory_kind") == "dedicated" and int(worker.get("planned_gpu_memory_target_bytes") or 0) > 0
    ]
    for worker in dedicated_workers[:8]:
        lines.append(
            "  dedicated GPU memory: "
            + f"target={worker.get('target_id') or worker.get('card') or '-'}, "
            + f"capacity={float(worker.get('dedicated_vram_capacity_bytes') or 0) / (1024 ** 3):.2f}GiB, "
            + f"planned={float(worker.get('planned_gpu_memory_target_bytes') or 0) / (1024 ** 3):.2f}GiB "
            + "(outside system-memory pool)"
        )
    shared_or_unknown_workers = [
        worker for worker in workers if worker.get("gpu_memory_kind") in {"shared", "unknown"}
    ]
    for worker in shared_or_unknown_workers[:8]:
        lines.append(
            "  GPU memory: "
            + f"target={worker.get('target_id') or worker.get('card') or '-'}, "
            + f"kind={worker.get('gpu_memory_kind')}, "
            + f"capacity={float(worker.get('backend_addressable_capacity_bytes') or 0) / (1024 ** 3):.2f}GiB "
            + f"({worker.get('backend_addressable_capacity_status') or 'unknown'}; {worker.get('backend_addressable_capacity_source') or '-'}), "
            + f"requested={float(worker.get('requested_gpu_memory_target_bytes') or 0) / (1024 ** 3):.2f}GiB, "
            + f"planned={float(worker.get('planned_gpu_memory_target_bytes') or 0) / (1024 ** 3):.2f}GiB, "
            + f"single/object_limit={float(worker.get('max_single_allocation_bytes') or worker.get('max_buffer_or_object_bytes') or 0) / (1024 ** 3):.2f}GiB, "
            + f"chunks={int(worker.get('planned_allocation_chunk_count') or 0)}, "
            + f"cap={worker.get('target_cap_reason') or '-'}, "
            + f"budgetability={worker.get('memory_budgetability') or '-'}"
        )
    if workers:
        rendered_workers = []
        for worker in workers[:8]:
            workload = worker.get("workload") or "gpu"
            backend = worker.get("backend") or "-"
            target = worker.get("target_id") or worker.get("card") or "-"
            rendered_workers.append(f"{workload}:{backend}@{target}")
        lines.append(f"  gpu workers ({len(workers)}): {', '.join(rendered_workers)}")
    return lines


def profile_execution_summary_lines(report: Dict[str, Any]) -> List[str]:
    lines: List[str] = []
    lines.append("Execution Plan")
    lines.append(f"Profile: {report.get('profile_name', '')}")
    lines.append(f"Runnable: {bool(report.get('runnable'))}")
    enabled_count = int(report.get("enabled_stage_count") or 0)
    runnable_count = int(report.get("runnable_stage_count") or 0)
    if enabled_count:
        lines.append(f"Runnable stages: {runnable_count}/{enabled_count}")
    lines.append("")
    for stage in report.get("plan") or []:
        lines.append(profile_execution_stage_header_line(stage))
        if stage.get("trim_start_seconds") or stage.get("trim_end_seconds"):
            lines.append(profile_execution_trim_line(stage))
        lines.extend(profile_execution_system_memory_lines(stage))
        if "cpu" in (stage.get("workloads") or []):
            lines.append(profile_execution_cpu_line(stage))
        if "memory" in (stage.get("workloads") or []):
            lines.append(profile_execution_memory_line(stage))
        if "gpu_3d" in (stage.get("workloads") or []):
            lines.append(profile_execution_gpu_3d_line(stage))
        if "vram" in (stage.get("workloads") or []):
            lines.append(profile_execution_vram_line(stage))
        if "storage_benchmark" in (stage.get("workloads") or []):
            storage = stage.get("storage_benchmark") or {}
            lines.append(
                "  storage benchmark: "
                f"profile={storage.get('profile_id') or '-'}, target_mode={storage.get('target_mode') or '-'}, "
                f"drive_execution={storage.get('drive_execution') or '-'}, size={storage.get('test_size_gib')} GiB, "
                f"runs={storage.get('runs')}, estimated_max_writes={storage.get('estimated_max_writes_gib_per_drive')} GiB/drive, "
                f"allow_system_drive={bool(storage.get('allow_system_drive'))}"
            )
            if storage.get("target_mode") == "all_internal_non_root_low_occupancy":
                lines.append(
                    "  storage selection policy: "
                    f"selected-filesystem used <= {float(storage.get('max_used_percent') or 0):.2f}%; "
                    "root/system drives excluded; unmounted filesystems are not measured"
                )
            preview = storage.get("target_preview") or {}
            if preview:
                lines.append(
                    "  storage target preview: "
                    f"eligible={preview.get('eligible_target_count', 0)}, "
                    f"skipped={len(preview.get('skipped_targets') or [])}"
                    + (f", warning={preview.get('preflight_warning')}" if preview.get("preflight_warning") else "")
                )
                for target in preview.get("included_targets") or []:
                    free = target.get("free_bytes")
                    free_text = f"{float(free) / 1024**3:.2f} GiB" if free is not None else "unavailable"
                    used = target.get("used_percent")
                    used_text = f"{float(used):.2f}%" if used is not None else "unavailable"
                    lines.append(
                        "    include "
                        f"{target.get('device')}: workspace={target.get('workspace')}, "
                        f"filesystem={target.get('filesystem') or 'unknown'}, used={used_text}, free={free_text}"
                    )
                    if target.get("warning"):
                        lines.append(f"      warning: {target.get('warning')}")
                for target in preview.get("skipped_targets") or []:
                    used = target.get("used_percent")
                    used_text = f", used={float(used):.2f}%" if used is not None else ""
                    lines.append(
                        "    skip "
                        f"{target.get('device')}: {target.get('reason')}"
                        f"{used_text}"
                    )
                    if target.get("warning"):
                        lines.append(f"      warning: {target.get('warning')}")
        if {"gpu_3d", "vram"} & set(stage.get("workloads") or []):
            lines.extend(profile_execution_gpu_detail_lines(stage))
        commands = stage.get("commands") or []
        if commands:
            lines.append(f"  commands: {len(commands)} command(s); full command bodies are in diagnostics.json")
        for issue in list(stage.get("issues") or [])[:5]:
            lines.append(f"  [issue] {issue}")
        for warning in list(stage.get("warnings") or [])[:5]:
            lines.append(f"  [warn] {warning}")
    return lines


def diagnostics_summary_text(report: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("Diagnostics Summary")
    lines.append(f"Profile: {report.get('profile_name', '')}")
    lines.append(f"Runnable: {bool(report.get('runnable'))}")
    validation = report.get("validation") or {}
    errors = list(validation.get("errors") or [])
    warnings = list(validation.get("warnings") or [])
    lines.append(f"Validation errors: {len(errors)}")
    for error in errors[:12]:
        lines.append(f"  [error] {error}")
    if len(errors) > 12:
        lines.append(f"  ... {len(errors) - 12} more error(s)")
    lines.append(f"Validation warnings: {len(warnings)}")
    for warning in warnings[:16]:
        lines.append(f"  [warn] {warning}")
    if len(warnings) > 16:
        lines.append(f"  ... {len(warnings) - 16} more warning(s)")
    lines.append("")
    lines.extend(profile_execution_summary_lines(report))
    lines.append("")
    lines.append("Telemetry:")
    telemetry = report.get("telemetry_capabilities") or {}
    for key in (
        "gpu_temp_c",
        "gpu_power_w",
        "gpu_clock_mhz",
        "gpu_memory_clock_mhz",
        "gpu_busy_percent",
        "gpu_memory_busy_percent",
        "gpu_vram_used_gb",
    ):
        cap = telemetry.get(key) or {}
        count = cap.get("count")
        count_text = f", count={count}" if count else ""
        lines.append(
            f"  - {key}: available={bool(cap.get('available'))}, source={cap.get('source') or 'not found'}{count_text}"
        )
    gpu_matrix = ((telemetry.get("gpu_telemetry_by_gpu") or {}).get("gpus") or [])
    if gpu_matrix:
        lines.append("")
        lines.append("Per-GPU Telemetry:")
        for gpu in gpu_matrix:
            metrics = gpu.get("metrics") or {}
            available = [
                name
                for name, detail in metrics.items()
                if isinstance(detail, dict) and detail.get("available")
            ]
            missing = [
                name
                for name, detail in metrics.items()
                if isinstance(detail, dict) and not detail.get("available")
            ]
            label = gpu.get("slot") or gpu.get("card") or f"gpu{gpu.get('gpu_index')}"
            lines.append(
                f"  - GPU {gpu.get('gpu_index')} {label} {gpu.get('vendor') or ''} {gpu.get('driver') or ''}".rstrip()
            )
            lines.append(f"    available: {', '.join(available) if available else '-'}")
            lines.append(f"    missing: {', '.join(missing) if missing else '-'}")
            for name in available:
                detail = metrics.get(name) or {}
                lines.append(f"    {name}: {detail.get('source')}")
    lines.append("")
    lines.append("Full details: diagnostics.json")
    return "\n".join(lines) + "\n"


def preflight_summary_text(report: Dict[str, Any]) -> str:
    text = diagnostics_summary_text(report)
    text = text.replace("Diagnostics Summary", "Preflight Summary", 1)
    text = text.replace("Full details: diagnostics.json", "Full details: preflight_report.json", 1)
    return text


def dry_run_summary_text(profile_path: Path, report: Dict[str, Any]) -> str:
    validation = report.get("validation") if isinstance(report.get("validation"), dict) else {}
    errors = list(validation.get("errors") or [])
    warnings = list(validation.get("warnings") or [])
    lines: List[str] = [
        f"Profile: {report.get('profile_name', profile_path.name)}",
        f"Runnable: {'yes' if report.get('runnable') else 'no'}",
        f"Runnable stages: {report.get('runnable_stage_count', 0)}/{report.get('enabled_stage_count', 0)}",
        f"Errors: {len(errors)}",
    ]
    lines.extend(f"  [error] {message}" for message in errors[:20])
    if len(errors) > 20:
        lines.append(f"  ... {len(errors) - 20} more error(s)")
    lines.append(f"Warnings: {len(warnings)}")
    lines.extend(f"  [warn] {message}" for message in warnings[:30])
    if len(warnings) > 30:
        lines.append(f"  ... {len(warnings) - 30} more warning(s)")
    lines.append("")
    lines.append("Plan:")
    for stage in report.get("plan") or []:
        lines.append(dry_run_plan_line(stage))
    return "\n".join(lines)
