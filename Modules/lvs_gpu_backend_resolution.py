from __future__ import annotations

from typing import Any, Dict, List, Optional


def gpu_backend_usage_summary(
    *,
    cpu_backend: str,
    memory_backend: str,
    gpu_3d_resolution: Dict[str, Any],
    vram_resolution: Dict[str, Any],
    cpu_enabled: bool,
    memory_enabled: bool,
    gpu_3d_enabled: bool,
    vram_enabled: bool,
) -> Dict[str, str]:
    return {
        "cpu": cpu_backend if cpu_enabled else "",
        "memory": memory_backend if memory_enabled else "",
        "gpu_3d": str(gpu_3d_resolution.get("backend") or "none") if gpu_3d_enabled else "",
        "vram": str(vram_resolution.get("backend") or "none") if vram_enabled else "",
    }


def best_partial_gpu_backend_report(resolution: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    available_reports = [
        report
        for report in resolution.get("candidate_reports", [])
        if report.get("available") and report.get("support")
    ]
    if not available_reports:
        return None
    return max(
        available_reports,
        key=lambda report: len(report["support"].get("supported_targets", [])),
    )


def unsupported_gpu_target_issue(
    *,
    workload_label: str,
    resolution: Dict[str, Any],
    preference: str,
) -> Optional[str]:
    best_report = best_partial_gpu_backend_report(resolution)
    if not best_report:
        return None
    backend = str(best_report.get("backend") or "unknown")
    support = best_report.get("support") or {}
    unsupported_targets = support.get("unsupported_targets", [])
    if not unsupported_targets:
        return None
    unsupported_text = ", ".join(
        f"{entry.get('target_label')} ({entry.get('reason')})"
        for entry in unsupported_targets
    )
    supported_targets = support.get("supported_targets", [])
    if supported_targets:
        supported_text = ", ".join(
            str(entry.get("target_label") or "GPU")
            for entry in supported_targets
        )
        return (
            f"{workload_label} backend '{backend}' cannot support all requested GPU targets; "
            f"supported: {supported_text}; unsupported: {unsupported_text}"
        )
    if preference and preference != "auto":
        return (
            f"{workload_label} backend preference '{preference}' cannot support the requested GPU targets: "
            f"{unsupported_text}"
        )
    return f"{workload_label} backend '{backend}' cannot support the requested GPU targets: {unsupported_text}"


def partial_gpu_target_warning(
    *,
    workload_label: str,
    resolution: Dict[str, Any],
) -> Optional[str]:
    support = resolution.get("support") or {}
    unsupported_targets = support.get("unsupported_targets", [])
    supported_targets = support.get("supported_targets", [])
    if not unsupported_targets or not supported_targets:
        return None
    backend = str(resolution.get("backend") or "unknown")
    supported_text = ", ".join(str(entry.get("target_label") or "GPU") for entry in supported_targets)
    unsupported_text = ", ".join(
        f"{entry.get('target_label')} ({entry.get('reason')})"
        for entry in unsupported_targets
    )
    return (
        f"{workload_label} backend '{backend}' will run on supported GPU targets only; "
        f"running: {supported_text}; skipped: {unsupported_text}"
    )


def gpu_backend_resolution_messages(
    *,
    workload_label: str,
    resolution: Dict[str, Any],
    preference: str,
) -> Dict[str, Optional[str]]:
    return {
        "issue": unsupported_gpu_target_issue(
            workload_label=workload_label,
            resolution=resolution,
            preference=preference,
        ),
        "warning": partial_gpu_target_warning(
            workload_label=workload_label,
            resolution=resolution,
        ),
    }


def gpu_resolution_excluded_target_labels(resolution: Dict[str, Any]) -> List[str]:
    support = resolution.get("support") or {}
    return [
        str(entry.get("target_label") or "")
        for entry in support.get("unsupported_targets", [])
        if str(entry.get("target_label") or "")
    ]


def gpu_excluded_targets_summary(
    *,
    gpu_3d_resolution: Dict[str, Any],
    vram_resolution: Dict[str, Any],
) -> Dict[str, List[str]]:
    return {
        "gpu_3d": gpu_resolution_excluded_target_labels(gpu_3d_resolution),
        "vram": gpu_resolution_excluded_target_labels(vram_resolution),
    }
