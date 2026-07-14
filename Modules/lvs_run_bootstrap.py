#!/usr/bin/env python3
"""Shared run bootstrap/setup artifact helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from Modules.lvs_advanced_debug import AdvancedDebugLogger
from Modules.lvs_core import JsonStore
from Modules.lvs_profile_models import StageConfig, ValidationProfile


@dataclass(frozen=True)
class RunBootstrapResult:
    run_dir: Path
    effective_profile: ValidationProfile
    effective_labels: List[str]
    skipped_stages: List[Dict[str, Any]]
    recovery_report: Dict[str, Any]
    system_info: Dict[str, Any]
    manifest_payload: Dict[str, Any]
    advanced_debug: AdvancedDebugLogger


def build_effective_profile_for_run(
    profile: ValidationProfile,
    labels: List[str],
    preflight_plan: List[Dict[str, Any]],
) -> tuple[ValidationProfile, List[Dict[str, Any]], List[str]]:
    effective_stages: List[StageConfig] = []
    skipped_stages: List[Dict[str, Any]] = []
    for idx, stage in enumerate(profile.stages):
        stage_plan = dict(preflight_plan[idx]) if idx < len(preflight_plan) else {}
        effective_enabled = bool(stage.enabled)
        if stage.enabled and not stage_plan.get("runnable", True):
            effective_enabled = False
            skipped_stages.append(
                {
                    "stage_id": stage.id,
                    "label": labels[idx] if idx < len(labels) else stage.name,
                    "issues": list(stage_plan.get("issues", [])),
                }
            )
        effective_stages.append(
            StageConfig(
                id=stage.id,
                name=stage.name,
                duration_seconds=stage.duration_seconds,
                enabled=effective_enabled,
                modules=stage.modules,
                normalization=stage.normalization,
                strict_threshold_recommendation_warnings=stage.strict_threshold_recommendation_warnings,
            )
        )
    effective_profile = ValidationProfile(
        profile_name=profile.profile_name,
        profile_type=profile.profile_type,
        segment_label_source=profile.segment_label_source,
        menu_description=profile.menu_description,
        menu_group=profile.menu_group,
        defaults=profile.defaults,
        stages=effective_stages,
    )
    effective_labels = [
        labels[idx]
        for idx, stage in enumerate(effective_profile.stages)
        if stage.enabled and idx < len(labels)
    ]
    return effective_profile, skipped_stages, effective_labels


def bootstrap_run_artifacts(
    *,
    app_name: str,
    app_version: str,
    profile_path: Path,
    profile: ValidationProfile,
    labels: List[str],
    metadata: Any,
    preflight: Dict[str, Any],
    run_dir: Path,
    started_iso: str,
    runtime_environment: Dict[str, Any],
    backends: Dict[str, Any],
    backend_details: Dict[str, Any],
    abort_on_fail_threshold: bool,
    abort_on_worker_error: bool,
    abort_on_system_fault: bool,
    abort_run_on_stage_abort: bool,
    privileged_helper_enabled: bool,
    recovery_report: Dict[str, Any],
    collect_system_info: Callable[[str, List[str], str, Any, bool], Dict[str, Any]],
    print_run_header: Callable[[str, Path, bool], None],
    print_stage_skip: Callable[[str, str], None],
    print_run_start: Callable[[str], None],
) -> RunBootstrapResult:
    preflight_plan = list(preflight.get("plan", []) or [])
    effective_profile, skipped_stages, effective_labels = build_effective_profile_for_run(
        profile,
        labels,
        preflight_plan,
    )
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    advanced_debug = AdvancedDebugLogger(
        run_dir,
        enabled=bool(getattr(metadata, "advanced_debug_logging", False)),
        runtime_environment=runtime_environment,
    )
    system_info = collect_system_info(
        profile.profile_name,
        effective_labels,
        profile_path.name,
        metadata,
        privileged_helper_enabled,
    )
    JsonStore.write(run_dir / "system_info.json", system_info)
    JsonStore.write(run_dir / "run_metadata.json", asdict(metadata))
    JsonStore.write(run_dir / "profile_used.json", asdict(effective_profile))
    manifest_payload = {
        "app_name": app_name,
        "app_version": app_version,
        "profile_name": profile.profile_name,
        "profile_file": profile_path.name,
        "menu_description": profile.menu_description,
        "menu_group": profile.menu_group,
        "segment_labels": effective_labels,
        "started": started_iso,
        "metadata": asdict(metadata),
        "runtime_environment": runtime_environment,
        "backends": backends,
        "backend_details": backend_details,
        "telemetry_capabilities": preflight["telemetry_capabilities"],
        "preflight_validation": preflight["validation"],
        "strict_threshold_recommendation_warnings": preflight.get("strict_threshold_recommendation_warnings", {}),
        "abort_policy": {
            "abort_on_fail_threshold": bool(abort_on_fail_threshold),
            "abort_on_worker_error": abort_on_worker_error,
            "abort_on_system_fault": abort_on_system_fault,
            "abort_run_on_stage_abort": abort_run_on_stage_abort,
        },
        "gpu_recovery": recovery_report,
        "plan": preflight_plan,
        "skipped_stages": skipped_stages,
        "verdict": "pass",
        "error_events": [],
        "warning_events": [],
        "events": [],
        "advanced_debug_logging": bool(getattr(metadata, "advanced_debug_logging", False)),
        "advanced_debug": {
            "enabled": bool(getattr(metadata, "advanced_debug_logging", False)),
            "path": "advanced_debug/advanced_debug_log.txt" if bool(getattr(metadata, "advanced_debug_logging", False)) else "",
        },
    }
    JsonStore.write(run_dir / "run_manifest.json", manifest_payload)
    advanced_debug.capture_run_start(started_iso=started_iso, profile_name=profile.profile_name)

    print_run_header(profile.profile_name, run_dir, bool(getattr(metadata, "advanced_debug_logging", False)))
    for skipped in skipped_stages:
        issue_summary = "; ".join(str(issue) for issue in skipped.get("issues", [])) or "stage is not runnable in the current environment"
        print_stage_skip(str(skipped["label"]), issue_summary)
    print_run_start(profile.profile_name)
    return RunBootstrapResult(
        run_dir=run_dir,
        effective_profile=effective_profile,
        effective_labels=effective_labels,
        skipped_stages=skipped_stages,
        recovery_report=recovery_report,
        system_info=system_info,
        manifest_payload=manifest_payload,
        advanced_debug=advanced_debug,
    )
